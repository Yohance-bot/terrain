"""Stage 02 -- select the linework allowed to become territory borders.

CONTRACT
========

Requires: `raw/download_manifest.json` (and the extracts it lists).
Produces: `intermediate/02_separators.geojson`.

What this stage does
--------------------
Reads the raw extracts, keeps only features whose class appears in the `include`
section of `highway_classes.yaml`, drops everything in `exclude`, clips the
result to the AOI bbox, and writes it as lines.

Invariants Phase B must hold
----------------------------
- The include/exclude lists in config are the only authority. Do not hardcode a
  class here. Border rules are the thing most likely to need tuning after the
  first human review, and tuning must be a config edit.
- Exclusion beats inclusion. A `highway=residential` tagged `service=driveway`
  is excluded. Getting this backwards fills the map with borders drawn down
  apartment driveways.
- Emit the OUTER RING of `area_boundary` features as lines, not the polygons.
  A park's edge is a border; its interior is not, and stage 03 handles the
  interior.
- Clip to `ctx.region.bbox`, expanded by a small margin. Lines cut exactly at
  the bbox leave the outermost faces open, and polygonization silently drops
  open faces -- a hole around the entire AOI edge.
- Carry a `source` property (`overture` or `osm`) and the original class on
  every feature. Reviewers will ask why a border is where it is, and without
  provenance the only answer is to re-run the stage by hand.
- Sort features on a stable key before writing (see `lib.determinism.stable_sort`).

Non-goals
---------
No noding, no snapping, no polygon building. That is stage 04.

Notes for the author
--------------------
The single highest-risk judgement in this pipeline lives in this stage. A border
following something people run along -- a park path, a promenade, a quiet lane --
invites border-hugging, where a player farms two territories at once by running
the line between them. `03_MAP_AND_TERRITORY_PIPELINE` is explicit that borders
must follow things people do not run along.
"""

from __future__ import annotations

from lib import artifacts
from lib import extract as extract_lib
from lib.contracts import PipelineContext, StageResult, StageStatus, assert_requires
from lib.io import write_geojson

NUMBER = 2
NAME = "extract_features"

REQUIRES = (artifacts.RAW_MANIFEST,)
PRODUCES = (artifacts.SEPARATORS,)


def run(ctx: PipelineContext) -> StageResult:
    assert_requires(NAME, REQUIRES, ctx)

    features = extract_lib.extract_separators(ctx)

    by_group: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for feature in features:
        props = feature.get("properties") or {}
        by_group[str(props.get("group") or "?")] = (
            by_group.get(str(props.get("group") or "?"), 0) + 1
        )
        by_source[str(props.get("source") or "?")] = (
            by_source.get(str(props.get("source") or "?"), 0) + 1
        )

    path = write_geojson(
        artifacts.SEPARATORS.path(ctx),
        features,
        pipeline={
            "status": "ok",
            "stage": NAME,
            "feature_count": len(features),
            "by_group": by_group,
            "by_source": by_source,
            "clip_margin_m": extract_lib.CLIP_MARGIN_M,
        },
    )

    message = (
        f"{len(features)} separators "
        f"(sources={by_source}, groups={by_group})"
    )
    return StageResult(
        stage=NAME,
        status=StageStatus.OK,
        written=[path],
        message=message,
    )
