"""Ghosts: built from server evidence, trimmed for strangers, reusable forever."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import SessionLocal, engine, get_session
from app.main import app
from app.models import GhostRun, Run
from app.services.ghosts import PUBLIC_TRIM_M, build_path, trim_for_public
from app.services.races import metres_between
from tests.test_social_friends import make_player


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


def add_recorded_run(session, headers, *, points: int = 60, spacing_m: float = 20.0):
    """An applied run with a straight route and one fix every 10 seconds."""
    lat, lon = 12.9716, 77.5946
    step = spacing_m / 111_320.0
    coordinates = [(lon, lat + step * index) for index in range(points)]
    wkt = ", ".join(f"{point_lon} {point_lat}" for point_lon, point_lat in coordinates)
    started = datetime.now(UTC) - timedelta(hours=2)
    origin_ms = int(started.timestamp() * 1000)

    run = Run(
        id=uuid.uuid4(),
        device_id=uuid.UUID(headers["X-Device-Id"]),
        started_at=started,
        ended_at=started + timedelta(seconds=10 * (points - 1)),
        duration_s=10 * (points - 1),
        distance_m=spacing_m * (points - 1),
        geom=f"SRID=4326;LINESTRING({wkt})",
        sample_ts=[origin_ms + index * 10_000 for index in range(points)],
        sample_accuracy_m=[5.0] * points,
        raw_payload={},
        pipeline_version=1,
        status="applied",
    )
    session.add(run)
    session.flush()
    return run


def test_a_ghost_carries_position_and_pacing_from_the_server(social):
    client, session = social
    runner, headers = make_player(session, "Route Setter")
    run = add_recorded_run(session, headers)

    path = build_path(session, run)
    assert len(path) == 60
    assert path[0][2] == 0
    # Offsets are milliseconds from the start, which is what a client replays.
    assert path[1][2] == 10_000

    created = client.post(
        "/v1/social/ghosts",
        json={"run_id": str(run.id), "name": "Evening loop"},
        headers=headers,
    )
    session.flush()
    assert created.status_code == 201, created.text
    assert created.json()["duration_s"] == run.duration_s
    assert created.json()["is_public"] is False
    assert created.json()["share_live_location"] is False


def test_only_your_own_processed_run_becomes_a_ghost(social):
    client, session = social
    _, headers = make_player(session, "Owner")
    _, other_headers = make_player(session, "Someone Else")
    run = add_recorded_run(session, headers)

    theirs = client.post(
        "/v1/social/ghosts", json={"run_id": str(run.id), "name": "Not mine"}, headers=other_headers
    )
    assert theirs.status_code == 404

    run.status = "submitted"
    session.flush()
    unprocessed = client.post(
        "/v1/social/ghosts", json={"run_id": str(run.id), "name": "Too early"}, headers=headers
    )
    assert unprocessed.status_code == 409


def test_a_public_ghost_hides_where_its_runner_started_and_finished(social):
    client, session = social
    runner, headers = make_player(session, "Broadcaster")
    _, stranger_headers = make_player(session, "Passer By")
    run = add_recorded_run(session, headers)
    created = client.post(
        "/v1/social/ghosts",
        json={"run_id": str(run.id), "name": "Park benchmark", "is_public": True},
        headers=headers,
    ).json()
    session.flush()

    full = client.get(f"/v1/social/ghosts/{created['id']}", headers=headers).json()["path"]
    trimmed = client.get(
        f"/v1/social/ghosts/{created['id']}", headers=stranger_headers
    ).json()["path"]

    assert len(full) == 60
    assert len(trimmed) < len(full)
    assert metres_between(full[0][1], full[0][0], trimmed[0][1], trimmed[0][0]) >= PUBLIC_TRIM_M
    assert metres_between(full[-1][1], full[-1][0], trimmed[-1][1], trimmed[-1][0]) >= PUBLIC_TRIM_M


def test_a_short_route_is_not_publishable_rather_than_partly_exposed(social):
    # Trimming both ends off a short route leaves nothing that can be shown.
    path = [[77.5946, 12.9716, 0], [77.5946, 12.9717, 10_000], [77.5946, 12.9718, 20_000]]
    assert trim_for_public(path) == []


def test_broadcasting_a_ghost_never_shares_live_location(social):
    client, session = social
    runner, headers = make_player(session, "Careful")
    run = add_recorded_run(session, headers)
    created = client.post(
        "/v1/social/ghosts",
        json={"run_id": str(run.id), "name": "Public route", "is_public": True},
        headers=headers,
    ).json()
    session.flush()

    ghost = session.get(GhostRun, uuid.UUID(created["id"]))
    assert ghost.is_public is True
    assert ghost.share_live_location is False

    # It is a separate switch, and it cannot be set without the broadcast.
    private = client.post(
        "/v1/social/ghosts",
        json={"run_id": str(add_recorded_run(session, headers).id), "name": "Private"},
        headers=headers,
    ).json()
    session.flush()
    refused = client.put(
        f"/v1/social/ghosts/{private['id']}",
        json={"share_live_location": True},
        headers=headers,
    )
    assert refused.status_code == 422

    client.put(
        f"/v1/social/ghosts/{created['id']}", json={"share_live_location": True}, headers=headers
    )
    session.flush()
    session.refresh(ghost)
    assert ghost.share_live_location is True

    # Withdrawing the broadcast withdraws the live sharing that sat on top of it.
    client.put(f"/v1/social/ghosts/{created['id']}", json={"is_public": False}, headers=headers)
    session.flush()
    session.refresh(ghost)
    assert ghost.share_live_location is False


def test_a_private_ghost_is_not_visible_or_raceable_by_others(social):
    client, session = social
    runner, headers = make_player(session, "Keeps It Quiet")
    _, stranger_headers = make_player(session, "Curious")
    run = add_recorded_run(session, headers)
    created = client.post(
        "/v1/social/ghosts", json={"run_id": str(run.id), "name": "Mine only"}, headers=headers
    ).json()
    session.flush()

    assert (
        client.get(f"/v1/social/ghosts/{created['id']}", headers=stranger_headers).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/social/ghosts/{created['id']}/attempts", headers=stranger_headers
        ).status_code
        == 404
    )


def test_a_broadcast_ghost_is_a_reusable_benchmark(social):
    client, session = social
    runner, headers = make_player(session, "Benchmark Setter")
    _, first_headers = make_player(session, "First Racer")
    _, second_headers = make_player(session, "Second Racer")
    run = add_recorded_run(session, headers)
    created = client.post(
        "/v1/social/ghosts",
        json={"run_id": str(run.id), "name": "The riverside", "is_public": True},
        headers=headers,
    ).json()
    session.flush()

    attempts = ((first_headers, run.duration_s - 60), (second_headers, run.duration_s + 60))
    for racer_headers, elapsed in attempts:
        attempt = client.post(
            f"/v1/social/ghosts/{created['id']}/attempts", headers=racer_headers
        ).json()
        session.flush()
        finished = client.post(
            f"/v1/social/ghosts/attempts/{attempt['id']}/finish",
            json={"elapsed_s": elapsed},
            headers=racer_headers,
        ).json()
        session.flush()
        assert finished["beat_ghost"] is (elapsed < run.duration_s)

    # Still there, and still raceable, after both attempts.
    still_available = client.get(f"/v1/social/ghosts/{created['id']}", headers=first_headers)
    assert still_available.status_code == 200
    assert still_available.json()["best_elapsed_s"] == run.duration_s - 60


def test_nearby_lists_public_ghosts_only(social):
    client, session = social
    runner, headers = make_player(session, "Local Runner")
    _, seeker_headers = make_player(session, "Visitor")
    public_run = add_recorded_run(session, headers)
    private_run = add_recorded_run(session, headers)
    client.post(
        "/v1/social/ghosts",
        json={"run_id": str(public_run.id), "name": "Open benchmark", "is_public": True},
        headers=headers,
    )
    client.post(
        "/v1/social/ghosts",
        json={"run_id": str(private_run.id), "name": "Hidden"},
        headers=headers,
    )
    session.flush()

    found = client.get(
        "/v1/social/ghosts/nearby?lat=12.9716&lon=77.5946&radius_m=1000", headers=seeker_headers
    ).json()
    assert [ghost["name"] for ghost in found] == ["Open benchmark"]

    far = client.get(
        "/v1/social/ghosts/nearby?lat=19.0760&lon=72.8777&radius_m=1000", headers=seeker_headers
    ).json()
    assert far == []


def test_a_run_becomes_at_most_one_ghost(social):
    client, session = social
    _, headers = make_player(session, "Duplicate")
    run = add_recorded_run(session, headers)
    body = {"run_id": str(run.id), "name": "Once"}
    assert client.post("/v1/social/ghosts", json=body, headers=headers).status_code == 201
    session.flush()
    assert client.post("/v1/social/ghosts", json=body, headers=headers).status_code == 409
