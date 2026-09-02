"""Stage 10 -- barrier-aware agglomerative clustering into gameplay territories.

CONTRACT
========

Requires: `published/territories.geojson` (Stage 09 parcels),
          `intermediate/02_separators.geojson` (class-aware barriers).
Produces: `staging/gameplay_candidates.geojson`,
          `staging/gameplay_cluster_report.json`,
          `staging/gameplay_validation_report.json`.

Invariants
----------
- Never mutates Stage 09 parcels.
- Protected landmarks pass through with identical geometry and territory_id.
- Merges only along shared borders that are not major barriers.
- Fail closed on hard validation (gap/overlap/coverage/protected freeze).
- Deterministic: same parcels + separators + thresholds → same output.
"""

from __future__ import annotations

from lib import artifacts
from lib import cluster as cluster_lib
from lib import validate as validate_lib
from lib.contracts import PipelineContext, StageResult, StageStatus, assert_requires
from lib.io import read_geojson, write_geojson, write_json
from lib.validate import ValidationFailedError

NUMBER = 10
NAME = "cluster_gameplay"

REQUIRES = (artifacts.PUBLISHED_TERRITORIES, artifacts.SEPARATORS)
PRODUCES = (
    artifacts.GAMEPLAY_CANDIDATES,
    artifacts.GAMEPLAY_CLUSTER_REPORT,
    artifacts.GAMEPLAY_VALIDATION_REPORT,
)


def run(ctx: PipelineContext) -> StageResult:
    assert_requires(NAME, REQUIRES, ctx)

    try:
        result = cluster_lib.cluster_parcels(ctx)
    except cluster_lib.ClusterError:
        raise

    parcels = list(
        read_geojson(artifacts.PUBLISHED_TERRITORIES.path(ctx)).get("features") or []
    )
    validation = validate_lib.validate_gameplay_features(
        ctx, result.features, parcel_features=parcels
    )
    report_path = artifacts.GAMEPLAY_CLUSTER_REPORT.path(ctx)
    validation_path = artifacts.GAMEPLAY_VALIDATION_REPORT.path(ctx)
    write_json(report_path, cluster_lib.report_to_dict(result.report))
    write_json(validation_path, validation)

    if not validation.get("hard", {}).get("passed", False):
        raise ValidationFailedError(
            f"Stage 10: gameplay validation failed; see {validation_path}"
        )

    candidates_path = artifacts.GAMEPLAY_CANDIDATES.path(ctx)
    write_geojson(
        candidates_path,
        result.features,
        pipeline={
            "status": "ok",
            "stage": NAME,
            "artifact": "gameplay_candidates",
            "input_count": result.report.input_count,
            "output_count": result.report.output_count,
            "merges": result.report.merges,
            "parcel_hash": result.report.parcel_hash,
            "separators_hash": result.report.separators_hash,
        },
    )

    message = (
        f"clustered {result.report.input_count} parcels → "
        f"{result.report.output_count} gameplay "
        f"(merges={result.report.merges}, "
        f"protected={result.report.protected_count}, "
        f"needs_review={result.report.needs_review_count})"
    )
    return StageResult(
        stage=NAME,
        status=StageStatus.OK,
        written=[candidates_path, report_path, validation_path],
        message=message,
    )
