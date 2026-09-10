"""Friend graph regressions inside an outer rollback transaction; never commit fixtures."""

import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import SessionLocal, engine, get_session
from app.main import app
from app.models import Account, Device, DeviceLink, Friendship
from app.services.social import friend_ids, friendship_between, require_friend


@pytest.fixture()
def social(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    # Sessions are exercised by the authentication tests; these cover the graph.
    monkeypatch.setattr(settings, "authenticated_accounts_enabled", False)
    app.dependency_overrides[get_session] = lambda: session
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.pop(get_session, None)
        session.close()
        transaction.rollback()
        connection.close()


def make_player(session, display_name: str) -> tuple[Account, dict[str, str]]:
    """An account with a linked device, and the headers that speak for it."""
    account = Account(display_name=display_name, role="player")
    session.add(account)
    session.flush()
    session.refresh(account, ["handle"])
    device = Device(id=uuid.uuid4())
    session.add(device)
    session.flush()
    session.add(DeviceLink(device_id=device.id, account_id=account.id))
    session.flush()
    return account, {"X-Device-Id": str(device.id)}


def test_handle_is_assigned_on_insert_and_is_unique(social):
    _, session = social
    first, _ = make_player(session, "Priya Runs")
    second, _ = make_player(session, "Priya Runs")

    assert first.handle == "priyaruns"
    assert second.handle == "priyaruns1"


def test_search_finds_by_handle_prefix_display_name_and_exact_id(social):
    client, session = social
    _, seeker = make_player(session, "Seeker")
    target, _ = make_player(session, "Zephyr Kumar")

    for query in (target.handle[:4], "@" + target.handle, "Zephyr", str(target.id)):
        found = client.get(f"/v1/social/search?q={query}", headers=seeker).json()
        assert [row["id"] for row in found] == [str(target.id)], query
        assert found[0]["relationship"] == "none"


def test_search_excludes_yourself_and_rejects_one_character(social):
    client, session = social
    account, headers = make_player(session, "Solo Runner")

    found = client.get("/v1/social/search?q=solo", headers=headers).json()
    assert [row["id"] for row in found] == []
    assert client.get("/v1/social/search?q=s", headers=headers).status_code == 422
    assert account.handle == "solorunner"


def test_request_accept_makes_both_sides_friends(social):
    client, session = social
    sender, sender_headers = make_player(session, "Sender")
    recipient, recipient_headers = make_player(session, "Recipient")

    created = client.post(
        "/v1/social/friends/requests",
        json={"handle": recipient.handle},
        headers=sender_headers,
    )
    assert created.status_code == 201, created.text

    pending = client.get("/v1/social/friends", headers=recipient_headers).json()
    assert [row["account"]["id"] for row in pending["incoming"]] == [str(sender.id)]
    assert pending["incoming"][0]["account"]["relationship"] == "request_received"
    assert client.get("/v1/social/friends", headers=sender_headers).json()["outgoing"]

    request_id = pending["incoming"][0]["id"]
    accepted = client.post(
        f"/v1/social/friends/requests/{request_id}/accept", headers=recipient_headers
    )
    assert accepted.status_code == 200, accepted.text

    for headers, other in ((sender_headers, recipient), (recipient_headers, sender)):
        friends = client.get("/v1/social/friends", headers=headers).json()["friends"]
        assert [row["account"]["id"] for row in friends] == [str(other.id)]
    session.flush()  # the override never commits, so pending writes are not yet visible
    assert friend_ids(session, sender.id) == {recipient.id}


def test_a_pair_only_ever_holds_one_row(social):
    client, session = social
    sender, sender_headers = make_player(session, "Persistent")
    recipient, recipient_headers = make_player(session, "Reluctant")

    def pair_rows() -> int:
        return len(
            [
                row
                for row in session.query(Friendship).all()
                if {row.requester_id, row.addressee_id} == {sender.id, recipient.id}
            ]
        )

    first = client.post(
        "/v1/social/friends/requests", json={"handle": recipient.handle}, headers=sender_headers
    ).json()
    assert client.post(
        "/v1/social/friends/requests", json={"handle": recipient.handle}, headers=sender_headers
    ).status_code == 409
    client.post(f"/v1/social/friends/requests/{first['id']}/decline", headers=recipient_headers)
    # Re-requesting after a decline reopens the same row rather than adding one.
    client.post(
        "/v1/social/friends/requests",
        json={"account_id": str(recipient.id)},
        headers=sender_headers,
    )
    session.flush()
    assert pair_rows() == 1
    assert friendship_between(session, sender.id, recipient.id).status == "pending"


def test_requesting_someone_who_already_asked_you_accepts(social):
    client, session = social
    first, first_headers = make_player(session, "Early Bird")
    second, second_headers = make_player(session, "Second Mover")

    client.post(
        "/v1/social/friends/requests", json={"handle": second.handle}, headers=first_headers
    )
    mutual = client.post(
        "/v1/social/friends/requests", json={"handle": first.handle}, headers=second_headers
    )
    assert mutual.status_code == 201, mutual.text
    session.flush()
    assert friendship_between(session, first.id, second.id).status == "accepted"


def test_blocking_hides_the_account_and_is_not_detectable(social):
    client, session = social
    blocker, blocker_headers = make_player(session, "Blocker")
    blocked, blocked_headers = make_player(session, "Blocked Person")

    assert client.post(f"/v1/social/block/{blocked.id}", headers=blocker_headers).status_code == 204
    session.flush()

    assert client.get(f"/v1/social/search?q={blocker.handle}", headers=blocked_headers).json() == []
    refused = client.post(
        "/v1/social/friends/requests", json={"handle": blocker.handle}, headers=blocked_headers
    )
    # The same 404 an unknown handle produces: a block must not be observable.
    assert refused.status_code == 404
    assert refused.json()["detail"] == "No account matches that name or ID."

    assert (
        client.delete(f"/v1/social/block/{blocked.id}", headers=blocker_headers).status_code == 204
    )
    session.flush()
    assert friendship_between(session, blocker.id, blocked.id) is None


def test_unfriending_clears_the_pair(social):
    client, session = social
    first, first_headers = make_player(session, "Parting One")
    second, second_headers = make_player(session, "Parting Two")

    request = client.post(
        "/v1/social/friends/requests", json={"handle": second.handle}, headers=first_headers
    ).json()
    client.post(f"/v1/social/friends/requests/{request['id']}/accept", headers=second_headers)
    removed = client.delete(f"/v1/social/friends/{second.id}", headers=first_headers)
    assert removed.status_code == 204
    session.flush()
    assert friendship_between(session, first.id, second.id) is None


def test_features_are_gated_on_an_accepted_friendship(social):
    _, session = social
    first, _ = make_player(session, "Gate One")
    second, _ = make_player(session, "Gate Two")

    with pytest.raises(HTTPException) as strangers:
        require_friend(session, first.id, second.id)
    assert strangers.value.status_code == 403
    assert "accepted friend" in strangers.value.detail

    session.add(Friendship(requester_id=first.id, addressee_id=second.id, status="pending"))
    session.flush()
    with pytest.raises(HTTPException):
        require_friend(session, first.id, second.id)


def test_handle_can_be_changed_but_not_taken_or_reserved(social):
    client, session = social
    _, headers = make_player(session, "Renamer")
    taken, _ = make_player(session, "Already Here")

    def set_handle(handle: str):
        return client.put("/v1/social/handle", json={"handle": handle}, headers=headers)

    assert set_handle("Trail_Blazer").json()["handle"] == "trail_blazer"
    assert set_handle("ad min").status_code == 422
    assert set_handle("admin").status_code == 422
    assert set_handle(taken.handle).status_code == 409
