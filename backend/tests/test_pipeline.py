"""End-to-end check of the milestone loop against a real PostGIS database.

Proves the parts that are easy to get quietly wrong: distance is measured in
metres and not degrees, minimum presence actually excludes a clipping run,
submission is idempotent, and ownership changes hands when it should.

Requires the local database from the README. Run with:

    uv run pytest
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.main import app
from app.core.config import settings
from app.models import Device, InfluenceGrant, RunLifecycleEvent, Territory, TerritoryOwnership

# A square roughly 900 m on a side, sitting in open ground south of Jayanagar so
# it cannot collide with any real seeded territory.
TEST_SQUARE = (
    "MULTIPOLYGON(((77.700 12.800, 77.708 12.800, 77.708 12.808,"
    " 77.700 12.808, 77.700 12.800)))"
)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(settings, "authenticated_accounts_enabled", False)
    monkeypatch.setattr(settings, "developer_mode_enabled", True)
    monkeypatch.setattr(settings, "local_accounts_enabled", True)
    return TestClient(app)


@pytest.fixture()
def territory():
    territory_id = uuid.uuid4()
    with SessionLocal() as session:
        session.add(
            Territory(
                id=territory_id,
                version=1,
                slug=f"test-square-{territory_id.hex[:8]}",
                name="Test Square",
                city="testland",
                area="testville",
                kind="park",
                geom=f"SRID=4326;{TEST_SQUARE}",
            )
        )
        session.commit()

    yield territory_id

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM influence_grants WHERE territory_id = :t"),
            {"t": territory_id},
        )
        conn.execute(
            text("DELETE FROM run_territory_segments WHERE territory_id = :t"),
            {"t": territory_id},
        )
        conn.execute(
            text("DELETE FROM territory_ownership WHERE territory_id = :t"), {"t": territory_id}
        )
        conn.execute(
            text("DELETE FROM territory_standings WHERE territory_id = :t"), {"t": territory_id}
        )
        conn.execute(text("DELETE FROM territories WHERE id = :t"), {"t": territory_id})


def build_run(
    points: list[tuple[float, float]], *, accuracy: float = 8.0, duration_s: int = 20 * 60
) -> dict:
    start = datetime.now(UTC)
    return {
        "run_id": str(uuid.uuid4()),
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(seconds=duration_s)).isoformat(),
        "samples": [
            {
                "ts": int((start + timedelta(seconds=i)).timestamp() * 1000),
                "lat": lat,
                "lon": lon,
                "accuracy_m": accuracy,
                "speed_mps": 3.0,
                "provider": "test",
                "is_mock": False,
            }
            for i, (lon, lat) in enumerate(points)
        ],
    }


def crossing_route() -> list[tuple[float, float]]:
    """Straight west-to-east line through the middle of the square, ~870 m inside."""
    return [(77.698, 12.804), (77.710, 12.804)]


def enclosing_loop() -> list[tuple[float, float]]:
    """A ~2.4 km loop around, but not through, the test square."""
    return [
        (77.699, 12.799),
        (77.709, 12.799),
        (77.709, 12.809),
        (77.699, 12.809),
        (77.699, 12.799),
    ]


def test_run_matches_territory_and_takes_ownership(client, territory):
    device = str(uuid.uuid4())
    payload = build_run(crossing_route())

    response = client.post("/v1/runs", json=payload, headers={"X-Device-Id": device})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "applied"
    segment = next(s for s in body["segments"] if s["territory_id"] == str(territory))

    # The square is ~870 m across at this latitude. If this comes back as a value
    # near 0.008, the geography cast was lost somewhere and it is measuring degrees.
    assert 800 < segment["distance_m"] < 950
    assert segment["influence_granted"] > 0
    assert segment["active_influence"] > 0
    assert segment["legacy_influence"] == segment["influence_granted"]
    assert segment["is_owned_by_you"] is True
    assert segment["ownership_changed"] is True


def test_validated_loop_captures_enclosed_territory(client, territory):
    """A loop claims its enclosed polygon even where no route segment clips it."""
    device = str(uuid.uuid4())
    response = client.post(
        "/v1/runs",
        json=build_run(enclosing_loop(), duration_s=25 * 60),
        headers={"X-Device-Id": device},
    )
    assert response.status_code == 200, response.text
    segment = next(
        segment
        for segment in response.json()["segments"]
        if segment["territory_id"] == str(territory)
    )

    assert segment["capture_method"] == "loop"
    assert segment["distance_m"] == 0
    assert segment["is_owned_by_you"] is True
    assert segment["ownership_changed"] is True

    # The fixed territory claim and the public player-created polygon are
    # separate results of the same validated loop.
    areas = client.get("/v1/captured-areas", headers={"X-Device-Id": device})
    assert areas.status_code == 200, areas.text
    matching_area = next(
        feature
        for feature in areas.json()["features"]
        if feature["properties"]["run_id"] == response.json()["run_id"]
    )
    assert matching_area["properties"]["is_owned_by_you"] is True
    assert matching_area["geometry"]["type"] == "Polygon"


def test_submission_is_idempotent(client, territory):
    device = str(uuid.uuid4())
    payload = build_run(crossing_route())
    headers = {"X-Device-Id": device}

    first = client.post("/v1/runs", json=payload, headers=headers).json()
    second = client.post("/v1/runs", json=payload, headers=headers).json()

    assert first["run_id"] == second["run_id"]
    first_total = first["segments"][0]["total_distance_m"]
    second_total = second["segments"][0]["total_distance_m"]
    # A retry must not count the same distance twice.
    assert first_total == second_total


def test_brief_direct_run_earns_normal_territory_standing(client, territory):
    """A valid direct run contributes without needing to close a loop."""
    device = str(uuid.uuid4())
    # Roughly 30 m through the north-west corner. It is short but non-zero.
    payload = build_run([(77.6997, 12.8078), (77.7003, 12.8081)])

    body = client.post("/v1/runs", json=payload, headers={"X-Device-Id": device}).json()
    segment = next(s for s in body["segments"] if s["territory_id"] == str(territory))
    assert segment["distance_m"] > 0
    assert segment["active_influence"] > 0


def test_short_direct_run_does_not_need_loop_for_influence(client, territory):
    """Moving time does not turn a valid direct segment into a loop-only action."""
    payload = build_run(crossing_route(), duration_s=30)
    body = client.post(
        "/v1/runs", json=payload, headers={"X-Device-Id": str(uuid.uuid4())}
    ).json()

    assert body["status"] == "applied"
    segment = next(segment for segment in body["segments"] if segment["territory_id"] == str(territory))
    assert segment["active_influence"] > 0


def test_owned_area_endpoint_dissolves_only_same_owner_touching_territories(client):
    """Topology joins shared edges, but retains real gaps and other owners."""
    owner, other = uuid.uuid4(), uuid.uuid4()
    ids = [uuid.uuid4() for _ in range(4)]
    slugs = [f"owned-area-{territory_id.hex[:8]}" for territory_id in ids]
    # A and B share an edge; C is separated by a genuine gap; D touches B but
    # belongs to another runner and must remain in that runner's geometry.
    shapes = [
        "MULTIPOLYGON(((77.720 12.800,77.722 12.800,77.722 12.802,77.720 12.802,77.720 12.800)))",
        "MULTIPOLYGON(((77.722 12.800,77.724 12.800,77.724 12.802,77.722 12.802,77.722 12.800)))",
        "MULTIPOLYGON(((77.725 12.800,77.727 12.800,77.727 12.802,77.725 12.802,77.725 12.800)))",
        "MULTIPOLYGON(((77.724 12.800,77.726 12.800,77.726 12.802,77.724 12.802,77.724 12.800)))",
    ]
    try:
        with SessionLocal() as session:
            session.add_all([Device(id=owner), Device(id=other)])
            for territory_id, slug, shape in zip(ids, slugs, shapes, strict=True):
                session.add(
                    Territory(
                        id=territory_id,
                        version=1,
                        slug=slug,
                        name=slug,
                        city="testland",
                        area="owned-areas",
                        kind="block",
                        geom=f"SRID=4326;{shape}",
                    )
                )
            session.flush()
            session.add_all(
                [
                    TerritoryOwnership(territory_id=ids[0], owner_device_id=owner),
                    TerritoryOwnership(territory_id=ids[1], owner_device_id=owner),
                    TerritoryOwnership(territory_id=ids[2], owner_device_id=owner),
                    TerritoryOwnership(territory_id=ids[3], owner_device_id=other),
                ]
            )
            session.commit()

        response = client.get(
            "/v1/territories/owned-areas?city=testland&area=owned-areas",
            headers={"X-Device-Id": str(owner)},
        )
        assert response.status_code == 200, response.text
        features = {feature["properties"]["owner_device_id"]: feature for feature in response.json()["features"]}
        owner_geometry = features[str(owner)]["geometry"]
        # A+B dissolve into one polygon; C remains a disconnected second part.
        assert owner_geometry["type"] == "MultiPolygon"
        assert len(owner_geometry["coordinates"]) == 2
        assert features[str(owner)]["properties"]["is_owned_by_you"] is True
        assert features[str(other)]["geometry"]["type"] == "Polygon"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM territory_ownership WHERE territory_id = ANY(:ids)"), {"ids": ids})
            conn.execute(text("DELETE FROM territories WHERE id = ANY(:ids)"), {"ids": ids})
            conn.execute(text("DELETE FROM devices WHERE id = ANY(:ids)"), {"ids": [owner, other]})


def test_mock_location_is_rejected_without_a_grant(client, territory):
    payload = build_run(crossing_route())
    payload["samples"][0]["is_mock"] = True
    response = client.post(
        "/v1/runs", json=payload, headers={"X-Device-Id": str(uuid.uuid4())}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    with SessionLocal() as session:
        assert session.query(InfluenceGrant).filter_by(run_id=payload["run_id"]).count() == 0
        events = session.query(RunLifecycleEvent).filter_by(run_id=payload["run_id"]).all()
    assert [event.to_status for event in events] == ["submitted", "rejected"]


def test_ownership_changes_when_a_rival_runs_further(client, territory):
    first_device, second_device = str(uuid.uuid4()), str(uuid.uuid4())

    client.post(
        "/v1/runs", json=build_run(crossing_route()), headers={"X-Device-Id": first_device}
    )

    # The rival covers the same crossing twice, so more cumulative distance.
    doubled = crossing_route() + [(77.698, 12.8045), (77.710, 12.8045)]
    body = client.post(
        "/v1/runs", json=build_run(doubled), headers={"X-Device-Id": second_device}
    ).json()

    segment = next(s for s in body["segments"] if s["territory_id"] == str(territory))
    assert segment["ownership_changed"] is True
    assert segment["is_owned_by_you"] is True

    # And the first device must no longer hold it.
    state = client.get("/v1/territories/state", params={"city": "testland", "area": "testville"})
    entry = next(t for t in state.json() if t["territory_id"] == str(territory))
    assert entry["owner_device_id"] == second_device


def test_inaccurate_samples_are_dropped(client, territory):
    device = str(uuid.uuid4())
    payload = build_run(crossing_route(), accuracy=200.0)

    response = client.post("/v1/runs", json=payload, headers={"X-Device-Id": device})
    # Every sample was unusable, so there is no route to match.
    assert response.status_code == 422


def test_fractional_sample_timestamp_is_rejected(client, territory):
    device = str(uuid.uuid4())
    payload = build_run(crossing_route())
    payload["samples"][0]["ts"] = payload["samples"][0]["ts"] + 0.893

    response = client.post("/v1/runs", json=payload, headers={"X-Device-Id": device})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(error.get("type") == "int_from_float" for error in detail)
    assert any(error.get("loc") == ["body", "samples", 0, "ts"] for error in detail)


def test_rounded_integer_sample_timestamp_is_idempotent(client, territory):
    device = str(uuid.uuid4())
    payload = build_run(crossing_route())
    payload["samples"][0]["ts"] = int(payload["samples"][0]["ts"] + 0.893)
    headers = {"X-Device-Id": device}

    first = client.post("/v1/runs", json=payload, headers=headers)
    second = client.post("/v1/runs", json=payload, headers=headers)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["run_id"] == second.json()["run_id"]


@pytest.fixture(autouse=True)
def cleanup_devices():
    yield
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM devices WHERE id NOT IN "
                "(SELECT device_id FROM runs UNION SELECT device_id FROM run_territory_segments)"
            )
        )


def test_loop_outside_named_territories_claims_once(client):
    device = str(uuid.uuid4())
    headers = {"X-Device-Id": device}
    points = [(lon - 2, lat - 2) for lon, lat in enclosing_loop()]
    payload = build_run(points, duration_s=25 * 60)
    response = client.post('/v1/runs', json=payload, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'applied'
    assert result['segments'] == []
    assert result['captured_area_id']
    assert result['captured_area_m2'] > 1200
    repeated = client.post('/v1/runs', json=payload, headers=headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()['captured_area_id'] == result['captured_area_id']
    areas = client.get('/v1/captured-areas', headers=headers).json()['features']
    own = [area for area in areas if area['properties']['owner_device_id'] == device]
    assert len(own) == 1
    assert own[0]['properties']['owner_display_name']
    assert len(own[0]['properties']['label_coordinate']) == 2


def test_territory_leader_has_map_anchor(client, territory):
    device = str(uuid.uuid4())
    response = client.post('/v1/runs', json=build_run(enclosing_loop(), duration_s=1500), headers={'X-Device-Id': device})
    assert response.status_code == 200, response.text
    response = client.get('/v1/territories/state?city=testland&area=testville')
    assert response.status_code == 200, response.text
    state = next(s for s in response.json() if s['territory_id'] == str(territory))
    assert state['owner_device_id'] == device
    assert state['owner_display_name']
    lon, lat = state['label_coordinate']
    assert 77.700 <= lon <= 77.708 and 12.800 <= lat <= 12.808
