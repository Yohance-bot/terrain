import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_territories.py"
SPEC = importlib.util.spec_from_file_location("publish_territories", SCRIPT)
assert SPEC and SPEC.loader
publisher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = publisher
SPEC.loader.exec_module(publisher)

GEOMETRY = {
    "type": "MultiPolygon",
    "coordinates": [[[[77.0, 12.0], [77.1, 12.0], [77.1, 12.1], [77.0, 12.0]]]],
}


def write_publish_pair(tmp_path: Path, *, territory_id: str | None = None) -> tuple[Path, Path]:
    territory_id = territory_id or str(
        uuid.uuid5(publisher.TERRITORY_NAMESPACE, "test-city/test-area/gameplay/test-park")
    )
    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "territory_id": territory_id,
                    "slug": "test-park",
                    "name": "Test Park",
                    "kind": "park",
                },
                "geometry": GEOMETRY,
            }
        ],
        "pipeline": {"stage": "publish_gameplay"},
    }
    geojson_path = tmp_path / "gameplay_territories.geojson"
    manifest_path = tmp_path / "gameplay_publish_manifest.json"
    geojson_path.write_text(json.dumps(collection), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "city": "test-city",
                "area": "test-area",
                "layer": "gameplay",
                "validation_status": "pass",
                "territory_count": 1,
                "published_hash": publisher._artifact_hash(collection),
            }
        ),
        encoding="utf-8",
    )
    return geojson_path, manifest_path


def test_load_accepts_reviewed_gameplay_publish_pair(tmp_path):
    geojson_path, manifest_path = write_publish_pair(tmp_path)

    publish = publisher.load_reviewed_publish(geojson_path, manifest_path)

    assert publish.city == "test-city"
    assert publish.area == "test-area"
    assert publish.territories[0].slug == "test-park"


def test_load_rejects_unstable_territory_identity(tmp_path):
    geojson_path, manifest_path = write_publish_pair(
        tmp_path, territory_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )

    with pytest.raises(publisher.PublishControlError, match="stable ID"):
        publisher.load_reviewed_publish(geojson_path, manifest_path)


def test_load_rejects_manifest_that_does_not_match_geojson(tmp_path):
    geojson_path, manifest_path = write_publish_pair(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["published_hash"] = "not-the-published-geojson"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(publisher.PublishControlError, match="published_hash"):
        publisher.load_reviewed_publish(geojson_path, manifest_path)


def test_impact_bumps_only_changed_geometry_version(tmp_path):
    geojson_path, manifest_path = write_publish_pair(tmp_path)
    publish = publisher.load_reviewed_publish(geojson_path, manifest_path)
    territory = publish.territories[0]
    current = SimpleNamespace(
        id=territory.id,
        version=4,
        slug=territory.slug,
        city="test-city",
        area="test-area",
    )

    unchanged = publisher.build_impact_summary(
        publish, [(current, json.dumps(territory.geometry))]
    )
    assert unchanged["unchanged"] == 1
    assert unchanged["versions"][str(territory.id)] == 4

    changed = publisher.build_impact_summary(
        publish, [(current, json.dumps({**territory.geometry, "coordinates": []}))]
    )
    assert changed["geometry_updates"] == 1
    assert changed["versions"][str(territory.id)] == 5


def test_impact_refuses_to_retire_territories(tmp_path):
    geojson_path, manifest_path = write_publish_pair(tmp_path)
    publish = publisher.load_reviewed_publish(geojson_path, manifest_path)
    absent = SimpleNamespace(
        id=uuid.uuid4(),
        version=1,
        slug="old-park",
        city="test-city",
        area="test-area",
    )

    with pytest.raises(publisher.PublishControlError, match="refusing to remove"):
        publisher.build_impact_summary(publish, [(absent, json.dumps(GEOMETRY))])
