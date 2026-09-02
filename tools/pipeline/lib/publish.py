"""Publish validated staging candidates (stage 09).

Copies `staging/candidates.geojson` into `published/` without geometry edits,
identity regeneration, or CRS changes. Atomic temp→rename writes. PostGIS and
`data/territories/` export remain deferred.
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
    "role",
    "needs_review",
    "area_m2",
)


class PublishError(RuntimeError):
    """Stage 09 cannot publish safely."""


@dataclass(frozen=True)
class PublishResult:
    territories_path: Path
    manifest_path: Path
    territory_count: int
    protected_count: int
    candidate_hash: str
    published_hash: str


def territories_path(ctx: PipelineContext) -> Path:
    return artifacts.PUBLISHED_TERRITORIES.path(ctx)


def publish_candidates(ctx: PipelineContext) -> PublishResult:
    """Copy staging candidates to published/; verify hashes; write manifest."""
    candidates_path = artifacts.CANDIDATES.path(ctx)
    report_path = artifacts.VALIDATION_REPORT.path(ctx)

    if not candidates_path.exists():
        raise PublishError(
            f"Stage 09: missing {candidates_path} — Stage 08 must pass before publish"
        )
    if is_placeholder(candidates_path):
        raise PublishError("Stage 09: candidates are a placeholder, not a real pass")
    if not report_path.exists():
        raise PublishError(f"Stage 09: missing validation report at {report_path}")

    report = read_json(report_path)
    if report.get("status") != "pass" or not (report.get("hard") or {}).get("passed", False):
        raise PublishError(
            "Stage 09: validation report is not a hard pass; refusing to publish"
        )

    candidates = read_json(candidates_path)
    if candidates.get("type") != "FeatureCollection":
        raise PublishError("Stage 09: candidates is not a FeatureCollection")

    source_features = list(candidates.get("features") or [])
    published_features = _copy_features(source_features)
    _assert_identity_and_geometry_unchanged(source_features, published_features)

    candidate_hash = content_hash(artifact_hash_input(candidates))
    published_collection = feature_collection(
        published_features,
        pipeline={
            "status": "ok",
            "stage": "publish",
            "artifact": "territories",
            "published_from": str(candidates_path.relative_to(ctx.repo_root)),
            "source_validation": str(report_path.relative_to(ctx.repo_root)),
        },
    )
    published_hash = content_hash(artifact_hash_input(published_collection))
    if published_hash != candidate_hash:
        raise PublishError(
            "Stage 09: published feature hash differs from candidates "
            "(geometry or properties were altered during copy)"
        )

    protected_count = sum(
        1
        for f in published_features
        if (f.get("properties") or {}).get("protected") is True
    )

    manifest = {
        "region": ctx.region.name,
        "city": ctx.region.city,
        "area": ctx.region.area,
        "territory_count": len(published_features),
        "protected_count": protected_count,
        "validation_status": "pass",
        "candidate_hash": candidate_hash,
        "published_hash": published_hash,
    }

    out_territories = territories_path(ctx)
    out_manifest = artifacts.PUBLISH_MANIFEST.path(ctx)
    ctx.published_dir.mkdir(parents=True, exist_ok=True)

    # Write both temps first, then rename — avoids a half-published pair when
    # the process dies mid-write. Cross-file atomicity is best-effort.
    tmp_territories = _atomic_write_json(out_territories, published_collection)
    tmp_manifest = _atomic_write_json(out_manifest, manifest)
    os.replace(tmp_territories, out_territories)
    os.replace(tmp_manifest, out_manifest)

    # Re-read published artifact and confirm hash still matches (disk truth).
    on_disk = read_json(out_territories)
    disk_hash = content_hash(artifact_hash_input(on_disk))
    if disk_hash != candidate_hash:
        raise PublishError(
            "Stage 09: on-disk published hash does not match candidates"
        )

    return PublishResult(
        territories_path=out_territories,
        manifest_path=out_manifest,
        territory_count=len(published_features),
        protected_count=protected_count,
        candidate_hash=candidate_hash,
        published_hash=published_hash,
    )


def _copy_features(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deep-copy features without reordering or mutating geometry/identity."""
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
        raise PublishError("Stage 09: feature count changed during copy")
    for i, (src, dst) in enumerate(zip(source, published, strict=True)):
        src_geom = src.get("geometry")
        dst_geom = dst.get("geometry")
        if content_hash(src_geom) != content_hash(dst_geom):
            raise PublishError(
                f"Stage 09: geometry hash changed for feature[{i}]"
            )
        src_props = src.get("properties") or {}
        dst_props = dst.get("properties") or {}
        for key in _IDENTITY_KEYS:
            if src_props.get(key) != dst_props.get(key):
                raise PublishError(
                    f"Stage 09: identity field {key!r} changed for feature[{i}]"
                )


def _atomic_write_json(final_path: Path, payload: Any) -> Path:
    """Write payload to a temp file beside the destination; return temp path."""
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
