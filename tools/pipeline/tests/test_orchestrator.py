"""The stage chain runs end to end and enforces its own contracts.

Stages 01–13 are implemented. Download / extract / landmark / graph / faces /
normalize / naming / validate / cluster I/O are stubbed via `stub_pipeline_io`
so the suite stays offline.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

import run_pipeline
from lib import artifacts
from lib.contracts import MissingArtifactError, StageStatus, assert_requires
from lib.io import is_placeholder, read_json
from lib.registry import discover_stages


def test_full_chain_runs_and_stops_at_parcel_approval(ctx, stub_pipeline_io):
    results = run_pipeline.run_pipeline(ctx, echo=False)

    assert len(results) == 9
    assert all(results[i].status is StageStatus.OK for i in range(8))
    # Stage 09 waits for parcel APPROVED.
    assert results[8].status is StageStatus.BLOCKED


def test_every_intermediate_artifact_is_written(ctx, stub_pipeline_io):
    run_pipeline.run_pipeline(ctx, echo=False)

    for spec in (
        artifacts.RAW_MANIFEST,
        artifacts.SEPARATORS,
        artifacts.LANDMARKS,
        artifacts.BOUNDARY_GRAPH,
        artifacts.FACES,
        artifacts.NORMALIZED,
        artifacts.NAMED,
        artifacts.CANDIDATES,
        artifacts.VALIDATION_REPORT,
    ):
        assert spec.path(ctx).exists(), f"{spec.key} was not written"


def test_stage01_manifest_is_not_a_placeholder(ctx, stub_pipeline_io):
    run_pipeline.run_pipeline(ctx, to_stage=1, echo=False)
    assert not is_placeholder(artifacts.RAW_MANIFEST.path(ctx))
    manifest = read_json(artifacts.RAW_MANIFEST.path(ctx))
    assert manifest["status"] == "ok"
    assert manifest["overture_release"]


def test_stage02_separators_are_not_a_placeholder(ctx, stub_pipeline_io):
    run_pipeline.run_pipeline(ctx, to_stage=2, echo=False)
    assert not is_placeholder(artifacts.SEPARATORS.path(ctx))
    data = read_json(artifacts.SEPARATORS.path(ctx))
    assert data["pipeline"]["status"] == "ok"
    assert len(data["features"]) >= 1


def test_stage03_landmarks_are_not_a_placeholder(ctx, stub_pipeline_io):
    run_pipeline.run_pipeline(ctx, to_stage=3, echo=False)
    assert not is_placeholder(artifacts.LANDMARKS.path(ctx))
    data = read_json(artifacts.LANDMARKS.path(ctx))
    assert data["pipeline"]["status"] == "ok"
    assert data["pipeline"]["lalbagh_present"] is True
    assert all(f["properties"]["role"] == "major" for f in data["features"])
    assert all(f["properties"]["protected"] is True for f in data["features"])


def test_stage04_boundary_graph_is_not_a_placeholder(ctx, stub_pipeline_io):
    run_pipeline.run_pipeline(ctx, to_stage=4, echo=False)
    assert not is_placeholder(artifacts.BOUNDARY_GRAPH.path(ctx))
    data = read_json(artifacts.BOUNDARY_GRAPH.path(ctx))
    assert data["pipeline"]["status"] == "ok"
    assert data["pipeline"]["crs"] == ctx.region.crs_work
    assert len(data["features"]) >= 1


def test_stage05_faces_are_not_a_placeholder(ctx, stub_pipeline_io):
    run_pipeline.run_pipeline(ctx, to_stage=5, echo=False)
    assert not is_placeholder(artifacts.FACES.path(ctx))
    data = read_json(artifacts.FACES.path(ctx))
    assert data["pipeline"]["status"] == "ok"
    assert data["pipeline"]["protected_count"] >= 1
    assert len(data["features"]) >= 1


def test_stage06_normalized_are_not_a_placeholder(ctx, stub_pipeline_io):
    run_pipeline.run_pipeline(ctx, to_stage=6, echo=False)
    assert not is_placeholder(artifacts.NORMALIZED.path(ctx))
    data = read_json(artifacts.NORMALIZED.path(ctx))
    assert data["pipeline"]["status"] == "ok"
    assert data["pipeline"]["protected_count"] >= 1
    assert len(data["features"]) >= 1


def test_stage07_named_are_not_a_placeholder(ctx, stub_pipeline_io):
    run_pipeline.run_pipeline(ctx, to_stage=7, echo=False)
    assert not is_placeholder(artifacts.NAMED.path(ctx))
    data = read_json(artifacts.NAMED.path(ctx))
    assert data["pipeline"]["status"] == "ok"
    assert data["pipeline"]["protected_count"] >= 1
    assert all("territory_id" in f["properties"] for f in data["features"])
    assert all("slug" in f["properties"] for f in data["features"])


def test_stage08_candidates_are_not_a_placeholder(ctx, stub_pipeline_io):
    run_pipeline.run_pipeline(ctx, to_stage=8, echo=False)
    assert not is_placeholder(artifacts.CANDIDATES.path(ctx))
    data = read_json(artifacts.CANDIDATES.path(ctx))
    assert data["pipeline"]["status"] == "ok"
    assert len(data["features"]) >= 1
    report = read_json(artifacts.VALIDATION_REPORT.path(ctx))
    assert report["status"] == "pass"


def test_publish_is_real_after_approval(ctx, stub_pipeline_io):
    """Stage 09 copies candidates into published/ once APPROVED exists."""
    run_pipeline.run_pipeline(ctx, echo=False)
    artifacts.APPROVED.path(ctx).write_text("reviewed by test\n", encoding="utf-8")
    results = run_pipeline.run_pipeline(ctx, from_stage=9, to_stage=9, echo=False)
    assert len(results) == 1
    assert results[0].status is StageStatus.OK
    assert not is_placeholder(artifacts.PUBLISH_MANIFEST.path(ctx))
    assert artifacts.PUBLISHED_TERRITORIES.path(ctx).exists()
    manifest = read_json(artifacts.PUBLISH_MANIFEST.path(ctx))
    assert manifest["validation_status"] == "pass"
    assert manifest["candidate_hash"] == manifest["published_hash"]


def test_publish_proceeds_once_a_human_approves(ctx, stub_pipeline_io):
    run_pipeline.run_pipeline(ctx, echo=False)
    artifacts.APPROVED.path(ctx).write_text("reviewed by test\n", encoding="utf-8")
    results = run_pipeline.run_pipeline(ctx, from_stage=9, to_stage=9, echo=False)
    assert len(results) == 1
    assert results[0].status is StageStatus.OK
    assert artifacts.PUBLISH_MANIFEST.path(ctx).exists()


def test_chain_stops_at_gameplay_approval_after_parcels(ctx, stub_pipeline_io):
    run_pipeline.run_pipeline(ctx, echo=False)
    artifacts.APPROVED.path(ctx).write_text("parcels ok\n", encoding="utf-8")
    results = run_pipeline.run_pipeline(ctx, from_stage=9, echo=False)
    # 09 publish, 10 cluster, 11 beautify, 12 blocked on GAMEPLAY_APPROVED
    assert len(results) == 4
    assert results[0].status is StageStatus.OK
    assert results[1].status is StageStatus.OK
    assert results[2].status is StageStatus.OK
    assert results[3].status is StageStatus.BLOCKED
    assert artifacts.GAMEPLAY_CANDIDATES.path(ctx).exists()
    assert artifacts.GAMEPLAY_BEAUTIFIED.path(ctx).exists()
    assert artifacts.GAMEPLAY_CLUSTER_REPORT.path(ctx).exists()


def test_gameplay_publish_after_both_approvals(ctx, stub_pipeline_io):
    run_pipeline.run_pipeline(ctx, echo=False)
    artifacts.APPROVED.path(ctx).write_text("parcels ok\n", encoding="utf-8")
    run_pipeline.run_pipeline(ctx, from_stage=9, echo=False)
    artifacts.GAMEPLAY_APPROVED.path(ctx).write_text("gameplay ok\n", encoding="utf-8")
    results = run_pipeline.run_pipeline(ctx, from_stage=12, echo=False)
    assert len(results) == 2
    assert results[0].status is StageStatus.OK
    assert results[1].status is StageStatus.OK
    assert artifacts.PUBLISHED_GAMEPLAY_TERRITORIES.path(ctx).exists()
    assert artifacts.GAMEPLAY_PUBLISH_MANIFEST.path(ctx).exists()
    manifest = read_json(artifacts.GAMEPLAY_PUBLISH_MANIFEST.path(ctx))
    assert manifest["layer"] == "gameplay"
    assert manifest["candidate_hash"] == manifest["published_hash"]


def test_a_stage_refuses_to_run_without_its_inputs(ctx):
    with pytest.raises(MissingArtifactError, match="missing required inputs"):
        run_pipeline.run_pipeline(ctx, from_stage=5, echo=False)


def test_stage_range_runs_only_the_requested_stages(ctx, stub_pipeline_io):
    run_pipeline.run_pipeline(ctx, to_stage=3, echo=False)
    assert artifacts.LANDMARKS.path(ctx).exists()
    assert not artifacts.BOUNDARY_GRAPH.path(ctx).exists()


def test_dry_run_writes_nothing(ctx):
    run_pipeline.run_pipeline(replace(ctx, dry_run=True), echo=False)
    assert not artifacts.RAW_MANIFEST.path(ctx).exists()


def test_assert_requires_names_the_missing_file(ctx):
    stage = next(s for s in discover_stages() if s.number == 5)
    with pytest.raises(MissingArtifactError) as excinfo:
        assert_requires(stage.name, stage.requires, ctx)
    assert "boundary_graph" in str(excinfo.value)


def test_cli_lists_regions_and_stages(capsys):
    assert run_pipeline.main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "bengaluru_jayanagar_lalbagh" in out
    assert "polygonize_and_carve" in out
    assert "cluster_gameplay" in out
    assert "beautify_gameplay" in out
    assert "publish_gameplay" in out


def test_cli_reports_an_unknown_region_without_a_traceback(capsys):
    assert run_pipeline.main(["--region", "atlantis"]) == 1
    assert "not found" in capsys.readouterr().err


def test_discover_stages_includes_10_through_13():
    numbers = [s.number for s in discover_stages()]
    assert numbers == list(range(1, 14))
