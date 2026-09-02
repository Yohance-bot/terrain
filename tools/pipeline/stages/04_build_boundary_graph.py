"""Stage 04 -- turn separator lines into a planar, fully-noded graph.

CONTRACT
========

Requires: `intermediate/02_separators.geojson`.
Produces: `intermediate/04_boundary_graph.geojson`.

What this stage does
--------------------
Splits every separator at every intersection with every other separator, snaps
endpoints that are within `thresholds.snap_m` of each other, and writes the
result in the working CRS.

Does not re-add landmark rings -- Stage 02 already emitted `area_boundary`
outers; majors are carved in Stage 05, not drawn as graph edges here.

Invariants Phase B must hold
----------------------------
- Reproject to `ctx.region.crs_work` first. `snap_m` is 3 metres; applied to
  degrees it would be a snap radius of roughly 330 kilometres.
- Node everything. Two roads that cross without a shared vertex are, to a
  polygonizer, two lines that do not touch -- and the face between them leaks
  into its neighbour. `shapely.ops.unary_union` over the full line set is the
  standard way to get this.
- Snap conservatively. Too large a radius collapses genuinely distinct
  junctions and merges streets that should divide territories; too small leaves
  the leaks that noding was meant to fix. Start at the configured 3 m and tune
  against the output of stage 05, not against this stage.
- Drop dangles -- line ends that close no face. They cannot contribute a border
  and they slow polygonization down considerably.
- Output must be deterministic. Union and noding operations return geometry in
  whatever order the underlying library produced it; sort on a stable key
  (first-vertex coordinate tuple works) before writing.
- Record the working CRS in `pipeline` foreign members so stage 05 knows the
  coordinates are metres, not degrees.

Non-goals
---------
No polygons yet, no landmark handling, no naming. Preferring one source when
Overture and OSM duplicate a corridor is a later optimization -- noding collapses
coincident lines for M2.

Notes for the author
--------------------
When stage 05 returns one enormous face covering the whole AOI, the bug is
almost always here: a gap in the noded network let the interior connect to the
exterior. Rendering this stage's output and looking for the leak is faster than
debugging the polygonizer.
"""

from __future__ import annotations

from lib import artifacts
from lib import graph as graph_lib
from lib.contracts import PipelineContext, StageResult, StageStatus, assert_requires
from lib.io import write_geojson

NUMBER = 4
NAME = "build_boundary_graph"

REQUIRES = (artifacts.SEPARATORS,)
PRODUCES = (artifacts.BOUNDARY_GRAPH,)


def run(ctx: PipelineContext) -> StageResult:
    assert_requires(NAME, REQUIRES, ctx)

    features = graph_lib.build_boundary_graph(ctx)
    total_length_m = 0.0
    for feature in features:
        coords = feature["geometry"]["coordinates"]
        # Length in working CRS is metres; sum segment lengths for the log.
        for i in range(len(coords) - 1):
            x0, y0 = coords[i][0], coords[i][1]
            x1, y1 = coords[i + 1][0], coords[i + 1][1]
            total_length_m += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5

    path = write_geojson(
        artifacts.BOUNDARY_GRAPH.path(ctx),
        features,
        pipeline={
            "status": "ok",
            "stage": NAME,
            "crs": ctx.region.crs_work,
            "snap_m": ctx.thresholds.snap_m,
            "feature_count": len(features),
            "total_length_m": round(total_length_m, 3),
        },
    )

    return StageResult(
        stage=NAME,
        status=StageStatus.OK,
        written=[path],
        message=(
            f"{len(features)} noded edges in {ctx.region.crs_work} "
            f"(snap_m={ctx.thresholds.snap_m}, length_m={total_length_m:.0f})"
        ),
    )
