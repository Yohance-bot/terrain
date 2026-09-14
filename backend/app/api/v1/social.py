"""Finding people, and the friend graph that gates every other social feature.

Nothing here exposes location, routes or run history. A player who is not an
accepted friend can see only what `PublicAccount` carries: a name, a handle and
an avatar.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import device_id_header
from app.api.v1.accounts import account_for_device
from app.core.db import get_session
from app.models import Account, Friendship
from app.schemas import (
    Friend,
    FriendList,
    FriendProfile,
    FriendRequest,
    FriendRequestCreate,
    HandleUpdate,
    PublicAccount,
)
from app.services.athlete import athlete_stats, recent_public_runs
from app.services.social import (
    friendship_between,
    handle_for,
    normalise_handle,
    record_event,
    relationship_label,
    require_friend,
    search_accounts,
)

router = APIRouter(prefix="/social", tags=["social"])


def current_account(
    device_id: uuid.UUID = Depends(device_id_header), session: Session = Depends(get_session)
) -> Account:
    account = account_for_device(session, device_id)
    if account is None:
        raise HTTPException(401, "Sign in to use social features")
    return account


def public(session: Session, account: Account, viewer_id: uuid.UUID) -> PublicAccount:
    return PublicAccount(
        id=account.id,
        display_name=account.display_name,
        handle=handle_for(session, account),
        avatar_url=account.avatar_url,
        relationship=relationship_label(
            friendship_between(session, viewer_id, account.id), viewer_id
        ),
    )


@router.put("/handle", response_model=PublicAccount)
def set_handle(
    update: HandleUpdate,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> PublicAccount:
    handle = normalise_handle(update.handle)
    if handle != account.handle:
        account.handle = handle
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "That handle is already taken.") from exc
    return public(session, account, account.id)


@router.get("/search", response_model=list[PublicAccount])
def search(
    q: str = Query(min_length=2, max_length=64),
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> list[PublicAccount]:
    return [public(session, found, account.id) for found in search_accounts(session, account.id, q)]


@router.get("/friends", response_model=FriendList)
def list_friends(
    account: Account = Depends(current_account), session: Session = Depends(get_session)
) -> FriendList:
    rows = session.execute(
        select(Friendship, Account)
        .join(
            Account,
            or_(
                (Friendship.requester_id == account.id) & (Account.id == Friendship.addressee_id),
                (Friendship.addressee_id == account.id) & (Account.id == Friendship.requester_id),
            ),
        )
        .where(or_(Friendship.requester_id == account.id, Friendship.addressee_id == account.id))
    ).all()

    friends: list[Friend] = []
    incoming: list[FriendRequest] = []
    outgoing: list[FriendRequest] = []
    blocked: list[PublicAccount] = []
    for friendship, other in rows:
        other_public = public(session, other, account.id)
        if friendship.status == "accepted":
            friends.append(Friend(account=other_public, friends_since=friendship.updated_at))
        elif friendship.status == "pending":
            outgoing_request = friendship.requester_id == account.id
            request = FriendRequest(
                id=friendship.id,
                account=other_public,
                direction="outgoing" if outgoing_request else "incoming",
                created_at=friendship.created_at,
            )
            (outgoing if outgoing_request else incoming).append(request)
        elif friendship.status == "blocked" and friendship.blocked_by == account.id:
            blocked.append(other_public)

    friends.sort(key=lambda entry: entry.account.display_name.lower())
    return FriendList(friends=friends, incoming=incoming, outgoing=outgoing, blocked=blocked)


@router.post("/friends/requests", response_model=FriendRequest, status_code=201)
def send_request(
    payload: FriendRequestCreate,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> FriendRequest:
    if payload.account_id is not None:
        target = session.get(Account, payload.account_id)
    elif payload.handle is not None:
        target = session.execute(
            select(Account).where(Account.handle == payload.handle.strip().lstrip("@").lower())
        ).scalar_one_or_none()
    else:
        raise HTTPException(422, "Provide a handle or an account id.")

    if target is None:
        raise HTTPException(404, "No account matches that name or ID.")
    if target.id == account.id:
        raise HTTPException(422, "You cannot add yourself.")

    friendship = friendship_between(session, account.id, target.id)
    if friendship is not None:
        if friendship.status == "blocked":
            # Same message the recipient's absence would produce, so a block is
            # not observable from the outside.
            raise HTTPException(404, "No account matches that name or ID.")
        if friendship.status == "accepted":
            raise HTTPException(409, f"You are already friends with {target.display_name}.")
        if friendship.status == "pending":
            if friendship.requester_id == account.id:
                raise HTTPException(409, "That request is already waiting for a reply.")
            # They asked first: answering with a request of your own is an accept.
            friendship.status = "accepted"
            friendship.updated_at = datetime.now(UTC)
            record_event(
                session,
                target.id,
                "friend_accepted",
                f"{account.display_name} is now your friend.",
                actor_id=account.id,
            )
            return FriendRequest(
                id=friendship.id,
                account=public(session, target, account.id),
                direction="outgoing",
                created_at=friendship.created_at,
            )
        # A declined pair reopens on the same row rather than accumulating rows.
        friendship.requester_id = account.id
        friendship.addressee_id = target.id
        friendship.status = "pending"
        friendship.updated_at = datetime.now(UTC)
    else:
        friendship = Friendship(
            requester_id=account.id, addressee_id=target.id, status="pending"
        )
        session.add(friendship)
        session.flush()

    record_event(
        session,
        target.id,
        "friend_request",
        f"{account.display_name} wants to be your friend.",
        actor_id=account.id,
        subject_id=friendship.id,
    )
    return FriendRequest(
        id=friendship.id,
        account=public(session, target, account.id),
        direction="outgoing",
        created_at=friendship.created_at,
    )


def _pending_for(session: Session, request_id: uuid.UUID, account_id: uuid.UUID) -> Friendship:
    friendship = session.get(Friendship, request_id)
    if friendship is None or friendship.addressee_id != account_id:
        raise HTTPException(404, "That request no longer exists.")
    if friendship.status != "pending":
        raise HTTPException(409, "That request has already been answered.")
    return friendship


@router.post("/friends/requests/{request_id}/accept", response_model=Friend)
def accept_request(
    request_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> Friend:
    friendship = _pending_for(session, request_id, account.id)
    friendship.status = "accepted"
    friendship.updated_at = datetime.now(UTC)
    other = session.get(Account, friendship.requester_id)
    record_event(
        session,
        other.id,
        "friend_accepted",
        f"{account.display_name} accepted your friend request.",
        actor_id=account.id,
    )
    return Friend(
        account=public(session, other, account.id), friends_since=friendship.updated_at
    )


@router.post("/friends/requests/{request_id}/decline", status_code=204)
def decline_request(
    request_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> None:
    friendship = _pending_for(session, request_id, account.id)
    friendship.status = "declined"
    friendship.updated_at = datetime.now(UTC)


@router.delete("/friends/{account_id}", status_code=204)
def remove_friend(
    account_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> None:
    """Unfriend, or withdraw a request you sent.

    The row is deleted rather than marked, so the pair starts clean; the shared
    state that hangs off a friendship is removed by the caller of this endpoint's
    later phases (sharing settings, open challenges).
    """
    friendship = friendship_between(session, account.id, account_id)
    if friendship is None or friendship.status == "blocked":
        raise HTTPException(404, "You are not connected to that account.")
    session.delete(friendship)


@router.post("/block/{account_id}", status_code=204)
def block_account(
    account_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> None:
    """Block: ends any friendship, and prevents contact from either direction."""
    if account_id == account.id:
        raise HTTPException(422, "You cannot block yourself.")
    if session.get(Account, account_id) is None:
        raise HTTPException(404, "No account matches that ID.")
    friendship = friendship_between(session, account.id, account_id)
    if friendship is None:
        friendship = Friendship(requester_id=account.id, addressee_id=account_id)
        session.add(friendship)
    friendship.status = "blocked"
    friendship.blocked_by = account.id
    friendship.updated_at = datetime.now(UTC)
    session.flush()


@router.delete("/block/{account_id}", status_code=204)
def unblock_account(
    account_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> None:
    friendship = friendship_between(session, account.id, account_id)
    if (
        friendship is None
        or friendship.status != "blocked"
        or friendship.blocked_by != account.id
    ):
        raise HTTPException(404, "You have not blocked that account.")
    # Unblocking returns the pair to strangers, not to their previous friendship.
    session.delete(friendship)


@router.get("/accounts/{account_id}/profile", response_model=FriendProfile)
def friend_profile(
    account_id: uuid.UUID,
    tz: str | None = Query(default=None, max_length=64),
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> FriendProfile:
    """A friend's training. Same refusal for strangers and blocks, by design."""
    friendship = require_friend(session, account.id, account_id)
    other = session.get(Account, account_id)
    if other is None:
        raise HTTPException(404, "Account not found")
    stats = athlete_stats(session, other, tz)
    return FriendProfile(
        account=public(session, other, account.id),
        friends_since=friendship.updated_at,
        this_week=stats.this_week,
        year_to_date=stats.year_to_date,
        all_time=stats.all_time,
        weeks=stats.weeks,
        streak=stats.streak,
        best_efforts=stats.best_efforts,
        longest_run=stats.longest_run,
        territories_held=stats.territories_held,
        recent_runs=recent_public_runs(session, other),
    )
