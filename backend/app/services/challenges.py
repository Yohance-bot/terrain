"""Measuring a challenge, settling it, and moving a lost stake.

Every metric here reads a column the run pipeline already writes. Nothing is
self-reported by a client, and nothing new is tracked for the sake of social
features: a challenge is a question asked of the existing ledger.

Runs are counted by when they *finished*, so a run straddling the end of a
window belongs to whichever side of it the run ended on, and "fastest to 10 km"
has an unambiguous instant to compare.
"""

import uuid
from datetime import UTC, datetime, timedelta

from geoalchemy2 import Geography, Geometry
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Account,
    CapturedArea,
    Challenge,
    ChallengeStake,
    DeviceLink,
    Run,
    RunTerritorySegment,
)
from app.services.social import record_event

# Only what the pipeline measures. Step count is deliberately absent: nothing in
# the app counts steps, and a challenge must never be settled on a number the
# server cannot verify.
METRICS = ("distance", "runs", "moving_time", "captured_area", "territories")
COMPARISONS = ("most", "fastest_to")

METRIC_LABELS = {
    "distance": "distance",
    "runs": "runs",
    "moving_time": "moving time",
    "captured_area": "captured area",
    "territories": "territories taken",
}

# How long an unanswered challenge stands before it lapses. Long enough to catch
# someone the next evening, short enough that a stake is not tied up for days.
DEFAULT_ACCEPT_WINDOW = timedelta(hours=36)


def _device_ids(session: Session, account_id: uuid.UUID):
    return select(DeviceLink.device_id).where(DeviceLink.account_id == account_id)


def _runs_in_window(session: Session, account_id: uuid.UUID, start: datetime, end: datetime):
    return (
        select(Run)
        .where(
            Run.device_id.in_(_device_ids(session, account_id)),
            Run.status == "applied",
            Run.ended_at > start,
            Run.ended_at <= end,
        )
        .order_by(Run.ended_at)
    )


def measure(
    session: Session, account_id: uuid.UUID, metric: str, start: datetime, end: datetime
) -> float:
    """This player's total for one metric over the challenge window."""
    devices = _device_ids(session, account_id)
    finished = (Run.status == "applied", Run.ended_at > start, Run.ended_at <= end)

    if metric == "distance":
        total = session.execute(
            select(func.coalesce(func.sum(Run.distance_m), 0)).where(
                Run.device_id.in_(devices), *finished
            )
        ).scalar_one()
    elif metric == "runs":
        total = session.execute(
            select(func.count()).select_from(Run).where(Run.device_id.in_(devices), *finished)
        ).scalar_one()
    elif metric == "moving_time":
        total = session.execute(
            select(func.coalesce(func.sum(Run.duration_s), 0)).where(
                Run.device_id.in_(devices), *finished
            )
        ).scalar_one()
    elif metric == "captured_area":
        total = session.execute(
            select(func.coalesce(func.sum(func.ST_Area(CapturedArea.geom)), 0))
            .join(Run, Run.id == CapturedArea.run_id)
            .where(CapturedArea.owner_device_id.in_(devices), *finished)
        ).scalar_one()
    elif metric == "territories":
        total = session.execute(
            select(func.count())
            .select_from(RunTerritorySegment)
            .join(Run, Run.id == RunTerritorySegment.run_id)
            .where(
                RunTerritorySegment.device_id.in_(devices),
                RunTerritorySegment.caused_ownership_change.is_(True),
                *finished,
            )
        ).scalar_one()
    else:
        raise ValueError(f"unknown metric {metric}")
    return float(total or 0)


def first_reached(
    session: Session,
    account_id: uuid.UUID,
    metric: str,
    target: float,
    start: datetime,
    end: datetime,
) -> datetime | None:
    """When this player's running total first passed the target, if it did.

    Walks finished runs in order rather than asking the database for a window
    function, because a challenge covers days rather than thousands of rows.
    """
    running_total = 0.0
    for run in session.execute(_runs_in_window(session, account_id, start, end)).scalars():
        if metric == "distance":
            running_total += float(run.distance_m or 0)
        elif metric == "runs":
            running_total += 1
        elif metric == "moving_time":
            running_total += float(run.duration_s or 0)
        else:
            # Area and territory counts are not cumulative per run in a way that
            # gives a meaningful "first past the post" instant.
            raise ValueError(f"{metric} cannot be raced to a target")
        if running_total >= target:
            return run.ended_at
    return None


def captured_area_m2(session: Session, account_id: uuid.UUID) -> float:
    """Total enclosed area this player currently holds.

    Overlapping loops are unioned before measuring, the same way the map layer
    normalises them, so an entry condition cannot be met by running the same
    loop twice.
    """
    union = func.ST_UnaryUnion(
        func.ST_Collect(
            func.ST_MakeValid(CapturedArea.geom.cast(Geometry(geometry_type="GEOMETRY", srid=4326)))
        )
    )
    geometry = session.execute(
        select(func.ST_Area(union.cast(Geography(geometry_type="GEOMETRY", srid=4326))))
        .join(Run, Run.id == CapturedArea.run_id)
        .where(
            CapturedArea.owner_device_id.in_(_device_ids(session, account_id)),
            Run.status == "applied",
        )
    ).scalar_one_or_none()
    return float(geometry or 0)


def describe(challenge: Challenge, value: float) -> str:
    """A metric value in the units a player reads it in."""
    if challenge.metric == "distance":
        return f"{value / 1000:.2f} km"
    if challenge.metric == "moving_time":
        return f"{value / 60:.0f} min"
    if challenge.metric == "captured_area":
        return f"{value / 1000:.0f} k m²" if value >= 1000 else f"{value:.0f} m²"
    return f"{value:.0f}"


def settle(session: Session, challenge: Challenge, *, now: datetime | None = None) -> Challenge:
    """Compare both players and write the outcome. Idempotent once resolved."""
    if challenge.status != "accepted":
        return challenge
    now = now or datetime.now(UTC)

    window = (challenge.window_start, challenge.window_end)
    challenger_total = measure(session, challenge.challenger_id, challenge.metric, *window)
    opponent_total = measure(session, challenge.opponent_id, challenge.metric, *window)
    challenge.challenger_value = challenger_total
    challenge.opponent_value = opponent_total

    if challenge.comparison == "fastest_to":
        target = float(challenge.target_value or 0)
        challenger_at = first_reached(
            session,
            challenge.challenger_id,
            challenge.metric,
            target,
            challenge.window_start,
            challenge.window_end,
        )
        opponent_at = first_reached(
            session,
            challenge.opponent_id,
            challenge.metric,
            target,
            challenge.window_start,
            challenge.window_end,
        )
        if challenger_at is None and opponent_at is None:
            outcome = "nobody"
        elif opponent_at is None or (challenger_at is not None and challenger_at < opponent_at):
            outcome = "challenger"
        elif challenger_at is None or opponent_at < challenger_at:
            outcome = "opponent"
        else:
            outcome = "draw"
    elif challenger_total == opponent_total:
        # Nobody moved at all is a different story from a genuine tie, and the
        # stake should not change hands on either.
        outcome = "nobody" if challenger_total == 0 else "draw"
    else:
        outcome = "challenger" if challenger_total > opponent_total else "opponent"

    challenge.outcome = outcome
    challenge.winner_id = {
        "challenger": challenge.challenger_id,
        "opponent": challenge.opponent_id,
    }.get(outcome)
    challenge.status = "resolved"
    challenge.resolved_at = now
    challenge.updated_at = now

    if challenge.winner_id is not None:
        transfer_stake(session, challenge)

    challenger = session.get(Account, challenge.challenger_id)
    opponent = session.get(Account, challenge.opponent_id)
    for account, rival, own, theirs in (
        (challenger, opponent, challenger_total, opponent_total),
        (opponent, challenger, opponent_total, challenger_total),
    ):
        if account is None or rival is None:
            continue
        if challenge.winner_id is None:
            headline = "Your challenge ended level"
        elif challenge.winner_id == account.id:
            headline = f"You beat {rival.display_name}"
        else:
            headline = f"{rival.display_name} beat you"
        record_event(
            session,
            account.id,
            "challenge_resolved",
            f"{headline}: {describe(challenge, own)} to {describe(challenge, theirs)}.",
            actor_id=rival.id,
            subject_id=challenge.id,
        )
    return challenge


def transfer_stake(session: Session, challenge: Challenge) -> None:
    """Move a staked loop closure to the winner.

    The stake follows the outcome rather than the side that put it up: if the
    challenger wins, the area they staked simply stays theirs.
    """
    stake = session.get(ChallengeStake, challenge.id)
    if stake is None or stake.staked_area_id is None or stake.transferred_at is not None:
        return
    area = session.get(CapturedArea, stake.staked_area_id)
    if area is None or challenge.winner_id is None:
        return

    winner_device = session.execute(
        select(DeviceLink.device_id)
        .where(DeviceLink.account_id == challenge.winner_id)
        .order_by(DeviceLink.linked_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if winner_device is None or winner_device == area.owner_device_id:
        return

    area.transferred_from_device_id = area.owner_device_id
    area.transferred_at = challenge.resolved_at or datetime.now(UTC)
    area.transferred_by_challenge_id = challenge.id
    area.owner_device_id = winner_device
    stake.transferred_at = area.transferred_at


def resolve_due(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Expire unanswered challenges and settle finished ones.

    Safe to run repeatedly and from anywhere — a read path, an operator, or a
    cron ping — because both transitions are guarded by the current status.
    """
    now = now or datetime.now(UTC)

    lapsed = list(
        session.execute(
            select(Challenge).where(
                Challenge.status == "pending", Challenge.accept_deadline <= now
            )
        ).scalars()
    )
    for challenge in lapsed:
        challenge.status = "expired"
        challenge.updated_at = now
        challenger = session.get(Account, challenge.challenger_id)
        opponent = session.get(Account, challenge.opponent_id)
        if challenger is not None and opponent is not None:
            record_event(
                session,
                challenge.challenger_id,
                "challenge_expired",
                f"{opponent.display_name} did not answer your challenge in time.",
                actor_id=challenge.opponent_id,
                subject_id=challenge.id,
            )

    due = list(
        session.execute(
            select(Challenge).where(Challenge.status == "accepted", Challenge.window_end <= now)
        ).scalars()
    )
    for challenge in due:
        settle(session, challenge, now=now)

    return {"expired": len(lapsed), "resolved": len(due)}
