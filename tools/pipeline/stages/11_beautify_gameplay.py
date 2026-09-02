"""Stage 11 -- gameplay beautification critic + GIS apply.

CONTRACT
========

Requires: `staging/gameplay_candidates.geojson`,
          `staging/gameplay_validation_report.json`,
          `staging/separators.geojson` (barrier checks).
Produces: `staging/gameplay_metrics.json`,
          `staging/beautify_suggestions.json`,
          `staging/beautify_apply_report.json`,
          `staging/gameplay_beautified.geojson`,
          `staging/gameplay_beautify_validation_report.json`.

Deterministic metrics + heuristic critic emit a restricted suggestion toolbox.
Only high-confidence merge / absorb_peninsula ops that pass GIS guards are
auto-applied. Soft flags go to Stage 12 human review. No freeform vertex edits.
"""

from __future__ import annotations

from lib import artifacts
from lib.beautify_apply import (
    BeautifyApplyError,
    apply_beautify_suggestions,
    apply_report_to_dict,
)
from lib.beautify_critic import get_critic
from lib.beautify_metrics import compute_gameplay_metrics
from lib.contracts import PipelineContext, StageResult, StageStatus, assert_requires
from lib.io import feature_collection, is_placeholder, read_geojson, read_json, write_json

NUMBER = 11
NAME = "beautify_gameplay"

REQUIRES = (
    artifacts.GAMEPLAY_CANDIDATES,
    artifacts.GAMEPLAY_VALIDATION_REPORT,
    artifacts.SEPARATORS,
)
PRODUCES = (
    artifacts.GAMEPLAY_METRICS,
    artifacts.BEAUTIFY_SUGGESTIONS,
    artifacts.BEAUTIFY_APPLY_REPORT,
    artifacts.GAMEPLAY_BEAUTIFIED,
    artifacts.GAMEPLAY_BEAUTIFY_VALIDATION_REPORT,
)


def run(ctx: PipelineContext) -> StageResult:
    assert_requires(NAME, REQUIRES, ctx)

    candidates_path = artifacts.GAMEPLAY_CANDIDATES.path(ctx)
    validation_path = artifacts.GAMEPLAY_VALIDATION_REPORT.path(ctx)
    if is_placeholder(candidates_path):
        raise RuntimeError("Stage 11: gameplay candidates are a placeholder")

    validation = read_json(validation_path)
    if validation.get("status") != "pass" or not (validation.get("hard") or {}).get(
        "passed", False
    ):
        raise RuntimeError(
            "Stage 11: gameplay validation is not a hard pass; refusing beautify"
        )

    candidates = read_geojson(candidates_path)
    features = list(candidates.get("features") or [])
    separators = read_geojson(artifacts.SEPARATORS.path(ctx))

    metrics = compute_gameplay_metrics(features, ctx)
    critic = get_critic(ctx.thresholds.beautify.critic)
    suggestions = critic.suggest(
        metrics,
        gp=ctx.thresholds.gameplay,
        bt=ctx.thresholds.beautify,
    )

    metrics_path = artifacts.GAMEPLAY_METRICS.path(ctx)
    suggestions_path = artifacts.BEAUTIFY_SUGGESTIONS.path(ctx)
    write_json(
        metrics_path,
        {
            "region": ctx.region.name,
            "territory_count": len(metrics),
            "metrics": metrics,
        },
    )
    write_json(
        suggestions_path,
        {
            "region": ctx.region.name,
            "critic": ctx.thresholds.beautify.critic,
            "suggestion_count": len(suggestions),
            "suggestions": suggestions,
        },
    )

    try:
        result = apply_beautify_suggestions(
            ctx, features, suggestions, separators=separators
        )
    except BeautifyApplyError:
        raise

    beautified_path = artifacts.GAMEPLAY_BEAUTIFIED.path(ctx)
    apply_path = artifacts.BEAUTIFY_APPLY_REPORT.path(ctx)
    beautify_val_path = artifacts.GAMEPLAY_BEAUTIFY_VALIDATION_REPORT.path(ctx)

    write_json(
        beautified_path,
        feature_collection(
            result.features,
            pipeline={
                "status": "ok",
                "stage": NAME,
                "artifact": "gameplay_beautified",
                "input_count": result.report.input_count,
                "output_count": result.report.output_count,
                "applied_count": len(result.report.applied),
            },
        ),
    )
    write_json(apply_path, apply_report_to_dict(result.report))
    write_json(beautify_val_path, result.validation)

    message = (
        f"beautified {result.report.input_count}→{result.report.output_count} "
        f"(applied={len(result.report.applied)}, "
        f"soft={len(result.report.soft_flags)}, "
        f"skipped={len(result.report.skipped)})"
    )
    return StageResult(
        stage=NAME,
        status=StageStatus.OK,
        written=[
            metrics_path,
            suggestions_path,
            apply_path,
            beautified_path,
            beautify_val_path,
        ],
        message=message,
    )
