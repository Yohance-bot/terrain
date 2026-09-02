"""Stage 11 beautify + Stage 12 review + Stage 13 gameplay publish."""

from __future__ import annotations

import math

from shapely.geometry import box, mapping

from lib import artifacts
from lib.beautify_apply import apply_beautify_suggestions
from lib.beautify_critic import HeuristicCritic
from lib.beautify_metrics import compute_gameplay_metrics
from lib.contracts import StageStatus
from lib.crs import to_store
from lib.determinism import content_hash, gameplay_territory_id, territory_id
from lib.io import artifact_hash_input, read_json, write_geojson, write_json
from lib.publish_gameplay import PublishGameplayError, publish_gameplay
from lib.registry import discover_stages


def _square_feature(ctx, *, slug: str, minx: float, miny: float, size: float, **props):
    """Axis-aligned square in work CRS, stored as EPSG:4326."""
    crs_work = ctx.region.crs_work
    crs_store = ctx.region.crs_store
    geom = box(minx, miny, minx + size, miny + size)
    store = to_store(geom, crs_work, crs_store)
    tid = str(gameplay_territory_id(ctx.region.city, ctx.region.area, slug))
    base = {
        "territory_id": tid,
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "kind": "block",
        "protected": False,
        "area_m2": float(geom.area),
        "member_territory_ids": [tid],
        "member_count": 1,
        "layer": "gameplay",
    }
    base.update(props)
    return {
        "type": "Feature",
        "geometry": mapping(store),
        "properties": base,
    }


def _write_beautify_inputs(ctx, features):
    write_geojson(
        artifacts.GAMEPLAY_CANDIDATES.path(ctx),
        features,
        pipeline={"status": "ok", "stage": "cluster_gameplay"},
    )
    write_json(
        artifacts.GAMEPLAY_VALIDATION_REPORT.path(ctx),
        {
            "status": "pass",
            "stage": "cluster_gameplay",
            "hard": {"passed": True, "failures": []},
            "metrics": {"feature_count": len(features)},
        },
    )
    # Minimal separators (no motorway) so barrier checks stay quiet.
    write_geojson(
        artifacts.SEPARATORS.path(ctx),
        [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[77.57, 12.91], [77.58, 12.92]],
                },
                "properties": {
                    "source": "test",
                    "group": "highway",
                    "class": "residential",
                },
            }
        ],
        pipeline={"status": "ok", "stage": "extract_features"},
    )


def _write_review_inputs(ctx, features):
    write_geojson(
        artifacts.GAMEPLAY_BEAUTIFIED.path(ctx),
        features,
        pipeline={"status": "ok", "stage": "beautify_gameplay"},
    )
    write_json(
        artifacts.GAMEPLAY_BEAUTIFY_VALIDATION_REPORT.path(ctx),
        {
            "status": "pass",
            "stage": "beautify_gameplay",
            "hard": {"passed": True, "failures": []},
            "metrics": {"feature_count": len(features)},
        },
    )
    write_json(
        artifacts.BEAUTIFY_APPLY_REPORT.path(ctx),
        {"input_count": len(features), "output_count": len(features), "applied": []},
    )


def test_metrics_square_compactness_is_pi_over_4(ctx):
    # Axis-aligned square → isoperimetric quotient = π/4 ≈ 0.785
    features = [
        _square_feature(ctx, slug="square", minx=500_000, miny=1_430_000, size=1000)
    ]
    metrics = compute_gameplay_metrics(features, ctx)
    assert len(metrics) == 1
    assert abs(metrics[0]["compactness"] - (math.pi / 4)) < 0.01


def test_metrics_peninsula_low_compactness(ctx):
    # Long thin rectangle → low isoperimetric quotient
    features = [
        _square_feature(
            ctx, slug="peninsula", minx=500_000, miny=1_430_000, size=100
        )
    ]
    # Replace with thin L-ish via wide+short box already low; use 50x2000
    crs_work = ctx.region.crs_work
    crs_store = ctx.region.crs_store
    geom = box(500_000, 1_430_000, 500_050, 1_432_000)
    tid = str(gameplay_territory_id(ctx.region.city, ctx.region.area, "peninsula"))
    features = [
        {
            "type": "Feature",
            "geometry": mapping(to_store(geom, crs_work, crs_store)),
            "properties": {
                "territory_id": tid,
                "slug": "peninsula",
                "name": "Peninsula",
                "kind": "block",
                "protected": False,
                "area_m2": float(geom.area),
                "member_territory_ids": [tid],
                "member_count": 1,
                "layer": "gameplay",
            },
        }
    ]
    metrics = compute_gameplay_metrics(features, ctx)
    assert metrics[0]["compactness"] < 0.2


def test_critic_peninsula_skips_protected_neighbour(ctx):
    """Longest border may be a protected prize; absorb into fabric instead."""
    # Spindly territory sits above the ordinary floor; its fabric neighbour is
    # smaller so a+b still fits under hard_max (two floor-sized cells cannot).
    floor = float(ctx.thresholds.gameplay.soft_min_m2)
    metrics = [
        {
            "territory_id": "a",
            "name": "Spindly Fabric",
            "kind": "block",
            "protected": False,
            "area_m2": floor + 10_000,
            "compactness": 0.10,
            "convexity": 0.40,
            "boundary_complexity": 2.0,
            "neighbours": [
                {"territory_id": "prot", "shared_border_m": 5000},
                {"territory_id": "b", "shared_border_m": 2600},
            ],
        },
        {
            "territory_id": "prot",
            "name": "Lalbagh",
            "kind": "park",
            "protected": True,
            "area_m2": 900_000,
            "compactness": 0.6,
            "convexity": 0.9,
            "boundary_complexity": 1.0,
            "neighbours": [{"territory_id": "a", "shared_border_m": 5000}],
        },
        {
            "territory_id": "b",
            "name": "Neighbour Block",
            "kind": "block",
            "protected": False,
            "area_m2": 200_000,
            "compactness": 0.5,
            "convexity": 0.8,
            "boundary_complexity": 1.1,
            "neighbours": [{"territory_id": "a", "shared_border_m": 2600}],
        },
    ]
    suggestions = HeuristicCritic().suggest(
        metrics, gp=ctx.thresholds.gameplay, bt=ctx.thresholds.beautify
    )
    actionable = [
        s
        for s in suggestions
        if s["op"] in {"absorb_peninsula", "merge"}
        and set(s["territory_ids"]) == {"a", "b"}
    ]
    assert actionable, suggestions
    assert actionable[0]["confidence"] >= 0.85
    # Must not propose merging the spindly fabric into the protected prize.
    assert all("prot" not in s["territory_ids"] for s in actionable)


def test_apply_merge_reduces_count(ctx, monkeypatch):
    monkeypatch.setattr(
        "lib.validate.validate_gameplay_features",
        lambda ctx, features, parcel_features=None, strict_shape=False: {
            "status": "pass",
            "hard": {"passed": True, "failures": []},
            "metrics": {"feature_count": len(features)},
        },
    )
    fabric = _square_feature(
        ctx, slug="fabric-a", minx=500_000, miny=1_430_000, size=600
    )
    park = _square_feature(
        ctx,
        slug="tiny-park",
        minx=500_600,
        miny=1_430_000,
        size=200,
        kind="park",
        name="Tiny Park",
    )
    features = [fabric, park]
    suggestions = [
        {
            "id": "sug-0001",
            "op": "merge",
            "territory_ids": sorted(
                [
                    fabric["properties"]["territory_id"],
                    park["properties"]["territory_id"],
                ]
            ),
            "reason": "test",
            "confidence": 0.97,
            "metrics_refs": ["area_m2"],
        }
    ]
    result = apply_beautify_suggestions(ctx, features, suggestions, separators=[])
    assert result.report.output_count == 1
    assert len(result.report.applied) == 1


def test_apply_refuses_merge_above_ordinary_hard_max(ctx, monkeypatch):
    monkeypatch.setattr(
        "lib.validate.validate_gameplay_features",
        lambda ctx, features, parcel_features=None, strict_shape=False: {
            "status": "pass",
            "hard": {"passed": True, "failures": []},
            "metrics": {"feature_count": len(features)},
        },
    )
    left = _square_feature(
        ctx, slug="large-west", minx=500_000, miny=1_430_000, size=1100
    )
    right = _square_feature(
        ctx, slug="large-east", minx=501_100, miny=1_430_000, size=1100
    )
    suggestion = {
        "id": "sug-0001",
        "op": "merge",
        "territory_ids": sorted(
            [
                left["properties"]["territory_id"],
                right["properties"]["territory_id"],
            ]
        ),
        "reason": "test",
        "confidence": 0.99,
        "metrics_refs": ["area_m2"],
    }
    result = apply_beautify_suggestions(
        ctx, [left, right], [suggestion], separators=[]
    )
    assert result.report.output_count == 2
    assert result.report.skipped[0]["reason"] == "exceeds_hard_max"


def test_apply_refuses_protected(ctx, monkeypatch):
    monkeypatch.setattr(
        "lib.validate.validate_gameplay_features",
        lambda ctx, features, parcel_features=None, strict_shape=False: {
            "status": "pass",
            "hard": {"passed": True, "failures": []},
            "metrics": {"feature_count": len(features)},
        },
    )
    fabric = _square_feature(
        ctx, slug="fabric-a", minx=500_000, miny=1_430_000, size=600
    )
    prize = _square_feature(
        ctx,
        slug="lalbagh",
        minx=500_600,
        miny=1_430_000,
        size=800,
        kind="park",
        name="Lalbagh",
        protected=True,
    )
    suggestions = [
        {
            "id": "sug-0001",
            "op": "merge",
            "territory_ids": sorted(
                [
                    fabric["properties"]["territory_id"],
                    prize["properties"]["territory_id"],
                ]
            ),
            "reason": "test",
            "confidence": 0.99,
            "metrics_refs": ["area_m2"],
        }
    ]
    result = apply_beautify_suggestions(ctx, [fabric, prize], suggestions, separators=[])
    assert result.report.output_count == 2
    assert any(s.get("reason") == "protected_merge_refused" for s in result.report.skipped)


def test_apply_refuses_motorway_barrier(ctx, monkeypatch):
    monkeypatch.setattr(
        "lib.validate.validate_gameplay_features",
        lambda ctx, features, parcel_features=None, strict_shape=False: {
            "status": "pass",
            "hard": {"passed": True, "failures": []},
            "metrics": {"feature_count": len(features)},
        },
    )
    left = _square_feature(ctx, slug="west", minx=500_000, miny=1_430_000, size=500)
    right = _square_feature(ctx, slug="east", minx=500_500, miny=1_430_000, size=500)
    # Mid-line motorway between west/east squares
    import pyproj
    from shapely.geometry import LineString
    from shapely.geometry import mapping as geom_mapping
    from shapely.ops import transform

    project = pyproj.Transformer.from_crs(
        ctx.region.crs_work, ctx.region.crs_store, always_xy=True
    ).transform
    barrier_line = transform(
        project, LineString([(500_500, 1_430_000), (500_500, 1_430_500)])
    )
    separators = [
        {
            "type": "Feature",
            "geometry": geom_mapping(barrier_line),
            "properties": {"group": "highway", "class": "motorway"},
        }
    ]
    suggestions = [
        {
            "id": "sug-0001",
            "op": "merge",
            "territory_ids": sorted(
                [left["properties"]["territory_id"], right["properties"]["territory_id"]]
            ),
            "reason": "test",
            "confidence": 0.99,
            "metrics_refs": ["area_m2"],
        }
    ]
    result = apply_beautify_suggestions(
        ctx, [left, right], suggestions, separators=separators
    )
    assert result.report.output_count == 2
    assert any(s.get("reason") == "crosses_barrier" for s in result.report.skipped)


def test_apply_determinism(ctx, monkeypatch):
    monkeypatch.setattr(
        "lib.validate.validate_gameplay_features",
        lambda ctx, features, parcel_features=None, strict_shape=False: {
            "status": "pass",
            "hard": {"passed": True, "failures": []},
            "metrics": {"feature_count": len(features)},
        },
    )
    fabric = _square_feature(
        ctx, slug="fabric-a", minx=500_000, miny=1_430_000, size=600
    )
    park = _square_feature(
        ctx,
        slug="tiny-park",
        minx=500_600,
        miny=1_430_000,
        size=200,
        kind="park",
    )
    features = [fabric, park]
    metrics = compute_gameplay_metrics(features, ctx)
    suggestions = HeuristicCritic().suggest(
        metrics, gp=ctx.thresholds.gameplay, bt=ctx.thresholds.beautify
    )
    a = apply_beautify_suggestions(ctx, features, suggestions, separators=[])
    b = apply_beautify_suggestions(ctx, features, suggestions, separators=[])
    ha = content_hash(
        artifact_hash_input({"type": "FeatureCollection", "features": a.features})
    )
    hb = content_hash(
        artifact_hash_input({"type": "FeatureCollection", "features": b.features})
    )
    assert ha == hb


def test_stage11_writes_beautified(ctx, monkeypatch):
    monkeypatch.setattr(
        "lib.validate.validate_gameplay_features",
        lambda ctx, features, parcel_features=None, strict_shape=False: {
            "status": "pass",
            "hard": {"passed": True, "failures": []},
            "metrics": {"feature_count": len(features)},
        },
    )
    features = [
        _square_feature(ctx, slug="solo", minx=500_000, miny=1_430_000, size=1000)
    ]
    _write_beautify_inputs(ctx, features)
    stage = next(s for s in discover_stages() if s.number == 11)
    assert stage.name == "beautify_gameplay"
    result = stage.run(ctx)
    assert result.status is StageStatus.OK
    assert artifacts.GAMEPLAY_BEAUTIFIED.path(ctx).exists()
    assert artifacts.BEAUTIFY_SUGGESTIONS.path(ctx).exists()
    assert artifacts.GAMEPLAY_METRICS.path(ctx).exists()


def _lalbagh_feature(ctx):
    ring = [
        [77.58, 12.94],
        [77.59, 12.94],
        [77.59, 12.95],
        [77.58, 12.95],
        [77.58, 12.94],
    ]
    tid = str(
        territory_id(ctx.region.city, ctx.region.area, "lalbagh-botanical-gardens")
    )
    return {
        "type": "Feature",
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": [[ring]],
        },
        "properties": {
            "territory_id": tid,
            "slug": "lalbagh-botanical-gardens",
            "name": "Lalbagh Botanical Gardens",
            "kind": "park",
            "protected": True,
            "role": "major",
            "area_m2": 900000.0,
            "member_territory_ids": [],
            "member_count": 1,
            "layer": "gameplay",
        },
    }


def test_stage12_blocked_without_approval(ctx):
    features = [_lalbagh_feature(ctx)]
    _write_review_inputs(ctx, features)
    stage = next(s for s in discover_stages() if s.number == 12)
    result = stage.run(ctx)
    assert result.status is StageStatus.BLOCKED
    assert not artifacts.GAMEPLAY_REVIEW.path(ctx).exists()


def test_stage12_writes_review_ack(ctx):
    features = [_lalbagh_feature(ctx)]
    _write_review_inputs(ctx, features)
    artifacts.GAMEPLAY_APPROVED.path(ctx).write_text("ok\n", encoding="utf-8")
    stage = next(s for s in discover_stages() if s.number == 12)
    result = stage.run(ctx)
    assert result.status is StageStatus.OK
    review = read_json(artifacts.GAMEPLAY_REVIEW.path(ctx))
    assert review["status"] == "approved"
    assert review["feature_count"] == len(features)


def test_stage13_exact_copy(ctx):
    features = [_lalbagh_feature(ctx)]
    _write_review_inputs(ctx, features)
    artifacts.GAMEPLAY_APPROVED.path(ctx).write_text("ok\n", encoding="utf-8")
    next(s for s in discover_stages() if s.number == 12).run(ctx)
    result = publish_gameplay(ctx)
    assert result.territory_count == 1
    assert result.candidate_hash == result.published_hash
    published = read_json(artifacts.PUBLISHED_GAMEPLAY_TERRITORIES.path(ctx))
    assert content_hash(artifact_hash_input(published)) == result.published_hash


def test_stage13_refuses_failed_validation(ctx):
    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [
                        [
                            [77.58, 12.94],
                            [77.59, 12.94],
                            [77.59, 12.95],
                            [77.58, 12.95],
                            [77.58, 12.94],
                        ]
                    ]
                ],
            },
            "properties": {
                "territory_id": "x",
                "slug": "x",
                "name": "X",
                "kind": "block",
                "protected": False,
                "area_m2": 1.0,
                "member_territory_ids": [],
                "member_count": 0,
                "layer": "gameplay",
            },
        }
    ]
    _write_review_inputs(ctx, features)
    write_json(
        artifacts.GAMEPLAY_BEAUTIFY_VALIDATION_REPORT.path(ctx),
        {"status": "fail", "hard": {"passed": False, "failures": [{"check": "gap"}]}},
    )
    write_json(artifacts.GAMEPLAY_REVIEW.path(ctx), {"status": "approved"})
    try:
        publish_gameplay(ctx)
        raised = False
    except PublishGameplayError:
        raised = True
    assert raised
