"""Stage 06 -- make anonymous street fabric a sensible size to run in.

CONTRACT
========

Requires: `intermediate/05_faces.geojson`.
Produces: `intermediate/06_normalized.geojson`.

What this stage does
--------------------
Merges scraps into neighbours and flags oversized anonymous fabric, so that a
normal run interacts with roughly one to two territories. Protected landmarks
(stage 03 majors only) pass through untouched. Soft band thresholds are
diagnostics only -- this stage does not chase them with forced merges or
splits.

Invariants Phase B must hold
----------------------------
- A protected landmark is never merged, never split, never resized, never
  repaired. Invalid protected input fails the stage.
- Fabric scraps below `thresholds.scrap_m2` merge into a fabric neighbour that
  shares at least `min_shared_border_m` (5 m) of border. Among eligible
  neighbours: longest shared border, then shortest centroid distance, then
  stable face id. Centroid alone never qualifies a non-touching neighbour.
  Scraps never merge into protected landmarks.
- Merges go through `safe_merge_geometry`: unary_union, optional make_valid,
  polygonal-only, area conserved within `validation.max_gap_m2`. Failed merges
  leave originals and flag the scrap `needs_review`.
- Every output geometry is valid Polygon/MultiPolygon or the stage fails
  without writing.
- Input union vs output union is reported as a Stage-06 conservation
  diagnostic (not AOI coverage). AOI gaps belong to Stage 05 / Stage 08.
- Soft fabric bands are diagnostics only; oversized fabric gets `needs_review`.

Non-goals
---------
No naming, no publishing, no gameplay parameters. No splitting of oversized
fabric in M2.
"""

from __future__ import annotations

import warnings

from lib import artifacts
from lib import normalize as normalize_lib
from lib.contracts import PipelineContext, StageResult, StageStatus, assert_requires
from lib.io import write_geojson
from lib.normalize import NormalizeError

NUMBER = 6
NAME = "normalize_sizes"

REQUIRES = (artifacts.FACES,)
PRODUCES = (artifacts.NORMALIZED,)


def run(ctx: PipelineContext) -> StageResult:
    assert_requires(NAME, REQUIRES, ctx)

    try:
        features, stats = normalize_lib.normalize_faces(ctx)
    except NormalizeError:
        raise

    max_gap = float(ctx.thresholds.validation.max_gap_m2)
    if stats.union_delta_m2 > max_gap:
        warnings.warn(
            f"Stage 06 area conservation: |input_union - output_union| = "
            f"{stats.union_delta_m2:.3f} m² exceeds max_gap_m2={max_gap} "
            f"(input_union={stats.input_union_area_m2:.3f}, "
            f"output_union={stats.output_union_area_m2:.3f}). "
            "This is Stage-06 face conservation, not AOI coverage.",
            stacklevel=2,
        )

    aoi_cov = stats.aoi_coverage_ratio
    aoi_cov_rounded = None if aoi_cov is None else round(aoi_cov, 9)

    path = write_geojson(
        artifacts.NORMALIZED.path(ctx),
        features,
        pipeline={
            "status": "ok",
            "stage": NAME,
            "crs_work": ctx.region.crs_work,
            "crs_store": ctx.region.crs_store,
            "input_face_count": stats.input_face_count,
            "feature_count": stats.output_face_count,
            "protected_count": stats.protected_count,
            "fabric_count": stats.fabric_count,
            "scrap_merges": stats.scrap_merges,
            "orphan_scraps": stats.orphan_scraps,
            "needs_review_count": stats.needs_review_count,
            "below_soft_min": stats.below_soft_min,
            "in_soft_band": stats.in_soft_band,
            "above_soft_max": stats.above_soft_max,
            "above_review_max": stats.above_review_max,
            "area_min_m2": round(stats.area_min_m2, 3),
            "area_max_m2": round(stats.area_max_m2, 3),
            "area_mean_m2": round(stats.area_mean_m2, 3),
            "area_total_m2": round(stats.area_total_m2, 3),
            "input_area_total_m2": round(stats.input_area_total_m2, 3),
            "scrap_m2": ctx.thresholds.scrap_m2,
            "fabric_soft_min_m2": ctx.thresholds.fabric_soft_min_m2,
            "fabric_soft_max_m2": ctx.thresholds.fabric_soft_max_m2,
            "fabric_review_max_m2": ctx.thresholds.fabric_review_max_m2,
            "min_shared_border_m": 5.0,
            "invalid_merge_attempts": stats.invalid_merge_attempts,
            "make_valid_repairs": stats.make_valid_repairs,
            "failed_geometry_repairs": stats.failed_geometry_repairs,
            "area_loss_rejections": stats.area_loss_rejections,
            "fabric_input_repairs": stats.fabric_input_repairs,
            "input_union_area_m2": round(stats.input_union_area_m2, 3),
            "output_union_area_m2": round(stats.output_union_area_m2, 3),
            "union_delta_m2": round(stats.union_delta_m2, 6),
            "aoi_coverage_ratio_diagnostic": aoi_cov_rounded,
            "merge_failures": list(stats.merge_failures),
        },
    )

    message = (
        f"{stats.input_face_count}->{stats.output_face_count} faces "
        f"(protected={stats.protected_count}, fabric={stats.fabric_count}, "
        f"merges={stats.scrap_merges}, orphans={stats.orphan_scraps}, "
        f"review={stats.needs_review_count}, "
        f"union_delta_m2={stats.union_delta_m2:.3f}, "
        f"invalid_merges={stats.invalid_merge_attempts}, "
        f"soft_band={stats.in_soft_band}, "
        f"mean_m2={stats.area_mean_m2:.0f})"
    )
    return StageResult(
        stage=NAME,
        status=StageStatus.OK,
        written=[path],
        message=message,
    )
