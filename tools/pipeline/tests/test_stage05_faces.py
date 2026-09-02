"""Stage 05 polygonize + carve rules against synthetic graph / landmarks."""

from __future__ import annotations

from shapely.geometry import Point, box, mapping, shape

from lib import artifacts
from lib.contracts import StageStatus
from lib.crs import to_store, to_work
from lib.io import artifact_hash_input, is_placeholder, read_json, write_geojson
from lib.registry import discover_stages


def _stage05():
    return next(s for s in discover_stages() if s.number == 5)


def _aoi_work(ctx):
    return to_work(box(*ctx.region.bbox.as_xy_bounds()), ctx.region.crs_work)


def _write_grid_graph(ctx, *, cell_m: float = 200.0) -> tuple[float, float]:
    """Write a 2x2 grid of separators near the AOI centre (working CRS)."""
    aoi = _aoi_work(ctx)
    minx, miny, maxx, maxy = aoi.bounds
    cx = (minx + maxx) / 2.0
    cy = (miny + maxy) / 2.0
    # Three vertical + three horizontal lines spanning 2 cells.
    xs = [cx - cell_m, cx, cx + cell_m]
    ys = [cy - cell_m, cy, cy + cell_m]
    lines = []
    for x in xs:
        lines.append([[x, ys[0]], [x, ys[-1]]])
    for y in ys:
        lines.append([[xs[0], y], [xs[-1], y]])

    features = []
    for idx, coords in enumerate(lines, start=1):
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {"edge_id": idx},
            }
        )
    write_geojson(
        artifacts.BOUNDARY_GRAPH.path(ctx),
        features,
        pipeline={
            "status": "ok",
            "stage": "build_boundary_graph",
            "crs": ctx.region.crs_work,
            "feature_count": len(features),
        },
    )
    return cx, cy


def _write_landmarks(ctx, features: list[dict]) -> None:
    write_geojson(
        artifacts.LANDMARKS.path(ctx),
        features,
        pipeline={
            "status": "ok",
            "stage": "extract_landmarks",
            "feature_count": len(features),
            "major_count": sum(
                1 for f in features if (f.get("properties") or {}).get("role") == "major"
            ),
            "minor_count": sum(
                1 for f in features if (f.get("properties") or {}).get("role") == "minor"
            ),
        },
    )


def test_synthetic_grid_polygonizes_exhaustive_cover(ctx):
    _write_grid_graph(ctx)
    _write_landmarks(ctx, [])

    result = _stage05().run(ctx)
    assert result.status is StageStatus.OK
    data = read_json(artifacts.FACES.path(ctx))
    assert not is_placeholder(artifacts.FACES.path(ctx))
    assert data["pipeline"]["status"] == "ok"
    assert data["pipeline"]["feature_count"] >= 4

    aoi = _aoi_work(ctx)
    face_union_area = 0.0
    for feature in data["features"]:
        work = to_work(shape(feature["geometry"]), ctx.region.crs_work)
        face_union_area += float(work.area)

    # Exhaustive cover within float noise (metres²).
    assert abs(face_union_area - float(aoi.area)) < 1.0
    # Interior grid cells exist as distinct fabric faces.
    fabric = [
        f
        for f in data["features"]
        if (f.get("properties") or {}).get("protected") is False
    ]
    assert len(fabric) >= 4


def test_major_landmark_remains_whole(ctx):
    cx, cy = _write_grid_graph(ctx)
    # Landmark spans two grid cells around the centre.
    landmark_work = box(cx - 150, cy - 80, cx + 150, cy + 80)
    landmark_store = to_store(landmark_work, ctx.region.crs_work)
    _write_landmarks(
        ctx,
        [
            {
                "type": "Feature",
                "geometry": mapping(landmark_store),
                "properties": {
                    "protected": True,
                    "role": "major",
                    "name": "Lalbagh Botanical Garden",
                    "slug": "lalbagh-botanical-garden",
                    "kind": "park",
                    "category": "park",
                    "source": "test",
                    "source_id": "1",
                    "area_m2": float(landmark_work.area),
                },
            }
        ],
    )

    _stage05().run(ctx)
    data = read_json(artifacts.FACES.path(ctx))
    protected = [
        f
        for f in data["features"]
        if (f.get("properties") or {}).get("protected") is True
    ]
    assert len(protected) == 1
    props = protected[0]["properties"]
    assert props["slug"] == "lalbagh-botanical-garden"
    assert props["role"] == "major"
    assert props["name"] == "Lalbagh Botanical Garden"

    carved = to_work(shape(protected[0]["geometry"]), ctx.region.crs_work)
    assert abs(float(carved.area) - float(landmark_work.area)) < 1.0

    # No fabric face should contain the landmark centroid.
    centroid = landmark_work.centroid
    for feature in data["features"]:
        if feature["properties"].get("protected"):
            continue
        fabric = to_work(shape(feature["geometry"]), ctx.region.crs_work)
        assert not fabric.contains(centroid)


def test_minor_landmark_is_not_carved(ctx):
    cx, cy = _write_grid_graph(ctx)
    minor_work = box(cx - 30, cy - 30, cx + 30, cy + 30)
    minor_store = to_store(minor_work, ctx.region.crs_work)
    _write_landmarks(
        ctx,
        [
            {
                "type": "Feature",
                "geometry": mapping(minor_store),
                "properties": {
                    "protected": False,
                    "role": "minor",
                    "name": "Pocket Park",
                    "slug": "pocket-park",
                    "kind": "park",
                    "category": "park",
                    "source": "test",
                    "source_id": "2",
                    "area_m2": float(minor_work.area),
                },
            }
        ],
    )

    _stage05().run(ctx)
    data = read_json(artifacts.FACES.path(ctx))
    assert data["pipeline"]["protected_count"] == 0
    slugs = {
        (f.get("properties") or {}).get("slug")
        for f in data["features"]
        if (f.get("properties") or {}).get("slug")
    }
    assert "pocket-park" not in slugs

    # The minor park's centre sits inside some fabric face, not as its own.
    centre = Point(cx, cy)
    containing = 0
    for feature in data["features"]:
        work = to_work(shape(feature["geometry"]), ctx.region.crs_work)
        if work.contains(centre):
            containing += 1
            assert feature["properties"]["protected"] is False
            assert feature["properties"]["kind"] == "fabric"
    assert containing == 1


def test_output_is_deterministic_across_reruns(ctx):
    _write_grid_graph(ctx)
    cx, cy = _aoi_work(ctx).centroid.x, _aoi_work(ctx).centroid.y
    landmark_work = box(cx - 100, cy - 100, cx + 100, cy + 100)
    _write_landmarks(
        ctx,
        [
            {
                "type": "Feature",
                "geometry": mapping(to_store(landmark_work, ctx.region.crs_work)),
                "properties": {
                    "protected": True,
                    "role": "major",
                    "name": "Named Lake",
                    "slug": "named-lake",
                    "kind": "lake",
                    "category": "lake",
                    "source": "test",
                    "source_id": "3",
                    "area_m2": float(landmark_work.area),
                },
            }
        ],
    )

    _stage05().run(ctx)
    first = artifact_hash_input(read_json(artifacts.FACES.path(ctx)))
    _stage05().run(ctx)
    second = artifact_hash_input(read_json(artifacts.FACES.path(ctx)))
    assert first == second


def test_faces_are_written_in_storage_crs(ctx):
    _write_grid_graph(ctx)
    _write_landmarks(ctx, [])
    _stage05().run(ctx)
    data = read_json(artifacts.FACES.path(ctx))
    assert data["pipeline"]["crs_store"] == "EPSG:4326"
    for feature in data["features"]:
        for ring in feature["geometry"]["coordinates"]:
            # MultiPolygon: coordinates[poly][ring][point]
            pts = ring if feature["geometry"]["type"] == "Polygon" else ring[0]
            for x, y in pts[:1]:
                assert abs(x) < 180
                assert abs(y) < 90


def test_output_has_no_zero_area_or_invalid_faces(ctx):
    from shapely import is_valid

    from lib.faces import FACE_AREA_EPSILON_M2

    _write_grid_graph(ctx)
    _write_landmarks(ctx, [])
    _stage05().run(ctx)
    data = read_json(artifacts.FACES.path(ctx))
    for feature in data["features"]:
        geom = shape(feature["geometry"])
        assert geom.geom_type in {"Polygon", "MultiPolygon"}
        assert is_valid(geom)
        work = to_work(geom, ctx.region.crs_work)
        assert float(work.area) > FACE_AREA_EPSILON_M2
        assert float(feature["properties"]["area_m2"]) > 0


def test_invalid_protected_landmark_fails(ctx):
    import pytest

    from lib.faces import FaceBuildError

    _write_grid_graph(ctx)
    bowtie = {
        "type": "Polygon",
        "coordinates": [
            [
                [77.58, 12.94],
                [77.59, 12.95],
                [77.59, 12.94],
                [77.58, 12.95],
                [77.58, 12.94],
            ]
        ],
    }
    _write_landmarks(
        ctx,
        [
            {
                "type": "Feature",
                "geometry": bowtie,
                "properties": {
                    "protected": True,
                    "role": "major",
                    "name": "Bad Park",
                    "slug": "bad-park",
                    "kind": "park",
                    "category": "park",
                    "source": "test",
                    "source_id": "bad",
                    "area_m2": 1.0,
                },
            }
        ],
    )
    with pytest.raises(FaceBuildError, match="atomic landmark"):
        _stage05().run(ctx)
    assert not artifacts.FACES.path(ctx).exists()
