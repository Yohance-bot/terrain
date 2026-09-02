"""Stage 09 publish: exact copy of staging candidates into published/."""

from __future__ import annotations

from copy import deepcopy

import pytest

from lib import artifacts
from lib.contracts import StageStatus
from lib.determinism import content_hash, territory_id
from lib.io import artifact_hash_input, is_placeholder, read_json, write_geojson, write_json
from lib.publish import PublishError, publish_candidates, territories_path
from lib.registry import discover_stages


def _stage09():
    return next(s for s in discover_stages() if s.number == 9)


def _sample_features(ctx):
    tid = str(territory_id(ctx.region.city, ctx.region.area, "lalbagh-botanical-gardens"))
    return [
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
                "territory_id": tid,
                "slug": "lalbagh-botanical-gardens",
                "name": "Lalbagh Botanical Gardens",
                "kind": "park",
                "protected": True,
                "role": "major",
                "needs_review": False,
                "area_m2": 900000.0,
            },
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [
                        [
                            [77.57, 12.91],
                            [77.58, 12.91],
                            [77.58, 12.92],
                            [77.57, 12.92],
                            [77.57, 12.91],
                        ]
                    ]
                ],
            },
            "properties": {
                "territory_id": str(
                    territory_id(ctx.region.city, ctx.region.area, "west-fabric")
                ),
                "slug": "west-fabric",
                "name": "West Fabric",
                "kind": "block",
                "protected": False,
                "needs_review": True,
                "area_m2": 50000.0,
            },
        },
    ]


def _write_pass_staging(ctx, features=None):
    features = features if features is not None else _sample_features(ctx)
    write_geojson(
        artifacts.CANDIDATES.path(ctx),
        features,
        pipeline={"status": "ok", "stage": "validate", "artifact": "candidates"},
    )
    write_json(
        artifacts.VALIDATION_REPORT.path(ctx),
        {
            "status": "pass",
            "stage": "validate",
            "hard": {"passed": True, "failures": []},
            "metrics": {"feature_count": len(features), "protected_count": 1},
        },
    )
    artifacts.APPROVED.path(ctx).write_text("reviewed by test\n", encoding="utf-8")
    return features


def test_happy_path_writes_published_artifacts(ctx):
    _write_pass_staging(ctx)
    result = _stage09().run(ctx)
    assert result.status is StageStatus.OK
    assert territories_path(ctx).exists()
    assert artifacts.PUBLISH_MANIFEST.path(ctx).exists()
    assert not is_placeholder(artifacts.PUBLISH_MANIFEST.path(ctx))
    data = read_json(territories_path(ctx))
    assert data["pipeline"]["status"] == "ok"
    assert len(data["features"]) == 2
    manifest = read_json(artifacts.PUBLISH_MANIFEST.path(ctx))
    assert manifest["validation_status"] == "pass"
    assert manifest["territory_count"] == 2
    assert manifest["protected_count"] == 1
    assert manifest["candidate_hash"] == manifest["published_hash"]


def test_missing_candidates_fails(ctx):
    from lib.contracts import MissingArtifactError

    write_json(
        artifacts.VALIDATION_REPORT.path(ctx),
        {"status": "pass", "hard": {"passed": True, "failures": []}},
    )
    artifacts.APPROVED.path(ctx).write_text("ok\n", encoding="utf-8")
    # Orchestrator/REQUIRES check fires before publish_candidates.
    with pytest.raises(MissingArtifactError, match="candidates"):
        _stage09().run(ctx)
    assert not territories_path(ctx).exists()
    assert not artifacts.PUBLISH_MANIFEST.path(ctx).exists()

    # Direct helper also refuses.
    with pytest.raises(PublishError, match="missing"):
        publish_candidates(ctx)


def test_geometry_corruption_during_copy_detected(ctx, monkeypatch):
    _write_pass_staging(ctx)

    def corrupt_copy(features):
        out = deepcopy(features)
        # Nudge a coordinate so geometry hash changes.
        out[0]["geometry"]["coordinates"][0][0][0][0] += 0.001
        return out

    monkeypatch.setattr("lib.publish._copy_features", corrupt_copy)
    with pytest.raises(PublishError, match="geometry hash|feature hash"):
        publish_candidates(ctx)
    assert not territories_path(ctx).exists()


def test_identity_preserved(ctx):
    features = _write_pass_staging(ctx)
    _stage09().run(ctx)
    published = read_json(territories_path(ctx))["features"]
    for src, dst in zip(features, published, strict=True):
        for key in (
            "territory_id",
            "slug",
            "name",
            "kind",
            "protected",
            "needs_review",
            "area_m2",
        ):
            assert src["properties"].get(key) == dst["properties"].get(key)
        assert content_hash(src["geometry"]) == content_hash(dst["geometry"])


def test_determinism_two_publishes(ctx):
    _write_pass_staging(ctx)
    _stage09().run(ctx)
    first_t = artifact_hash_input(read_json(territories_path(ctx)))
    first_m = content_hash(read_json(artifacts.PUBLISH_MANIFEST.path(ctx)))
    _stage09().run(ctx)
    second_t = artifact_hash_input(read_json(territories_path(ctx)))
    second_m = content_hash(read_json(artifacts.PUBLISH_MANIFEST.path(ctx)))
    assert first_t == second_t
    assert first_m == second_m


def test_published_geometry_hash_equals_candidates(ctx):
    features = _write_pass_staging(ctx)
    _stage09().run(ctx)
    published = read_json(territories_path(ctx))
    candidates = read_json(artifacts.CANDIDATES.path(ctx))
    assert artifact_hash_input(published) == artifact_hash_input(candidates)
    for src, dst in zip(features, published["features"], strict=True):
        assert content_hash(src["geometry"]) == content_hash(dst["geometry"])


def test_blocked_without_approval(ctx):
    _write_pass_staging(ctx)
    artifacts.APPROVED.path(ctx).unlink()
    result = _stage09().run(ctx)
    assert result.status is StageStatus.BLOCKED
    assert not territories_path(ctx).exists()


def test_refuses_failed_validation_report(ctx):
    features = _sample_features(ctx)
    write_geojson(
        artifacts.CANDIDATES.path(ctx),
        features,
        pipeline={"status": "ok", "stage": "validate"},
    )
    write_json(
        artifacts.VALIDATION_REPORT.path(ctx),
        {"status": "fail", "hard": {"passed": False, "failures": [{"check": "gap"}]}},
    )
    artifacts.APPROVED.path(ctx).write_text("ok\n", encoding="utf-8")
    with pytest.raises(PublishError, match="hard pass"):
        _stage09().run(ctx)
