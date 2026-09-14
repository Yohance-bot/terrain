"""The athlete profile end to end: real submissions, inside a rolled-back transaction."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import SessionLocal, engine, get_session
from app.main import app
from app.models import Account, Device, DeviceLink, Friendship, Run, RunMetrics
from app.services.athlete_metrics import haversine_m

# Far from any seeded territory, so runs score nothing and change no ownership.
LAT0, LON0 = 59.91, 10.75
DEG_PER_M = 1 / haversine_m(0, 0, 1, 0)
KOLKATA = ZoneInfo("Asia/Kolkata")


@pytest.fixture()
def lab(monkeypatch):
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


def make_player(session, name):
    account = Account(display_name=name, role="player")
    session.add(account)
    session.flush()
    device = Device(id=uuid.uuid4())
    session.add(device)
    session.flush()
    session.add(DeviceLink(device_id=device.id, account_id=account.id))
    session.flush()
    return account, {"X-Device-Id": str(device.id)}


def submission(start, *, km, pace_s_per_km=300.0, altitude=None, conditions=None, step_s=2):
    speed = 1000 / pace_s_per_km
    count = int(km * 1000 / speed / step_s)
    samples = []
    for i in range(count + 1):
        north = i * step_s * speed
        sample = {
            "ts": int((start + timedelta(seconds=i * step_s)).timestamp() * 1000),
            "lat": LAT0 + north * DEG_PER_M,
            "lon": LON0,
            "accuracy_m": 5.0,
            "speed_mps": speed,
            "provider": "test",
            "is_mock": False,
        }
        if altitude:
            sample["altitude_m"] = altitude(north)
        samples.append(sample)
    body = {
        "run_id": str(uuid.uuid4()),
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(seconds=count * step_s)).isoformat(),
        "samples": samples,
    }
    if conditions:
        body["conditions"] = conditions
    return body


def submit(client, headers, body):
    response = client.post("/v1/runs", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["run_id"]


def this_week_monday(zone):
    today = datetime.now(UTC).astimezone(zone).date()
    monday = today - timedelta(days=today.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=zone)


def test_stats_totals_streak_and_records(lab):
    client, session = lab
    _, headers = make_player(session, "Stats Runner")
    monday = this_week_monday(KOLKATA)
    submit(client, headers, submission(monday + timedelta(hours=1), km=5.2))

    def hill(north):
        return 900 + min(north, 1000) / 1000 * 15

    submit(client, headers, submission(monday - timedelta(days=6), km=3.0, altitude=hill))
    long_run = submit(
        client, headers, submission(monday - timedelta(days=20), km=10.1, pace_s_per_km=280)
    )

    stats = client.get("/v1/athlete/stats", params={"tz": "Asia/Kolkata"}, headers=headers).json()

    assert stats["timezone"] == "Asia/Kolkata"
    assert stats["this_week"]["runs"] == 1
    assert stats["this_week"]["distance_m"] == pytest.approx(5200, rel=0.01)
    assert stats["this_week"]["moving_s"] == pytest.approx(1560, abs=10)
    assert stats["all_time"]["runs"] == 3
    distances = [week["distance_m"] for week in stats["weeks"]]
    assert distances[-1] == pytest.approx(5200, rel=0.01)
    assert distances[-2] == pytest.approx(3000, rel=0.01)
    assert distances[-3] == 0
    assert distances[-4] == pytest.approx(10100, rel=0.01)
    assert stats["streak"] == {
        "current_weeks": 2,
        "best_weeks": 2,
        "current_since": stats["weeks"][-2]["week_start"],
        "ran_this_week": True,
    }
    assert stats["longest_run"]["run_id"] == long_run
    efforts = {effort["distance_m"]: effort for effort in stats["best_efforts"]}
    assert efforts[5000]["elapsed_s"] == pytest.approx(1400, abs=5)
    assert efforts[5000]["run_id"] == long_run
    assert 10000 in efforts
    assert stats["biggest_climb"]["elevation_gain_m"] == pytest.approx(15, abs=3)
    assert stats["week_days_m"][0] == pytest.approx(5200, rel=0.01)


def test_weeks_follow_the_athletes_timezone(lab):
    client, session = lab
    _, headers = make_player(session, "Zone Runner")
    # Monday 01:00 in Kolkata is still Sunday evening in UTC.
    submit(client, headers, submission(this_week_monday(KOLKATA) + timedelta(hours=1), km=2))

    kolkata = client.get("/v1/athlete/stats", params={"tz": "Asia/Kolkata"}, headers=headers).json()
    utc = client.get("/v1/athlete/stats", params={"tz": "UTC"}, headers=headers).json()
    assert kolkata["weeks"][-1]["runs"] == 1
    assert utc["weeks"][-1]["runs"] == 0 and utc["weeks"][-2]["runs"] == 1


def test_month_filter_uses_the_timezone(lab):
    client, session = lab
    _, headers = make_player(session, "Month Runner")
    start = datetime(2025, 9, 1, 1, 30, tzinfo=KOLKATA)  # 31 Aug 20:00 UTC
    run_id = submit(client, headers, submission(start, km=1))

    def month(value, zone):
        body = client.get(
            "/v1/athlete/runs", params={"month": value, "tz": zone}, headers=headers
        ).json()
        return [run["run_id"] for run in body["runs"]]

    assert month("2025-09", "Asia/Kolkata") == [run_id]
    assert month("2025-08", "UTC") == [run_id]
    assert month("2025-09", "UTC") == []


def test_notes_titles_and_ownership(lab):
    client, session = lab
    _, headers = make_player(session, "Note Runner")
    _, stranger = make_player(session, "Stranger")
    run_id = submit(client, headers, submission(datetime.now(UTC) - timedelta(days=1), km=1))

    changed = client.patch(
        f"/v1/athlete/runs/{run_id}",
        json={"title": "  Easy loop ", "note": "Legs heavy"},
        headers=headers,
    ).json()
    assert changed["title"] == "Easy loop" and changed["note"] == "Legs heavy"
    assert (
        client.patch(
            f"/v1/athlete/runs/{run_id}", json={"note": "mine"}, headers=stranger
        ).status_code
        == 404
    )

    cleared = client.patch(
        f"/v1/athlete/runs/{run_id}", json={"note": None}, headers=headers
    ).json()
    assert cleared["note"] is None and cleared["title"] == "Easy loop"


def test_weekly_goal_progress(lab):
    client, session = lab
    _, headers = make_player(session, "Goal Runner")
    submit(client, headers, submission(this_week_monday(UTC) + timedelta(hours=2), km=4))

    assert client.get("/v1/athlete/goal", params={"tz": "UTC"}, headers=headers).json() is None
    assert (
        client.put(
            "/v1/athlete/goal", json={"metric": "distance", "target": 0}, headers=headers
        ).status_code
        == 422
    )
    goal = client.put(
        "/v1/athlete/goal",
        params={"tz": "UTC"},
        json={"metric": "distance", "target": 25000},
        headers=headers,
    ).json()
    assert goal["target"] == 25000 and goal["value"] == pytest.approx(4000, rel=0.01)
    runs_goal = client.put(
        "/v1/athlete/goal",
        params={"tz": "UTC"},
        json={"metric": "runs", "target": 3},
        headers=headers,
    ).json()
    assert runs_goal["value"] == 1
    stats = client.get("/v1/athlete/stats", params={"tz": "UTC"}, headers=headers).json()
    assert stats["goal"]["metric"] == "runs"
    assert client.delete("/v1/athlete/goal", headers=headers).status_code == 204
    assert client.get("/v1/athlete/goal", headers=headers).json() is None


def test_shoes_default_assignment_and_mileage(lab):
    client, session = lab
    _, headers = make_player(session, "Shoe Runner")
    first = client.post(
        "/v1/athlete/shoes", json={"name": "Daily trainers"}, headers=headers
    ).json()
    assert first["is_default"] is True  # the first pair is the default

    run_id = submit(client, headers, submission(datetime.now(UTC) - timedelta(hours=3), km=2))
    shoes = client.get("/v1/athlete/shoes", headers=headers).json()
    assert shoes[0]["distance_m"] == pytest.approx(2000, rel=0.01) and shoes[0]["runs"] == 1
    runs = client.get("/v1/athlete/runs", headers=headers).json()["runs"]
    assert runs[0]["run_id"] == run_id and runs[0]["shoe"]["name"] == "Daily trainers"

    second = client.post(
        "/v1/athlete/shoes", json={"name": "Racers", "is_default": True}, headers=headers
    ).json()
    by_id = {shoe["id"]: shoe for shoe in client.get("/v1/athlete/shoes", headers=headers).json()}
    assert by_id[second["id"]]["is_default"] and not by_id[first["id"]]["is_default"]

    retired = client.patch(
        f"/v1/athlete/shoes/{second['id']}", json={"retired": True}, headers=headers
    ).json()
    assert retired["retired"] and not retired["is_default"]
    assert (
        client.patch(
            f"/v1/athlete/shoes/{second['id']}", json={"is_default": True}, headers=headers
        ).status_code
        == 422
    )
    assert client.delete(f"/v1/athlete/shoes/{first['id']}", headers=headers).status_code == 204
    assert client.get("/v1/athlete/runs", headers=headers).json()["runs"][0]["shoe"] is None


def test_activity_detail_efforts_and_calories(lab):
    client, session = lab
    _, headers = make_player(session, "Detail Runner")
    fast = submit(client, headers, submission(datetime.now(UTC) - timedelta(days=3), km=5.2))
    slow = submit(
        client,
        headers,
        submission(datetime.now(UTC) - timedelta(days=1), km=2.1, pace_s_per_km=330),
    )

    without_weight = client.get(f"/v1/athlete/runs/{fast}", headers=headers).json()
    assert without_weight["calories"] is None
    assert client.put("/v1/athlete/settings", json={"weight_kg": 70}, headers=headers).json() == {
        "weight_kg": 70
    }

    detail = client.get(f"/v1/athlete/runs/{fast}", headers=headers).json()
    assert detail["calories"] == pytest.approx(70 * 5.2 * 1.036, abs=5)
    assert len(detail["splits"]) == 6
    assert detail["splits"][0]["moving_s"] == pytest.approx(300, abs=3)
    assert len(detail["pace_series"]) > 100
    fast_1k = next(effort for effort in detail["best_efforts"] if effort["distance_m"] == 1000)
    assert fast_1k["rank"] == 1 and fast_1k["personal_record"] is True

    slow_detail = client.get(f"/v1/athlete/runs/{slow}", headers=headers).json()
    slow_1k = next(effort for effort in slow_detail["best_efforts"] if effort["distance_m"] == 1000)
    assert slow_1k["rank"] == 2 and slow_1k["personal_record"] is False
    runs = {
        run["run_id"]: run for run in client.get("/v1/athlete/runs", headers=headers).json()["runs"]
    }
    assert 1000 in runs[fast]["personal_records"] and runs[slow]["personal_records"] == []


def test_friend_profile_requires_friendship_and_hides_private_entries(lab):
    client, session = lab
    runner, runner_headers = make_player(session, "Friendly Runner")
    viewer, viewer_headers = make_player(session, "Viewer")
    shoe = client.post(
        "/v1/athlete/shoes", json={"name": "Secret shoes"}, headers=runner_headers
    ).json()
    run_id = submit(
        client, runner_headers, submission(datetime.now(UTC) - timedelta(hours=5), km=3)
    )
    client.patch(
        f"/v1/athlete/runs/{run_id}",
        json={"note": "private", "title": "Tempo"},
        headers=runner_headers,
    )

    path = f"/v1/social/accounts/{runner.id}/profile"
    assert client.get(path, headers=viewer_headers).status_code == 403

    session.add(Friendship(requester_id=runner.id, addressee_id=viewer.id, status="accepted"))
    session.flush()
    profile = client.get(path, headers=viewer_headers).json()
    assert profile["account"]["relationship"] == "friends"
    assert profile["all_time"]["runs"] == 1
    recent = profile["recent_runs"][0]
    assert recent["title"] == "Tempo"
    assert recent["note"] is None and recent["shoe"] is None
    assert shoe["name"] not in str(profile)


def test_older_runs_get_metrics_on_first_read(lab):
    client, session = lab
    account, headers = make_player(session, "Legacy Runner")
    device_id = uuid.UUID(headers["X-Device-Id"])
    started = datetime.now(UTC) - timedelta(days=40)
    points = [(LON0, LAT0 + index * 10 * DEG_PER_M) for index in range(301)]  # 3 km
    run = Run(
        id=uuid.uuid4(),
        device_id=device_id,
        started_at=started,
        ended_at=started + timedelta(seconds=900),
        duration_s=900,
        distance_m=3000,
        geom="SRID=4326;LINESTRING(" + ", ".join(f"{lon} {lat}" for lon, lat in points) + ")",
        sample_ts=[
            int((started + timedelta(seconds=3 * index)).timestamp() * 1000) for index in range(301)
        ],
        sample_accuracy_m=[5.0] * 301,
        raw_payload={},
        status="applied",
        source="tracked",
        pipeline_version=settings.pipeline_version,
    )
    session.add(run)
    session.flush()
    assert session.get(RunMetrics, run.id) is None

    stats = client.get("/v1/athlete/stats", headers=headers).json()
    assert stats["all_time"]["moving_s"] == pytest.approx(900, abs=5)
    assert session.get(RunMetrics, run.id) is not None
    assert {effort["distance_m"] for effort in stats["best_efforts"]} >= {1000, 1609}


def test_conditions_are_kept_and_rejected_runs_do_not_count(lab):
    client, session = lab
    _, headers = make_player(session, "Weather Runner")
    submit(
        client,
        headers,
        submission(
            datetime.now(UTC) - timedelta(hours=2),
            km=1,
            conditions={"temperature_c": 27.5, "weather_code": 3},
        ),
    )
    mock = submission(datetime.now(UTC) - timedelta(hours=1), km=1)
    mock["samples"][0]["is_mock"] = True
    client.post("/v1/runs", json=mock, headers=headers)

    runs = client.get("/v1/athlete/runs", headers=headers).json()["runs"]
    assert len(runs) == 1
    assert runs[0]["temperature_c"] == 27.5 and runs[0]["weather_code"] == 3
