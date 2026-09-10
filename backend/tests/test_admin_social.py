"""The console can see the social layer's shape without seeing anyone's location."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import settings
from app.core.db import SessionLocal, engine, get_session
from app.main import app
from app.models import Challenge, FriendShareSettings, Friendship, LivePosition, Race
from tests.test_social_friends import make_player

TOKEN = "social-console-test-only"


@pytest.fixture()
def console(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    monkeypatch.setattr(settings, "admin_operations_token", SecretStr(TOKEN))
    monkeypatch.setattr(settings, "authenticated_accounts_enabled", False)
    app.dependency_overrides[get_session] = lambda: session
    try:
        yield TestClient(app), session, {"X-Admin-Token": TOKEN}
    finally:
        app.dependency_overrides.pop(get_session, None)
        session.close()
        transaction.rollback()
        connection.close()


def test_social_console_requires_authorization(console):
    client, _, _ = console
    assert client.get("/v1/admin/social/overview").status_code == 403
    assert client.get("/v1/admin/social/challenges").status_code == 403
    assert client.post("/v1/admin/social/resolve").status_code == 403


def test_overview_counts_relationships_challenges_and_races(console):
    client, session, headers = console
    first, _ = make_player(session, "Console One")
    second, _ = make_player(session, "Console Two")
    now = datetime.now(UTC)
    session.add(Friendship(requester_id=first.id, addressee_id=second.id, status="accepted"))
    session.add(
        FriendShareSettings(owner_id=first.id, viewer_id=second.id, share_location=True)
    )
    session.add(
        Challenge(
            challenger_id=first.id,
            opponent_id=second.id,
            metric="distance",
            comparison="most",
            window_start=now - timedelta(days=1),
            window_end=now + timedelta(days=2),
            goal_text="More distance",
            status="accepted",
            accept_deadline=now + timedelta(hours=12),
        )
    )
    session.add(
        Race(
            challenger_id=first.id,
            opponent_id=second.id,
            pin_lat=12.98,
            pin_lon=77.6,
            radius_m=25,
            status="running",
            accept_deadline=now + timedelta(minutes=20),
            started_at=now,
            expires_at=now + timedelta(hours=2),
        )
    )
    session.flush()

    overview = client.get("/v1/admin/social/overview", headers=headers).json()
    assert overview["friendships_accepted"] >= 1
    assert overview["sharing_location"] >= 1
    assert overview["challenges_open"] >= 1
    assert overview["races_running"] >= 1


def test_the_console_never_exposes_a_position(console):
    client, session, headers = console
    runner, _ = make_player(session, "Tracked")
    watcher, _ = make_player(session, "Watcher")
    session.add(Friendship(requester_id=runner.id, addressee_id=watcher.id, status="accepted"))
    session.add(
        FriendShareSettings(owner_id=runner.id, viewer_id=watcher.id, share_location=True)
    )
    session.add(
        LivePosition(account_id=runner.id, lat=12.9716, lon=77.5946, updated_at=datetime.now(UTC))
    )
    session.flush()

    overview = client.get("/v1/admin/social/overview", headers=headers)
    assert overview.status_code == 200
    # A count of who is reporting, and nothing that could place them.
    assert overview.json()["players_visible_now"] >= 1
    body = overview.text
    assert "12.97" not in body and "77.59" not in body

    races = client.get("/v1/admin/social/races", headers=headers)
    assert "pin_lat" not in races.text and "pin_lon" not in races.text


def test_challenges_listing_names_both_sides_and_the_stake(console):
    client, session, headers = console
    first, _ = make_player(session, "Stake Holder")
    second, _ = make_player(session, "Rival")
    now = datetime.now(UTC)
    session.add(
        Challenge(
            challenger_id=first.id,
            opponent_id=second.id,
            metric="distance",
            comparison="most",
            window_start=now - timedelta(days=3),
            window_end=now - timedelta(days=1),
            goal_text="Settled already",
            status="resolved",
            accept_deadline=now - timedelta(days=3),
            outcome="opponent",
            winner_id=second.id,
            challenger_value=3000,
            opponent_value=9000,
            resolved_at=now,
        )
    )
    session.flush()

    listed = client.get("/v1/admin/social/challenges", headers=headers).json()
    row = next(entry for entry in listed if entry["goal_text"] == "Settled already")
    assert row["challenger"] == "Stake Holder"
    assert row["opponent"] == "Rival"
    assert row["winner"] == "Rival"
    assert row["stake_transferred"] is False


def test_health_surfaces_work_the_resolver_still_owes(console):
    client, session, headers = console
    first, _ = make_player(session, "Overdue One")
    second, _ = make_player(session, "Overdue Two")
    now = datetime.now(UTC)
    session.add(
        Challenge(
            challenger_id=first.id,
            opponent_id=second.id,
            metric="distance",
            comparison="most",
            window_start=now - timedelta(days=4),
            window_end=now - timedelta(hours=6),
            goal_text="Nobody opened the app",
            status="accepted",
            accept_deadline=now - timedelta(days=4),
        )
    )
    session.flush()

    health = client.get("/v1/admin/social/health", headers=headers).json()
    assert health["challenges_overdue"] >= 1
    assert health["oldest_overdue_challenge_hours"] >= 5

    resolved = client.post("/v1/admin/social/resolve", headers=headers).json()
    assert resolved["resolved"] >= 1
    session.flush()
    assert client.get("/v1/admin/social/health", headers=headers).json()["challenges_overdue"] == 0
