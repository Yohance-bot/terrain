"""Challenges between friends, and the loop closures staked on them.

A challenge's window starts when it is *accepted*, not when it is sent, so a
slow reply never eats into the time someone has to run. An unanswered challenge
lapses on its own, and a stake is only ever moved by the resolver.

Nothing here can be settled by a client: values come from the run ledger.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_operations_token
from app.api.v1.social import current_account, public
from app.core.db import get_session
from app.models import Account, CapturedArea, Challenge, ChallengeStake, Run
from app.schemas import (
    ChallengeCreate,
    ChallengeRecord,
    ChallengeStakeSummary,
    StakeableArea,
)
from app.services.challenges import (
    DEFAULT_ACCEPT_WINDOW,
    METRIC_LABELS,
    captured_area_m2,
    measure,
    resolve_due,
    settle,
)
from app.services.social import account_device_ids, record_event, require_friend

router = APIRouter(prefix="/social/challenges", tags=["social"])

# Metrics with no meaningful "first past the post" instant cannot be raced to a
# target; they can still be compared as totals.
RACEABLE_METRICS = ("distance", "runs", "moving_time")

OPEN_STATUSES = ("pending", "accepted")


def _stake_summary(session: Session, challenge: Challenge) -> ChallengeStakeSummary | None:
    stake = session.get(ChallengeStake, challenge.id)
    if stake is None:
        return None
    area_m2 = None
    if stake.staked_area_id is not None:
        area_m2 = session.execute(
            select(func.ST_Area(CapturedArea.geom)).where(CapturedArea.id == stake.staked_area_id)
        ).scalar_one_or_none()
    return ChallengeStakeSummary(
        staked_area_id=stake.staked_area_id,
        staked_area_m2=float(area_m2) if area_m2 is not None else None,
        require_opponent_area_m2=stake.require_opponent_area_m2,
        transferred_at=stake.transferred_at,
    )


def _record(session: Session, challenge: Challenge, viewer: Account) -> ChallengeRecord:
    challenger = session.get(Account, challenge.challenger_id)
    opponent = session.get(Account, challenge.opponent_id)
    challenger_value = challenge.challenger_value
    opponent_value = challenge.opponent_value
    if challenge.status == "accepted":
        # Live standings while the window is open, so both players can see where
        # they are without waiting for the result.
        window = (challenge.window_start, challenge.window_end)
        challenger_value = measure(session, challenge.challenger_id, challenge.metric, *window)
        opponent_value = measure(session, challenge.opponent_id, challenge.metric, *window)
    return ChallengeRecord(
        id=challenge.id,
        challenger=public(session, challenger, viewer.id),
        opponent=public(session, opponent, viewer.id),
        role="challenger" if challenge.challenger_id == viewer.id else "opponent",
        metric=challenge.metric,
        comparison=challenge.comparison,
        target_value=challenge.target_value,
        window_start=challenge.window_start,
        window_end=challenge.window_end,
        goal_text=challenge.goal_text,
        status=challenge.status,
        accept_deadline=challenge.accept_deadline,
        outcome=challenge.outcome,
        winner_id=challenge.winner_id,
        challenger_value=challenger_value,
        opponent_value=opponent_value,
        stake=_stake_summary(session, challenge),
        resolved_at=challenge.resolved_at,
        created_at=challenge.created_at,
    )


def _mine(session: Session, challenge_id: uuid.UUID, account: Account) -> Challenge:
    challenge = session.get(Challenge, challenge_id)
    if challenge is None or account.id not in (challenge.challenger_id, challenge.opponent_id):
        raise HTTPException(404, "That challenge no longer exists.")
    return challenge


@router.post("", response_model=ChallengeRecord, status_code=201)
def create_challenge(
    payload: ChallengeCreate,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> ChallengeRecord:
    require_friend(session, account.id, payload.opponent_id)
    opponent = session.get(Account, payload.opponent_id)
    if opponent is None:
        raise HTTPException(404, "That account no longer exists.")

    if payload.comparison == "fastest_to":
        if payload.target_value is None:
            raise HTTPException(422, "A race to a target needs a target value.")
        if payload.metric not in RACEABLE_METRICS:
            raise HTTPException(
                422, f"{METRIC_LABELS[payload.metric]} can be compared as a total, not raced to."
            )

    open_already = session.execute(
        select(Challenge).where(
            Challenge.status.in_(OPEN_STATUSES),
            or_(
                (Challenge.challenger_id == account.id)
                & (Challenge.opponent_id == payload.opponent_id),
                (Challenge.challenger_id == payload.opponent_id)
                & (Challenge.opponent_id == account.id),
            ),
        )
    ).first()
    if open_already:
        raise HTTPException(
            409, f"You already have a challenge running with {opponent.display_name}."
        )

    now = datetime.now(UTC)
    challenge = Challenge(
        challenger_id=account.id,
        opponent_id=payload.opponent_id,
        metric=payload.metric,
        comparison=payload.comparison,
        target_value=payload.target_value,
        # Provisional: the real window is stamped when the opponent accepts, so
        # a pending challenge never burns the time it promises.
        window_start=now,
        window_end=now + timedelta(days=payload.window_days),
        goal_text=payload.goal_text.strip(),
        status="pending",
        accept_deadline=now + DEFAULT_ACCEPT_WINDOW,
    )
    session.add(challenge)
    session.flush()

    if payload.stake is not None:
        _attach_stake(session, challenge, payload, account)

    record_event(
        session,
        opponent.id,
        "challenge_received",
        f"{account.display_name} challenged you: {challenge.goal_text}",
        actor_id=account.id,
        subject_id=challenge.id,
    )
    return _record(session, challenge, account)


def _attach_stake(
    session: Session, challenge: Challenge, payload: ChallengeCreate, account: Account
) -> None:
    """Validate and record what the challenger is putting up."""
    stake_input = payload.stake
    staked_area_id = None
    if stake_input.staked_area_id is not None:
        area = session.get(CapturedArea, stake_input.staked_area_id)
        devices = account_device_ids(session, account.id)
        if area is None or area.owner_device_id not in devices:
            raise HTTPException(422, "You can only stake a loop closure you own.")
        # A stake must be settled land: an area from a run still being reviewed
        # could vanish before the challenge ends.
        run = session.get(Run, area.run_id)
        if run is None or run.status != "applied":
            raise HTTPException(422, "That loop closure is not confirmed yet.")
        staked_area_id = area.id

    session.add(
        ChallengeStake(
            challenge_id=challenge.id,
            staked_area_id=staked_area_id,
            require_opponent_area_m2=stake_input.require_opponent_area_m2,
        )
    )
    session.flush()


@router.get("", response_model=list[ChallengeRecord])
def list_challenges(
    include_finished: bool = True,
    limit: int = Query(default=50, ge=1, le=200),
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> list[ChallengeRecord]:
    """Reading the list also settles anything that has come due.

    There is no worker process, so the read path is the reliable trigger; the
    tick endpoint below covers players who never open the app.
    """
    resolve_due(session)
    statement = (
        select(Challenge)
        .where(
            or_(Challenge.challenger_id == account.id, Challenge.opponent_id == account.id)
        )
        .order_by(Challenge.created_at.desc())
        .limit(limit)
    )
    if not include_finished:
        statement = statement.where(Challenge.status.in_(OPEN_STATUSES))
    found = session.execute(statement).scalars()
    return [_record(session, challenge, account) for challenge in found]


@router.get("/stakeable", response_model=list[StakeableArea])
def stakeable_areas(
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> list[StakeableArea]:
    """Loop closures this player can put up.

    The public map merges a player's overlapping loops into one shape; a stake
    needs the individual areas, because a wager transfers one of them.
    """
    rows = session.execute(
        select(CapturedArea, func.ST_Area(CapturedArea.geom))
        .join(Run, Run.id == CapturedArea.run_id)
        .where(
            CapturedArea.owner_device_id.in_(account_device_ids(session, account.id)),
            Run.status == "applied",
        )
        .order_by(CapturedArea.created_at.desc())
    ).all()
    return [
        StakeableArea(
            id=area.id,
            area_m2=float(area_m2 or 0),
            run_id=area.run_id,
            created_at=area.created_at,
        )
        for area, area_m2 in rows
    ]


@router.post("/{challenge_id}/accept", response_model=ChallengeRecord)
def accept_challenge(
    challenge_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> ChallengeRecord:
    challenge = _mine(session, challenge_id, account)
    if challenge.opponent_id != account.id:
        raise HTTPException(403, "Only the person challenged can accept.")
    if challenge.status != "pending":
        raise HTTPException(409, "That challenge is no longer open.")

    now = datetime.now(UTC)
    if challenge.accept_deadline <= now:
        challenge.status = "expired"
        raise HTTPException(409, "That challenge has expired.")

    stake = session.get(ChallengeStake, challenge.id)
    if stake is not None and stake.require_opponent_area_m2:
        held = captured_area_m2(session, account.id)
        if held < stake.require_opponent_area_m2:
            raise HTTPException(
                403,
                "You need at least "
                f"{stake.require_opponent_area_m2:.0f} m² of captured area to accept this. "
                f"You currently hold {held:.0f} m².",
            )

    # The promised window starts now, keeping its original length.
    length = challenge.window_end - challenge.window_start
    challenge.window_start = now
    challenge.window_end = now + length
    challenge.status = "accepted"
    challenge.updated_at = now

    record_event(
        session,
        challenge.challenger_id,
        "challenge_accepted",
        f"{account.display_name} accepted your challenge. It runs until "
        f"{challenge.window_end:%d %b %H:%M}.",
        actor_id=account.id,
        subject_id=challenge.id,
    )
    return _record(session, challenge, account)


@router.post("/{challenge_id}/decline", response_model=ChallengeRecord)
def decline_challenge(
    challenge_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> ChallengeRecord:
    challenge = _mine(session, challenge_id, account)
    if challenge.opponent_id != account.id:
        raise HTTPException(403, "Only the person challenged can decline.")
    if challenge.status != "pending":
        raise HTTPException(409, "That challenge is no longer open.")
    challenge.status = "declined"
    challenge.updated_at = datetime.now(UTC)
    record_event(
        session,
        challenge.challenger_id,
        "challenge_declined",
        f"{account.display_name} declined your challenge.",
        actor_id=account.id,
        subject_id=challenge.id,
    )
    return _record(session, challenge, account)


@router.post("/{challenge_id}/cancel", response_model=ChallengeRecord)
def cancel_challenge(
    challenge_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> ChallengeRecord:
    """Withdraw a challenge you sent, before it has been accepted.

    Once someone has accepted and started running against it, the challenge is
    theirs as much as yours; pulling it out from under them is exactly the kind
    of thing that turns rivalry into resentment.
    """
    challenge = _mine(session, challenge_id, account)
    if challenge.challenger_id != account.id:
        raise HTTPException(403, "Only the challenger can cancel.")
    if challenge.status != "pending":
        raise HTTPException(409, "An accepted challenge has to play out.")
    challenge.status = "cancelled"
    challenge.updated_at = datetime.now(UTC)
    record_event(
        session,
        challenge.opponent_id,
        "challenge_cancelled",
        f"{account.display_name} withdrew their challenge.",
        actor_id=account.id,
        subject_id=challenge.id,
    )
    return _record(session, challenge, account)


@router.post("/tick", dependencies=[Depends(require_admin_operations_token)])
def tick(session: Session = Depends(get_session)) -> dict[str, int]:
    """Expire and settle everything that is due.

    Idempotent, so it can be called on any schedule from outside the app; there
    is no worker in the deployment to own this.
    """
    return resolve_due(session)


@router.post("/{challenge_id}/settle", response_model=ChallengeRecord)
def settle_now(
    challenge_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> ChallengeRecord:
    """Settle a challenge whose window has already closed."""
    challenge = _mine(session, challenge_id, account)
    if challenge.status != "accepted":
        raise HTTPException(409, "That challenge is not running.")
    if challenge.window_end > datetime.now(UTC):
        raise HTTPException(409, "This challenge is still running.")
    settle(session, challenge)
    return _record(session, challenge, account)
