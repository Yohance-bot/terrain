"""Stage 03 -- extract named places, then classify which stay whole.

CONTRACT
========

Requires: `raw/download_manifest.json` (and the extracts it lists).
Produces: `intermediate/03_landmarks.geojson`.

What this stage does
--------------------
Two jobs in one artifact:

1. **Extract** every named park, lake, campus, pitch, cemetery and similar
   place from the source data into one FeatureCollection.
2. **Classify** each as `role: major | minor`. Only majors get
   `protected: true`. Stage 05 carves protected majors; minors keep name and
   geometry for Stage 07 naming hints but must not become standalone
   territories.

Final territory count is driven by polygonize + normalize (stages 05–06), not
by how many named places were extracted here. Expect majors in the single
digits to low teens for the Jayanagar→Lalbagh AOI, not ~100 protected faces.

Invariants Phase B must hold
----------------------------
- Every feature carries `role`, `protected` (= role is major), a `name`, and a
  `kind`. A landmark without a name is not a landmark -- it is anonymous
  fabric, and belongs in stage 05's face set instead.
- Dissolve overlapping and adjacent parts of the same named place into one
  polygon. Lalbagh is mapped in OSM as several adjoining polygons; publishing
  them separately gives players four territories where they see one park.
- Resolve overlaps between different landmarks deterministically -- larger area
  wins, ties broken by slug -- so that two runs never disagree about which of
  two overlapping campuses owns the contested strip.
- Measure any area filter (including `territory_min_area_m2`) in the
  working CRS via `lib.crs`, never on 4326 coordinates.
- Protected majors are exempt from fabric size rules in `thresholds.yaml`.
  Lalbagh is far larger than the fabric band and that is correct: it is one
  place. A named pocket park below `territory_min_area_m2` is minor and is
  not carved.

Non-goals
---------
No merging landmarks into fabric, no splitting, no size normalisation. No
hand-curated allowlist of majors -- classification is rule-based.

Notes for the author
--------------------
This stage is what makes the generated map feel like Bengaluru rather than a
grid. Milestone 1 proved the point by accident: the hand-drawn Lalbagh territory
read as a real place, while the Jayanagar blocks read as boxes. Getting major
parks and lakes out whole is the difference between a player thinking "I took
Lalbagh" and "I took polygon 47".

Validate majors by eye before moving on. Lalbagh, Sarakki Lake, Puttenahalli
Lake and similar must be major; playgrounds and small neighbourhood parks must
be minor. Milestone 1 hand-made data under
`data/territories/bengaluru/jayanagar/v1/` is a free correctness check.
"""

from __future__ import annotations

from lib import artifacts
from lib import landmarks as landmarks_lib
from lib.contracts import PipelineContext, StageResult, StageStatus, assert_requires
from lib.io import write_geojson

NUMBER = 3
NAME = "extract_landmarks"

REQUIRES = (artifacts.RAW_MANIFEST,)
PRODUCES = (artifacts.LANDMARKS,)


def run(ctx: PipelineContext) -> StageResult:
    assert_requires(NAME, REQUIRES, ctx)

    features = landmarks_lib.extract_landmarks(ctx)

    by_kind: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_role: dict[str, int] = {}
    for feature in features:
        props = feature.get("properties") or {}
        kind = str(props.get("kind") or "?")
        source = str(props.get("source") or "?")
        role = str(props.get("role") or "?")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1
        by_role[role] = by_role.get(role, 0) + 1

    names = sorted(
        str((f.get("properties") or {}).get("name") or "")
        for f in features
        if (f.get("properties") or {}).get("name")
    )
    has_lalbagh = any("lalbagh" in n.lower() for n in names)
    major_count = by_role.get("major", 0)
    minor_count = by_role.get("minor", 0)

    path = write_geojson(
        artifacts.LANDMARKS.path(ctx),
        features,
        pipeline={
            "status": "ok",
            "stage": NAME,
            "feature_count": len(features),
            "major_count": major_count,
            "minor_count": minor_count,
            "by_role": by_role,
            "by_kind": by_kind,
            "by_source": by_source,
            "lalbagh_present": has_lalbagh,
        },
    )

    message = (
        f"{len(features)} landmarks "
        f"(major={major_count}, minor={minor_count}, "
        f"kinds={by_kind}, sources={by_source}, "
        f"lalbagh={'yes' if has_lalbagh else 'NO'})"
    )
    return StageResult(
        stage=NAME,
        status=StageStatus.OK,
        written=[path],
        message=message,
    )
