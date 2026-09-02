"""Stage 12 -- human review gate for beautified gameplay.

CONTRACT
========

Requires: `staging/gameplay_beautified.geojson`,
          `staging/gameplay_beautify_validation_report.json`,
          `staging/beautify_apply_report.json`.
Gates on: `staging/GAMEPLAY_APPROVED` (human-created).
Produces: `staging/gameplay_review.json`.

When the gate is missing this stage returns BLOCKED. Parcel APPROVED and
GAMEPLAY_APPROVED are independent so reality and playability can be signed
off separately.
"""

from __future__ import annotations

from lib import artifacts
from lib.contracts import PipelineContext, StageResult, StageStatus, assert_requires
from lib.determinism import content_hash
from lib.io import artifact_hash_input, is_placeholder, read_json, write_json

NUMBER = 12
NAME = "gameplay_review"

REQUIRES = (
    artifacts.GAMEPLAY_BEAUTIFIED,
    artifacts.GAMEPLAY_BEAUTIFY_VALIDATION_REPORT,
    artifacts.BEAUTIFY_APPLY_REPORT,
)
PRODUCES = (artifacts.GAMEPLAY_REVIEW,)
GATES = (artifacts.GAMEPLAY_APPROVED,)


def run(ctx: PipelineContext) -> StageResult:
    assert_requires(NAME, REQUIRES, ctx)

    missing_gates = [gate for gate in GATES if not gate.path(ctx).exists()]
    if missing_gates:
        paths = ", ".join(str(gate.path(ctx)) for gate in missing_gates)
        return StageResult(
            stage=NAME,
            status=StageStatus.BLOCKED,
            message=(
                f"waiting for gameplay approval. Review "
                f"{artifacts.GAMEPLAY_BEAUTIFIED.path(ctx)} and "
                f"{artifacts.BEAUTIFY_APPLY_REPORT.path(ctx)}, then create: {paths}"
            ),
        )

    beautified_path = artifacts.GAMEPLAY_BEAUTIFIED.path(ctx)
    report_path = artifacts.GAMEPLAY_BEAUTIFY_VALIDATION_REPORT.path(ctx)
    if is_placeholder(beautified_path):
        raise RuntimeError("Stage 12: gameplay beautified is a placeholder")

    validation = read_json(report_path)
    if validation.get("status") != "pass" or not (validation.get("hard") or {}).get(
        "passed", False
    ):
        raise RuntimeError(
            "Stage 12: beautify validation is not a hard pass; refusing review ack"
        )

    beautified = read_json(beautified_path)
    payload = {
        "status": "approved",
        "stage": NAME,
        "region": ctx.region.name,
        "city": ctx.region.city,
        "area": ctx.region.area,
        "feature_count": len(beautified.get("features") or []),
        "beautified_hash": content_hash(artifact_hash_input(beautified)),
        "validation_status": "pass",
    }
    out = artifacts.GAMEPLAY_REVIEW.path(ctx)
    write_json(out, payload)
    return StageResult(
        stage=NAME,
        status=StageStatus.OK,
        written=[out],
        message=f"gameplay review ack written ({payload['feature_count']} territories)",
    )
