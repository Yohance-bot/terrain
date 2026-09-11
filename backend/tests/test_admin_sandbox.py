"""The test lab: real sessions for disposable runners, and a clean teardown."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import settings
from app.core.db import SessionLocal, engine, get_session
from app.main import app
from app.models import Account, Challenge, Friendship, Run, SandboxAccount
from app.services.sandbox import mint_session, require_sandbox, teardown
from tests.test_social_friends import make_player

TOKEN = "sandbox-test-only"


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


def add_runner(client, headers, label: str):
    response = client.post("/v1/admin/sandbox/runners", json={"label": label}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def as_runner(runner) -> dict[str, str]:
    """The same two headers the phone sends."""
    return {
        "X-Device-Id": runner["device_id"],
        "Authorization": f"Bearer {runner['token']}",
    }


def test_the_lab_is_closed_without_authorization_or_the_dev_flag(lab, monkeypatch):
    client, _, headers = lab
    assert client.get("/v1/admin/sandbox/runners").status_code == 403

    monkeypatch.setattr(settings, "developer_mode_enabled", False)
    refused = client.get("/v1/admin/sandbox/runners", headers=headers)
    assert refused.status_code == 403
    assert "test lab is disabled" in refused.json()["detail"]


def test_a_session_can_never_be_minted_for_a_real_player(lab):
    _, session, _ = lab
    real_player, _ = make_player(session, "A Real Person")
    session.flush()

    # The allowlist is the whole safety argument for this feature.
    with pytest.raises(HTTPException) as refusal:
        mint_session(session, real_player.id)
    assert refusal.value.status_code == 404

    with pytest.raises(HTTPException):
        require_sandbox(session, uuid.uuid4())


def test_a_runner_can_drive_the_real_player_api(lab):
    client, session, headers = lab
    first = add_runner(client, headers, "Lab One")
    second = add_runner(client, headers, "Lab Two")
    session.flush()

    # Authenticated accounts are on: this proves the minted session is genuine
    # rather than the endpoint being open.
    unauthenticated = client.get(
        "/v1/social/friends", headers={"X-Device-Id": first["device_id"]}
    )
    assert unauthenticated.status_code == 401

    created = client.post(
        "/v1/social/friends/requests",
        json={"handle": second["handle"]},
        headers=as_runner(first),
    )
    assert created.status_code == 201, created.text
    session.flush()

    incoming = client.get("/v1/social/friends", headers=as_runner(second)).json()["incoming"]
    assert [row["account"]["id"] for row in incoming] == [first["account_id"]]
    accepted = client.post(
        f"/v1/social/friends/requests/{incoming[0]['id']}/accept", headers=as_runner(second)
    )
    assert accepted.status_code == 200, accepted.text


def test_a_synthetic_run_scores_without_touching_territory(lab):
    client, session, headers = lab
    runner = add_runner(client, headers, "Ledger Filler")
    session.flush()

    created = client.post(
        f"/v1/admin/sandbox/runners/{runner['account_id']}/runs",
        json={"distance_m": 8000, "duration_s": 2400},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    session.flush()

    run = session.get(Run, uuid.UUID(created.json()["run_id"]))
    assert run.status == "applied"
    assert float(run.distance_m) == 8000

    # The guarantee is not "no geometry" but "no claim": the lab never runs the
    # matching pipeline, so nothing is granted against any territory.
    from app.models import CapturedArea, InfluenceGrant, RunTerritorySegment

    for model in (InfluenceGrant, RunTerritorySegment, CapturedArea):
        assert session.query(model).filter_by(run_id=run.id).count() == 0

    routed = client.post(
        f"/v1/admin/sandbox/runners/{runner['account_id']}/runs",
        json={"distance_m": 1000, "route_lon": 77.5946, "route_lat": 12.9716},
        headers=headers,
    )
    assert routed.status_code == 201, routed.text
    session.flush()
    with_route = session.get(Run, uuid.UUID(routed.json()["run_id"]))
    assert with_route.geom is not None
    assert len(with_route.sample_ts) >= 2


def test_fast_forward_settles_a_challenge_that_would_take_days(lab):
    client, session, headers = lab
    first = add_runner(client, headers, "Challenger")
    second = add_runner(client, headers, "Opponent")
    session.add(
        Friendship(
            requester_id=uuid.UUID(first["account_id"]),
            addressee_id=uuid.UUID(second["account_id"]),
            status="accepted",
        )
    )
    session.flush()

    created = client.post(
        "/v1/social/challenges",
        json={
            "opponent_id": second["account_id"],
            "metric": "distance",
            "comparison": "most",
            "window_days": 7,
            "goal_text": "A week of running",
        },
        headers=as_runner(first),
    )
    assert created.status_code == 201, created.text
    challenge_id = created.json()["id"]
    client.post(f"/v1/social/challenges/{challenge_id}/accept", headers=as_runner(second))
    session.flush()

    for runner, distance in ((first, 3000), (second, 9000)):
        client.post(
            f"/v1/admin/sandbox/runners/{runner['account_id']}/runs",
            json={"distance_m": distance, "duration_s": 1800},
            headers=headers,
        )
    session.flush()

    settled = client.post(
        f"/v1/admin/sandbox/challenges/{challenge_id}/fast-forward", headers=headers
    )
    assert settled.status_code == 200, settled.text
    assert settled.json()["resolved"] >= 1
    session.flush()

    challenge = session.get(Challenge, uuid.UUID(challenge_id))
    assert challenge.status == "resolved"
    assert challenge.winner_id == uuid.UUID(second["account_id"])


def test_teardown_removes_the_lab_and_leaves_real_players_alone(lab):
    client, session, headers = lab
    keeper, _ = make_player(session, "Stays Put")
    runner = add_runner(client, headers, "Goes Away")
    client.post(
        f"/v1/admin/sandbox/runners/{runner['account_id']}/runs",
        json={"distance_m": 5000},
        headers=headers,
    )
    session.flush()

    result = client.delete("/v1/admin/sandbox/runners", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["runners"] == 1
    assert result.json()["runs"] == 1
    session.flush()

    assert session.get(Account, uuid.UUID(runner["account_id"])) is None
    assert session.get(SandboxAccount, uuid.UUID(runner["account_id"])) is None
    # A real account in the same database is untouched.
    assert session.get(Account, keeper.id) is not None


def test_sandbox_runners_stay_off_the_public_map(lab):
    client, session, headers = lab
    runner = add_runner(client, headers, "Invisible")
    session.flush()

    # The public captured-areas layer excludes sandbox devices by construction.
    from app.models import SandboxAccount as Sandbox

    assert session.get(Sandbox, uuid.UUID(runner["account_id"])).device_id is not None
    public = client.get(
        "/v1/captured-areas?linked_only=true",
        headers={"X-Device-Id": runner["device_id"]},
    )
    assert public.status_code == 200
    assert runner["device_id"] not in public.text


def test_teardown_of_an_empty_lab_is_harmless(lab):
    client, session, headers = lab
    assert teardown(session, []) == {"runners": 0, "runs": 0, "territories_recomputed": 0}
    assert client.delete("/v1/admin/sandbox/runners", headers=headers).json()["runners"] == 0


def test_a_race_can_be_aged_out_from_the_console(lab):
    client, session, headers = lab
    first = add_runner(client, headers, "Racer A")
    second = add_runner(client, headers, "Racer B")
    session.add(
        Friendship(
            requester_id=uuid.UUID(first["account_id"]),
            addressee_id=uuid.UUID(second["account_id"]),
            status="accepted",
        )
    )
    session.flush()

    race = client.post(
        "/v1/social/races",
        json={"opponent_id": second["account_id"], "pin_lat": 12.98, "pin_lon": 77.6},
        headers=as_runner(first),
    )
    assert race.status_code == 201, race.text
    client.post(f"/v1/social/races/{race.json()['id']}/accept", headers=as_runner(second))
    session.flush()

    aged = client.post(
        f"/v1/admin/sandbox/races/{race.json()['id']}/fast-forward", headers=headers
    )
    assert aged.status_code == 200
    assert aged.json()["expired"] >= 1
    assert datetime.now(UTC) > datetime.now(UTC) - timedelta(seconds=1)
