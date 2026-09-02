"""Stage 06 scrap-merge and protected-freeze rules."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point, Polygon, box, mapping, shape

from lib import artifacts
from lib.contracts import StageStatus
from lib.crs import to_store, to_work
from lib.determinism import content_hash
from lib.io import artifact_hash_input, is_placeholder, read_json, write_geojson
from lib.normalize import NormalizeError, safe_merge_geometry
from lib.registry import discover_stages


def _stage06():
    return next(s for s in discover_stages() if s.number == 6)


def _poly_feature(geom_store, **props):
    return {
        "type": "Feature",
        "geometry": mapping(geom_store),
        "properties": props,
    }


def _write_faces(ctx, features: list[dict]) -> None:
    write_geojson(
        artifacts.FACES.path(ctx),
        features,
        pipeline={
            "status": "ok",
            "stage": "polygonize_and_carve",
            "feature_count": len(features),
            "protected_count": sum(
                1 for f in features if (f.get("properties") or {}).get("protected")
            ),
        },
    )


def _centre_work(ctx):
    aoi = to_work(
        box(*ctx.region.bbox.as_xy_bounds()),
        ctx.region.crs_work,
    )
    minx, miny, maxx, maxy = aoi.bounds
    return (minx + maxx) / 2.0, (miny + maxy) / 2.0


def test_scraps_merge_into_longest_shared_border(ctx):
    """Three tiny scraps abut a large fabric block on a long edge."""
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    # Large fabric: 100m x 100m = 10_000 m² (above scrap).
    large = box(cx, cy, cx + 100, cy + 100)
    # Three scraps 20x20 = 400 m² each, stacked along the west edge of large
    # (shared border 20m each). A distractor to the south shares only a corner.
    s1 = box(cx - 20, cy, cx, cy + 20)
    s2 = box(cx - 20, cy + 20, cx, cy + 40)
    s3 = box(cx - 20, cy + 40, cx, cy + 60)
    distractor = box(cx + 40, cy - 20, cx + 60, cy)  # touches large on short edge

    features = []
    for i, g in enumerate((large, s1, s2, s3, distractor), start=1):
        features.append(
            _poly_feature(
                to_store(g, crs),
                face_id=f"face-{i:05d}",
                protected=False,
                kind="fabric",
                area_m2=round(float(g.area), 3),
            )
        )
    _write_faces(ctx, features)

    result = _stage06().run(ctx)
    assert result.status is StageStatus.OK
    data = read_json(artifacts.NORMALIZED.path(ctx))
    assert not is_placeholder(artifacts.NORMALIZED.path(ctx))
    assert data["pipeline"]["status"] == "ok"
    assert data["pipeline"]["scrap_merges"] >= 3

    fabric = [
        f
        for f in data["features"]
        if (f.get("properties") or {}).get("protected") is not True
    ]
    # Scraps absorbed; distractor may remain if it was above scrap or merged.
    assert len(fabric) <= 2
    areas = sorted(float(f["properties"]["area_m2"]) for f in fabric)
    # Big block ate three 400 m² scraps → ~11200, distractor ~400.
    assert areas[-1] >= 10000 + 3 * 400 - 1


def test_protected_landmark_untouched(ctx):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    park = box(cx, cy, cx + 1000, cy + 1000)  # 1 km²
    scrap = box(cx - 10, cy, cx, cy + 10)

    park_store = to_store(park, crs)
    features = [
        _poly_feature(
            park_store,
            face_id="face-00001",
            protected=True,
            role="major",
            name="Lalbagh Botanical Garden",
            slug="lalbagh-botanical-garden",
            kind="park",
            area_m2=round(float(park.area), 3),
        ),
        _poly_feature(
            to_store(scrap, crs),
            face_id="face-00002",
            protected=False,
            kind="fabric",
            area_m2=round(float(scrap.area), 3),
        ),
        _poly_feature(
            to_store(box(cx - 200, cy, cx - 10, cy + 200), crs),
            face_id="face-00003",
            protected=False,
            kind="fabric",
            area_m2=38000.0,
        ),
    ]
    _write_faces(ctx, features)
    before_area = float(park.area)

    _stage06().run(ctx)
    data = read_json(artifacts.NORMALIZED.path(ctx))
    protected = [
        f for f in data["features"] if f["properties"].get("protected") is True
    ]
    assert len(protected) == 1
    assert protected[0]["properties"]["slug"] == "lalbagh-botanical-garden"
    assert protected[0]["properties"]["name"] == "Lalbagh Botanical Garden"
    assert abs(protected[0]["properties"]["area_m2"] - before_area) < 1.0
    # Geometry must survive without absorbing fabric (same shape within CRS noise).
    after = to_work(shape(protected[0]["geometry"]), crs)
    assert after.equals_exact(park, tolerance=0.5)


def test_scrap_does_not_merge_into_protected(ctx):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    park = box(cx, cy, cx + 500, cy + 500)
    # Scrap shares long edge with park and short edge with fabric.
    scrap = box(cx - 20, cy, cx, cy + 100)
    fabric = box(cx - 220, cy, cx - 20, cy + 200)  # 200x200 = 40k

    features = [
        _poly_feature(
            to_store(park, crs),
            face_id="face-00001",
            protected=True,
            role="major",
            name="Big Park",
            slug="big-park",
            kind="park",
            area_m2=round(float(park.area), 3),
        ),
        _poly_feature(
            to_store(scrap, crs),
            face_id="face-00002",
            protected=False,
            kind="fabric",
            area_m2=round(float(scrap.area), 3),
        ),
        _poly_feature(
            to_store(fabric, crs),
            face_id="face-00003",
            protected=False,
            kind="fabric",
            area_m2=round(float(fabric.area), 3),
        ),
    ]
    _write_faces(ctx, features)
    park_area = float(park.area)

    _stage06().run(ctx)
    data = read_json(artifacts.NORMALIZED.path(ctx))
    protected = next(f for f in data["features"] if f["properties"].get("protected"))
    assert abs(protected["properties"]["area_m2"] - park_area) < 1.0

    fabric_faces = [
        f for f in data["features"] if not f["properties"].get("protected")
    ]
    assert len(fabric_faces) == 1
    assert fabric_faces[0]["properties"]["area_m2"] >= float(fabric.area) + float(
        scrap.area
    ) - 1


def test_coverage_preserved(ctx):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    tiles = [
        box(cx + dx, cy + dy, cx + dx + 30, cy + dy + 30)
        for dx in (0, 30, 60)
        for dy in (0, 30, 60)
    ]
    features = [
        _poly_feature(
            to_store(g, crs),
            face_id=f"face-{i:05d}",
            protected=False,
            kind="fabric",
            area_m2=round(float(g.area), 3),
        )
        for i, g in enumerate(tiles, start=1)
    ]
    _write_faces(ctx, features)
    before = sum(float(g.area) for g in tiles)

    _stage06().run(ctx)
    data = read_json(artifacts.NORMALIZED.path(ctx))
    after = sum(float(f["properties"]["area_m2"]) for f in data["features"])
    assert abs(after - before) <= ctx.thresholds.validation.max_gap_m2


def test_oversized_fabric_flagged_not_split(ctx):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    # 600m x 600m = 360_000 m² > fabric_review_max_m2 (250k).
    huge = box(cx, cy, cx + 600, cy + 600)
    features = [
        _poly_feature(
            to_store(huge, crs),
            face_id="face-00001",
            protected=False,
            kind="fabric",
            area_m2=round(float(huge.area), 3),
        )
    ]
    _write_faces(ctx, features)

    _stage06().run(ctx)
    data = read_json(artifacts.NORMALIZED.path(ctx))
    assert len(data["features"]) == 1
    props = data["features"][0]["properties"]
    assert props["needs_review"] is True
    assert props["protected"] is not True
    assert abs(props["area_m2"] - float(huge.area)) < 1.0


def test_output_deterministic(ctx):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    features = [
        _poly_feature(
            to_store(box(cx + dx, cy, cx + dx + 40, cy + 40), crs),
            face_id=f"face-{i:05d}",
            protected=False,
            kind="fabric",
            area_m2=1600.0,
        )
        for i, dx in enumerate((0, 40, 80, 120), start=1)
    ]
    features.append(
        _poly_feature(
            to_store(box(cx, cy + 40, cx + 160, cy + 200), crs),
            face_id="face-00099",
            protected=False,
            kind="fabric",
            area_m2=25600.0,
        )
    )
    _write_faces(ctx, features)

    _stage06().run(ctx)
    first = artifact_hash_input(read_json(artifacts.NORMALIZED.path(ctx)))
    _stage06().run(ctx)
    second = artifact_hash_input(read_json(artifacts.NORMALIZED.path(ctx)))
    assert first == second


def test_safe_merge_rejects_non_polygonal_collection(monkeypatch):
    a = box(0, 0, 10, 10)
    b = box(10, 0, 20, 10)

    def fake_union(_geoms):
        # Force a collection with a line so polygonal extraction fails the merge.
        from shapely.geometry import GeometryCollection

        return GeometryCollection([LineString([(0, 0), (1, 1)]), Point(2, 2)])

    monkeypatch.setattr("lib.normalize.unary_union", fake_union)
    result = safe_merge_geometry(a, b, max_area_loss_m2=1.0)
    assert result.geometry is None
    assert result.rejected_reason in {"non_polygonal", "empty_or_non_polygonal"}


def test_invalid_merge_rejected_keeps_valid_output(ctx, monkeypatch):
    """When union is invalid and irreparable, scrap stays + needs_review."""
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    large = box(cx, cy, cx + 100, cy + 100)
    scrap = box(cx - 20, cy, cx, cy + 20)

    from shapely.ops import unary_union as real_union

    def fake_union(geoms):
        geoms = list(geoms)
        # Only poison pairwise scrap merges; leave multi-face unions alone.
        if len(geoms) == 2:
            return Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])
        return real_union(geoms)

    def fake_make_valid(geom):
        return geom  # leave invalid

    monkeypatch.setattr("lib.normalize.unary_union", fake_union)
    monkeypatch.setattr("lib.normalize.make_valid", fake_make_valid)

    features = [
        _poly_feature(
            to_store(large, crs),
            face_id="face-00001",
            protected=False,
            kind="fabric",
            area_m2=round(float(large.area), 3),
        ),
        _poly_feature(
            to_store(scrap, crs),
            face_id="face-00002",
            protected=False,
            kind="fabric",
            area_m2=round(float(scrap.area), 3),
        ),
    ]
    _write_faces(ctx, features)
    _stage06().run(ctx)
    data = read_json(artifacts.NORMALIZED.path(ctx))
    assert data["pipeline"]["invalid_merge_attempts"] >= 1
    assert data["pipeline"]["scrap_merges"] == 0
    assert len(data["features"]) == 2
    for feature in data["features"]:
        assert shape(feature["geometry"]).is_valid
    scraps = [
        f
        for f in data["features"]
        if float(f["properties"]["area_m2"]) < ctx.thresholds.scrap_m2
    ]
    assert scraps
    assert all(f["properties"].get("needs_review") is True for f in scraps)


def test_protected_geometry_hash_unchanged(ctx):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    park = box(cx, cy, cx + 800, cy + 800)
    fabric = box(cx - 200, cy, cx - 20, cy + 200)
    scrap = box(cx - 20, cy, cx, cy + 100)
    park_store = to_store(park, crs)
    before_hash = content_hash(mapping(park_store))
    features = [
        _poly_feature(
            park_store,
            face_id="face-00001",
            protected=True,
            role="major",
            name="Lalbagh Botanical Garden",
            slug="lalbagh-botanical-garden",
            kind="park",
            area_m2=round(float(park.area), 3),
        ),
        _poly_feature(
            to_store(fabric, crs),
            face_id="face-00002",
            protected=False,
            kind="fabric",
            area_m2=round(float(fabric.area), 3),
        ),
        _poly_feature(
            to_store(scrap, crs),
            face_id="face-00003",
            protected=False,
            kind="fabric",
            area_m2=round(float(scrap.area), 3),
        ),
    ]
    _write_faces(ctx, features)
    _stage06().run(ctx)
    data = read_json(artifacts.NORMALIZED.path(ctx))
    protected = [f for f in data["features"] if f["properties"].get("protected")]
    assert len(protected) == 1
    assert content_hash(protected[0]["geometry"]) == before_hash
    assert abs(protected[0]["properties"]["area_m2"] - float(park.area)) < 1.0


def test_make_valid_area_loss_rejects_merge(monkeypatch):
    a = box(0, 0, 100, 100)  # 10_000
    b = box(100, 0, 120, 20)  # 400

    def fake_union(_geoms):
        return Polygon([(0, 0), (10, 10), (10, 0), (0, 10), (0, 0)])  # invalid

    def fake_make_valid(_geom):
        return box(0, 0, 1, 1)  # tiny — huge area loss

    monkeypatch.setattr("lib.normalize.unary_union", fake_union)
    monkeypatch.setattr("lib.normalize.make_valid", fake_make_valid)
    result = safe_merge_geometry(a, b, max_area_loss_m2=1.0)
    assert result.geometry is None
    assert result.rejected_reason == "area_loss"
    assert result.repaired is True


def test_point_touch_does_not_merge(ctx):
    """Corner-only contact shares ~0 border — below min_shared_border_m."""
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    large = box(cx, cy, cx + 100, cy + 100)
    # Touches only at the SW corner of large.
    scrap = box(cx - 20, cy - 20, cx, cy)
    features = [
        _poly_feature(
            to_store(large, crs),
            face_id="face-00001",
            protected=False,
            kind="fabric",
            area_m2=round(float(large.area), 3),
        ),
        _poly_feature(
            to_store(scrap, crs),
            face_id="face-00002",
            protected=False,
            kind="fabric",
            area_m2=round(float(scrap.area), 3),
        ),
    ]
    _write_faces(ctx, features)
    _stage06().run(ctx)
    data = read_json(artifacts.NORMALIZED.path(ctx))
    assert data["pipeline"]["scrap_merges"] == 0
    assert len(data["features"]) == 2


def test_non_touching_centroid_neighbour_does_not_merge(ctx):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    large = box(cx, cy, cx + 100, cy + 100)
    # Separated by a gap — centroid is nearer to large than anything else.
    scrap = box(cx - 50, cy, cx - 30, cy + 20)
    features = [
        _poly_feature(
            to_store(large, crs),
            face_id="face-00001",
            protected=False,
            kind="fabric",
            area_m2=round(float(large.area), 3),
        ),
        _poly_feature(
            to_store(scrap, crs),
            face_id="face-00002",
            protected=False,
            kind="fabric",
            area_m2=round(float(scrap.area), 3),
        ),
    ]
    _write_faces(ctx, features)
    _stage06().run(ctx)
    data = read_json(artifacts.NORMALIZED.path(ctx))
    assert data["pipeline"]["scrap_merges"] == 0
    assert len(data["features"]) == 2
    scrap_out = min(data["features"], key=lambda f: f["properties"]["area_m2"])
    assert scrap_out["properties"].get("needs_review") is True


def test_invalid_protected_input_fails(ctx):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
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
    features = [
        {
            "type": "Feature",
            "geometry": bowtie,
            "properties": {
                "face_id": "face-00001",
                "protected": True,
                "role": "major",
                "name": "Bad Park",
                "slug": "bad-park",
                "kind": "park",
                "area_m2": 1.0,
            },
        },
        _poly_feature(
            to_store(box(cx, cy, cx + 50, cy + 50), crs),
            face_id="face-00002",
            protected=False,
            kind="fabric",
            area_m2=2500.0,
        ),
    ]
    _write_faces(ctx, features)
    with pytest.raises(NormalizeError, match="protected"):
        _stage06().run(ctx)
    assert not artifacts.NORMALIZED.path(ctx).exists()


def test_every_output_geometry_is_valid(ctx):
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    features = [
        _poly_feature(
            to_store(box(cx + dx, cy, cx + dx + 40, cy + 40), crs),
            face_id=f"face-{i:05d}",
            protected=False,
            kind="fabric",
            area_m2=1600.0,
        )
        for i, dx in enumerate((0, 40, 80), start=1)
    ]
    features.append(
        _poly_feature(
            to_store(box(cx, cy + 40, cx + 120, cy + 160), crs),
            face_id="face-00099",
            protected=False,
            kind="fabric",
            area_m2=14400.0,
        )
    )
    _write_faces(ctx, features)
    _stage06().run(ctx)
    data = read_json(artifacts.NORMALIZED.path(ctx))
    for feature in data["features"]:
        geom = shape(feature["geometry"])
        assert geom.is_valid
        assert geom.geom_type in {"Polygon", "MultiPolygon"}
        assert not geom.is_empty


def test_degenerate_stage05_input_fails_loudly(ctx):
    """Stage 06 must not silently drop Stage 05 garbage."""
    crs = ctx.region.crs_work
    cx, cy = _centre_work(ctx)
    # Tiny / zero-area-looking multipolygon that Stage 05 should never emit.
    degenerate = {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [
                    [77.58, 12.94],
                    [77.58000001, 12.94],
                    [77.58000001, 12.94000001],
                    [77.58, 12.94000001],
                    [77.58, 12.94],
                ]
            ]
        ],
    }
    features = [
        {
            "type": "Feature",
            "geometry": degenerate,
            "properties": {
                "face_id": "face-00001",
                "protected": False,
                "kind": "fabric",
                "area_m2": 0.0,
            },
        },
        _poly_feature(
            to_store(box(cx, cy, cx + 100, cy + 100), crs),
            face_id="face-00002",
            protected=False,
            kind="fabric",
            area_m2=10000.0,
        ),
    ]
    _write_faces(ctx, features)
    with pytest.raises(NormalizeError, match="degenerate|near-zero|Stage 05"):
        _stage06().run(ctx)
    assert not artifacts.NORMALIZED.path(ctx).exists()
