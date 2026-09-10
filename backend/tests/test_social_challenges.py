"""Challenge measurement, settlement and stake transfer, on real ledger rows."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func

from app.core.config import settings
from app.core.db import SessionLocal, engine, get_session
from app.main import app
from app.models import CapturedArea, Challenge, ChallengeStake, Friendship, Run
from app.services.challenges import captured_area_m2, resolve_due
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


def befriend(session, first, second) -> None:
    session.add(Friendship(requester_id=first.id, addressee_id=second.id, status="accepted"))
    session.flush()


def device_of(session, headers) -> uuid.UUID:
    return uuid.UUID(headers["X-Device-Id"])


def add_run(session, headers, *, distance_m: float, ended_at: datetime, duration_s: int = 1800):
    """An applied run, which is the only kind a challenge counts."""
    run = Run(
        id=uuid.uuid4(),
        device_id=device_of(session, headers),
        started_at=ended_at - timedelta(seconds=duration_s),
        ended_at=ended_at,
        duration_s=duration_s,
        distance_m=distance_m,
        raw_payload={},
        pipeline_version=1,
        status="applied",
    )
    session.add(run)
    session.flush()
    return run


def add_captured_area(session, headers, run, *, size_deg: float = 0.001):
    """A square loop closure owned by this player's device."""
    lon, lat = 77.5946, 12.9716
    ring = (
        f"{lon} {lat}, {lon + size_deg} {lat}, {lon + size_deg} {lat + size_deg}, "
        f"{lon} {lat + size_deg}, {lon} {lat}"
    )
    area = CapturedArea(
        run_id=run.id,
        owner_device_id=device_of(session, headers),
        geom=func.ST_GeogFromText(f"POLYGON(({ring}))"),
    )
    session.add(area)
    session.flush()
    session.refresh(area)
    return area


def close_window(session, challenge) -> None:
    """Move a live challenge's whole window into the past so it comes due."""
    length = challenge.window_end - challenge.window_start
    challenge.window_end = datetime.now(UTC) - timedelta(seconds=1)
    challenge.window_start = challenge.window_end - length
    session.flush()


def start_challenge(client, session, headers, opponent, **overrides):
    body = {
        "opponent_id": str(opponent.id),
        "metric": "distance",
        "comparison": "most",
        "window_days": 3,
        "goal_text": "I'll cover more distance than you in the next 3 days",
    }
    body.update(overrides)
    response = client.post("/v1/social/challenges", json=body, headers=headers)
    session.flush()
    return response


def test_a_challenge_needs_an_accepted_friendship(social):
    client, session = social
    _, headers = make_player(session, "Challenger")
    stranger, _ = make_player(session, "Stranger")

    assert start_challenge(client, session, headers, stranger).status_code == 403


def test_step_count_is_not_an_available_metric(social):
    client, session = social
    challenger, headers = make_player(session, "Metric Tester")
    opponent, _ = make_player(session, "Opponent")
    befriend(session, challenger, opponent)

    # Nothing in the app counts steps, so the API must not accept it as a
    # condition it could never settle.
    assert start_challenge(client, session, headers, opponent, metric="steps").status_code == 422


def test_the_window_starts_when_the_challenge_is_accepted(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Waiting")
    opponent, opponent_headers = make_player(session, "Slow Reply")
    befriend(session, challenger, opponent)

    created = start_challenge(client, session, challenger_headers, opponent).json()
    challenge = session.get(Challenge, uuid.UUID(created["id"]))
    challenge.window_start = datetime.now(UTC) - timedelta(days=1)
    challenge.window_end = challenge.window_start + timedelta(days=3)
    session.flush()

    accepted = client.post(
        f"/v1/social/challenges/{created['id']}/accept", headers=opponent_headers
    ).json()
    session.flush()
    # The promised three days are still three days, counted from the reply.
    started = datetime.fromisoformat(accepted["window_start"])
    ended = datetime.fromisoformat(accepted["window_end"])
    assert (ended - started) == timedelta(days=3)
    assert (datetime.now(UTC) - started) < timedelta(minutes=1)


def test_most_distance_is_settled_from_the_run_ledger(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Further")
    opponent, opponent_headers = make_player(session, "Shorter")
    befriend(session, challenger, opponent)

    created = start_challenge(client, session, challenger_headers, opponent).json()
    client.post(f"/v1/social/challenges/{created['id']}/accept", headers=opponent_headers)
    session.flush()

    inside_window = datetime.now(UTC) - timedelta(hours=1)
    add_run(session, challenger_headers, distance_m=8000, ended_at=inside_window)
    add_run(session, opponent_headers, distance_m=5000, ended_at=inside_window)
    # A run outside the window must not count.
    add_run(
        session,
        opponent_headers,
        distance_m=90000,
        ended_at=datetime.now(UTC) - timedelta(days=30),
    )

    challenge = session.get(Challenge, uuid.UUID(created["id"]))
    close_window(session, challenge)

    assert resolve_due(session) == {"expired": 0, "resolved": 1}
    session.flush()
    session.refresh(challenge)
    assert challenge.status == "resolved"
    assert challenge.outcome == "challenger"
    assert challenge.winner_id == challenger.id
    assert challenge.challenger_value == 8000
    assert challenge.opponent_value == 5000

    for headers in (challenger_headers, opponent_headers):
        kinds = [
            event["kind"] for event in client.get("/v1/social/events", headers=headers).json()
        ]
        assert "challenge_resolved" in kinds


def test_nobody_running_is_not_a_draw_and_moves_no_stake(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Idle One")
    opponent, opponent_headers = make_player(session, "Idle Two")
    befriend(session, challenger, opponent)

    staked_run = add_run(
        session, challenger_headers, distance_m=4000, ended_at=datetime.now(UTC) - timedelta(days=9)
    )
    area = add_captured_area(session, challenger_headers, staked_run)
    created = start_challenge(
        client,
        session,
        challenger_headers,
        opponent,
        stake={"staked_area_id": str(area.id)},
    ).json()
    client.post(f"/v1/social/challenges/{created['id']}/accept", headers=opponent_headers)
    session.flush()

    challenge = session.get(Challenge, uuid.UUID(created["id"]))
    close_window(session, challenge)
    resolve_due(session)
    session.flush()
    session.refresh(challenge)
    session.refresh(area)

    assert challenge.outcome == "nobody"
    assert challenge.winner_id is None
    assert area.owner_device_id == device_of(session, challenger_headers)
    assert session.get(ChallengeStake, challenge.id).transferred_at is None


def test_fastest_to_a_target_beats_running_further_afterwards(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Quick Off")
    opponent, opponent_headers = make_player(session, "Late Surge")
    befriend(session, challenger, opponent)

    created = start_challenge(
        client,
        session,
        challenger_headers,
        opponent,
        comparison="fastest_to",
        target_value=5000,
        goal_text="First to 5 km",
    ).json()
    client.post(f"/v1/social/challenges/{created['id']}/accept", headers=opponent_headers)
    session.flush()

    now = datetime.now(UTC)
    add_run(session, challenger_headers, distance_m=5200, ended_at=now - timedelta(hours=10))
    # The opponent covers far more, but reaches the target later.
    add_run(session, opponent_headers, distance_m=4000, ended_at=now - timedelta(hours=9))
    add_run(session, opponent_headers, distance_m=9000, ended_at=now - timedelta(hours=2))

    challenge = session.get(Challenge, uuid.UUID(created["id"]))
    close_window(session, challenge)
    resolve_due(session)
    session.flush()
    session.refresh(challenge)

    assert challenge.outcome == "challenger"
    assert challenge.opponent_value == 13000


def test_an_unanswered_challenge_expires(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Ignored")
    opponent, _ = make_player(session, "Silent")
    befriend(session, challenger, opponent)

    created = start_challenge(client, session, challenger_headers, opponent).json()
    challenge = session.get(Challenge, uuid.UUID(created["id"]))
    challenge.accept_deadline = datetime.now(UTC) - timedelta(seconds=1)
    session.flush()

    assert resolve_due(session)["expired"] == 1
    session.flush()
    session.refresh(challenge)
    assert challenge.status == "expired"

    late = client.post(f"/v1/social/challenges/{created['id']}/accept", headers=challenger_headers)
    assert late.status_code in (403, 409)


def test_an_entry_condition_keeps_out_a_player_without_enough_ground(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Land Holder")
    opponent, opponent_headers = make_player(session, "Landless")
    befriend(session, challenger, opponent)

    run = add_run(
        session, challenger_headers, distance_m=4000, ended_at=datetime.now(UTC) - timedelta(days=9)
    )
    area = add_captured_area(session, challenger_headers, run)
    session.refresh(area)
    held = captured_area_m2(session, challenger.id)
    assert held > 1000

    created = start_challenge(
        client,
        session,
        challenger_headers,
        opponent,
        stake={"staked_area_id": str(area.id), "require_opponent_area_m2": held},
    ).json()
    refused = client.post(
        f"/v1/social/challenges/{created['id']}/accept", headers=opponent_headers
    )
    assert refused.status_code == 403
    assert "captured area" in refused.json()["detail"]

    # Once they hold enough ground of their own, they can accept.
    opponent_run = add_run(
        session, opponent_headers, distance_m=4000, ended_at=datetime.now(UTC) - timedelta(days=9)
    )
    add_captured_area(session, opponent_headers, opponent_run, size_deg=0.002)
    session.flush()
    assert (
        client.post(
            f"/v1/social/challenges/{created['id']}/accept", headers=opponent_headers
        ).status_code
        == 200
    )


def test_a_lost_stake_moves_to_the_winner(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Confident")
    opponent, opponent_headers = make_player(session, "Underdog")
    befriend(session, challenger, opponent)

    run = add_run(
        session, challenger_headers, distance_m=4000, ended_at=datetime.now(UTC) - timedelta(days=9)
    )
    area = add_captured_area(session, challenger_headers, run)
    created = start_challenge(
        client, session, challenger_headers, opponent, stake={"staked_area_id": str(area.id)}
    ).json()
    assert created["stake"]["staked_area_m2"] > 1000

    client.post(f"/v1/social/challenges/{created['id']}/accept", headers=opponent_headers)
    session.flush()
    inside_window = datetime.now(UTC) - timedelta(hours=1)
    add_run(session, opponent_headers, distance_m=12000, ended_at=inside_window)
    add_run(session, challenger_headers, distance_m=3000, ended_at=inside_window)

    challenge = session.get(Challenge, uuid.UUID(created["id"]))
    close_window(session, challenge)
    resolve_due(session)
    session.flush()
    session.refresh(area)

    assert challenge.outcome == "opponent"
    assert area.owner_device_id == device_of(session, opponent_headers)
    assert area.transferred_from_device_id == device_of(session, challenger_headers)
    assert area.transferred_by_challenge_id == challenge.id


def test_a_won_stake_stays_where_it_was(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Defender")
    opponent, opponent_headers = make_player(session, "Attacker")
    befriend(session, challenger, opponent)

    run = add_run(
        session, challenger_headers, distance_m=4000, ended_at=datetime.now(UTC) - timedelta(days=9)
    )
    area = add_captured_area(session, challenger_headers, run)
    created = start_challenge(
        client, session, challenger_headers, opponent, stake={"staked_area_id": str(area.id)}
    ).json()
    client.post(f"/v1/social/challenges/{created['id']}/accept", headers=opponent_headers)
    session.flush()
    add_run(
        session,
        challenger_headers,
        distance_m=12000,
        ended_at=datetime.now(UTC) - timedelta(hours=1),
    )

    challenge = session.get(Challenge, uuid.UUID(created["id"]))
    close_window(session, challenge)
    resolve_due(session)
    session.flush()
    session.refresh(area)

    assert challenge.outcome == "challenger"
    assert area.owner_device_id == device_of(session, challenger_headers)
    assert area.transferred_at is None


def test_you_cannot_stake_ground_you_do_not_own(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Borrower")
    opponent, opponent_headers = make_player(session, "Owner")
    befriend(session, challenger, opponent)

    run = add_run(
        session, opponent_headers, distance_m=4000, ended_at=datetime.now(UTC) - timedelta(days=9)
    )
    theirs = add_captured_area(session, opponent_headers, run)

    refused = start_challenge(
        client, session, challenger_headers, opponent, stake={"staked_area_id": str(theirs.id)}
    )
    assert refused.status_code == 422


def test_only_the_challenger_can_cancel_and_only_before_acceptance(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Withdrawer")
    opponent, opponent_headers = make_player(session, "Accepter")
    befriend(session, challenger, opponent)

    created = start_challenge(client, session, challenger_headers, opponent).json()
    assert (
        client.post(
            f"/v1/social/challenges/{created['id']}/cancel", headers=opponent_headers
        ).status_code
        == 403
    )
    client.post(f"/v1/social/challenges/{created['id']}/accept", headers=opponent_headers)
    session.flush()
    assert (
        client.post(
            f"/v1/social/challenges/{created['id']}/cancel", headers=challenger_headers
        ).status_code
        == 409
    )


def test_only_one_challenge_runs_between_two_players_at_a_time(social):
    client, session = social
    challenger, challenger_headers = make_player(session, "Eager")
    opponent, _ = make_player(session, "Busy")
    befriend(session, challenger, opponent)

    assert start_challenge(client, session, challenger_headers, opponent).status_code == 201
    assert start_challenge(client, session, challenger_headers, opponent).status_code == 409
