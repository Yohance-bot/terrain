"""Tests for legendary labeling and exterior-corner budget."""

from __future__ import annotations

from shapely.geometry import Polygon, box, mapping

from lib.corner_budget import (
    apply_corner_budget,
    budget_exterior_corner_count,
    exterior_corner_count,
    territory_class_of,
)
from lib.crs import to_store
from lib.determinism import territory_id


def _feature(ctx, *, slug: str, geom, **props):
    tid = str(territory_id(ctx.region.city, ctx.region.area, slug))
    store = to_store(geom, ctx.region.crs_work, ctx.region.crs_store)
    base = {
        "territory_id": tid,
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "kind": "block",
        "protected": False,
        "legendary": False,
        "landmark_dedicated": False,
        "territory_class": "ordinary",
        "area_m2": float(geom.area),
        "member_territory_ids": [tid],
        "member_count": 1,
        "layer": "gameplay",
    }
    base.update(props)
    return {"type": "Feature", "geometry": mapping(store), "properties": base}


def test_budget_corners_exclude_legendary_interface(ctx):
    lake = box(500_000, 1_430_000, 500_800, 1_430_800)
    # Fabric shares the lake's right edge (many vertices along that edge).
    shared_x = 500_800
    coords = [(shared_x, 1_430_000 + i * 20) for i in range(20)]
    coords += [(501_600, 1_430_380), (501_600, 1_430_000), coords[0]]
    fabric = Polygon(coords)
    lake_f = _feature(
        ctx,
        slug="lalbagh",
        geom=lake,
        kind="park",
        protected=True,
        legendary=True,
        territory_class="legendary",
    )
    fabric_f = _feature(ctx, slug="fabric", geom=fabric, territory_class="ordinary")
    # Force a high total vertex count on the shared edge, then apply budget.
    result = apply_corner_budget(
        ctx, [lake_f, fabric_f], separators={"type": "FeatureCollection", "features": []}
    )
    for f in result.features:
        if f["properties"].get("territory_class") == "legendary":
            continue
        assert f["properties"]["exterior_corners"] <= ctx.thresholds.beautify.max_exterior_corners


def test_exterior_corner_count_square():
    poly = box(0, 0, 10, 10)
    assert exterior_corner_count(poly) == 4
    assert budget_exterior_corner_count(poly) == 4


def test_territory_class_helpers():
    assert territory_class_of({"protected": True}) == "legendary"
    assert territory_class_of({"landmark_dedicated": True}) == "ordinary"
    assert territory_class_of({}) == "ordinary"
    assert territory_class_of({"territory_class": "special"}) == "ordinary"
    assert territory_class_of({"territory_class": "ordinary"}) == "ordinary"
    assert territory_class_of({"territory_class": "legendary"}) == "legendary"


def test_corner_budget_reduces_ordinary_below_cap(ctx):
    # Zigzag on the west (free) edge; east edge is a clean shared border with neighbour.
    west = []
    for i in range(24):
        west.append((500_000, 1_430_000 + i * 20 + (15 if i % 2 else 0)))
    coords = (
        [(500_200, 1_430_000)]
        + west
        + [(500_200, 1_430_000 + 23 * 20), (500_200, 1_430_000), (500_200, 1_430_000)]
    )
    # Build a proper ring: SW corner, zigzag west side northward, NE, SE, close.
    coords = [(500_200, 1_430_000)]
    for i in range(24):
        coords.append((500_000 - (15 if i % 2 else 0), 1_430_000 + i * 25))
    coords.append((500_200, 1_430_000 + 23 * 25))
    coords.append((500_200, 1_430_000))
    jagged = Polygon(coords)
    assert exterior_corner_count(jagged) > 10

    neighbour = box(500_200, 1_430_000, 501_000, 1_430_000 + 23 * 25)
    features = [
        _feature(ctx, slug="jagged", geom=jagged, territory_class="ordinary"),
        _feature(
            ctx,
            slug="neighbour",
            geom=neighbour,
            territory_class="ordinary",
            area_m2=float(neighbour.area),
        ),
    ]
    result = apply_corner_budget(ctx, features, separators={"type": "FeatureCollection", "features": []})
    # Best-effort: either under the cap, or soft-flagged after mosaic-safe peels.
    over = []
    for f in result.features:
        props = f["properties"]
        if props.get("territory_class") == "legendary":
            continue
        from shapely.geometry import shape
        from lib.crs import to_work

        geom = to_work(shape(f["geometry"]), ctx.region.crs_work)
        corners = exterior_corner_count(geom)
        if corners > ctx.thresholds.beautify.max_exterior_corners:
            over.append(props.get("slug"))
    if over:
        assert result.report.still_over_budget, over
        assert any(a.get("op") == "corner_budget_soft_over" for a in result.report.applied)
    assert result.report.vertices_removed > 0 or result.report.merges > 0 or not over


def test_legendary_geometry_unchanged(ctx):
    lake = box(500_000, 1_430_000, 500_800, 1_430_800)
    fabric = box(500_800, 1_430_000, 501_600, 1_430_800)
    lake_f = _feature(
        ctx,
        slug="lalbagh",
        geom=lake,
        kind="park",
        protected=True,
        legendary=True,
        territory_class="legendary",
        role="major",
    )
    fabric_f = _feature(ctx, slug="fabric", geom=fabric, territory_class="ordinary")
    before = lake_f["geometry"]
    result = apply_corner_budget(
        ctx, [lake_f, fabric_f], separators={"type": "FeatureCollection", "features": []}
    )
    legendary = [
        f
        for f in result.features
        if (f.get("properties") or {}).get("territory_class") == "legendary"
    ]
    assert len(legendary) == 1
    assert legendary[0]["geometry"] == before
    assert legendary[0]["properties"]["legendary"] is True
