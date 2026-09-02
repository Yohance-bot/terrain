"""Stage 08 — Validate.

Contract: docs/09_TERRITORY_GENERATION_PIPELINE.md § Stages table + Review.

Hard checks fail closed: write validation_report.json, do not write
candidates.geojson, raise ValidationFailedError. Soft findings never block.
No geometry repair in this stage.

Known-exceptions mechanism (opt-in, off by default)
-----------------------------------------------------
When `ctx.allow_validation_exceptions` is on (region config
`allow_validation_exceptions: true`, or `run_pipeline.py
--allow-known-validation-exceptions`), Stage 08 consults a fixed, reviewed
`config/regions/{region}.exceptions.json` slug list. A "names" failure whose
slug is in that list is excluded entirely from candidates -- not given a
fake name, not silently passed -- and recorded under
`validation_report.json["excluded_known_exceptions"]`, separate from
`hard.failures` and `soft.needs_review`. Off by default, this changes
nothing for any region that does not opt in.
"""

from __future__ import annotations

from lib import artifacts
from lib import validate as validate_lib
from lib.contracts import PipelineContext, StageResult, StageStatus
from lib.io import write_geojson, write_json
from lib.validate import ValidationFailedError

NUMBER = 8
NAME = "validate"
REQUIRES = (artifacts.NAMED,)
PRODUCES = (artifacts.CANDIDATES, artifacts.VALIDATION_REPORT)


def run(ctx: PipelineContext) -> StageResult:
    result = validate_lib.validate_named(ctx)
    write_json(artifacts.VALIDATION_REPORT.path(ctx), result.report)

    metrics = result.report["metrics"]
    soft = result.report["soft"]
    excluded = result.report.get("excluded_known_exceptions")
    summary = (
        f"features={metrics['feature_count']} protected={metrics['protected_count']} "
        f"coverage={metrics['coverage_ratio']:.6f} gap_m2={metrics['gap_m2']:.3f} "
        f"overlap_m2={metrics['overlap_m2']:.3f} needs_review={soft['needs_review_count']} "
        f"fingerprint={result.fingerprint_path.name}"
    )
    if excluded is not None:
        summary += f" excluded_known_exceptions={excluded['count']}"

    if not result.passed:
        checks = sorted({f["check"] for f in result.failures})
        raise ValidationFailedError(
            f"Stage 08 validation failed [{', '.join(checks)}]; "
            f"report written, candidates withheld. {summary}"
        )

    assert result.candidates is not None
    write_geojson(
        artifacts.CANDIDATES.path(ctx),
        result.candidates,
        pipeline={"status": "ok", "stage": NAME, "artifact": artifacts.CANDIDATES.key},
    )
    return StageResult(
        stage=NAME,
        status=StageStatus.OK,
        written=[
            artifacts.CANDIDATES.path(ctx),
            artifacts.VALIDATION_REPORT.path(ctx),
        ],
        message=f"validation passed; {summary}",
    )
