"""Run submission: accept a trace, derive everything from it, apply the result.

The client sends raw GPS samples and nothing else. It does not send distance, it
does not send which territories it thinks it visited, and it does not send who it
thinks owns them. `05_ANTICHEAT_AND_TRUST` Principle 1 -- the client asserts
nothing, the server derives every fact that matters.
"""

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Device,
    InfluenceGrant,
    Run,
    RunLifecycleEvent,
    RunTerritorySegment,
    Territory,
    TerritoryOwnership,
    TerritoryStanding,
)
from app.schemas import GpsSample, RunResult, RunSubmission, SegmentResult
from app.services.athlete import (
    altitudes_for,
    apply_new_run_defaults,
    record_run_metrics,
)
from app.services.influence import (
    InfluenceTuning,
    active_share,
    classify_activity,
    effort_for_segment,
    influence_for_effort,
)
from app.services.matching import (
    create_public_captured_area,
    match_loop_capture_territories,
    match_run,
)
from app.services.ownership import recompute_ownership


def _usable_samples(samples: list[GpsSample]) -> list[GpsSample]:
    """Drop samples too inaccurate to trust, and collapse consecutive duplicates.

    A standing-still runner emits many identical fixes; feeding those into a
    LineString adds vertices without adding length, and PostGIS rejects
    zero-length segments in some operations.
    """
    kept: list[GpsSample] = []
    for sample in samples:
        if sample.accuracy_m is not None and sample.accuracy_m > settings.max_accuracy_m:
            continue
        if kept and kept[-1].lat == sample.lat and kept[-1].lon == sample.lon:
            continue
        kept.append(sample)
    return kept


def _tuning() -> InfluenceTuning:
    return InfluenceTuning(
        distance_weight=settings.influence_distance_weight,
        moving_time_weight=settings.influence_moving_time_weight,
        walking_weight=settings.walking_weight,
        running_weight=settings.running_weight,
        gamma=settings.influence_gamma,
        running_pace_ceiling_s_per_km=settings.running_pace_ceiling_s_per_km,
        abandonment_floor=settings.abandonment_floor,
    )


def _transition(session: Session, run: Run, to_status: str, *, reason: str | None = None) -> None:
    """Advance a persisted run and append its corresponding lifecycle event."""
    from_status = run.status
    run.lifecycle_version += 1
    run.status = to_status
    # The caller's session owns the transaction, so the state and audit record
    # are atomic even though this synchronous prototype has no worker.
    session.add(
        RunLifecycleEvent(
            run_id=run.id,
            sequence=run.lifecycle_version,
            from_status=from_status,
            to_status=to_status,
            actor_kind="system",
            reason=reason,
            details={"pipeline_version": run.pipeline_version},
        )
    )


def process_run(session: Session, device: Device, submission: RunSubmission) -> RunResult:
    existing = session.get(Run, submission.run_id)
    if existing is not None:
        if existing.device_id != device.id:
            raise HTTPException(409, "Run ID belongs to another runner")
        # Idempotent by client-generated run id, so a retry after a flaky upload
        # returns the original result instead of double-counting distance.
        return build_result(session, existing)

    if len(_usable_samples(submission.samples)) < 2 and not any(
        sample.is_mock for sample in submission.samples
    ):
        raise HTTPException(
            status_code=422,
            detail="Run needs at least two usable GPS samples to form a route.",
        )

    usable = _usable_samples(submission.samples)
    duration_s = max(int((submission.ended_at - submission.started_at).total_seconds()), 0)
    wkt = ", ".join(f"{s.lon} {s.lat}" for s in usable) if len(usable) >= 2 else None

    run = Run(
        id=submission.run_id,
        device_id=device.id,
        started_at=submission.started_at,
        ended_at=submission.ended_at,
        duration_s=duration_s,
        geom=f"SRID=4326;LINESTRING({wkt})" if wkt else None,
        sample_ts=[s.ts for s in usable],
        sample_accuracy_m=[s.accuracy_m or -1.0 for s in usable],
        sample_altitude_m=altitudes_for(usable),
        temperature_c=submission.conditions.temperature_c if submission.conditions else None,
        weather_code=submission.conditions.weather_code if submission.conditions else None,
        raw_payload=submission.model_dump(mode="json"),
        status="submitted",
        source=submission.source,
        pipeline_version=settings.pipeline_version,
    )
    session.add(run)
    session.flush()
    session.add(
        RunLifecycleEvent(
            run_id=run.id,
            sequence=run.lifecycle_version,
            from_status=None,
            to_status="submitted",
            actor_kind="device",
            actor_ref=str(device.id),
        )
    )

    if any(sample.is_mock for sample in submission.samples):
        _transition(session, run, "rejected", reason="mock_location_detected")
        run.processed_at = datetime.now(UTC)
        session.flush()
        return build_result(session, run)

    run.distance_m = (
        session.execute(select(func.ST_Length(Run.geom)).where(Run.id == run.id)).scalar_one()
        if run.geom is not None
        else 0
    )
    _transition(session, run, "validated")
    _transition(session, run, "applied")
    run.processed_at = datetime.now(UTC)

    # Derived once here, from every usable fix: retention later thins the trace.
    record_run_metrics(session, run, usable)
    apply_new_run_defaults(session, run, device.id)

    # Separate public overlay: never mutates fixed territory geometry.
    if run.source == "tracked":
        create_public_captured_area(session, run.id, device.id)

    matched_segments = {
        segment.territory_id: segment for segment in match_run(session, run.id, duration_s)
    }
    for loop_capture in match_loop_capture_territories(session, run.id):
        existing = matched_segments.get(loop_capture.territory_id)
        matched_segments[loop_capture.territory_id] = (
            replace(existing, capture_method="loop") if existing else loop_capture
        )

    for segment in matched_segments.values():
        row = RunTerritorySegment(
            run_id=run.id,
            device_id=device.id,
            territory_id=segment.territory_id,
            territory_version=segment.territory_version,
            distance_m=segment.distance_m,
            seconds_in=segment.seconds_in,
            capture_method=segment.capture_method,
        )
        session.add(row)
        if run.source != "tracked":
            continue
        # Current share is calculated from the same decayed ledger that will
        # determine the owner after this grant is persisted.
        recompute_ownership(session, segment.territory_id)
        session.flush()
        standing = session.get(
            TerritoryStanding,
            {"territory_id": segment.territory_id, "device_id": device.id},
        )
        active = standing.active_influence if standing is not None else 0
        total = session.execute(
            select(func.coalesce(func.sum(TerritoryStanding.active_influence), 0)).where(
                TerritoryStanding.territory_id == segment.territory_id
            )
        ).scalar_one()
        tuning = _tuning()
        activity = classify_activity(segment.distance_m, segment.seconds_in, tuning)
        if segment.capture_method == "loop":
            # Server-validated loops secure the enclosed territory. Determine
            # the grant from live ledger state so it overtakes the current
            # leader by a small, configurable margin instead of trusting a
            # client-selected owner or using a magic client score.
            highest_active = session.execute(
                select(func.coalesce(func.max(TerritoryStanding.active_influence), 0)).where(
                    TerritoryStanding.territory_id == segment.territory_id
                )
            ).scalar_one()
            granted = max(
                float(settings.loop_capture_margin),
                float(highest_active or 0)
                - float(active or 0)
                + float(settings.loop_capture_margin),
            )
            effort = granted
        else:
            effort = effort_for_segment(
                distance_m=segment.distance_m,
                moving_time_s=segment.seconds_in,
                activity=activity,
                tuning=tuning,
            )
            granted = influence_for_effort(
                effort=effort,
                current_share=active_share(
                    contributor_active=float(active or 0), total_active=float(total or 0)
                ),
                tuning=tuning,
            )
        session.add(
            InfluenceGrant(
                run_id=run.id,
                device_id=device.id,
                territory_id=segment.territory_id,
                territory_version=segment.territory_version,
                pipeline_version=run.pipeline_version,
                ruleset_version=run.ruleset_version,
                activity=activity,
                distance_m=segment.distance_m,
                moving_time_s=segment.seconds_in,
                effort=effort,
                active_influence=granted,
                legacy_influence=granted,
                half_life_days=settings.default_decay_half_life_days,
                granted_at=run.ended_at,
            )
        )
        session.flush()
        outcome = recompute_ownership(session, segment.territory_id)
        row.caused_ownership_change = outcome.changed and outcome.owner_id == device.id

    session.flush()
    return build_result(session, run)


def build_result(session: Session, run: Run, samples_dropped: int | None = None) -> RunResult:
    rows = session.execute(
        select(
            RunTerritorySegment,
            Territory,
            TerritoryStanding.total_distance_m,
            TerritoryStanding.active_influence,
            TerritoryStanding.legacy_influence,
            TerritoryOwnership.owner_device_id,
            InfluenceGrant.active_influence,
        )
        .join(Territory, Territory.id == RunTerritorySegment.territory_id)
        .outerjoin(
            TerritoryStanding,
            (TerritoryStanding.territory_id == RunTerritorySegment.territory_id)
            & (TerritoryStanding.device_id == run.device_id),
        )
        .outerjoin(TerritoryOwnership, TerritoryOwnership.territory_id == Territory.id)
        .outerjoin(
            InfluenceGrant,
            (InfluenceGrant.run_id == RunTerritorySegment.run_id)
            & (InfluenceGrant.territory_id == RunTerritorySegment.territory_id),
        )
        .where(RunTerritorySegment.run_id == run.id)
        .order_by(RunTerritorySegment.distance_m.desc())
    ).all()

    segments = [
        SegmentResult(
            territory_id=territory.id,
            slug=territory.slug,
            name=territory.name,
            distance_m=float(segment.distance_m),
            seconds_in=segment.seconds_in,
            total_distance_m=float(total or 0),
            active_influence=round(float(active or 0), 4),
            legacy_influence=round(float(legacy or 0), 4),
            influence_granted=round(float(granted or 0), 4),
            owner_device_id=owner_id,
            is_owned_by_you=owner_id == run.device_id,
            ownership_changed=segment.caused_ownership_change,
            capture_method=segment.capture_method,
        )
        for segment, territory, total, active, legacy, owner_id, granted in rows
    ]
    if samples_dropped is None:
        samples_dropped = len(run.raw_payload.get("samples", [])) - len(run.sample_ts or [])

    return RunResult(
        run_id=run.id,
        status=run.status,
        distance_m=round(float(run.distance_m), 2),
        duration_s=run.duration_s,
        sample_count=len(run.sample_ts or []),
        samples_dropped=samples_dropped,
        segments=segments,
    )


def get_run_or_404(session: Session, run_id: uuid.UUID) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
