"""Operational visibility into the social layer.

Read-only, and deliberately narrow about location: operators can see *that* two
players share position with each other, never where anyone is. `live_positions`
is never read here. The same rule that keeps a player's location behind their own
opt-in keeps it out of the console.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_operations_token
from app.core.db import get_session
from app.models import (
    Account,
    CapturedArea,
    Challenge,
    ChallengeStake,
    FriendShareSettings,
    Friendship,
    GhostAttempt,
    GhostRun,
    LivePosition,
    Race,
    SocialEvent,
)
from app.services.challenges import resolve_due
from app.services.social import POSITION_FRESHNESS

router = APIRouter(
    prefix="/admin/social",
    tags=["internal-admin-social"],
    dependencies=[Depends(require_admin_operations_token)],
)


class SocialOverview(BaseModel):
    friendships_accepted: int
    friend_requests_pending: int
    blocks: int
    sharing_location: int
    sharing_run_starts: int
    players_visible_now: int
    challenges_open: int
    challenges_resolved: int
    challenges_awaiting_answer: int
    stakes_open: int
    stakes_transferred: int
    races_running: int
    races_finished: int
    ghosts_total: int
    ghosts_public: int
    ghost_attempts: int
    events_unread: int
    # Work the resolver still owes: anything past its window but not settled.
    challenges_overdue: int


def _count(session: Session, model, *where) -> int:
    return int(
        session.execute(select(func.count()).select_from(model).where(*where)).scalar_one() or 0
    )


@router.get("/overview", response_model=SocialOverview)
def overview(session: Session = Depends(get_session)) -> SocialOverview:
    now = datetime.now(UTC)
    return SocialOverview(
        friendships_accepted=_count(session, Friendship, Friendship.status == "accepted"),
        friend_requests_pending=_count(session, Friendship, Friendship.status == "pending"),
        blocks=_count(session, Friendship, Friendship.status == "blocked"),
        sharing_location=_count(
            session, FriendShareSettings, FriendShareSettings.share_location.is_(True)
        ),
        sharing_run_starts=_count(
            session, FriendShareSettings, FriendShareSettings.notify_on_run_start.is_(True)
        ),
        # A count only: presence is who is reporting, never where they are.
        players_visible_now=_count(
            session, LivePosition, LivePosition.updated_at > now - POSITION_FRESHNESS
        ),
        challenges_open=_count(session, Challenge, Challenge.status == "accepted"),
        challenges_resolved=_count(session, Challenge, Challenge.status == "resolved"),
        challenges_awaiting_answer=_count(session, Challenge, Challenge.status == "pending"),
        stakes_open=_count(
            session,
            ChallengeStake,
            ChallengeStake.staked_area_id.is_not(None),
            ChallengeStake.transferred_at.is_(None),
        ),
        stakes_transferred=_count(
            session, ChallengeStake, ChallengeStake.transferred_at.is_not(None)
        ),
        races_running=_count(session, Race, Race.status == "running"),
        races_finished=_count(session, Race, Race.status == "finished"),
        ghosts_total=_count(session, GhostRun),
        ghosts_public=_count(session, GhostRun, GhostRun.is_public.is_(True)),
        ghost_attempts=_count(session, GhostAttempt, GhostAttempt.finished_at.is_not(None)),
        events_unread=_count(session, SocialEvent, SocialEvent.read_at.is_(None)),
        challenges_overdue=_count(
            session, Challenge, Challenge.status == "accepted", Challenge.window_end <= now
        ),
    )


class AdminChallenge(BaseModel):
    id: uuid.UUID
    challenger: str
    opponent: str
    metric: str
    comparison: str
    goal_text: str
    status: str
    window_start: datetime
    window_end: datetime
    outcome: str | None
    winner: str | None
    challenger_value: float | None
    opponent_value: float | None
    staked_area_m2: float | None
    stake_transferred: bool
    created_at: datetime


@router.get("/challenges", response_model=list[AdminChallenge])
def challenges(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[AdminChallenge]:
    challenger = Account.__table__.alias("challenger")
    opponent = Account.__table__.alias("opponent")
    rows = session.execute(
        select(Challenge, challenger.c.display_name, opponent.c.display_name)
        .join(challenger, challenger.c.id == Challenge.challenger_id)
        .join(opponent, opponent.c.id == Challenge.opponent_id)
        .order_by(Challenge.created_at.desc())
        .limit(limit)
    ).all()

    records: list[AdminChallenge] = []
    for challenge, challenger_name, opponent_name in rows:
        stake = session.get(ChallengeStake, challenge.id)
        staked_area_m2 = None
        if stake is not None and stake.staked_area_id is not None:
            staked_area_m2 = session.execute(
                select(func.ST_Area(CapturedArea.geom)).where(
                    CapturedArea.id == stake.staked_area_id
                )
            ).scalar_one_or_none()
        winner = None
        if challenge.winner_id is not None:
            winner = (
                challenger_name if challenge.winner_id == challenge.challenger_id else opponent_name
            )
        records.append(
            AdminChallenge(
                id=challenge.id,
                challenger=challenger_name,
                opponent=opponent_name,
                metric=challenge.metric,
                comparison=challenge.comparison,
                goal_text=challenge.goal_text,
                status=challenge.status,
                window_start=challenge.window_start,
                window_end=challenge.window_end,
                outcome=challenge.outcome,
                winner=winner,
                challenger_value=challenge.challenger_value,
                opponent_value=challenge.opponent_value,
                staked_area_m2=float(staked_area_m2) if staked_area_m2 is not None else None,
                stake_transferred=bool(stake and stake.transferred_at),
                created_at=challenge.created_at,
            )
        )
    return records


class AdminRace(BaseModel):
    id: uuid.UUID
    challenger: str
    opponent: str
    label: str | None
    radius_m: float
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    winner: str | None
    created_at: datetime


@router.get("/races", response_model=list[AdminRace])
def races(
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[AdminRace]:
    """Races without their pin coordinates: a race is a destination someone
    chose, and the console has no operational need for the place itself."""
    challenger = Account.__table__.alias("challenger")
    opponent = Account.__table__.alias("opponent")
    rows = session.execute(
        select(Race, challenger.c.display_name, opponent.c.display_name)
        .join(challenger, challenger.c.id == Race.challenger_id)
        .join(opponent, opponent.c.id == Race.opponent_id)
        .order_by(Race.created_at.desc())
        .limit(limit)
    ).all()
    return [
        AdminRace(
            id=race.id,
            challenger=challenger_name,
            opponent=opponent_name,
            label=race.pin_label,
            radius_m=race.radius_m,
            status=race.status,
            started_at=race.started_at,
            finished_at=race.finished_at,
            winner=(
                None
                if race.winner_id is None
                else challenger_name
                if race.winner_id == race.challenger_id
                else opponent_name
            ),
            created_at=race.created_at,
        )
        for race, challenger_name, opponent_name in rows
    ]


class AdminGhost(BaseModel):
    id: uuid.UUID
    name: str
    owner: str
    distance_m: float
    duration_s: int
    is_public: bool
    share_live_location: bool
    attempts: int
    best_elapsed_s: int | None
    created_at: datetime


@router.get("/ghosts", response_model=list[AdminGhost])
def ghosts(
    public_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[AdminGhost]:
    """Ghost metadata only. The recorded route is a player's movement history and
    is not something an operator should be able to read out of the console."""
    statement = (
        select(GhostRun, Account.display_name)
        .join(Account, Account.id == GhostRun.account_id)
        .order_by(GhostRun.created_at.desc())
        .limit(limit)
    )
    if public_only:
        statement = statement.where(GhostRun.is_public.is_(True))

    records: list[AdminGhost] = []
    for ghost, owner in session.execute(statement).all():
        attempts, best = session.execute(
            select(func.count(), func.min(GhostAttempt.elapsed_s)).where(
                GhostAttempt.ghost_id == ghost.id, GhostAttempt.finished_at.is_not(None)
            )
        ).one()
        records.append(
            AdminGhost(
                id=ghost.id,
                name=ghost.name,
                owner=owner,
                distance_m=ghost.distance_m,
                duration_s=ghost.duration_s,
                is_public=ghost.is_public,
                share_live_location=ghost.share_live_location,
                attempts=int(attempts or 0),
                best_elapsed_s=int(best) if best is not None else None,
                created_at=ghost.created_at,
            )
        )
    return records


class ResolverResult(BaseModel):
    expired: int
    resolved: int


@router.post("/resolve", response_model=ResolverResult)
def run_resolver(session: Session = Depends(get_session)) -> ResolverResult:
    """Settle every challenge that is due, from the console.

    The deployment has no worker; challenges normally settle when a player opens
    their list. This is the operator's version of the same idempotent call, for
    the case where neither player has opened the app.
    """
    return ResolverResult(**resolve_due(session))


class SocialHealth(BaseModel):
    """Things worth an operator's attention rather than raw counts."""

    challenges_overdue: int
    races_overdue: int
    requests_stale: int
    oldest_overdue_challenge_hours: float | None


@router.get("/health", response_model=SocialHealth)
def health(session: Session = Depends(get_session)) -> SocialHealth:
    now = datetime.now(UTC)
    overdue = session.execute(
        select(func.min(Challenge.window_end)).where(
            Challenge.status == "accepted", Challenge.window_end <= now
        )
    ).scalar_one_or_none()
    return SocialHealth(
        challenges_overdue=_count(
            session, Challenge, Challenge.status == "accepted", Challenge.window_end <= now
        ),
        races_overdue=_count(
            session, Race, Race.status == "running", Race.expires_at <= now
        ),
        # A request nobody has answered in a fortnight is clutter, not a signal,
        # but it is worth seeing before deciding to prune anything.
        requests_stale=_count(
            session,
            Friendship,
            Friendship.status == "pending",
            Friendship.created_at <= now - timedelta(days=14),
        ),
        oldest_overdue_challenge_hours=(
            round((now - overdue).total_seconds() / 3600, 1) if overdue else None
        ),
    )
