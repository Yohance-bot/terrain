"""Stage 03 landmark rules against tiny synthetic extracts."""

from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import box

from lib import artifacts
from lib.contracts import StageStatus
from lib.io import is_placeholder, read_json, write_json
from lib.landmarks import classify_flags, classify_role
from lib.registry import discover_stages


def test_named_eligible_landmarks_are_major_at_any_size(thresholds):
    min_m2 = thresholds.territory_min_area_m2
    assert min_m2 == 20000

    # Size controls standalone protection, not whether the perimeter is atomic.
    assert (
        classify_role(
            name="Pocket Park",
            kind="park",
            category="park",
            area_m2=3000,
            territory_min_m2=min_m2,
        )
        == "major"
    )

    # Jain-sized colleges are still landmarks; they merge whole later.
    assert (
        classify_role(
            name="City Institute of Technology",
            kind="landmark",
            category="college",
            area_m2=8000,
            territory_min_m2=min_m2,
        )
        == "major"
    )

    # 20000 m² campus → major
    assert (
        classify_role(
            name="South Campus",
            kind="landmark",
            category="college",
            area_m2=20000,
            territory_min_m2=min_m2,
        )
        == "major"
    )

    # Botanical names use the same area rule as every other landmark.
    assert (
        classify_role(
            name="Lalbagh Botanical Garden",
            kind="park",
            category="park",
            area_m2=5000,
            territory_min_m2=min_m2,
        )
        == "major"
    )

    # Small named lake → major (exception)
    assert (
        classify_role(
            name="Tiny Named Lake",
            kind="lake",
            category="lake",
            area_m2=3000,
            territory_min_m2=min_m2,
        )
        == "major"
    )


def test_classify_flags_atomic_vs_standalone(thresholds):
    atomic_min = thresholds.atomic_min_area_m2
    standalone_min = thresholds.standalone_min_area_m2

    small_park = classify_flags(
        name="Pocket Park",
        kind="park",
        category="park",
        area_m2=8000,
        territory_min_m2=thresholds.territory_min_area_m2,
        atomic_min_m2=atomic_min,
        standalone_min_m2=standalone_min,
    )
    assert small_park.atomic is True
    assert small_park.protected is False

    huge_park = classify_flags(
        name="Big City Park",
        kind="park",
        category="park",
        area_m2=standalone_min + 1,
        territory_min_m2=thresholds.territory_min_area_m2,
        atomic_min_m2=atomic_min,
        standalone_min_m2=standalone_min,
    )
    assert huge_park.atomic is True
    assert huge_park.protected is True

    lalbagh = classify_flags(
        name="Lalbagh Botanical Gardens",
        kind="park",
        category="park",
        area_m2=5000,
        territory_min_m2=thresholds.territory_min_area_m2,
        atomic_min_m2=atomic_min,
        standalone_min_m2=standalone_min,
    )
    assert lalbagh.atomic is True
    assert lalbagh.protected is False

    lalbagh_scale = classify_flags(
        name="Lalbagh Botanical Gardens",
        kind="park",
        category="park",
        area_m2=standalone_min,
        territory_min_m2=thresholds.territory_min_area_m2,
        atomic_min_m2=atomic_min,
        standalone_min_m2=standalone_min,
    )
    assert lalbagh_scale.atomic is True
    assert lalbagh_scale.protected is True


def test_landmark_standalone_boundary_is_exactly_fifty_acres(thresholds):
    kwargs = {
        "name": "Test Campus",
        "kind": "landmark",
        "category": "college",
        "territory_min_m2": thresholds.territory_min_area_m2,
        "atomic_min_m2": thresholds.atomic_min_area_m2,
        "standalone_min_m2": thresholds.standalone_min_area_m2,
    }
    below = classify_flags(area_m2=49 * 4046.8564224, **kwargs)
    at_floor = classify_flags(area_m2=50 * 4046.8564224, **kwargs)
    assert below.atomic is True
    assert below.protected is False
    assert at_floor.atomic is True
    assert at_floor.protected is True


def _write_manifest(ctx, filenames: dict[str, str]) -> None:
    files = []
    for key, filename in sorted(filenames.items()):
        path = ctx.raw_dir / filename
        files.append(
            {
                "key": key,
                "source": "overture" if key.startswith("overture") else "geofabrik",
                "url": f"file://{filename}",
                "filename": filename,
                "sha256": "0" * 64,
                "bytes": path.stat().st_size if path.exists() else 0,
                "skipped": False,
            }
        )
    write_json(
        artifacts.RAW_MANIFEST.path(ctx),
        {
            "status": "ok",
            "stage": "download_data",
            "overture_release": "2026-07-22.0",
            "files": files,
        },
    )


@pytest.fixture
def stage03():
    return next(s for s in discover_stages() if s.number == 3)


def test_unnamed_parks_are_not_landmarks(ctx, stage03, monkeypatch):
    land = ctx.raw_dir / "overture_base_land_use.geoparquet"
    gpd.GeoDataFrame(
        [
            {
                "id": "anon",
                "class": "park",
                "names": None,
                "source_tags": [("leisure", "park")],
                "geometry": box(77.57, 12.91, 77.572, 12.912),
            }
        ],
        crs="EPSG:4326",
    ).to_parquet(land)
    _write_manifest(ctx, {"overture_base_land_use": land.name})
    monkeypatch.setattr("lib.landmarks._from_osm", lambda *_a, **_k: [])

    stage03.run(ctx)
    data = read_json(artifacts.LANDMARKS.path(ctx))
    assert data["features"] == []
    assert data["pipeline"]["status"] == "ok"
    assert not is_placeholder(artifacts.LANDMARKS.path(ctx))


def test_named_park_is_protected_with_kind(ctx, stage03, monkeypatch):
    land = ctx.raw_dir / "overture_base_land_use.geoparquet"
    gpd.GeoDataFrame(
        [
            {
                "id": "lalbagh",
                "class": "park",
                "names": {"primary": "Lalbagh Botanical Garden"},
                "source_tags": [("leisure", "park")],
                "geometry": box(77.58, 12.94, 77.59, 12.95),
            }
        ],
        crs="EPSG:4326",
    ).to_parquet(land)
    _write_manifest(ctx, {"overture_base_land_use": land.name})
    monkeypatch.setattr("lib.landmarks._from_osm", lambda *_a, **_k: [])

    result = stage03.run(ctx)
    assert result.status is StageStatus.OK
    data = read_json(artifacts.LANDMARKS.path(ctx))
    assert len(data["features"]) == 1
    props = data["features"][0]["properties"]
    assert props["protected"] is True
    assert props["role"] == "major"
    assert props["name"] == "Lalbagh Botanical Garden"
    assert props["slug"] == "lalbagh-botanical-garden"
    assert props["kind"] == "park"
    assert data["features"][0]["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    assert data["pipeline"]["lalbagh_present"] is True
    assert data["pipeline"]["major_count"] == 1


def test_named_lake_below_territory_min_is_still_major(ctx, stage03, monkeypatch):
    """Named lakes are a hard-floor exception -- small lakes stay major."""
    water = ctx.raw_dir / "overture_base_water.geoparquet"
    # ~55 m x 55 m ≈ 3 000 m², well under territory_min_area_m2.
    gpd.GeoDataFrame(
        [
            {
                "id": "lake-small",
                "class": "lake",
                "names": {"primary": "Tiny Named Lake"},
                "geometry": box(77.58, 12.90, 77.5805, 12.9005),
            }
        ],
        crs="EPSG:4326",
    ).to_parquet(water)
    _write_manifest(ctx, {"overture_base_water": water.name})
    monkeypatch.setattr("lib.landmarks._from_osm", lambda *_a, **_k: [])

    stage03.run(ctx)
    data = read_json(artifacts.LANDMARKS.path(ctx))
    assert len(data["features"]) == 1
    props = data["features"][0]["properties"]
    assert props["kind"] == "lake"
    assert props["area_m2"] < ctx.thresholds.territory_min_area_m2
    assert props["role"] == "major"
    assert props["atomic"] is True
    # Small lakes are carved whole but merge into neighbours (not standalone).
    assert props["protected"] is False


def test_small_named_park_is_atomic_but_mergeable(ctx, stage03, monkeypatch):
    land = ctx.raw_dir / "overture_base_land_use.geoparquet"
    # ~33 m x 33 m ≈ 1 100 m² -- below territory_min_area_m2.
    gpd.GeoDataFrame(
        [
            {
                "id": "pocket",
                "class": "park",
                "names": {"primary": "Pocket Park"},
                "source_tags": [("leisure", "park")],
                "geometry": box(77.57, 12.91, 77.5703, 12.9103),
            }
        ],
        crs="EPSG:4326",
    ).to_parquet(land)
    _write_manifest(ctx, {"overture_base_land_use": land.name})
    monkeypatch.setattr("lib.landmarks._from_osm", lambda *_a, **_k: [])

    stage03.run(ctx)
    data = read_json(artifacts.LANDMARKS.path(ctx))
    assert len(data["features"]) == 1
    props = data["features"][0]["properties"]
    assert props["area_m2"] < ctx.thresholds.territory_min_area_m2
    assert props["role"] == "major"
    assert props["atomic"] is True
    assert props["protected"] is False


def test_large_named_park_is_major(ctx, stage03, monkeypatch):
    land = ctx.raw_dir / "overture_base_land_use.geoparquet"
    # ~220 m x 220 m ≈ 48 000 m² -- above territory_min_area_m2.
    gpd.GeoDataFrame(
        [
            {
                "id": "big",
                "class": "park",
                "names": {"primary": "Neighbourhood Central Park"},
                "source_tags": [("leisure", "park")],
                "geometry": box(77.57, 12.91, 77.572, 12.912),
            }
        ],
        crs="EPSG:4326",
    ).to_parquet(land)
    _write_manifest(ctx, {"overture_base_land_use": land.name})
    monkeypatch.setattr("lib.landmarks._from_osm", lambda *_a, **_k: [])

    stage03.run(ctx)
    data = read_json(artifacts.LANDMARKS.path(ctx))
    props = data["features"][0]["properties"]
    assert props["area_m2"] >= ctx.thresholds.territory_min_area_m2
    assert props["role"] == "major"
    assert props["atomic"] is True
    # Mid-size parks are atomic but not standalone prizes.
    assert props["protected"] is False
    assert props["area_m2"] < ctx.thresholds.standalone_min_area_m2


def test_pitch_and_cemetery_are_minor(ctx, stage03, monkeypatch):
    land = ctx.raw_dir / "overture_base_land_use.geoparquet"
    gpd.GeoDataFrame(
        [
            {
                "id": "pitch",
                "class": "pitch",
                "names": {"primary": "School Football Pitch"},
                "source_tags": [("leisure", "pitch")],
                "geometry": box(77.57, 12.91, 77.572, 12.912),
            },
            {
                "id": "cem",
                "class": "cemetery",
                "names": {"primary": "City Cemetery"},
                "source_tags": [("landuse", "cemetery")],
                "geometry": box(77.58, 12.91, 77.582, 12.912),
            },
        ],
        crs="EPSG:4326",
    ).to_parquet(land)
    _write_manifest(ctx, {"overture_base_land_use": land.name})
    monkeypatch.setattr("lib.landmarks._from_osm", lambda *_a, **_k: [])

    stage03.run(ctx)
    data = read_json(artifacts.LANDMARKS.path(ctx))
    assert len(data["features"]) == 2
    for feature in data["features"]:
        props = feature["properties"]
        assert props["role"] == "minor"
        assert props["protected"] is False


def test_same_name_parts_dissolve_into_one(ctx, stage03, monkeypatch):
    land = ctx.raw_dir / "overture_base_land_use.geoparquet"
    # Two adjoining halves of the same park.
    gpd.GeoDataFrame(
        [
            {
                "id": "a",
                "class": "park",
                "names": {"primary": "Krishna Rao Park"},
                "source_tags": [("leisure", "park")],
                "geometry": box(77.57, 12.91, 77.571, 12.912),
            },
            {
                "id": "b",
                "class": "park",
                "names": {"primary": "Krishna Rao Park"},
                "source_tags": [("leisure", "park")],
                "geometry": box(77.571, 12.91, 77.572, 12.912),
            },
        ],
        crs="EPSG:4326",
    ).to_parquet(land)
    _write_manifest(ctx, {"overture_base_land_use": land.name})
    monkeypatch.setattr("lib.landmarks._from_osm", lambda *_a, **_k: [])

    stage03.run(ctx)
    data = read_json(artifacts.LANDMARKS.path(ctx))
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["slug"] == "krishna-rao-park"


def test_larger_landmark_wins_overlap(ctx, stage03, monkeypatch):
    land = ctx.raw_dir / "overture_base_land_use.geoparquet"
    # Big park fully contains a smaller named college footprint.
    gpd.GeoDataFrame(
        [
            {
                "id": "big",
                "class": "park",
                "names": {"primary": "Big Park"},
                "source_tags": [("leisure", "park")],
                "geometry": box(77.57, 12.91, 77.575, 12.915),
            },
            {
                "id": "small",
                "class": "college",
                "names": {"primary": "Tiny College"},
                "source_tags": [("amenity", "college")],
                "geometry": box(77.571, 12.911, 77.572, 12.912),
            },
        ],
        crs="EPSG:4326",
    ).to_parquet(land)
    _write_manifest(ctx, {"overture_base_land_use": land.name})
    monkeypatch.setattr("lib.landmarks._from_osm", lambda *_a, **_k: [])

    stage03.run(ctx)
    data = read_json(artifacts.LANDMARKS.path(ctx))
    slugs = {f["properties"]["slug"] for f in data["features"]}
    assert "big-park" in slugs
    # Tiny college is entirely inside the park; after carving it should vanish
    # (remaining area below cleanup threshold).
    assert "tiny-college" not in slugs


def test_named_lake_gets_kind_lake(ctx, stage03, monkeypatch):
    water = ctx.raw_dir / "overture_base_water.geoparquet"
    gpd.GeoDataFrame(
        [
            {
                "id": "lake-1",
                "class": "lake",
                "names": {"primary": "Sarakki Lake"},
                "geometry": box(77.58, 12.90, 77.582, 12.902),
            }
        ],
        crs="EPSG:4326",
    ).to_parquet(water)
    _write_manifest(ctx, {"overture_base_water": water.name})
    monkeypatch.setattr("lib.landmarks._from_osm", lambda *_a, **_k: [])

    stage03.run(ctx)
    data = read_json(artifacts.LANDMARKS.path(ctx))
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["kind"] == "lake"
    assert data["features"][0]["properties"]["role"] == "major"


def test_lake_dominating_park_keeps_the_lake(ctx, stage03, monkeypatch):
    """OSM 'X Lake Park' polygons often include the water; keep the lake."""
    land = ctx.raw_dir / "overture_base_land_use.geoparquet"
    water = ctx.raw_dir / "overture_base_water.geoparquet"
    # Park bbox, lake is ~50% of park area and fully inside.
    gpd.GeoDataFrame(
        [
            {
                "id": "park",
                "class": "park",
                "names": {"primary": "Sarakki Lake Park"},
                "source_tags": [("leisure", "park")],
                "geometry": box(77.57, 12.91, 77.574, 12.914),
            }
        ],
        crs="EPSG:4326",
    ).to_parquet(land)
    gpd.GeoDataFrame(
        [
            {
                "id": "lake",
                "class": "water",
                "names": {"primary": "Sarakki Kere"},
                "geometry": box(77.5705, 12.9105, 77.5735, 12.9135),
            }
        ],
        crs="EPSG:4326",
    ).to_parquet(water)
    _write_manifest(
        ctx,
        {
            "overture_base_land_use": land.name,
            "overture_base_water": water.name,
        },
    )
    monkeypatch.setattr("lib.landmarks._from_osm", lambda *_a, **_k: [])

    stage03.run(ctx)
    data = read_json(artifacts.LANDMARKS.path(ctx))
    slugs = {f["properties"]["slug"]: f["properties"]["kind"] for f in data["features"]}
    assert slugs.get("sarakki-kere") == "lake"


def test_small_tank_inside_park_is_absorbed(ctx, stage03, monkeypatch):
    land = ctx.raw_dir / "overture_base_land_use.geoparquet"
    water = ctx.raw_dir / "overture_base_water.geoparquet"
    gpd.GeoDataFrame(
        [
            {
                "id": "park",
                "class": "park",
                "names": {"primary": "Lalbagh Botanical Garden"},
                "source_tags": [("leisure", "park")],
                "geometry": box(77.58, 12.94, 77.59, 12.95),
            }
        ],
        crs="EPSG:4326",
    ).to_parquet(land)
    # Tiny tank, well under 35% of park area.
    gpd.GeoDataFrame(
        [
            {
                "id": "tank",
                "class": "pond",
                "names": {"primary": "Lalbagh Tank"},
                "geometry": box(77.584, 12.944, 77.585, 12.945),
            }
        ],
        crs="EPSG:4326",
    ).to_parquet(water)
    _write_manifest(
        ctx,
        {
            "overture_base_land_use": land.name,
            "overture_base_water": water.name,
        },
    )
    monkeypatch.setattr("lib.landmarks._from_osm", lambda *_a, **_k: [])

    stage03.run(ctx)
    data = read_json(artifacts.LANDMARKS.path(ctx))
    slugs = {f["properties"]["slug"] for f in data["features"]}
    assert "lalbagh-botanical-garden" in slugs
    assert "lalbagh-tank" not in slugs
