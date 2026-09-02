"""Stage 09 -- turn approved candidates into published territory data.

CONTRACT
========

Requires: `staging/candidates.geojson`, `staging/validation_report.json`.
Gates on: `staging/APPROVED`, which only a human creates.
Produces: `published/publish_manifest.json`.

Also writes (sidecar, not in PRODUCES): `published/territories.geojson` — an
exact copy of staging candidates. No geometry edits, no id regeneration, no
CRS change, no PostGIS in this milestone slice.

The approval gate
-----------------
`APPROVED` is deliberately not a stage output and not a flag. It is a file a
person creates after opening `candidates.geojson` against satellite imagery.
When absent this stage returns `StageStatus.BLOCKED` rather than failing.

Invariants
----------
- Refuse to publish if the validation report is not a hard pass, even when
  `APPROVED` exists.
- Copy features exactly; geometry and identity hashes must match candidates.
- Atomic temp→rename writes so a failed publish leaves prior published data.
- Deterministic: same staging input → same published and manifest hashes.
- PostGIS upsert and `data/territories/` export remain deferred (non-goals).
"""

from __future__ import annotations

from lib import artifacts
from lib import publish as publish_lib
from lib.contracts import PipelineContext, StageResult, StageStatus, assert_requires
from lib.publish import PublishError

NUMBER = 9
NAME = "publish"

REQUIRES = (artifacts.CANDIDATES, artifacts.VALIDATION_REPORT)
PRODUCES = (artifacts.PUBLISHED_TERRITORIES, artifacts.PUBLISH_MANIFEST,)

# Human-created gates, checked inside run() rather than by the orchestrator.
GATES = (artifacts.APPROVED,)


def run(ctx: PipelineContext) -> StageResult:
    assert_requires(NAME, REQUIRES, ctx)

    missing_gates = [gate for gate in GATES if not gate.path(ctx).exists()]
    if missing_gates:
        paths = ", ".join(str(gate.path(ctx)) for gate in missing_gates)
        return StageResult(
            stage=NAME,
            status=StageStatus.BLOCKED,
            message=(
                f"waiting for human approval. Review {artifacts.CANDIDATES.path(ctx)} "
                f"and {artifacts.VALIDATION_REPORT.path(ctx)}, then create: {paths}"
            ),
        )

    try:
        result = publish_lib.publish_candidates(ctx)
    except PublishError:
        raise

    message = (
        f"published {result.territory_count} territories "
        f"(protected={result.protected_count}, "
        f"hash={result.published_hash[:12]}…)"
    )
    return StageResult(
        stage=NAME,
        status=StageStatus.OK,
        written=[result.territories_path, result.manifest_path],
        message=message,
    )
