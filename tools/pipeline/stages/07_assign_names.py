"""Stage 07 -- give every territory a name a local would recognise.

CONTRACT
========

Requires: `intermediate/06_normalized.geojson`.
Produces: `intermediate/07_named.geojson`.

What this stage does
--------------------
Assigns `name`, `slug`, `kind`, `territory_id` and `needs_review` to every
territory, using source data only.

Naming priority (in order, first match wins)
--------------------------------------------
1. Place or neighbourhood name from Overture divisions or OSM `place=*`, when
   the territory sits substantially inside one. "Jayanagar 4th Block".
2. Park, lake or landmark name, for protected features. "Lalbagh Botanical
   Garden". These come pre-named from stage 03 and pass straight through.
3. Street-pair fallback, from the two longest bounding separators:
   "Between 30th Main and Kanakapura Road".
4. No name, plus `needs_review: true`.

Protected landmarks skip step 1 so a neighbourhood never overwrites Lalbagh.

Invariants Phase B must hold
----------------------------
- No AI. Explicitly out of scope for this milestone. Names come from OSM and
  Overture attributes or from the deterministic street-pair rule, and nothing
  else. An LLM-invented place name is unfalsifiable and would put fiction into
  the game map.
- `territory_id` comes from `lib.determinism.territory_id(city, area, slug)` and
  from nothing else. Never hash geometry into the id -- redrawing a boundary
  would mint a new territory and orphan every ownership row pointing at the old
  one. That module's docstring explains the split.
- Slugs must be unique within the region. On collision, disambiguate
  deterministically (append a stable ordinal derived from sorted position), so
  that two runs assign the same suffix to the same polygon.
- `kind` uses the Milestone 1 vocabulary already present in
  `data/territories/bengaluru/jayanagar/v1/manifest.json`. The `corridor` kind
  from the design docs is deferred; do not introduce it here.
- Anything that reaches priority 3 or 4 gets `needs_review: true`. A street-pair
  name is a placeholder that happens to be readable, not a real name.

Non-goals
---------
No translation, no transliteration, no importance scoring, no gameplay
parameters such as influence capacity. Minor landmarks are not used as
territory display names in M2.

Notes for the author
--------------------
A territory's name is most of what makes players care about it. "Lalbagh" is
something to fight over; "Between 30th Main and Kanakapura Road" is a label. The
fallback exists so the pipeline never blocks on a missing name, not because it
is an acceptable outcome -- which is why it always sets the review flag.
"""

from __future__ import annotations

from lib import artifacts
from lib import naming as naming_lib
from lib.contracts import PipelineContext, StageResult, StageStatus, assert_requires
from lib.io import write_geojson

NUMBER = 7
NAME = "assign_names"

REQUIRES = (artifacts.NORMALIZED,)
PRODUCES = (artifacts.NAMED,)


def run(ctx: PipelineContext) -> StageResult:
    assert_requires(NAME, REQUIRES, ctx)

    features, stats = naming_lib.assign_names(ctx)

    if stats.unique_slugs != stats.feature_count:
        raise RuntimeError(
            f"stage {NAME}: slug collision survived uniquify "
            f"({stats.unique_slugs} unique / {stats.feature_count} features)"
        )
    if stats.unique_ids != stats.feature_count:
        raise RuntimeError(
            f"stage {NAME}: territory_id collision "
            f"({stats.unique_ids} unique / {stats.feature_count} features)"
        )

    path = write_geojson(
        artifacts.NAMED.path(ctx),
        features,
        pipeline={
            "status": "ok",
            "stage": NAME,
            "feature_count": stats.feature_count,
            "protected_count": stats.protected_count,
            "needs_review_count": stats.needs_review_count,
            "by_name_source": stats.by_name_source,
            "unique_slugs": stats.unique_slugs,
            "unique_ids": stats.unique_ids,
        },
    )

    message = (
        f"{stats.feature_count} territories "
        f"(sources={stats.by_name_source}, "
        f"protected={stats.protected_count}, "
        f"needs_review={stats.needs_review_count})"
    )
    return StageResult(
        stage=NAME,
        status=StageStatus.OK,
        written=[path],
        message=message,
    )
