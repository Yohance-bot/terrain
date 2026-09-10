"""Opt-in live sharing, the position channel, and the in-app event feed.

Two separate toggles, per friend, per direction. Neither is implied by
friendship, and either side can end sharing at any time. A position is only ever
returned while it is fresh, so closing the app is itself a way to stop being
seen.

Delivery is by polling rather than a socket: the API runs on an instance that
sleeps when idle, and a run already survives a dropped connection by recording
locally. Positions are overwritten in place and never accumulate a trail.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.races import record as race_record
from app.api.v1.social import current_account, public
from app.core.db import get_session
from app.models import Account, LivePosition, SocialEvent
from app.schemas import (
    FriendPosition,
    LiveView,
    PositionUpdate,
    PublicAccount,
    SharingEntry,
    SharingOverview,
    SharingUpdate,
    SocialEventRecord,
)
from app.services.races import check_arrival, expire_due, open_races_for
from app.services.social import (
    friend_ids,
    record_event,
    require_friend,
    sharing_setting,
    visible_positions,
)

router = APIRouter(prefix="/social", tags=["social"])


def _entry(session: Session, setting, viewer: Account, account: Account) -> SharingEntry:
    return SharingEntry(
        account=public(session, account, viewer.id),
        share_location=bool(setting and setting.share_location),
        notify_on_run_start=bool(setting and setting.notify_on_run_start),
        location_expires_at=setting.location_expires_at if setting else None,
    )


@router.get("/sharing", response_model=SharingOverview)
def sharing_overview(
    account: Account = Depends(current_account), session: Session = Depends(get_session)
) -> SharingOverview:
    """What you share with each friend, and which friends currently share with you."""
    friends = friend_ids(session, account.id)
    if not friends:
        return SharingOverview(sharing_with=[], visible_to_me=[])

    others = {
        other.id: other
        for other in session.execute(select(Account).where(Account.id.in_(friends))).scalars()
    }
    sharing_with = [
        _entry(session, sharing_setting(session, account.id, friend_id), account, others[friend_id])
        for friend_id in others
    ]
    sharing_with.sort(key=lambda entry: entry.account.display_name.lower())

    visible_to_me = [
        public(session, other, account.id)
        for other, _ in visible_positions(session, account.id)
    ]
    return SharingOverview(sharing_with=sharing_with, visible_to_me=visible_to_me)


@router.put("/sharing/{account_id}", response_model=SharingEntry)
def update_sharing(
    account_id: uuid.UUID,
    update: SharingUpdate,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> SharingEntry:
    """Change what one friend may see. Off is always available and immediate."""
    require_friend(session, account.id, account_id)
    friend = session.get(Account, account_id)
    setting = sharing_setting(session, account.id, account_id, create=True)

    if update.share_location is not None:
        setting.share_location = update.share_location
        # Turning sharing on by hand replaces any temporary race grant with an
        # open-ended one; turning it off clears the window entirely.
        setting.location_expires_at = None
    if update.notify_on_run_start is not None:
        setting.notify_on_run_start = update.notify_on_run_start
    setting.updated_at = datetime.now(UTC)
    session.flush()
    return _entry(session, setting, account, friend)


@router.post("/position", response_model=LiveView)
def report_position(
    update: PositionUpdate,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> LiveView:
    """Report where you are and read back the friends you are allowed to see.

    One round trip in both directions, because the client polls this while the
    screen is on and every extra request costs battery on a phone that is
    already recording GPS.
    """
    position = session.get(LivePosition, account.id)
    if position is None:
        position = LivePosition(account_id=account.id, lat=update.lat, lon=update.lon)
        session.add(position)
    position.lat = update.lat
    position.lon = update.lon
    position.accuracy_m = update.accuracy_m
    position.heading = update.heading
    position.speed_mps = update.speed_mps
    position.is_running = update.is_running
    position.run_id = update.run_id
    position.updated_at = datetime.now(UTC)
    session.flush()
    # Arrival is settled from the position a runner is already sending, so
    # winning a race never requires looking at, or touching, the phone.
    check_arrival(session, account.id, update.lat, update.lon)
    return live_view(account, session)


@router.delete("/position", status_code=204)
def clear_position(
    account: Account = Depends(current_account), session: Session = Depends(get_session)
) -> None:
    """Disappear immediately rather than waiting for the freshness window."""
    position = session.get(LivePosition, account.id)
    if position is not None:
        session.delete(position)


@router.get("/live", response_model=LiveView)
def live_view(
    account: Account = Depends(current_account), session: Session = Depends(get_session)
) -> LiveView:
    """Everything the map needs in one poll: visible friends and live races."""
    expire_due(session)
    return LiveView(
        friends=[
            FriendPosition(
                account=public(session, other, account.id),
                lat=position.lat,
                lon=position.lon,
                accuracy_m=position.accuracy_m,
                heading=position.heading,
                speed_mps=position.speed_mps,
                is_running=position.is_running,
                updated_at=position.updated_at,
            )
            for other, position in visible_positions(session, account.id)
        ],
        races=[race_record(session, race, account) for race in open_races_for(session, account.id)],
    )


@router.post("/runs/{run_id}/started", status_code=204)
def announce_run_start(
    run_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> None:
    """Tell only the friends who asked to hear it.

    This is a separate opt-in from location sharing: knowing someone went out is
    a much smaller disclosure than knowing where they are.
    """
    friends = friend_ids(session, account.id)
    for friend_id in friends:
        setting = sharing_setting(session, account.id, friend_id)
        if setting is not None and setting.notify_on_run_start:
            record_event(
                session,
                friend_id,
                "run_started",
                f"{account.display_name} started a run.",
                actor_id=account.id,
                subject_id=run_id,
            )


@router.get("/events", response_model=list[SocialEventRecord])
def list_events(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> list[SocialEventRecord]:
    statement = (
        select(SocialEvent)
        .where(SocialEvent.account_id == account.id)
        .order_by(SocialEvent.created_at.desc())
        .limit(limit)
    )
    if unread_only:
        statement = statement.where(SocialEvent.read_at.is_(None))

    events = list(session.execute(statement).scalars())
    actors: dict[uuid.UUID, PublicAccount] = {}
    for event in events:
        if event.actor_id and event.actor_id not in actors:
            actor = session.get(Account, event.actor_id)
            if actor is not None:
                actors[event.actor_id] = public(session, actor, account.id)
    return [
        SocialEventRecord(
            id=event.id,
            kind=event.kind,
            body=event.body,
            actor=actors.get(event.actor_id) if event.actor_id else None,
            subject_id=event.subject_id,
            created_at=event.created_at,
            read_at=event.read_at,
        )
        for event in events
    ]


@router.post("/events/read", status_code=204)
def mark_events_read(
    up_to_id: int | None = None,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> None:
    statement = select(SocialEvent).where(
        SocialEvent.account_id == account.id, SocialEvent.read_at.is_(None)
    )
    if up_to_id is not None:
        statement = statement.where(SocialEvent.id <= up_to_id)
    now = datetime.now(UTC)
    for event in session.execute(statement).scalars():
        event.read_at = now


@router.get("/friends/{account_id}/sharing", response_model=SharingEntry)
def friend_sharing(
    account_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> SharingEntry:
    require_friend(session, account.id, account_id)
    friend = session.get(Account, account_id)
    if friend is None:
        raise HTTPException(404, "That account no longer exists.")
    return _entry(session, sharing_setting(session, account.id, account_id), account, friend)
