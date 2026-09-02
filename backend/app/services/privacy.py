"""Server-enforced privacy retention and device-scoped deletion primitives.

Raw location evidence is deliberately handled separately from derived gameplay
ledgers. Neither scheduled retention nor a device deletion request alters runs'
distance/duration, segments, influence grants, standings, or ownership records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Device, DeviceProfile, Run


@dataclass(frozen=True)
class RetentionResult:
    raw_traces_deleted: int
    route_polylines_reduced: int


@dataclass(frozen=True)
class DeviceDeletionResult:
    device_id: str
    raw_traces_deleted: int


def _erase_raw_trace(run: Run, *, now: datetime, erase_route: bool) -> None:
    """Destroy source location evidence while leaving derived history untouched."""
    run.raw_payload = {}
    run.sample_ts = None
    run.sample_accuracy_m = None
    run.raw_trace_deleted_at = now
    if erase_route:
        run.geom = None
        run.route_reduced_at = now


def enforce_retention(session: Session, *, now: datetime | None = None) -> RetentionResult:
    """Apply the declared retention windows in the caller's transaction."""
    now = now or datetime.now(UTC)
    raw_cutoff = now - timedelta(days=settings.raw_trace_retention_days)
    full_route_cutoff = now - timedelta(days=settings.route_polyline_full_precision_days)

    raw_runs = session.scalars(
        select(Run).where(
            Run.ended_at < raw_cutoff,
            Run.raw_trace_deleted_at.is_(None),
        )
    ).all()
    for run in raw_runs:
        _erase_raw_trace(run, now=now, erase_route=False)

    # Simplify in a metre-based projection: geographic degrees would make an
    # India-wide tolerance depend on latitude. This only reduces the display
    # polyline; it never touches gameplay or influence/ownership history.
    simplified = session.execute(
        update(Run)
        .where(
            Run.ended_at < full_route_cutoff,
            Run.geom.is_not(None),
            Run.route_reduced_at.is_(None),
        )
        .values(
            geom=text(
                "ST_Transform("
                "ST_SimplifyPreserveTopology(ST_Transform(geom::geometry, 3857), "
                ":simplification_m), 4326)::geography"
            ),
            route_reduced_at=now,
        ),
        {"simplification_m": settings.reduced_route_simplification_m},
    ).rowcount

    return RetentionResult(
        raw_traces_deleted=len(raw_runs),
        route_polylines_reduced=int(simplified or 0),
    )


def anonymize_device(
    session: Session,
    *,
    device_id: object,
    now: datetime | None = None,
) -> DeviceDeletionResult:
    """Remove device-scoped personal/location data without rewriting game history."""
    now = now or datetime.now(UTC)
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")

    raw_runs = session.scalars(
        select(Run).where(Run.device_id == device_id, Run.raw_trace_deleted_at.is_(None))
    ).all()
    for run in raw_runs:
        _erase_raw_trace(run, now=now, erase_route=True)

    # Home selection and its bounded metadata are personal preferences, not
    # gameplay history, so they are removed rather than anonymised.
    profile = session.get(DeviceProfile, device_id)
    if profile is not None:
        session.delete(profile)

    # Device UUIDs are already opaque pseudonyms in this pre-auth phase. Clearing
    # the only optional device metadata and marking deletion prevents new profile
    # use while ledgers retain their anonymous, historically consistent key.
    device.label = None
    device.privacy_deleted_at = now
    session.flush()
    return DeviceDeletionResult(device_id=str(device.id), raw_traces_deleted=len(raw_runs))
