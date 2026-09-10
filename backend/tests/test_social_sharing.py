"""Opt-in sharing regressions inside an outer rollback transaction."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import SessionLocal, engine, get_session
from app.main import app
from app.models import Friendship, LivePosition
from app.services.social import (
    POSITION_FRESHNESS,
    grant_temporary_location,
    revoke_temporary_location,
    sharing_setting,
    viewers_of,
)
from tests.test_social_friends import make_player

BENGALURU = {"lat": 12.9716, "lon": 77.5946}


@pytest.fixture()
def social(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    monkeypatch.setattr(settings, "authenticated_accounts_enabled", False)
    app.dependency_overrides[get_session] = lambda: session
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.pop(get_session, None)
        session.close()
        transaction.rollback()
        connection.close()


def befriend(session, first, second) -> None:
    session.add(
        Friendship(requester_id=first.id, addressee_id=second.id, status="accepted")
    )
    session.flush()


def test_friendship_alone_shares_nothing(social):
    client, session = social
    runner, runner_headers = make_player(session, "Runner")
    friend, friend_headers = make_player(session, "Friend")
    befriend(session, runner, friend)

    client.post(
        "/v1/social/position", json={**BENGALURU, "is_running": True}, headers=runner_headers
    )
    session.flush()

    assert client.get("/v1/social/live", headers=friend_headers).json()["friends"] == []
    overview = client.get("/v1/social/sharing", headers=runner_headers).json()
    assert [entry["share_location"] for entry in overview["sharing_with"]] == [False]
    assert [entry["notify_on_run_start"] for entry in overview["sharing_with"]] == [False]


def test_location_and_run_alerts_are_independent_toggles(social):
    client, session = social
    runner, runner_headers = make_player(session, "Toggler")
    friend, friend_headers = make_player(session, "Watcher")
    befriend(session, runner, friend)

    client.put(
        f"/v1/social/sharing/{friend.id}",
        json={"notify_on_run_start": True},
        headers=runner_headers,
    )
    session.flush()
    # Announcing a run must not make the runner's position visible.
    client.post(f"/v1/social/runs/{runner.id}/started", headers=runner_headers)
    client.post(
        "/v1/social/position", json={**BENGALURU, "is_running": True}, headers=runner_headers
    )
    session.flush()

    assert client.get("/v1/social/live", headers=friend_headers).json()["friends"] == []
    events = client.get("/v1/social/events", headers=friend_headers).json()
    assert [event["kind"] for event in events] == ["run_started"]

    client.put(
        f"/v1/social/sharing/{friend.id}", json={"share_location": True}, headers=runner_headers
    )
    session.flush()
    seen = client.get("/v1/social/live", headers=friend_headers).json()["friends"]
    assert [row["account"]["id"] for row in seen] == [str(runner.id)]
    assert seen[0]["is_running"] is True


def test_sharing_can_be_turned_off_at_any_time(social):
    client, session = social
    runner, runner_headers = make_player(session, "Leaver")
    friend, friend_headers = make_player(session, "Left Behind")
    befriend(session, runner, friend)

    client.put(
        f"/v1/social/sharing/{friend.id}", json={"share_location": True}, headers=runner_headers
    )
    client.post("/v1/social/position", json=BENGALURU, headers=runner_headers)
    session.flush()
    assert len(client.get("/v1/social/live", headers=friend_headers).json()["friends"]) == 1

    client.put(
        f"/v1/social/sharing/{friend.id}", json={"share_location": False}, headers=runner_headers
    )
    session.flush()
    assert client.get("/v1/social/live", headers=friend_headers).json()["friends"] == []
    assert viewers_of(session, runner.id) == []


def test_a_stale_position_is_not_shown(social):
    client, session = social
    runner, runner_headers = make_player(session, "Gone Quiet")
    friend, friend_headers = make_player(session, "Still Looking")
    befriend(session, runner, friend)
    client.put(
        f"/v1/social/sharing/{friend.id}", json={"share_location": True}, headers=runner_headers
    )
    client.post("/v1/social/position", json=BENGALURU, headers=runner_headers)
    session.flush()

    position = session.get(LivePosition, runner.id)
    position.updated_at = datetime.now(UTC) - POSITION_FRESHNESS - timedelta(seconds=30)
    session.flush()

    assert client.get("/v1/social/live", headers=friend_headers).json()["friends"] == []


def test_you_can_see_who_is_currently_watching_you(social):
    client, session = social
    runner, runner_headers = make_player(session, "Seen")
    friend, friend_headers = make_player(session, "Seer")
    befriend(session, runner, friend)

    client.put(
        f"/v1/social/sharing/{runner.id}", json={"share_location": True}, headers=friend_headers
    )
    client.post("/v1/social/position", json=BENGALURU, headers=friend_headers)
    session.flush()

    overview = client.get("/v1/social/sharing", headers=runner_headers).json()
    assert [row["id"] for row in overview["visible_to_me"]] == [str(friend.id)]


def test_a_temporary_grant_expires_without_touching_a_standing_choice(social):
    _, session = social
    runner, _ = make_player(session, "Racer")
    friend, _ = make_player(session, "Rival")
    befriend(session, runner, friend)

    until = datetime.now(UTC) + timedelta(minutes=30)
    grant_temporary_location(session, runner.id, friend.id, until)
    session.flush()
    assert viewers_of(session, runner.id) == [friend.id]

    setting = sharing_setting(session, runner.id, friend.id)
    setting.location_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.flush()
    assert viewers_of(session, runner.id) == []

    # A standing choice survives a race that grants and then revokes.
    setting.share_location = True
    setting.location_expires_at = None
    session.flush()
    grant_temporary_location(session, runner.id, friend.id, until)
    revoke_temporary_location(session, runner.id, friend.id)
    session.flush()
    assert viewers_of(session, runner.id) == [friend.id]


def test_position_reporting_requires_a_friendship_to_be_seen_by_anyone(social):
    client, session = social
    stranger, stranger_headers = make_player(session, "Stranger")
    other, other_headers = make_player(session, "Unrelated")

    # No friendship: sharing cannot even be configured.
    refused = client.put(
        f"/v1/social/sharing/{other.id}", json={"share_location": True}, headers=stranger_headers
    )
    assert refused.status_code == 403

    client.post("/v1/social/position", json=BENGALURU, headers=stranger_headers)
    session.flush()
    assert client.get("/v1/social/live", headers=other_headers).json()["friends"] == []


def test_clearing_a_position_hides_it_immediately(social):
    client, session = social
    runner, runner_headers = make_player(session, "Vanisher")
    friend, friend_headers = make_player(session, "Observer")
    befriend(session, runner, friend)
    client.put(
        f"/v1/social/sharing/{friend.id}", json={"share_location": True}, headers=runner_headers
    )
    client.post("/v1/social/position", json=BENGALURU, headers=runner_headers)
    session.flush()

    assert client.delete("/v1/social/position", headers=runner_headers).status_code == 204
    session.flush()
    assert client.get("/v1/social/live", headers=friend_headers).json()["friends"] == []


def test_events_are_marked_read(social):
    client, session = social
    runner, runner_headers = make_player(session, "Announcer")
    friend, friend_headers = make_player(session, "Listener")
    befriend(session, runner, friend)
    client.put(
        f"/v1/social/sharing/{friend.id}",
        json={"notify_on_run_start": True},
        headers=runner_headers,
    )
    client.post(f"/v1/social/runs/{runner.id}/started", headers=runner_headers)
    session.flush()

    assert len(client.get("/v1/social/events?unread_only=true", headers=friend_headers).json()) == 1
    client.post("/v1/social/events/read", headers=friend_headers)
    session.flush()
    assert client.get("/v1/social/events?unread_only=true", headers=friend_headers).json() == []
