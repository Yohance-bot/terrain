"""The console's scripted checks, run against the same endpoints they drive.

`admin/src/features/scenarios.ts` is the operator-facing copy of these
sequences. Keeping a server-side mirror means a change that breaks the lab fails
in CI rather than the first time somebody opens the console.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import settings
from app.core.db import SessionLocal, engine, get_session
from app.main import app

TOKEN = "lab-scenarios-only"
BENGALURU = {"lat": 12.9716, "lon": 77.5946}
PIN = {"pin_lat": 12.98, "pin_lon": 77.6}


@pytest.fixture()
def lab(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    monkeypatch.setattr(settings, "admin_operations_token", SecretStr(TOKEN))
    monkeypatch.setattr(settings, "developer_mode_enabled", True)
    monkeypatch.setattr(settings, "authenticated_accounts_enabled", True)
    app.dependency_overrides[get_session] = lambda: session
    try:
        yield TestClient(app), session, {"X-Admin-Token": TOKEN}
    finally:
        app.dependency_overrides.pop(get_session, None)
        session.close()
        transaction.rollback()
        connection.close()


def runner(client, headers, label):
    created = client.post("/v1/admin/sandbox/runners", json={"label": label}, headers=headers)
    assert created.status_code == 201, created.text
    return created.json()


def act(runner_row):
    return {
        "X-Device-Id": runner_row["device_id"],
        "Authorization": f"Bearer {runner_row['token']}",
    }


def befriend(client, session, first, second):
    client.post(
        "/v1/social/friends/requests",
        json={"handle": second["handle"]},
        headers=act(first),
    )
    session.flush()
    incoming = client.get("/v1/social/friends", headers=act(second)).json()["incoming"]
    assert incoming, "friend request did not arrive"
    client.post(
        f"/v1/social/friends/requests/{incoming[0]['id']}/accept", headers=act(second)
    )
    session.flush()


def place(client, session, runner_row, lat, lon):
    response = client.post(
        "/v1/social/position",
        json={"lat": lat, "lon": lon, "is_running": True},
        headers=act(runner_row),
    )
    session.flush()
    return response


def test_scenario_identity(lab):
    client, session, headers = lab
    first = runner(client, headers, "Identity A")
    second = runner(client, headers, "Identity B")
    session.flush()

    assert first["handle"]
    found = client.get(
        f"/v1/social/search?q={first['handle']}", headers=act(second)
    ).json()
    assert any(row["id"] == first["account_id"] for row in found)
    assert found[0]["relationship"] == "none"

    by_id = client.get(
        f"/v1/social/search?q={first['account_id']}", headers=act(second)
    ).json()
    assert len(by_id) == 1


def test_scenario_sharing_is_opt_in_and_revocable(lab):
    client, session, headers = lab
    sharer = runner(client, headers, "Sharer")
    watcher = runner(client, headers, "Watcher")
    befriend(client, session, sharer, watcher)

    place(client, session, sharer, BENGALURU["lat"], BENGALURU["lon"])
    assert client.get("/v1/social/live", headers=act(watcher)).json()["friends"] == []

    client.put(
        f"/v1/social/sharing/{watcher['account_id']}",
        json={"share_location": True},
        headers=act(sharer),
    )
    place(client, session, sharer, BENGALURU["lat"], BENGALURU["lon"])
    assert len(client.get("/v1/social/live", headers=act(watcher)).json()["friends"]) == 1

    client.put(
        f"/v1/social/sharing/{watcher['account_id']}",
        json={"share_location": False},
        headers=act(sharer),
    )
    session.flush()
    assert client.get("/v1/social/live", headers=act(watcher)).json()["friends"] == []


def test_scenario_run_alert_does_not_leak_position(lab):
    client, session, headers = lab
    announcer = runner(client, headers, "Announcer")
    listener = runner(client, headers, "Listener")
    befriend(client, session, announcer, listener)

    client.put(
        f"/v1/social/sharing/{listener['account_id']}",
        json={"notify_on_run_start": True},
        headers=act(announcer),
    )
    client.post(f"/v1/social/runs/{uuid.uuid4()}/started", headers=act(announcer))
    place(client, session, announcer, BENGALURU["lat"], BENGALURU["lon"])

    events = client.get("/v1/social/events", headers=act(listener)).json()
    assert any(event["kind"] == "run_started" for event in events)
    assert client.get("/v1/social/live", headers=act(listener)).json()["friends"] == []


def test_scenario_race_arrival_and_revocation(lab):
    client, session, headers = lab
    first = runner(client, headers, "Pin Dropper")
    second = runner(client, headers, "Sprinter")
    befriend(client, session, first, second)

    race = client.post(
        "/v1/social/races",
        json={"opponent_id": second["account_id"], **PIN, "pin_label": "Lab pin"},
        headers=act(first),
    )
    assert race.status_code == 201, race.text
    client.post(f"/v1/social/races/{race.json()['id']}/accept", headers=act(second))
    session.flush()

    place(client, session, first, BENGALURU["lat"], BENGALURU["lon"])
    seen = client.get("/v1/social/live", headers=act(second)).json()
    assert [row["account"]["id"] for row in seen["friends"]] == [first["account_id"]]
    assert len(seen["races"]) == 1

    # Fifteen metres from the pin, through the ordinary position endpoint.
    place(client, session, second, PIN["pin_lat"] + 0.00013, PIN["pin_lon"])
    races = client.get("/v1/social/races", headers=act(second)).json()
    finished = next(row for row in races if row["id"] == race.json()["id"])
    assert finished["status"] == "finished"
    assert finished["winner_id"] == second["account_id"]
    assert client.get("/v1/social/live", headers=act(second)).json()["friends"] == []


def test_scenario_ghost_broadcast_and_trim(lab):
    client, session, headers = lab
    owner = runner(client, headers, "Ghost Owner")
    racer = runner(client, headers, "Ghost Racer")

    routed = client.post(
        f"/v1/admin/sandbox/runners/{owner['account_id']}/runs",
        json={
            "distance_m": 1200,
            "duration_s": 600,
            "route_lon": BENGALURU["lon"],
            "route_lat": BENGALURU["lat"],
        },
        headers=headers,
    )
    assert routed.status_code == 201, routed.text
    session.flush()

    ghost = client.post(
        "/v1/social/ghosts",
        json={"run_id": routed.json()["run_id"], "name": "Lab benchmark", "is_public": True},
        headers=act(owner),
    )
    assert ghost.status_code == 201, ghost.text
    ghost_id = ghost.json()["id"]
    assert ghost.json()["is_public"] is True
    assert ghost.json()["share_live_location"] is False
    session.flush()

    nearby = client.get(
        f"/v1/social/ghosts/nearby?lat={BENGALURU['lat']}&lon={BENGALURU['lon']}&radius_m=2000",
        headers=act(racer),
    ).json()
    assert any(row["id"] == ghost_id for row in nearby)

    mine = client.get(f"/v1/social/ghosts/{ghost_id}", headers=act(owner)).json()
    theirs = client.get(f"/v1/social/ghosts/{ghost_id}", headers=act(racer)).json()
    assert len(theirs["path"]) < len(mine["path"]), "a public ghost was served untrimmed"

    attempt = client.post(
        f"/v1/social/ghosts/{ghost_id}/attempts", headers=act(racer)
    ).json()
    session.flush()
    finished = client.post(
        f"/v1/social/ghosts/attempts/{attempt['id']}/finish",
        json={"elapsed_s": ghost.json()["duration_s"] - 60},
        headers=act(racer),
    ).json()
    assert finished["beat_ghost"] is True
    # A benchmark is never consumed by being raced.
    assert client.get(f"/v1/social/ghosts/{ghost_id}", headers=act(racer)).status_code == 200


def test_scenario_challenge_settles_to_the_right_winner(lab):
    client, session, headers = lab
    challenger = runner(client, headers, "Challenger")
    opponent = runner(client, headers, "Opponent")
    befriend(client, session, challenger, opponent)

    challenge = client.post(
        "/v1/social/challenges",
        json={
            "opponent_id": opponent["account_id"],
            "metric": "distance",
            "comparison": "most",
            "window_days": 3,
            "goal_text": "Most distance over three days",
        },
        headers=act(challenger),
    )
    assert challenge.status_code == 201, challenge.text
    challenge_id = challenge.json()["id"]
    client.post(f"/v1/social/challenges/{challenge_id}/accept", headers=act(opponent))
    session.flush()

    for who, distance in ((challenger, 3000), (opponent, 9000)):
        client.post(
            f"/v1/admin/sandbox/runners/{who['account_id']}/runs",
            json={"distance_m": distance},
            headers=headers,
        )
    session.flush()

    settled = client.post(
        f"/v1/admin/sandbox/challenges/{challenge_id}/fast-forward", headers=headers
    )
    assert settled.json()["resolved"] >= 1
    session.flush()

    listed = client.get("/v1/social/challenges", headers=act(challenger)).json()
    resolved = next(row for row in listed if row["id"] == challenge_id)
    assert resolved["status"] == "resolved"
    assert resolved["winner_id"] == opponent["account_id"]
