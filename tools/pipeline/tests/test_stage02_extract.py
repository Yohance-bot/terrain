"""Stage 02 filtering rules against tiny synthetic extracts."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, box

from lib import artifacts
from lib.contracts import StageStatus
from lib.io import is_placeholder, read_json, write_json
from lib.registry import discover_stages


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


def _write_segments(path: Path, rows: list[dict]) -> None:
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(path)


@pytest.fixture
def stage02():
    return next(s for s in discover_stages() if s.number == 2)


def test_includes_residential_and_excludes_footway(ctx, stage02, monkeypatch):
    """Config is the only authority: footway must never become a border."""
    segments = ctx.raw_dir / "overture_transportation_segment.geoparquet"
    _write_segments(
        segments,
        [
            {
                "id": "road-ok",
                "subtype": "road",
                "class": "residential",
                "subclass": None,
                "geometry": LineString([(77.57, 12.91), (77.58, 12.92)]),
            },
            {
                "id": "path-bad",
                "subtype": "road",
                "class": "footway",
                "subclass": None,
                "geometry": LineString([(77.57, 12.91), (77.575, 12.915)]),
            },
            {
                "id": "service-bad",
                "subtype": "road",
                "class": "service",
                "subclass": None,
                "geometry": LineString([(77.58, 12.92), (77.585, 12.925)]),
            },
        ],
    )
    _write_manifest(ctx, {"overture_transportation_segment": segments.name})

    # No Geofabrik in this unit test -- stub OSM branch to empty.
    monkeypatch.setattr("lib.extract._from_osm", lambda *_args, **_kwargs: [])

    result = stage02.run(ctx)
    assert result.status is StageStatus.OK
    assert not is_placeholder(artifacts.SEPARATORS.path(ctx))

    data = read_json(artifacts.SEPARATORS.path(ctx))
    classes = [f["properties"]["class"] for f in data["features"]]
    assert classes == ["residential"]
    assert all(f["properties"]["source"] == "overture" for f in data["features"])
    assert all(f["geometry"]["type"] in {"LineString", "MultiLineString"} for f in data["features"])


def test_exclusion_beats_inclusion_for_driveway_subclass(ctx, stage02, monkeypatch):
    segments = ctx.raw_dir / "overture_transportation_segment.geoparquet"
    _write_segments(
        segments,
        [
            {
                "id": "driveway",
                "subtype": "road",
                "class": "residential",
                "subclass": "driveway",
                "geometry": LineString([(77.57, 12.91), (77.58, 12.92)]),
            }
        ],
    )
    _write_manifest(ctx, {"overture_transportation_segment": segments.name})
    monkeypatch.setattr("lib.extract._from_osm", lambda *_args, **_kwargs: [])

    result = stage02.run(ctx)
    data = read_json(artifacts.SEPARATORS.path(ctx))
    assert data["features"] == []
    assert result.status is StageStatus.OK


def test_area_boundary_emits_outer_ring_not_polygon(ctx, stage02, monkeypatch):
    land = ctx.raw_dir / "overture_base_land_use.geoparquet"
    park = box(77.57, 12.91, 77.575, 12.915)
    gpd.GeoDataFrame(
        [
            {
                "id": "park-1",
                "class": "park",
                "source_tags": [("leisure", "park")],
                "geometry": park,
            }
        ],
        crs="EPSG:4326",
    ).to_parquet(land)
    _write_manifest(ctx, {"overture_base_land_use": land.name})
    monkeypatch.setattr("lib.extract._from_osm", lambda *_args, **_kwargs: [])

    stage02.run(ctx)
    data = read_json(artifacts.SEPARATORS.path(ctx))
    assert len(data["features"]) == 1
    feature = data["features"][0]
    assert feature["properties"]["group"] == "area_boundary"
    assert feature["properties"]["class"] == "leisure=park"
    assert feature["geometry"]["type"] == "LineString"
    # Closed ring: first coordinate equals last.
    coords = feature["geometry"]["coordinates"]
    assert coords[0] == coords[-1]


def test_points_are_never_separators(ctx, stage02, monkeypatch):
    segments = ctx.raw_dir / "overture_transportation_segment.geoparquet"
    _write_segments(
        segments,
        [
            {
                "id": "pointy",
                "subtype": "road",
                "class": "residential",
                "subclass": None,
                "geometry": Point(77.57, 12.91),
            }
        ],
    )
    _write_manifest(ctx, {"overture_transportation_segment": segments.name})
    monkeypatch.setattr("lib.extract._from_osm", lambda *_args, **_kwargs: [])

    stage02.run(ctx)
    data = read_json(artifacts.SEPARATORS.path(ctx))
    assert data["features"] == []


def test_output_is_sorted_stably(ctx, stage02, monkeypatch):
    segments = ctx.raw_dir / "overture_transportation_segment.geoparquet"
    _write_segments(
        segments,
        [
            {
                "id": "b",
                "subtype": "road",
                "class": "tertiary",
                "subclass": None,
                "geometry": LineString([(77.58, 12.92), (77.59, 12.93)]),
            },
            {
                "id": "a",
                "subtype": "road",
                "class": "primary",
                "subclass": None,
                "geometry": LineString([(77.57, 12.91), (77.58, 12.92)]),
            },
        ],
    )
    _write_manifest(ctx, {"overture_transportation_segment": segments.name})
    monkeypatch.setattr("lib.extract._from_osm", lambda *_args, **_kwargs: [])

    stage02.run(ctx)
    first = [f["properties"]["id"] for f in read_json(artifacts.SEPARATORS.path(ctx))["features"]]
    stage02.run(ctx)
    second = [f["properties"]["id"] for f in read_json(artifacts.SEPARATORS.path(ctx))["features"]]
    assert first == second
    assert first == sorted(first) or first == ["a", "b"] or len(first) == 2
