"""Pin-drop races: temporary sharing, proximity arrival, and quiet expiry."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import SessionLocal, engine, get_session
from app.main import app
from app.models import Friendship, Race
from app.services.races import DEFAULT_ARRIVAL_RADIUS_M, expire_due, metres_between
from app.services.social import viewers_of
from tests.test_social_friends import make_player

PIN = {"pin_lat": 12.9800, "pin_lon": 77.6000}
FAR_AWAY = {"lat": 12.9716, "lon": 77.5946}


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
    session.add(Friendship(requester_id=first.id, addressee_id=second.id, status="accepted"))
    session.flush()


def open_race(client, session, headers, opponent, **overrides):
    body = {"opponent_id": str(opponent.id), **PIN, "pin_label": "The lake gate"}
    body.update(overrides)
    response = client.post("/v1/social/races", json=body, headers=headers)
    session.flush()
    return response


def test_arrival_radius_is_forgiving():
    # A step or two either side of the pin has to count.
    twenty_metres_north = metres_between(12.9800, 77.6000, 12.98018, 77.6000)
    assert twenty_metres_north < DEFAULT_ARRIVAL_RADIUS_M


def test_a_race_shares_location_only_while_it_runs(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Pin Dropper")
    opponent, opponent_headers = make_player(session, "Sprinter")
    befriend(session, challenger, opponent)

    created = open_race(client, session, challenger_headers, opponent).json()
    # A pending race shares nothing.
    assert viewers_of(session, challenger.id) == []

    client.post(f"/v1/social/races/{created['id']}/accept", headers=opponent_headers)
    session.flush()
    assert viewers_of(session, challenger.id) == [opponent.id]
    assert viewers_of(session, opponent.id) == [challenger.id]

    client.post("/v1/social/position", json=FAR_AWAY, headers=challenger_headers)
    session.flush()
    seen = client.get("/v1/social/live", headers=opponent_headers).json()
    assert [row["account"]["id"] for row in seen["friends"]] == [str(challenger.id)]
    assert len(seen["races"]) == 1


def test_reaching_the_pin_wins_without_touching_the_phone(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Chaser")
    opponent, opponent_headers = make_player(session, "Winner")
    befriend(session, challenger, opponent)

    created = open_race(client, session, challenger_headers, opponent).json()
    client.post(f"/v1/social/races/{created['id']}/accept", headers=opponent_headers)
    session.flush()

    # A position 15 m from the pin, reported by the ordinary position update.
    near = {"lat": PIN["pin_lat"] + 0.00013, "lon": PIN["pin_lon"], "is_running": True}
    client.post("/v1/social/position", json=near, headers=opponent_headers)
    session.flush()

    race = session.get(Race, uuid.UUID(created["id"]))
    assert race.status == "finished"
    assert race.winner_id == opponent.id
    # Sharing ends with the race.
    assert viewers_of(session, challenger.id) == []
    assert viewers_of(session, opponent.id) == []

    kinds = [
        event["kind"]
        for event in client.get("/v1/social/events", headers=challenger_headers).json()
    ]
    assert "race_finished" in kinds


def test_running_past_but_not_near_the_pin_does_not_win(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Nearly")
    opponent, opponent_headers = make_player(session, "Not Yet")
    befriend(session, challenger, opponent)

    created = open_race(client, session, challenger_headers, opponent).json()
    client.post(f"/v1/social/races/{created['id']}/accept", headers=opponent_headers)
    session.flush()

    client.post("/v1/social/position", json=FAR_AWAY, headers=opponent_headers)
    session.flush()
    assert session.get(Race, uuid.UUID(created["id"])).status == "running"


def test_an_abandoned_race_expires_without_a_loser(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Starter")
    opponent, opponent_headers = make_player(session, "Wanderer")
    befriend(session, challenger, opponent)

    created = open_race(client, session, challenger_headers, opponent).json()
    client.post(f"/v1/social/races/{created['id']}/accept", headers=opponent_headers)
    session.flush()

    race = session.get(Race, uuid.UUID(created["id"]))
    race.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.flush()
    assert expire_due(session) == 1
    session.flush()
    session.refresh(race)

    assert race.status == "expired"
    assert race.winner_id is None
    assert viewers_of(session, challenger.id) == []
    # Nobody is told they lost by walking away.
    kinds = [
        event["kind"] for event in client.get("/v1/social/events", headers=opponent_headers).json()
    ]
    assert "race_finished" not in kinds


def test_an_unanswered_race_invitation_lapses(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Hopeful")
    opponent, _ = make_player(session, "Busy Elsewhere")
    befriend(session, challenger, opponent)

    created = open_race(client, session, challenger_headers, opponent).json()
    race = session.get(Race, uuid.UUID(created["id"]))
    race.accept_deadline = datetime.now(UTC) - timedelta(seconds=1)
    session.flush()

    assert expire_due(session) == 1
    session.flush()
    session.refresh(race)
    assert race.status == "expired"


def test_either_side_can_walk_away_mid_race(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Quitter")
    opponent, opponent_headers = make_player(session, "Left Standing")
    befriend(session, challenger, opponent)

    created = open_race(client, session, challenger_headers, opponent).json()
    client.post(f"/v1/social/races/{created['id']}/accept", headers=opponent_headers)
    session.flush()

    withdrawn = client.post(
        f"/v1/social/races/{created['id']}/withdraw", headers=challenger_headers
    )
    session.flush()
    assert withdrawn.status_code == 200
    assert session.get(Race, uuid.UUID(created["id"])).winner_id is None
    assert viewers_of(session, opponent.id) == []


def test_a_race_needs_a_friendship_and_only_one_at_a_time(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Racer One")
    stranger, _ = make_player(session, "Unknown")
    assert open_race(client, session, challenger_headers, stranger).status_code == 403

    friend, _ = make_player(session, "Racer Two")
    befriend(session, challenger, friend)
    assert open_race(client, session, challenger_headers, friend).status_code == 201
    assert open_race(client, session, challenger_headers, friend).status_code == 409


def test_a_race_does_not_disturb_a_standing_sharing_choice(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Always Open")
    opponent, opponent_headers = make_player(session, "Race Partner")
    befriend(session, challenger, opponent)

    client.put(
        f"/v1/social/sharing/{opponent.id}",
        json={"share_location": True},
        headers=challenger_headers,
    )
    session.flush()

    created = open_race(client, session, challenger_headers, opponent).json()
    client.post(f"/v1/social/races/{created['id']}/accept", headers=opponent_headers)
    client.post(f"/v1/social/races/{created['id']}/withdraw", headers=opponent_headers)
    session.flush()

    # The permanent choice survives the race that ended around it.
    assert viewers_of(session, challenger.id) == [opponent.id]
    assert viewers_of(session, opponent.id) == []
