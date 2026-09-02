"""Publish approved beautified gameplay territories (stage 13).

Copies `staging/gameplay_beautified.geojson` into `published/` without geometry
edits. Mirrors Stage 09 parcel publish semantics for the gameplay layer.
"""

from __future__ import annotations

import os
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lib import artifacts
from lib.contracts import PipelineContext
from lib.determinism import content_hash
from lib.io import artifact_hash_input, feature_collection, is_placeholder, read_json

_IDENTITY_KEYS = (
    "territory_id",
    "slug",
    "name",
    "kind",
    "protected",
    "legendary",
    "landmark_dedicated",
    "territory_class",
    "role",
    "needs_review",
    "area_m2",
    "member_territory_ids",
    "member_count",
    "layer",
)


class PublishGameplayError(RuntimeError):
    """Stage 13 cannot publish safely."""


@dataclass(frozen=True)
class PublishGameplayResult:
    territories_path: Path
    manifest_path: Path
    territory_count: int
    protected_count: int
    candidate_hash: str
    published_hash: str


def publish_gameplay(ctx: PipelineContext) -> PublishGameplayResult:
    beautified_path = artifacts.GAMEPLAY_BEAUTIFIED.path(ctx)
    report_path = artifacts.GAMEPLAY_BEAUTIFY_VALIDATION_REPORT.path(ctx)
    review_path = artifacts.GAMEPLAY_REVIEW.path(ctx)

    if not beautified_path.exists():
        raise PublishGameplayError(f"Stage 13: missing {beautified_path}")
    if is_placeholder(beautified_path):
        raise PublishGameplayError("Stage 13: gameplay beautified is a placeholder")
    if not report_path.exists():
        raise PublishGameplayError(f"Stage 13: missing validation report at {report_path}")
    if not review_path.exists():
        raise PublishGameplayError(f"Stage 13: missing gameplay review ack at {review_path}")

    report = read_json(report_path)
    if report.get("status") != "pass" or not (report.get("hard") or {}).get("passed", False):
        raise PublishGameplayError(
            "Stage 13: beautify validation is not a hard pass; refusing to publish"
        )
    review = read_json(review_path)
    if review.get("status") != "approved":
        raise PublishGameplayError("Stage 13: gameplay review is not approved")

    beautified = read_json(beautified_path)
    if beautified.get("type") != "FeatureCollection":
        raise PublishGameplayError("Stage 13: beautified is not a FeatureCollection")

    source_features = list(beautified.get("features") or [])
    published_features = _copy_features(source_features)
    _assert_identity_and_geometry_unchanged(source_features, published_features)

    source_hash = content_hash(artifact_hash_input(beautified))
    published_collection = feature_collection(
        published_features,
        pipeline={
            "status": "ok",
            "stage": "publish_gameplay",
            "artifact": "gameplay_territories",
            "published_from": str(beautified_path.relative_to(ctx.repo_root)),
            "source_validation": str(report_path.relative_to(ctx.repo_root)),
        },
    )
    published_hash = content_hash(artifact_hash_input(published_collection))
    if published_hash != source_hash:
        raise PublishGameplayError(
            "Stage 13: published feature hash differs from gameplay beautified"
        )

    protected_count = sum(
        1
        for f in published_features
        if (f.get("properties") or {}).get("protected") is True
    )

    parcel_hash = None
    parcel_path = artifacts.PUBLISHED_TERRITORIES.path(ctx)
    if parcel_path.exists():
        parcel_hash = content_hash(artifact_hash_input(read_json(parcel_path)))

    cluster_hash = None
    cluster_path = artifacts.GAMEPLAY_CANDIDATES.path(ctx)
    if cluster_path.exists():
        cluster_hash = content_hash(artifact_hash_input(read_json(cluster_path)))

    manifest = {
        "region": ctx.region.name,
        "city": ctx.region.city,
        "area": ctx.region.area,
        "layer": "gameplay",
        "territory_count": len(published_features),
        "protected_count": protected_count,
        "validation_status": "pass",
        "candidate_hash": source_hash,
        "beautified_hash": source_hash,
        "cluster_candidates_hash": cluster_hash,
        "published_hash": published_hash,
        "parcel_hash": parcel_hash,
    }

    out_territories = artifacts.PUBLISHED_GAMEPLAY_TERRITORIES.path(ctx)
    out_manifest = artifacts.GAMEPLAY_PUBLISH_MANIFEST.path(ctx)
    ctx.published_dir.mkdir(parents=True, exist_ok=True)

    tmp_territories = _atomic_write_json(out_territories, published_collection)
    tmp_manifest = _atomic_write_json(out_manifest, manifest)
    os.replace(tmp_territories, out_territories)
    os.replace(tmp_manifest, out_manifest)

    on_disk = read_json(out_territories)
    disk_hash = content_hash(artifact_hash_input(on_disk))
    if disk_hash != source_hash:
        raise PublishGameplayError(
            "Stage 13: on-disk published hash does not match gameplay beautified"
        )

    return PublishGameplayResult(
        territories_path=out_territories,
        manifest_path=out_manifest,
        territory_count=len(published_features),
        protected_count=protected_count,
        candidate_hash=source_hash,
        published_hash=published_hash,
    )


def _copy_features(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    for feature in features:
        geom = feature.get("geometry")
        props = feature.get("properties") or {}
        copied.append(
            {
                "type": "Feature",
                "geometry": deepcopy(geom) if geom is not None else None,
                "properties": dict(props),
            }
        )
    return copied


def _assert_identity_and_geometry_unchanged(
    source: list[dict[str, Any]], published: list[dict[str, Any]]
) -> None:
    if len(source) != len(published):
        raise PublishGameplayError("Stage 13: feature count changed during copy")
    for i, (src, dst) in enumerate(zip(source, published, strict=True)):
        if content_hash(src.get("geometry")) != content_hash(dst.get("geometry")):
            raise PublishGameplayError(f"Stage 13: geometry hash changed for feature[{i}]")
        src_props = src.get("properties") or {}
        dst_props = dst.get("properties") or {}
        for key in _IDENTITY_KEYS:
            if src_props.get(key) != dst_props.get(key):
                raise PublishGameplayError(
                    f"Stage 13: identity field {key!r} changed for feature[{i}]"
                )


def _atomic_write_json(final_path: Path, payload: Any) -> Path:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{final_path.name}.",
        suffix=".tmp",
        dir=str(final_path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        import json

        text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        return tmp_path
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        tmp_path.unlink(missing_ok=True)
        raise
