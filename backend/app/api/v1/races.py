"""Spontaneous races: drop a pin, challenge a friend, first one there wins.

Sharing during a race is temporary by construction — it is granted on accept and
revoked on any ending, including an abandoned one. A race that nobody finishes
lapses silently rather than declaring a loser.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.v1.social import current_account, public
from app.core.db import get_session
from app.models import Account, Race
from app.schemas import RaceCreate, RaceRecord
from app.services.races import (
    DEFAULT_ACCEPT_WINDOW,
    abandon,
    expire_due,
    start,
)
from app.services.social import record_event, require_friend

router = APIRouter(prefix="/social/races", tags=["social"])

OPEN_STATUSES = ("pending", "running")


def record(session: Session, race: Race, viewer: Account) -> RaceRecord:
    return RaceRecord(
        id=race.id,
        challenger=public(session, session.get(Account, race.challenger_id), viewer.id),
        opponent=public(session, session.get(Account, race.opponent_id), viewer.id),
        role="challenger" if race.challenger_id == viewer.id else "opponent",
        pin_lat=race.pin_lat,
        pin_lon=race.pin_lon,
        pin_label=race.pin_label,
        radius_m=race.radius_m,
        status=race.status,
        accept_deadline=race.accept_deadline,
        started_at=race.started_at,
        expires_at=race.expires_at,
        winner_id=race.winner_id,
        finished_at=race.finished_at,
        created_at=race.created_at,
    )


def _mine(session: Session, race_id: uuid.UUID, account: Account) -> Race:
    race = session.get(Race, race_id)
    if race is None or account.id not in (race.challenger_id, race.opponent_id):
        raise HTTPException(404, "That race no longer exists.")
    return race


@router.post("", response_model=RaceRecord, status_code=201)
def create_race(
    payload: RaceCreate,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> RaceRecord:
    require_friend(session, account.id, payload.opponent_id)
    opponent = session.get(Account, payload.opponent_id)
    if opponent is None:
        raise HTTPException(404, "That account no longer exists.")

    already = session.execute(
        select(Race).where(
            Race.status.in_(OPEN_STATUSES),
            or_(
                (Race.challenger_id == account.id) & (Race.opponent_id == payload.opponent_id),
                (Race.challenger_id == payload.opponent_id) & (Race.opponent_id == account.id),
            ),
        )
    ).first()
    if already:
        raise HTTPException(409, f"You already have a race open with {opponent.display_name}.")

    now = datetime.now(UTC)
    race = Race(
        challenger_id=account.id,
        opponent_id=payload.opponent_id,
        pin_lat=payload.pin_lat,
        pin_lon=payload.pin_lon,
        pin_label=payload.pin_label,
        radius_m=payload.radius_m,
        status="pending",
        accept_deadline=now + DEFAULT_ACCEPT_WINDOW,
    )
    session.add(race)
    session.flush()

    where = f" to {race.pin_label}" if race.pin_label else ""
    record_event(
        session,
        opponent.id,
        "race_received",
        f"{account.display_name} challenged you to a race{where}.",
        actor_id=account.id,
        subject_id=race.id,
    )
    return record(session, race, account)


@router.get("", response_model=list[RaceRecord])
def list_races(
    account: Account = Depends(current_account), session: Session = Depends(get_session)
) -> list[RaceRecord]:
    expire_due(session)
    races = session.execute(
        select(Race)
        .where(or_(Race.challenger_id == account.id, Race.opponent_id == account.id))
        .order_by(Race.created_at.desc())
        .limit(50)
    ).scalars()
    return [record(session, race, account) for race in races]


@router.post("/{race_id}/accept", response_model=RaceRecord)
def accept_race(
    race_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> RaceRecord:
    race = _mine(session, race_id, account)
    if race.opponent_id != account.id:
        raise HTTPException(403, "Only the person challenged can accept.")
    if race.status != "pending":
        raise HTTPException(409, "That race is no longer open.")
    if race.accept_deadline <= datetime.now(UTC):
        abandon(session, race, "expired")
        raise HTTPException(409, "That race invitation has expired.")

    start(session, race)
    session.flush()
    record_event(
        session,
        race.challenger_id,
        "race_started",
        f"{account.display_name} accepted your race. You can both see each other until it ends.",
        actor_id=account.id,
        subject_id=race.id,
    )
    return record(session, race, account)


@router.post("/{race_id}/decline", response_model=RaceRecord)
def decline_race(
    race_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> RaceRecord:
    race = _mine(session, race_id, account)
    if race.opponent_id != account.id:
        raise HTTPException(403, "Only the person challenged can decline.")
    if race.status != "pending":
        raise HTTPException(409, "That race is no longer open.")
    abandon(session, race, "declined")
    record_event(
        session,
        race.challenger_id,
        "race_declined",
        f"{account.display_name} is not up for a race right now.",
        actor_id=account.id,
        subject_id=race.id,
    )
    return record(session, race, account)


@router.post("/{race_id}/withdraw", response_model=RaceRecord)
def withdraw_race(
    race_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> RaceRecord:
    """Either side can walk away, before or during the race.

    Stopping is always allowed and never punished: a race is a game, and the
    road it crosses is not.
    """
    race = _mine(session, race_id, account)
    if race.status not in OPEN_STATUSES:
        raise HTTPException(409, "That race has already ended.")
    other_id = race.opponent_id if race.challenger_id == account.id else race.challenger_id
    abandon(session, race, "cancelled" if race.status == "pending" else "expired")
    record_event(
        session,
        other_id,
        "race_ended",
        f"{account.display_name} ended the race.",
        actor_id=account.id,
        subject_id=race.id,
    )
    return record(session, race, account)
