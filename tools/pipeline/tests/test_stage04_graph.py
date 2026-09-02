"""Stage 04 boundary-graph rules against synthetic separators."""

from __future__ import annotations

from collections import Counter

import pytest
from shapely.geometry import LineString, mapping, shape

from lib import artifacts
from lib.contracts import StageStatus
from lib.io import artifact_hash_input, is_placeholder, read_json, write_geojson
from lib.registry import discover_stages


@pytest.fixture
def stage04():
    return next(s for s in discover_stages() if s.number == 4)


def _write_separators(ctx, lines_lonlat: list[LineString], **props) -> None:
    features = []
    for idx, line in enumerate(lines_lonlat, start=1):
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(line),
                "properties": {
                    "source": "test",
                    "group": "highway",
                    "class": "residential",
                    "id": str(idx),
                    **props,
                },
            }
        )
    write_geojson(
        artifacts.SEPARATORS.path(ctx),
        features,
        pipeline={"status": "ok", "stage": "extract_features", "feature_count": len(features)},
    )


def _endpoint_degrees(features) -> Counter:
    counts: Counter = Counter()
    for feature in features:
        coords = list(shape(feature["geometry"]).coords)
        for coord in (coords[0], coords[-1]):
            key = (round(coord[0], 3), round(coord[1], 3))
            counts[key] += 1
    return counts


def test_cross_nodes_into_degree_three_or_four_junction(ctx, stage04):
    """A + shape must split at the crossing -- not stay as two unsplit lines."""
    # Lon/lat roughly 200 m arms around a centre near the AOI.
    cx, cy = 77.58, 12.93
    # ~0.002° ≈ 220 m
    _write_separators(
        ctx,
        [
            LineString([(cx - 0.002, cy), (cx + 0.002, cy)]),
            LineString([(cx, cy - 0.002), (cx, cy + 0.002)]),
        ],
    )

    result = stage04.run(ctx)
    assert result.status is StageStatus.OK
    data = read_json(artifacts.BOUNDARY_GRAPH.path(ctx))
    assert not is_placeholder(artifacts.BOUNDARY_GRAPH.path(ctx))
    assert data["pipeline"]["status"] == "ok"
    assert data["pipeline"]["crs"] == ctx.region.crs_work
    assert data["pipeline"]["crs"].startswith("EPSG:")
    assert data["pipeline"]["crs"] != "EPSG:4326"

    features = data["features"]
    # Four half-arms after noding a cross.
    assert len(features) == 4

    # Coordinates must be metres in the working CRS, not degrees.
    for feature in features:
        for x, y in feature["geometry"]["coordinates"]:
            assert abs(x) > 1000
            assert abs(y) > 1000

    degrees = _endpoint_degrees(features)
    # Centre appears four times (one per half-edge); outer tips once each.
    centre_hits = max(degrees.values())
    assert centre_hits == 4
    assert sum(1 for v in degrees.values() if v == 1) == 4


def test_near_miss_within_snap_m_closes(ctx, stage04):
    """Two stubs ending ~1 m apart must snap; a 10 m gap must not."""
    # Build geometry in working CRS so snap_m is unambiguous, then store as 4326.
    from lib.crs import to_store

    crs = ctx.region.crs_work
    # Horizontal line; second line ends 1 m short of the junction.
    base = LineString([(500000.0, 1400000.0), (500100.0, 1400000.0)])
    near = LineString([(500050.0, 1400050.0), (500050.0, 1400001.0)])
    _write_separators(
        ctx,
        [
            to_store(base, crs),
            to_store(near, crs),
        ],
    )

    stage04.run(ctx)
    data = read_json(artifacts.BOUNDARY_GRAPH.path(ctx))
    features = data["features"]
    assert len(features) >= 2

    # After snap+node, the short vertical should meet the horizontal.
    # Collect all vertices and check min distance from the intended junction.
    junction = (500050.0, 1400000.0)
    min_dist = min(
        ((x - junction[0]) ** 2 + (y - junction[1]) ** 2) ** 0.5
        for f in features
        for x, y in f["geometry"]["coordinates"]
    )
    assert min_dist <= ctx.thresholds.snap_m


def test_dangle_spur_is_dropped(ctx, stage04):
    from lib.crs import to_store

    crs = ctx.region.crs_work
    # A triangle (cycle) plus a dangling spur off one vertex.
    a = (500000.0, 1400000.0)
    b = (500100.0, 1400000.0)
    c = (500050.0, 1400080.0)
    dangle_end = (500000.0, 1399900.0)
    _write_separators(
        ctx,
        [
            to_store(LineString([a, b]), crs),
            to_store(LineString([b, c]), crs),
            to_store(LineString([c, a]), crs),
            to_store(LineString([a, dangle_end]), crs),
        ],
    )

    stage04.run(ctx)
    data = read_json(artifacts.BOUNDARY_GRAPH.path(ctx))
    features = data["features"]
    # Spur gone; triangle remains as three edges.
    assert len(features) == 3
    tips = _endpoint_degrees(features)
    # Every remaining endpoint should have degree >= 2 (cycle).
    assert all(v >= 2 for v in tips.values())


def test_snap_tolerance_is_metres_not_degrees(ctx, stage04):
    """Regression: applying snap_m in 4326 would collapse the whole AOI."""
    assert ctx.thresholds.snap_m == 3.0
    # Two lines 50 m apart -- far more than 3 m, must NOT snap together.
    from lib.crs import to_store

    crs = ctx.region.crs_work
    left = LineString([(500000.0, 1400000.0), (500000.0, 140100.0)])
    right = LineString([(500050.0, 1400000.0), (500050.0, 140100.0)])
    _write_separators(
        ctx,
        [to_store(left, crs), to_store(right, crs)],
    )

    stage04.run(ctx)
    data = read_json(artifacts.BOUNDARY_GRAPH.path(ctx))
    # Still two separate corridors (possibly each as one edge).
    xs = {
        round(coord[0], 1)
        for f in data["features"]
        for coord in f["geometry"]["coordinates"]
    }
    assert 500000.0 in xs
    assert 500050.0 in xs


def test_output_is_deterministic_across_reruns(ctx, stage04):
    cx, cy = 77.58, 12.93
    _write_separators(
        ctx,
        [
            LineString([(cx - 0.001, cy), (cx + 0.001, cy)]),
            LineString([(cx, cy - 0.001), (cx, cy + 0.001)]),
            LineString([(cx - 0.001, cy - 0.001), (cx + 0.001, cy + 0.001)]),
        ],
    )

    stage04.run(ctx)
    first = artifact_hash_input(read_json(artifacts.BOUNDARY_GRAPH.path(ctx)))
    stage04.run(ctx)
    second = artifact_hash_input(read_json(artifacts.BOUNDARY_GRAPH.path(ctx)))
    assert first == second
