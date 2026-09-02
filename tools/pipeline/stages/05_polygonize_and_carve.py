"""Stage 05 -- build the first exhaustive partition of the AOI.

CONTRACT
========

Requires: `intermediate/04_boundary_graph.geojson`, `intermediate/03_landmarks.geojson`.
Produces: `intermediate/05_faces.geojson`.

What this stage does
--------------------
Polygonizes the boundary graph into closed faces, then carves each protected
major landmark (`protected: true` / `role == major` from stage 03) out of
whatever faces it overlaps and reinserts it whole. Minor landmarks are not
carved -- they remain naming hints only. The result covers the AOI with no
gaps and no overlaps.

Every face is validated in the working CRS and again after a storage-CRS
round-trip before the artifact is written. Degenerate fabric
(`area <= face_area_epsilon_m2`) is dropped; invalid protected majors fail
the stage; fabric may be repaired once under polygonal + area-conservation
rules.

Invariants Phase B must hold
----------------------------
- Exhaustive cover. Every point in the AOI belongs to exactly one face.
- Carve only features with `protected: true` (majors).
- Landmarks are carved, never clipped; protected geometry is never repaired.
- Work in the working CRS throughout. Reproject to storage CRS only when writing.
- Sort faces on a stable key before writing.
- The written artifact itself must contain only valid, positive-area polygons.

Non-goals
---------
No size normalisation, no naming, no scrap merging.
"""

from __future__ import annotations

from lib import artifacts
from lib import faces as faces_lib
from lib.contracts import PipelineContext, StageResult, StageStatus, assert_requires
from lib.faces import FACE_AREA_EPSILON_M2, FaceBuildError
from lib.io import write_geojson

NUMBER = 5
NAME = "polygonize_and_carve"

REQUIRES = (artifacts.BOUNDARY_GRAPH, artifacts.LANDMARKS)
PRODUCES = (artifacts.FACES,)


def run(ctx: PipelineContext) -> StageResult:
    assert_requires(NAME, REQUIRES, ctx)

    try:
        features, stats = faces_lib.build_faces(ctx)
    except FaceBuildError:
        raise

    path = write_geojson(
        artifacts.FACES.path(ctx),
        features,
        pipeline={
            "status": "ok",
            "stage": NAME,
            "crs_work": ctx.region.crs_work,
            "crs_store": ctx.region.crs_store,
            "feature_count": stats.face_count,
            "protected_count": stats.protected_count,
            "fabric_count": stats.fabric_count,
            "area_min_m2": round(stats.area_min_m2, 3),
            "area_max_m2": round(stats.area_max_m2, 3),
            "area_mean_m2": round(stats.area_mean_m2, 3),
            "area_total_m2": round(stats.area_total_m2, 3),
            "aoi_area_m2": round(stats.aoi_area_m2, 3),
            "scrap_count": stats.scrap_count,
            "scrap_m2": ctx.thresholds.scrap_m2,
            "face_area_epsilon_m2": FACE_AREA_EPSILON_M2,
            "faces_generated": stats.faces_generated,
            "dropped_empty": stats.dropped_empty,
            "dropped_zero_area": stats.dropped_zero_area,
            "invalid_repaired": stats.invalid_repaired,
            "invalid_failed": stats.invalid_failed,
            "post_store_invalid": stats.post_store_invalid,
            "dropped_polygonize": stats.dropped_polygonize,
            "dropped_carve": stats.dropped_carve,
            "dropped_post_store": stats.dropped_post_store,
        },
    )

    message = (
        f"{stats.face_count} faces "
        f"(protected={stats.protected_count}, fabric={stats.fabric_count}, "
        f"mean_m2={stats.area_mean_m2:.0f}, "
        f"dropped_zero={stats.dropped_zero_area}, "
        f"post_store_invalid={stats.post_store_invalid}, "
        f"repaired={stats.invalid_repaired}, "
        f"scraps_lt_{ctx.thresholds.scrap_m2:.0f}={stats.scrap_count})"
    )
    return StageResult(
        stage=NAME,
        status=StageStatus.OK,
        written=[path],
        message=message,
    )
