"""Stage 10 barrier-aware agglomerative clustering."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from shapely.geometry import box, mapping

from lib import artifacts
from lib.cluster import ClusterError, _PlaceHint, cluster_parcels
from lib.config import BBox
from lib.contracts import StageStatus
from lib.determinism import content_hash, gameplay_territory_id, territory_id
from lib.io import artifact_hash_input, write_geojson
from lib.registry import discover_stages


def _cell(west: float, south: float, size: float = 0.002) -> dict:
    poly = box(west, south, west + size, south + size)
    return mapping(poly)


def _parcel(
    *,
    city: str,
    area: str,
    slug: str,
    name: str,
    geom: dict,
    protected: bool = False,
    area_m2: float = 40000.0,
) -> dict:
    tid = str(territory_id(city, area, slug))
    props = {
        "territory_id": tid,
        "slug": slug,
        "name": name,
        "kind": "park" if protected else "block",
        "protected": protected,
        "area_m2": area_m2,
        "name_source": "landmark" if protected else "place",
    }
    if protected:
        props["role"] = "major"
    return {"type": "Feature", "geometry": geom, "properties": props}


def _sep_line(coords: list[list[float]], group: str, klass: str) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {"group": group, "class": klass, "source": "test"},
    }


def _tiny_ctx(ctx):
    """Shrink AOI to the synthetic grid so coverage checks can pass."""
    bbox = BBox(12.920, 77.570, 12.930, 77.582)
    region = replace(ctx.region, bbox=bbox)
    return replace(ctx, region=region)


def test_stage10_is_registered():
    stage = next(s for s in discover_stages() if s.number == 10)
    assert stage.name == "cluster_gameplay"
    assert artifacts.PUBLISHED_TERRITORIES in stage.requires
    assert artifacts.GAMEPLAY_CANDIDATES in stage.produces


def test_merges_across_residential_not_primary(ctx):
    ctx = _tiny_ctx(ctx)
    city, area = ctx.region.city, ctx.region.area
    size = 0.002
    # West of trunk (x < 77.576): two stacked cells
    w0 = _parcel(
        city=city,
        area=area,
        slug="west-a",
        name="Jayanagar 4th Block A",
        geom=_cell(77.570, 12.922, size),
        area_m2=25000,
    )
    w1 = _parcel(
        city=city,
        area=area,
        slug="west-b",
        name="Jayanagar 4th Block B",
        geom=_cell(77.570, 12.924, size),
        area_m2=25000,
    )
    # East of trunk
    e0 = _parcel(
        city=city,
        area=area,
        slug="east-a",
        name="Basavanagudi A",
        geom=_cell(77.578, 12.922, size),
        area_m2=25000,
    )
    e1 = _parcel(
        city=city,
        area=area,
        slug="east-b",
        name="Basavanagudi B",
        geom=_cell(77.578, 12.924, size),
        area_m2=25000,
    )
    lake = _parcel(
        city=city,
        area=area,
        slug="test-lake",
        name="Test Lake",
        geom=_cell(77.570, 12.926, 0.006),
        protected=True,
        area_m2=300000,
    )

    parcels = [w0, w1, e0, e1, lake]
    # Primary trunk between west and east; residential between stacked cells
    separators = [
        _sep_line([[77.576, 12.920], [77.576, 12.930]], "highway", "primary"),
        _sep_line([[77.570, 12.924], [77.574, 12.924]], "highway", "residential"),
        _sep_line([[77.578, 12.924], [77.582, 12.924]], "highway", "residential"),
    ]

    place_west = _PlaceHint(
        key="jayanagar-4th-block",
        name="Jayanagar 4th Block",
        slug="jayanagar-4th-block",
        geom=box(77.569, 12.921, 77.575, 12.926),
        area_m2=1e6,
    )
    # Place geoms are in work CRS in production; for tests inject already-projected.
    from lib.crs import to_work

    place_west = _PlaceHint(
        key=place_west.key,
        name=place_west.name,
        slug=place_west.slug,
        geom=to_work(place_west.geom, ctx.region.crs_work),
        area_m2=place_west.area_m2,
    )

    result = cluster_parcels(
        ctx,
        parcels=parcels,
        separators=separators,
        places=[place_west],
    )

    assert result.report.protected_count == 1
    assert result.report.merges >= 1
    # Must not merge west with east across primary.
    fabric = [
        f for f in result.features if (f.get("properties") or {}).get("protected") is not True
    ]
    assert len(fabric) >= 2
    member_sets = [
        set((f.get("properties") or {}).get("member_territory_ids") or []) for f in fabric
    ]
    west_ids = {w0["properties"]["territory_id"], w1["properties"]["territory_id"]}
    east_ids = {e0["properties"]["territory_id"], e1["properties"]["territory_id"]}
    for members in member_sets:
        assert not (members & west_ids and members & east_ids)

    protected = [
        f for f in result.features if (f.get("properties") or {}).get("protected") is True
    ]
    assert len(protected) == 1
    assert protected[0]["properties"]["territory_id"] == lake["properties"]["territory_id"]
    assert content_hash(protected[0]["geometry"]) == content_hash(lake["geometry"])


def test_determinism_same_inputs_same_ids(ctx):
    ctx = _tiny_ctx(ctx)
    city, area = ctx.region.city, ctx.region.area
    parcels = [
        _parcel(
            city=city,
            area=area,
            slug="a",
            name="Block A",
            geom=_cell(77.570, 12.922),
            area_m2=20000,
        ),
        _parcel(
            city=city,
            area=area,
            slug="b",
            name="Block B",
            geom=_cell(77.570, 12.924),
            area_m2=20000,
        ),
    ]
    separators = [
        _sep_line([[77.570, 12.924], [77.574, 12.924]], "highway", "residential"),
    ]
    r1 = cluster_parcels(ctx, parcels=parcels, separators=separators, places=[])
    r2 = cluster_parcels(ctx, parcels=deepcopy(parcels), separators=deepcopy(separators), places=[])
    ids1 = sorted(
        (f.get("properties") or {}).get("territory_id") for f in r1.features
    )
    ids2 = sorted(
        (f.get("properties") or {}).get("territory_id") for f in r2.features
    )
    assert ids1 == ids2
    assert r1.report.merges == r2.report.merges
    h1 = content_hash(artifact_hash_input({"type": "FeatureCollection", "features": r1.features}))
    h2 = content_hash(artifact_hash_input({"type": "FeatureCollection", "features": r2.features}))
    assert h1 == h2


def test_undersized_stuck_when_only_barrier_neighbours(ctx):
    ctx = _tiny_ctx(ctx)
    city, area = ctx.region.city, ctx.region.area
    small = _parcel(
        city=city,
        area=area,
        slug="island",
        name="Island",
        geom=_cell(77.570, 12.922, 0.001),
        area_m2=8000,
    )
    other = _parcel(
        city=city,
        area=area,
        slug="other",
        name="Other",
        geom=_cell(77.578, 12.922, 0.001),
        area_m2=8000,
    )
    separators = [
        _sep_line([[77.574, 12.920], [77.574, 12.930]], "highway", "trunk"),
    ]
    result = cluster_parcels(
        ctx, parcels=[small, other], separators=separators, places=[]
    )
    assert result.report.merges == 0
    assert result.report.undersized_stuck >= 1
    fabric = [
        f for f in result.features if not (f.get("properties") or {}).get("protected")
    ]
    assert all((f.get("properties") or {}).get("needs_review") for f in fabric)


def test_gameplay_id_namespace_differs_from_parcel(ctx):
    city, area = ctx.region.city, ctx.region.area
    parcel = territory_id(city, area, "jayanagar-4th-block")
    gameplay = gameplay_territory_id(city, area, "jayanagar-4th-block")
    assert parcel != gameplay


def test_mergeable_atomic_park_merges_lalbagh_scale_stays(ctx):
    """Tiny atomic parks fall back to absorb; source-protected landmarks freeze."""
    ctx = _tiny_ctx(ctx)
    city, area = ctx.region.city, ctx.region.area
    park = _parcel(
        city=city,
        area=area,
        slug="pocket-park",
        name="Pocket Park",
        geom=_cell(77.570, 12.922, 0.0015),
        area_m2=15000,
    )
    park["properties"]["atomic"] = True
    park["properties"]["protected"] = False
    park["properties"]["kind"] = "park"
    park["properties"]["atomic_source_name"] = "Pocket Park"
    park["properties"]["atomic_source_slug"] = "pocket-park"
    fabric = _parcel(
        city=city,
        area=area,
        slug="block-a",
        name="Block A",
        geom=_cell(77.570, 12.9235, 0.002),
        area_m2=25000,
    )
    lalbagh = _parcel(
        city=city,
        area=area,
        slug="lalbagh-botanical-gardens",
        name="Lalbagh Botanical Gardens",
        geom=_cell(77.578, 12.926, 0.006),
        protected=True,
        area_m2=900000,
    )
    lalbagh["properties"]["atomic"] = True
    separators = [
        _sep_line([[77.570, 12.9235], [77.573, 12.9235]], "highway", "residential"),
        _sep_line([[77.576, 12.920], [77.576, 12.930]], "highway", "motorway"),
    ]
    result = cluster_parcels(
        ctx, parcels=[park, fabric, lalbagh], separators=separators, places=[]
    )
    protected = [
        f for f in result.features if (f.get("properties") or {}).get("protected")
    ]
    assert len(protected) == 1
    assert protected[0]["properties"]["slug"] == "lalbagh-botanical-gardens"
    assert content_hash(protected[0]["geometry"]) == content_hash(lalbagh["geometry"])
    # Not enough adjacent fabric to reach 50 acres → absorb into fabric.
    fabric_out = [
        f
        for f in result.features
        if not (f.get("properties") or {}).get("protected")
    ]
    members = set()
    for f in fabric_out:
        members.update((f.get("properties") or {}).get("member_territory_ids") or [])
    assert park["properties"]["territory_id"] in members
    assert fabric["properties"]["territory_id"] in members
    assert len(result.report.atomic_absorptions) == 1
    assert result.report.atomic_absorptions[0]["landmark_name"] == "Pocket Park"
    assert result.report.atomic_expansions == []
    assert result.report.unabsorbed_atomic == []


def test_atomic_landmark_absorbs_into_fabric_never_expands(ctx):
    """Sub-50-acre atomics absorb into fabric; no special / dedicated class."""
    ctx = _tiny_ctx(ctx)
    city, area = ctx.region.city, ctx.region.area
    seed = _parcel(
        city=city,
        area=area,
        slug="jain-university",
        name="Jain University",
        geom=_cell(77.570, 12.920, 0.002),
        area_m2=48000,
    )
    seed["properties"].update(
        {
            "atomic": True,
            "protected": False,
            "kind": "landmark",
            "atomic_source_name": "Jain University",
            "atomic_source_slug": "jain-university",
        }
    )
    parcels = [seed]
    coords = [
        (77.572, 12.920),
        (77.570, 12.922),
        (77.572, 12.922),
        (77.570, 12.924),
        (77.572, 12.924),
    ]
    for i, (west, south) in enumerate(coords):
        parcels.append(
            _parcel(
                city=city,
                area=area,
                slug=f"fabric-{i}",
                name=f"Fabric {i}",
                geom=_cell(west, south, 0.002),
                area_m2=48000,
            )
        )
    separators = [
        _sep_line([[77.570, 12.922], [77.574, 12.922]], "highway", "residential"),
        _sep_line([[77.570, 12.924], [77.574, 12.924]], "highway", "residential"),
        _sep_line([[77.572, 12.920], [77.572, 12.926]], "highway", "residential"),
    ]
    result = cluster_parcels(ctx, parcels=parcels, separators=separators, places=[])
    assert result.report.atomic_expansions == []
    assert result.report.unabsorbed_atomic == []
    assert any(
        a.get("landmark_slug") == "jain-university"
        and a.get("decision")
        in {"absorbed_into_fabric", "deferred_to_general_clustering"}
        for a in result.report.atomic_absorptions
    ), result.report.atomic_absorptions
    holders = [
        f
        for f in result.features
        if seed["properties"]["territory_id"]
        in ((f.get("properties") or {}).get("member_territory_ids") or [])
    ]
    assert len(holders) == 1
    props = holders[0]["properties"]
    assert props.get("landmark_dedicated") is not True
    assert props.get("territory_class") == "ordinary"
    assert props.get("protected") is not True
    assert len(props.get("member_territory_ids") or []) >= 2


def test_stranded_atomic_absorbs_into_fabric_not_dedicated(ctx):
    """Multiple atomics absorb into ordinary fabric; never into a special class."""
    ctx = _tiny_ctx(ctx)
    city, area = ctx.region.city, ctx.region.area
    seed = _parcel(
        city=city,
        area=area,
        slug="big-campus",
        name="Big Campus",
        geom=_cell(77.570, 12.920, 0.002),
        area_m2=48000,
    )
    seed["properties"].update(
        {
            "atomic": True,
            "protected": False,
            "kind": "landmark",
            "atomic_source_name": "Big Campus",
            "atomic_source_slug": "big-campus",
        }
    )
    leftover = _parcel(
        city=city,
        area=area,
        slug="pocket-college",
        name="Pocket College",
        geom=_cell(77.574, 12.922, 0.0015),
        area_m2=12000,
    )
    leftover["properties"].update(
        {
            "atomic": True,
            "protected": False,
            "kind": "college",
            "atomic_source_name": "Pocket College",
            "atomic_source_slug": "pocket-college",
        }
    )
    parcels = [seed, leftover]
    for i, (west, south) in enumerate(
        [(77.572, 12.920), (77.570, 12.922), (77.572, 12.922), (77.570, 12.924), (77.572, 12.924)]
    ):
        parcels.append(
            _parcel(
                city=city,
                area=area,
                slug=f"fabric-{i}",
                name=f"Fabric {i}",
                geom=_cell(west, south, 0.002),
                area_m2=48000,
            )
        )
    separators = [
        _sep_line([[77.570, 12.922], [77.576, 12.922]], "highway", "residential"),
        _sep_line([[77.570, 12.924], [77.576, 12.924]], "highway", "residential"),
        _sep_line([[77.572, 12.920], [77.572, 12.926]], "highway", "residential"),
        _sep_line([[77.574, 12.920], [77.574, 12.926]], "highway", "residential"),
    ]
    result = cluster_parcels(ctx, parcels=parcels, separators=separators, places=[])
    assert result.report.unabsorbed_atomic == [], result.report.unabsorbed_atomic
    assert result.report.atomic_expansions == []
    assert any(
        a.get("landmark_slug") == "pocket-college"
        and a.get("decision")
        in {"absorbed_into_fabric", "deferred_to_general_clustering"}
        for a in result.report.atomic_absorptions
    ), result.report.atomic_absorptions
    leftover_holders = [
        f
        for f in result.features
        if leftover["properties"]["territory_id"]
        in ((f.get("properties") or {}).get("member_territory_ids") or [])
    ]
    assert len(leftover_holders) == 1
    assert leftover_holders[0]["properties"].get("landmark_dedicated") is not True
    assert leftover_holders[0]["properties"].get("territory_class") == "ordinary"


def test_undersized_ordinary_absorbs_across_barrier(ctx):
    """Sub-250-acre ordinary scraps must merge into adjacent fabric."""
    ctx = _tiny_ctx(ctx)
    city, area = ctx.region.city, ctx.region.area
    # Two stacked cells that share a long border; both far below the floor so
    # Stage 10 must absorb them into one ordinary territory.
    south = _parcel(
        city=city,
        area=area,
        slug="south-block",
        name="South Block",
        geom=_cell(77.570, 12.922, 0.002),
        area_m2=40_000,
    )
    north = _parcel(
        city=city,
        area=area,
        slug="north-block",
        name="North Block",
        geom=_cell(77.570, 12.924, 0.002),
        area_m2=40_000,
    )
    separators = [
        _sep_line([[77.570, 12.924], [77.574, 12.924]], "highway", "residential"),
        _sep_line([[77.574, 12.920], [77.574, 12.928]], "highway", "trunk"),
    ]
    result = cluster_parcels(
        ctx, parcels=[south, north], separators=separators, places=[]
    )
    ordinary = [
        f
        for f in result.features
        if not (f.get("properties") or {}).get("protected")
    ]
    assert len(ordinary) == 1, [f["properties"].get("slug") for f in ordinary]
    members = set(ordinary[0]["properties"].get("member_territory_ids") or [])
    assert south["properties"]["territory_id"] in members
    assert north["properties"]["territory_id"] in members


def test_oversized_ordinary_input_fails_closed(ctx):
    ctx = _tiny_ctx(ctx)
    # Far above the ordinary hard max so Stage 10 refuses without inventing a split.
    oversized = _parcel(
        city=ctx.region.city,
        area=ctx.region.area,
        slug="missing-separators",
        name="Missing Separators",
        geom=_cell(77.570, 12.920, 0.02),
    )
    with pytest.raises(ClusterError, match="Fix upstream separators"):
        cluster_parcels(ctx, parcels=[oversized], separators=[], places=[])


def test_stage10_run_writes_artifacts(ctx, monkeypatch):
    ctx = _tiny_ctx(ctx)
    city, area = ctx.region.city, ctx.region.area
    parcels = [
        _parcel(
            city=city,
            area=area,
            slug="a",
            name="Block A",
            geom=_cell(77.570, 12.922),
            area_m2=20000,
        ),
        _parcel(
            city=city,
            area=area,
            slug="b",
            name="Block B",
            geom=_cell(77.570, 12.924),
            area_m2=20000,
        ),
        _parcel(
            city=city,
            area=area,
            slug="lake",
            name="Lake",
            geom=_cell(77.578, 12.926, 0.0015),
            protected=True,
            area_m2=50000,
        ),
    ]
    write_geojson(
        artifacts.PUBLISHED_TERRITORIES.path(ctx),
        parcels,
        pipeline={"status": "ok", "stage": "publish"},
    )
    write_geojson(
        artifacts.SEPARATORS.path(ctx),
        [_sep_line([[77.570, 12.924], [77.574, 12.924]], "highway", "residential")],
        pipeline={"status": "ok", "stage": "extract"},
    )

    def loose_validate(ctx_, features, parcel_features=None):
        return {
            "status": "pass",
            "stage": "cluster_gameplay",
            "hard": {"passed": True, "failures": []},
            "metrics": {"feature_count": len(features)},
            "soft": {"needs_review_count": 0},
        }

    monkeypatch.setattr("lib.validate.validate_gameplay_features", loose_validate)
    stage = next(s for s in discover_stages() if s.number == 10)
    result = stage.run(ctx)
    assert result.status is StageStatus.OK
    assert artifacts.GAMEPLAY_CANDIDATES.path(ctx).exists()
    assert artifacts.GAMEPLAY_CLUSTER_REPORT.path(ctx).exists()
    assert artifacts.GAMEPLAY_VALIDATION_REPORT.path(ctx).exists()
