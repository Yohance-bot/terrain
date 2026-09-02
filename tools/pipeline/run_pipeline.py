#!/usr/bin/env python3
"""Territory generation pipeline orchestrator.

Runs stages 01 through 13 in order for one region, checking before each stage
that its declared inputs exist and after each stage that its declared outputs
were written.

Those two checks are the reason this file exists. Stages passing files between
each other by convention breaks quietly: a stage that fails halfway leaves a
stale artifact behind, the next stage reads it, and the error surfaces four
stages later as a strange-looking map. Asserting the contract at every
boundary turns that into an immediate, named failure.

Usage
-----
    uv run python run_pipeline.py --list
    uv run python run_pipeline.py --region bengaluru_jayanagar_lalbagh
    uv run python run_pipeline.py --region bengaluru_jayanagar_lalbagh --from-stage 4 --to-stage 6
    uv run python run_pipeline.py --region bengaluru_jayanagar_lalbagh --dry-run

Stage 09 reports `blocked` until a human creates `staging/APPROVED` (parcels).
Stage 12 reports `blocked` until `staging/GAMEPLAY_APPROVED` exists.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.config import (  # noqa: E402
    ConfigError,
    available_regions,
    load_feature_classes,
    load_region,
    load_thresholds,
)
from lib.contracts import (  # noqa: E402
    MissingArtifactError,
    PipelineContext,
    StageResult,
    StageStatus,
    assert_produces,
    assert_requires,
)
from lib.registry import LoadedStage, StageLoadError, discover_stages, select_stages  # noqa: E402
from lib.validate import ValidationFailedError  # noqa: E402

_STATUS_LABEL = {
    StageStatus.OK: "ok",
    StageStatus.NOT_IMPLEMENTED: "stub",
    StageStatus.BLOCKED: "blocked",
}


def build_context(
    region_name: str,
    force: bool = False,
    dry_run: bool = False,
    allow_known_validation_exceptions: bool = False,
) -> PipelineContext:
    region = load_region(region_name)
    return PipelineContext(
        region=region,
        thresholds=load_thresholds(),
        feature_classes=load_feature_classes(),
        force=force,
        dry_run=dry_run,
        # Either source turns it on; the CLI flag never has to be paired with
        # a config edit for a one-off run, and a config edit never has to be
        # paired with remembering the flag.
        allow_validation_exceptions=(
            region.allow_validation_exceptions or allow_known_validation_exceptions
        ),
    )


def run_stage(stage: LoadedStage, ctx: PipelineContext) -> StageResult:
    """Run one stage with its input and output contracts enforced.

    Stage 01 is exempt from the input check only because its input is the
    config, not a file.
    """
    if stage.number > 1:
        assert_requires(stage.name, stage.requires, ctx)

    result = stage.run(ctx)

    # A blocked stage has not written its outputs, and that is correct -- it is
    # waiting on a human, not claiming to have finished.
    if result.status is not StageStatus.BLOCKED:
        assert_produces(stage.name, stage.produces, ctx)

    return result


def run_pipeline(
    ctx: PipelineContext,
    from_stage: int | None = None,
    to_stage: int | None = None,
    echo: bool = True,
) -> list[StageResult]:
    stages = select_stages(discover_stages(), from_stage, to_stage)
    ctx.ensure_dirs()
    results: list[StageResult] = []

    for stage in stages:
        label = f"{stage.number:02d} {stage.name}"
        if ctx.dry_run:
            if echo:
                print(f"[--] {label}: dry run, not executed")
                for spec in stage.produces:
                    print(f"       would write {spec.path(ctx)}")
            continue

        started = time.monotonic()
        result = run_stage(stage, ctx)
        results.append(result)
        elapsed = time.monotonic() - started

        if echo:
            print(f"[{_STATUS_LABEL[result.status]:>7}] {label}  ({elapsed:.2f}s)")
            if result.message:
                print(f"          {result.message}")
            for path in result.written:
                print(f"          wrote {path.relative_to(ctx.repo_root)}")

        if result.status is StageStatus.BLOCKED:
            if echo:
                print(f"\nStopped at stage {stage.number:02d}. Nothing after it can run yet.")
            break

    return results


def _print_summary(ctx: PipelineContext, results: list[StageResult]) -> None:
    stubs = [r for r in results if r.status is StageStatus.NOT_IMPLEMENTED]
    blocked = [r for r in results if r.status is StageStatus.BLOCKED]

    print()
    if stubs:
        print(
            f"{len(stubs)} of {len(results)} stages are still Phase A stubs "
            f"({', '.join(r.stage for r in stubs)})."
        )
        print("Their output files are placeholders and must not be reviewed or published.")
    if blocked:
        print(f"Blocked: {blocked[-1].message}")
    if not stubs and not blocked:
        print(f"Pipeline complete. Artifacts under {ctx.region_root.relative_to(ctx.repo_root)}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate territories for one region.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--region", help="Region config stem, e.g. bengaluru_jayanagar_lalbagh")
    parser.add_argument("--from-stage", type=int, default=None, help="First stage to run (1-13)")
    parser.add_argument("--to-stage", type=int, default=None, help="Last stage to run (1-13)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redo work even when a valid artifact already exists (re-downloads sources)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan and the paths without running anything",
    )
    parser.add_argument(
        "--allow-known-validation-exceptions",
        action="store_true",
        help=(
            "Stage 08: exclude the region's fixed, reviewed list of known 'names' "
            "failures (config/regions/{region}.exceptions.json) from candidates "
            "instead of hard-failing on them. Off by default; equivalent to "
            "setting allow_validation_exceptions: true in the region YAML."
        ),
    )
    parser.add_argument("--list", action="store_true", help="List available regions and stages")
    args = parser.parse_args(argv)

    try:
        if args.list:
            print("Regions:")
            for name in available_regions():
                print(f"  {name}")
            print("\nStages:")
            for stage in discover_stages():
                print(f"  {stage.number:02d}  {stage.name}")
            return 0

        if not args.region:
            parser.error("--region is required (or use --list)")

        ctx = build_context(
            args.region,
            force=args.force,
            dry_run=args.dry_run,
            allow_known_validation_exceptions=args.allow_known_validation_exceptions,
        )
        print(
            f"Region {ctx.region.name}: {ctx.region.city}/{ctx.region.area} "
            f"bbox={ctx.region.bbox.as_tuple()} work_crs={ctx.region.crs_work}"
        )
        results = run_pipeline(ctx, args.from_stage, args.to_stage)
        if not args.dry_run:
            _print_summary(ctx, results)
        return 0

    except (
        ConfigError,
        StageLoadError,
        MissingArtifactError,
        ValidationFailedError,
        ValueError,
    ) as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
