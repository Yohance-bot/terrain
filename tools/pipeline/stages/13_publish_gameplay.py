"""Stage 13 -- publish approved beautified gameplay territories.

CONTRACT
========

Requires: `staging/gameplay_beautified.geojson`,
          `staging/gameplay_beautify_validation_report.json`,
          `staging/gameplay_review.json`.
Produces: `published/gameplay_territories.geojson`,
          `published/gameplay_publish_manifest.json`.

Exact copy of gameplay_beautified. No geometry edits. Atomic temp→rename.
"""

from __future__ import annotations

from lib import artifacts
from lib.contracts import PipelineContext, StageResult, StageStatus, assert_requires
from lib.publish_gameplay import PublishGameplayError, publish_gameplay

NUMBER = 13
NAME = "publish_gameplay"

REQUIRES = (
    artifacts.GAMEPLAY_BEAUTIFIED,
    artifacts.GAMEPLAY_BEAUTIFY_VALIDATION_REPORT,
    artifacts.GAMEPLAY_REVIEW,
)
PRODUCES = (
    artifacts.PUBLISHED_GAMEPLAY_TERRITORIES,
    artifacts.GAMEPLAY_PUBLISH_MANIFEST,
)


def run(ctx: PipelineContext) -> StageResult:
    assert_requires(NAME, REQUIRES, ctx)

    try:
        result = publish_gameplay(ctx)
    except PublishGameplayError:
        raise

    message = (
        f"published {result.territory_count} gameplay territories "
        f"(protected={result.protected_count}, "
        f"hash={result.published_hash[:12]}…)"
    )
    return StageResult(
        stage=NAME,
        status=StageStatus.OK,
        written=[result.territories_path, result.manifest_path],
        message=message,
    )
