"""The athlete profile: totals, streaks, records, goals, shoes and the log.

Per-run numbers (moving time, splits, best efforts, elevation) are computed
once and cached — at ingest from the full samples, or on first read for runs
recorded before this existed. Everything else is aggregated from the ledger at
read time, in the athlete's own timezone.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, load_only

from app.core.config import settings
from app.models import (
    Account,
    AthleteSettings,
    DeviceLink,
    Run,
    RunAnnotation,
    RunBestEffort,
    RunMetrics,
    RunTerritorySegment,
    Shoe,
    TerritoryOwnership,
    WeeklyGoal,
)
from app.schemas import (
    AthleteSettingsRecord,
    AthleteStats,
    AthleteTotals,
    BestEffortRecord,
    FourWeekAverages,
    GoalProgress,
    MonthBucket,
    RunActivity,
    RunAnnotationUpdate,
    RunEffort,
    RunPage,
    RunRecord,
    RunSplit,
    RunSummary,
    ShoeCreate,
    ShoeRecord,
    ShoeRef,
    ShoeUpdate,
    StreakSummary,
    WeekBucket,
    WeeklyGoalUpdate,
)
from app.services.athlete_metrics import METRICS_VERSION, TrackPoint, calories, compute_metrics

# Runs the athlete actually did. Rejected (mock location) and reversed (review)
# runs are not training, whatever territory rules made of them.
COUNTED_STATUSES = ("applied", "validated", "provisional", "challenged")

# Everything aggregation needs, and nothing heavy: the raw trace stays unloaded.
SUMMARY_COLUMNS = (
    Run.id,
    Run.device_id,
    Run.started_at,
    Run.ended_at,
    Run.duration_s,
    Run.distance_m,
    Run.status,
    Run.temperature_c,
    Run.weather_code,
)

RECENT_RUN_LIMIT = 10
MONTHS_SHOWN = 12


# --- Time -----------------------------------------------------------------------


def resolve_timezone(name: str | None) -> tzinfo:
    """The athlete's zone, or UTC when the phone sent nothing usable."""
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return UTC


def zone_name(zone: tzinfo) -> str:
    return getattr(zone, "key", None) or "UTC"


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def month_shift(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


# --- Runs and their metrics -------------------------------------------------------


def _device_ids(account_id: uuid.UUID):
    return select(DeviceLink.device_id).where(DeviceLink.account_id == account_id)


def _counted(account_id: uuid.UUID) -> tuple:
    return (Run.device_id.in_(_device_ids(account_id)), Run.status.in_(COUNTED_STATUSES))


def account_runs(session: Session, account_id: uuid.UUID) -> list[Run]:
    return list(
        session.execute(
            select(Run)
            .options(load_only(*SUMMARY_COLUMNS))
            .where(*_counted(account_id))
            .order_by(Run.started_at)
        ).scalars()
    )


def altitudes_for(samples: Iterable) -> list[float | None] | None:
    values = [getattr(sample, "altitude_m", None) for sample in samples]
    return values if any(value is not None for value in values) else None


def _points_from_samples(samples: list) -> list[TrackPoint]:
    if len(samples) < 2:
        return []
    origin = samples[0].ts
    return [
        TrackPoint(
            t=(sample.ts - origin) / 1000,
            lat=sample.lat,
            lon=sample.lon,
            altitude_m=getattr(sample, "altitude_m", None),
        )
        for sample in samples
    ]


def _points_from_payload(samples: list[dict]) -> list[TrackPoint]:
    """The fixes ingest would have kept: accurate enough, not a repeat of the last."""
    kept: list[dict] = []
    for sample in samples:
        accuracy = sample.get("accuracy_m")
        if accuracy is not None and accuracy > settings.max_accuracy_m:
            continue
        if (
            kept
            and kept[-1].get("lat") == sample.get("lat")
            and kept[-1].get("lon") == sample.get("lon")
        ):
            continue
        kept.append(sample)
    if len(kept) < 2:
        return []
    origin = kept[0]["ts"]
    return [
        TrackPoint(
            t=(sample["ts"] - origin) / 1000,
            lat=float(sample["lat"]),
            lon=float(sample["lon"]),
            altitude_m=sample.get("altitude_m"),
        )
        for sample in kept
    ]


def _parse_linestring(wkt: str) -> list[tuple[float, float]]:
    inner = wkt[wkt.index("(") + 1 : wkt.rindex(")")]
    return [(float(pair.split()[0]), float(pair.split()[1])) for pair in inner.split(",")]


def _points_from_ledger(session: Session, run: Run) -> list[TrackPoint]:
    """Rebuild a run's track from whatever the ledger still holds."""
    samples = (run.raw_payload or {}).get("samples")
    if (
        isinstance(samples, list)
        and len(samples) >= 2
        and all(isinstance(sample, dict) and "ts" in sample for sample in samples)
    ):
        return _points_from_payload(samples)
    if run.geom is None:
        return []
    wkt = session.execute(select(func.ST_AsText(Run.geom)).where(Run.id == run.id)).scalar_one()
    coordinates = _parse_linestring(wkt)
    timestamps = run.sample_ts or []
    altitudes = run.sample_altitude_m or []
    if len(timestamps) != len(coordinates):
        # Retention reduced the route: positions survive, the clock does not.
        return [TrackPoint(t=0.0, lat=lat, lon=lon) for lon, lat in coordinates]
    origin = timestamps[0]
    return [
        TrackPoint(
            t=(ts - origin) / 1000,
            lat=lat,
            lon=lon,
            altitude_m=altitudes[index] if index < len(altitudes) else None,
        )
        for index, ((lon, lat), ts) in enumerate(zip(coordinates, timestamps, strict=True))
    ]


def store_metrics(session: Session, run: Run, points: list[TrackPoint]) -> RunMetrics:
    result = compute_metrics(
        points, distance_m=float(run.distance_m or 0), elapsed_s=run.duration_s
    )
    row = session.get(RunMetrics, run.id)
    if row is None:
        row = RunMetrics(run_id=run.id)
        session.add(row)
    row.metrics_version = METRICS_VERSION
    row.moving_s = result.moving_s
    row.elevation_gain_m = result.elevation_gain_m
    row.elevation_loss_m = result.elevation_loss_m
    row.splits = [
        {
            "index": split.index,
            "distance_m": split.distance_m,
            "moving_s": split.moving_s,
            "elevation_delta_m": split.elevation_delta_m,
        }
        for split in result.splits
    ]
    row.pace_series = [list(point) for point in result.pace_series]
    row.elevation_series = [list(point) for point in result.elevation_series]
    session.execute(delete(RunBestEffort).where(RunBestEffort.run_id == run.id))
    for distance, elapsed in result.best_efforts.items():
        session.add(RunBestEffort(run_id=run.id, distance_m=distance, elapsed_s=elapsed))
    session.flush()
    return row


def record_run_metrics(session: Session, run: Run, samples: list) -> RunMetrics:
    """Called by ingest with the usable samples, before retention can thin them."""
    return store_metrics(session, run, _points_from_samples(samples))


def ensure_metrics(session: Session, runs: list[Run]) -> dict[uuid.UUID, RunMetrics]:
    if not runs:
        return {}
    ids = [run.id for run in runs]
    rows = {
        row.run_id: row
        for row in session.execute(select(RunMetrics).where(RunMetrics.run_id.in_(ids))).scalars()
    }
    for run in runs:
        existing = rows.get(run.id)
        if existing is None or existing.metrics_version != METRICS_VERSION:
            full = session.get(Run, run.id)
            rows[run.id] = store_metrics(session, full, _points_from_ledger(session, full))
    return rows


def apply_new_run_defaults(session: Session, run: Run, device_id: uuid.UUID) -> None:
    """A new run wears the athlete's default shoes unless they say otherwise."""
    shoe = session.execute(
        select(Shoe)
        .join(DeviceLink, DeviceLink.account_id == Shoe.account_id)
        .where(
            DeviceLink.device_id == device_id, Shoe.is_default.is_(True), Shoe.retired.is_(False)
        )
    ).scalar_one_or_none()
    if shoe is not None:
        session.add(RunAnnotation(run_id=run.id, shoe_id=shoe.id))
        session.flush()


# --- Aggregation --------------------------------------------------------------------


@dataclass(frozen=True)
class _Entry:
    run: Run
    local: datetime
    distance_m: float
    moving_s: int
    gain: float | None


def _entries(session: Session, account_id: uuid.UUID, zone: tzinfo) -> list[_Entry]:
    runs = account_runs(session, account_id)
    metrics = ensure_metrics(session, runs)
    return [
        _Entry(
            run=run,
            local=run.started_at.astimezone(zone),
            distance_m=float(run.distance_m or 0),
            moving_s=metrics[run.id].moving_s,
            gain=metrics[run.id].elevation_gain_m,
        )
        for run in runs
    ]


def _totals(entries: list[_Entry]) -> AthleteTotals:
    return AthleteTotals(
        runs=len(entries),
        distance_m=round(sum(entry.distance_m for entry in entries), 1),
        moving_s=sum(entry.moving_s for entry in entries),
        elevation_gain_m=round(sum(entry.gain or 0 for entry in entries), 1),
    )


def _streak(entries: list[_Entry], this_week: date) -> StreakSummary:
    weeks = sorted({week_start(entry.local.date()) for entry in entries})
    if not weeks:
        return StreakSummary(current_weeks=0, best_weeks=0, current_since=None, ran_this_week=False)
    best = length = 1
    for previous, current in zip(weeks, weeks[1:], strict=False):
        length = length + 1 if current - previous == timedelta(weeks=1) else 1
        best = max(best, length)
    ran = set(weeks)
    ran_this_week = this_week in ran
    # A week still in progress has not been missed yet, so the streak stays
    # alive on last week's run until this week is over.
    cursor = this_week if ran_this_week else this_week - timedelta(weeks=1)
    current, since = 0, None
    while cursor in ran:
        current, since = current + 1, cursor
        cursor -= timedelta(weeks=1)
    return StreakSummary(
        current_weeks=current, best_weeks=best, current_since=since, ran_this_week=ran_this_week
    )


def _account_efforts(
    session: Session, account_id: uuid.UUID
) -> list[tuple[int, float, uuid.UUID, datetime]]:
    return [
        tuple(row)
        for row in session.execute(
            select(RunBestEffort.distance_m, RunBestEffort.elapsed_s, Run.id, Run.started_at)
            .join(Run, Run.id == RunBestEffort.run_id)
            .where(*_counted(account_id))
            .order_by(Run.started_at, RunBestEffort.distance_m)
        ).all()
    ]


def _personal_records(efforts) -> dict[uuid.UUID, list[int]]:
    """Distances at which each run was the fastest yet, when it was run."""
    fastest: dict[int, float] = {}
    records: dict[uuid.UUID, list[int]] = defaultdict(list)
    for distance, elapsed, run_id, _ in efforts:
        if distance not in fastest or elapsed < fastest[distance]:
            fastest[distance] = elapsed
            records[run_id].append(distance)
    return records


def _captures(session: Session, run_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not run_ids:
        return {}
    return dict(
        session.execute(
            select(RunTerritorySegment.run_id, func.count())
            .where(
                RunTerritorySegment.run_id.in_(run_ids),
                or_(
                    RunTerritorySegment.capture_method == "loop",
                    RunTerritorySegment.caused_ownership_change.is_(True),
                ),
            )
            .group_by(RunTerritorySegment.run_id)
        ).all()
    )


def _goal_progress(goal: WeeklyGoal | None, week: AthleteTotals) -> GoalProgress | None:
    if goal is None:
        return None
    value = {"distance": week.distance_m, "time": float(week.moving_s), "runs": float(week.runs)}[
        goal.metric
    ]
    return GoalProgress(
        metric=goal.metric, target=goal.target, value=value, updated_at=goal.updated_at
    )


def athlete_stats(
    session: Session,
    account: Account,
    tz_name: str | None,
    *,
    weeks: int = 12,
    now: datetime | None = None,
) -> AthleteStats:
    zone = resolve_timezone(tz_name)
    now = now or datetime.now(UTC)
    local_now = now.astimezone(zone)
    today = local_now.date()
    this_week = week_start(today)
    entries = _entries(session, account.id, zone)

    by_week: dict[date, list[_Entry]] = defaultdict(list)
    by_month: dict[tuple[int, int], list[_Entry]] = defaultdict(list)
    for entry in entries:
        by_week[week_start(entry.local.date())].append(entry)
        by_month[(entry.local.year, entry.local.month)].append(entry)

    week_entries = by_week.get(this_week, [])
    week_days = [0.0] * 7
    for entry in week_entries:
        week_days[entry.local.weekday()] += entry.distance_m

    recent = [entry for entry in entries if entry.local >= local_now - timedelta(days=28)]
    recent_totals = _totals(recent)

    week_buckets = []
    for offset in range(weeks - 1, -1, -1):
        start = this_week - timedelta(weeks=offset)
        totals = _totals(by_week.get(start, []))
        week_buckets.append(WeekBucket(week_start=start, **totals.model_dump()))

    month_buckets = []
    for offset in range(MONTHS_SHOWN - 1, -1, -1):
        year, month = month_shift(today.year, today.month, -offset)
        totals = _totals(by_month.get((year, month), []))
        month_buckets.append(MonthBucket(month=f"{year:04d}-{month:02d}", **totals.model_dump()))

    fastest: dict[int, tuple[float, uuid.UUID, datetime]] = {}
    for distance, elapsed, run_id, started_at in _account_efforts(session, account.id):
        if distance not in fastest or elapsed < fastest[distance][0]:
            fastest[distance] = (elapsed, run_id, started_at)

    longest = max(entries, key=lambda entry: entry.distance_m, default=None)
    climbs = [entry for entry in entries if entry.gain]
    climb = max(climbs, key=lambda entry: entry.gain, default=None)

    device_ids = _device_ids(account.id)
    held = session.execute(
        select(func.count())
        .select_from(TerritoryOwnership)
        .where(TerritoryOwnership.owner_device_id.in_(device_ids))
    ).scalar_one()
    captured = sum(_captures(session, [entry.run.id for entry in entries]).values())

    week_totals = _totals(week_entries)
    return AthleteStats(
        timezone=zone_name(zone),
        generated_at=now,
        this_week=week_totals,
        this_month=_totals(by_month.get((today.year, today.month), [])),
        year_to_date=_totals([entry for entry in entries if entry.local.year == today.year]),
        all_time=_totals(entries),
        last_four_weeks=FourWeekAverages(
            runs_per_week=round(recent_totals.runs / 4, 2),
            distance_m_per_week=round(recent_totals.distance_m / 4, 1),
            moving_s_per_week=round(recent_totals.moving_s / 4, 1),
        ),
        week_days_m=[round(value, 1) for value in week_days],
        weeks=week_buckets,
        months=month_buckets,
        streak=_streak(entries, this_week),
        best_efforts=[
            BestEffortRecord(
                distance_m=distance, elapsed_s=elapsed, run_id=run_id, started_at=started_at
            )
            for distance, (elapsed, run_id, started_at) in sorted(fastest.items())
        ],
        longest_run=None
        if longest is None
        else RunRecord(
            run_id=longest.run.id,
            started_at=longest.run.started_at,
            distance_m=longest.distance_m,
            elevation_gain_m=longest.gain,
        ),
        biggest_climb=None
        if climb is None
        else RunRecord(
            run_id=climb.run.id,
            started_at=climb.run.started_at,
            distance_m=climb.distance_m,
            elevation_gain_m=climb.gain,
        ),
        goal=_goal_progress(session.get(WeeklyGoal, account.id), week_totals),
        territories_held=int(held or 0),
        territories_captured=int(captured),
    )


# --- The training log -------------------------------------------------------------------


def _summaries(
    session: Session, account_id: uuid.UUID, runs: list[Run], *, private: bool
) -> list[RunSummary]:
    # Personal records depend on every earlier run, so all of them need metrics.
    ensure_metrics(session, account_runs(session, account_id))
    metrics = ensure_metrics(session, runs)
    ids = [run.id for run in runs]
    annotations = (
        {
            row.run_id: row
            for row in session.execute(
                select(RunAnnotation).where(RunAnnotation.run_id.in_(ids))
            ).scalars()
        }
        if ids
        else {}
    )
    shoes = {
        shoe.id: shoe
        for shoe in session.execute(select(Shoe).where(Shoe.account_id == account_id)).scalars()
    }
    captures = _captures(session, ids)
    records = _personal_records(_account_efforts(session, account_id))
    summaries = []
    for run in runs:
        annotation = annotations.get(run.id)
        shoe = shoes.get(annotation.shoe_id) if annotation and annotation.shoe_id else None
        summaries.append(
            RunSummary(
                run_id=run.id,
                started_at=run.started_at,
                ended_at=run.ended_at,
                distance_m=round(float(run.distance_m or 0), 1),
                moving_s=metrics[run.id].moving_s,
                elapsed_s=run.duration_s,
                elevation_gain_m=metrics[run.id].elevation_gain_m,
                title=annotation.title if annotation else None,
                note=annotation.note if annotation and private else None,
                shoe=ShoeRef(id=shoe.id, name=shoe.name) if shoe and private else None,
                captures=captures.get(run.id, 0),
                personal_records=records.get(run.id, []),
                temperature_c=run.temperature_c,
                weather_code=run.weather_code,
            )
        )
    return summaries


def runs_page(
    session: Session,
    account: Account,
    *,
    tz_name: str | None,
    month: str | None,
    before: datetime | None,
    limit: int,
) -> RunPage:
    zone = resolve_timezone(tz_name)
    query = select(Run).options(load_only(*SUMMARY_COLUMNS)).where(*_counted(account.id))
    if month:
        year, month_number = (int(part) for part in month.split("-"))
        next_year, next_month = month_shift(year, month_number, 1)
        query = query.where(
            Run.started_at >= datetime(year, month_number, 1, tzinfo=zone),
            Run.started_at < datetime(next_year, next_month, 1, tzinfo=zone),
        )
        runs = list(session.execute(query.order_by(Run.started_at.desc())).scalars())
        return RunPage(runs=_summaries(session, account.id, runs, private=True), next_before=None)
    if before is not None:
        query = query.where(Run.started_at < before)
    runs = list(session.execute(query.order_by(Run.started_at.desc()).limit(limit + 1)).scalars())
    more = len(runs) > limit
    runs = runs[:limit]
    return RunPage(
        runs=_summaries(session, account.id, runs, private=True),
        next_before=runs[-1].started_at if more else None,
    )


def recent_public_runs(
    session: Session, account: Account, *, limit: int = RECENT_RUN_LIMIT
) -> list[RunSummary]:
    runs = list(
        session.execute(
            select(Run)
            .options(load_only(*SUMMARY_COLUMNS))
            .where(*_counted(account.id))
            .order_by(Run.started_at.desc())
            .limit(limit)
        ).scalars()
    )
    return _summaries(session, account.id, runs, private=False)


def _owned_run(session: Session, account_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    run = session.execute(
        select(Run).where(Run.id == run_id, *_counted(account_id))
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


def run_activity(session: Session, account: Account, run_id: uuid.UUID) -> RunActivity:
    run = _owned_run(session, account.id, run_id)
    summary = _summaries(session, account.id, [run], private=True)[0]
    metrics = session.get(RunMetrics, run.id)
    efforts = _account_efforts(session, account.id)
    records = _personal_records(efforts)
    by_distance: dict[int, list[float]] = defaultdict(list)
    for distance, elapsed, _, _ in efforts:
        by_distance[distance].append(elapsed)

    run_efforts = []
    for distance, elapsed, effort_run_id, _ in efforts:
        if effort_run_id != run.id:
            continue
        rank = 1 + sum(1 for other in by_distance[distance] if other < elapsed)
        run_efforts.append(
            RunEffort(
                distance_m=distance,
                elapsed_s=elapsed,
                rank=rank if rank <= 3 else None,
                personal_record=distance in records.get(run.id, []),
            )
        )
    athlete = session.get(AthleteSettings, account.id)
    return RunActivity(
        summary=summary,
        splits=[RunSplit(**split) for split in metrics.splits],
        pace_series=[tuple(point) for point in metrics.pace_series],
        elevation_series=[tuple(point) for point in metrics.elevation_series],
        best_efforts=run_efforts,
        elevation_loss_m=metrics.elevation_loss_m,
        calories=calories(float(run.distance_m or 0), athlete.weight_kg if athlete else None),
    )


def update_annotation(
    session: Session, account: Account, run_id: uuid.UUID, change: RunAnnotationUpdate
) -> RunSummary:
    run = _owned_run(session, account.id, run_id)
    row = session.get(RunAnnotation, run.id)
    if row is None:
        row = RunAnnotation(run_id=run.id)
        session.add(row)
    sent = change.model_fields_set
    if "title" in sent:
        row.title = (change.title or "").strip() or None
    if "note" in sent:
        row.note = (change.note or "").strip() or None
    if "shoe_id" in sent:
        if change.shoe_id is not None:
            shoe = session.get(Shoe, change.shoe_id)
            if shoe is None or shoe.account_id != account.id:
                raise HTTPException(404, "Shoe not found")
        row.shoe_id = change.shoe_id
    session.flush()
    return _summaries(session, account.id, [run], private=True)[0]


# --- Goals and settings --------------------------------------------------------------


def goal_progress(session: Session, account: Account, tz_name: str | None) -> GoalProgress | None:
    goal = session.get(WeeklyGoal, account.id)
    if goal is None:
        return None
    zone = resolve_timezone(tz_name)
    this_week = week_start(datetime.now(UTC).astimezone(zone).date())
    week = [
        entry
        for entry in _entries(session, account.id, zone)
        if week_start(entry.local.date()) == this_week
    ]
    return _goal_progress(goal, _totals(week))


def set_goal(
    session: Session, account: Account, change: WeeklyGoalUpdate, tz_name: str | None
) -> GoalProgress:
    goal = session.get(WeeklyGoal, account.id)
    if goal is None:
        goal = WeeklyGoal(account_id=account.id)
        session.add(goal)
    goal.metric = change.metric
    goal.target = change.target
    goal.updated_at = datetime.now(UTC)
    session.flush()
    return goal_progress(session, account, tz_name)


def clear_goal(session: Session, account: Account) -> None:
    session.execute(delete(WeeklyGoal).where(WeeklyGoal.account_id == account.id))


def get_settings(session: Session, account: Account) -> AthleteSettingsRecord:
    row = session.get(AthleteSettings, account.id)
    return AthleteSettingsRecord(weight_kg=row.weight_kg if row else None)


def put_settings(
    session: Session, account: Account, change: AthleteSettingsRecord
) -> AthleteSettingsRecord:
    row = session.get(AthleteSettings, account.id)
    if row is None:
        row = AthleteSettings(account_id=account.id)
        session.add(row)
    row.weight_kg = change.weight_kg
    row.updated_at = datetime.now(UTC)
    session.flush()
    return get_settings(session, account)


# --- Shoes --------------------------------------------------------------------------------


def _shoe_record(session: Session, shoe: Shoe) -> ShoeRecord:
    distance, count = session.execute(
        select(func.coalesce(func.sum(Run.distance_m), 0), func.count(Run.id))
        .select_from(RunAnnotation)
        .join(Run, Run.id == RunAnnotation.run_id)
        .where(RunAnnotation.shoe_id == shoe.id, Run.status.in_(COUNTED_STATUSES))
    ).one()
    return ShoeRecord(
        id=shoe.id,
        name=shoe.name,
        is_default=shoe.is_default,
        retired=shoe.retired,
        distance_m=round(float(distance or 0), 1),
        runs=int(count or 0),
        created_at=shoe.created_at,
    )


def _own_shoe(session: Session, account: Account, shoe_id: uuid.UUID) -> Shoe:
    shoe = session.get(Shoe, shoe_id)
    if shoe is None or shoe.account_id != account.id:
        raise HTTPException(404, "Shoe not found")
    return shoe


def _clear_default(session: Session, account: Account) -> None:
    # The unique index allows one default; clear it before setting another.
    session.execute(update(Shoe).where(Shoe.account_id == account.id).values(is_default=False))
    session.flush()


def list_shoes(session: Session, account: Account) -> list[ShoeRecord]:
    shoes = session.execute(
        select(Shoe).where(Shoe.account_id == account.id).order_by(Shoe.retired, Shoe.created_at)
    ).scalars()
    return [_shoe_record(session, shoe) for shoe in shoes]


def create_shoe(session: Session, account: Account, change: ShoeCreate) -> ShoeRecord:
    first = (
        session.execute(
            select(func.count()).select_from(Shoe).where(Shoe.account_id == account.id)
        ).scalar_one()
        == 0
    )
    make_default = change.is_default or first
    if make_default:
        _clear_default(session, account)
    shoe = Shoe(account_id=account.id, name=change.name.strip(), is_default=make_default)
    session.add(shoe)
    session.flush()
    session.refresh(shoe, ["created_at"])
    return _shoe_record(session, shoe)


def update_shoe(
    session: Session, account: Account, shoe_id: uuid.UUID, change: ShoeUpdate
) -> ShoeRecord:
    shoe = _own_shoe(session, account, shoe_id)
    sent = change.model_fields_set
    if "name" in sent and change.name:
        shoe.name = change.name.strip()
    if "retired" in sent and change.retired is not None:
        shoe.retired = change.retired
        if change.retired:
            shoe.is_default = False
    if "is_default" in sent and change.is_default is not None:
        if change.is_default:
            if shoe.retired:
                raise HTTPException(422, "Retired shoes cannot be the default.")
            _clear_default(session, account)
            session.refresh(shoe)
        shoe.is_default = change.is_default
    session.flush()
    return _shoe_record(session, shoe)


def delete_shoe(session: Session, account: Account, shoe_id: uuid.UUID) -> None:
    shoe = _own_shoe(session, account, shoe_id)
    session.delete(shoe)
    session.flush()
