"""Reading and writing pipeline artifacts.

Every write goes through here so that output is canonical: sorted keys, a
trailing newline, UTF-8, and features sorted on an explicit key. Determinism is
a property of the whole pipeline, and it only holds if no stage takes a
shortcut with `json.dump`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.artifacts import ArtifactSpec
from lib.contracts import ArtifactFormat, PipelineContext
from lib.determinism import canonical_json


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> Path:
    """Canonical JSON write.

    Pretty-printed with sorted keys rather than minified: these files are read
    by humans during review and diffed in pull requests, and a one-line file
    makes both useless. `canonical_json` is still what hashing uses.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def read_geojson(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if data.get("type") != "FeatureCollection":
        raise ValueError(f"{path}: expected a GeoJSON FeatureCollection, got {data.get('type')!r}")
    return data


def feature_collection(features: list[dict[str, Any]], **members: Any) -> dict[str, Any]:
    """Build a FeatureCollection with optional foreign members.

    Foreign members are how each stage records what produced a file -- source
    checksums, stage name, thresholds in effect -- without inventing a sidecar
    file per artifact.
    """
    return {"type": "FeatureCollection", "features": features, **members}


def write_geojson(path: Path, features: list[dict[str, Any]], **members: Any) -> Path:
    return write_json(path, feature_collection(features, **members))


def artifact_hash_input(collection: dict[str, Any]) -> str:
    """Canonical string for a FeatureCollection, ignoring provenance members.

    Comparing two runs should compare the geometry and properties, not the
    timestamp of the run. Anything under `pipeline` is provenance and is
    excluded.
    """
    return canonical_json({k: v for k, v in collection.items() if k != "pipeline"})


def write_placeholder(spec: ArtifactSpec, ctx: PipelineContext, stage_name: str) -> Path:
    """Write an empty-but-well-formed artifact for an unimplemented stage.

    Phase A ships stages that produce nothing real. Rather than have the
    orchestrator special-case them, each stub writes a valid file carrying
    `status: not_implemented`. The chain is then runnable end to end from day
    one, which is what makes the orchestrator and the contract tests meaningful
    before a single line of GIS code exists.

    Phase B deletes the call to this function; it does not delete the artifact.
    """
    path = spec.path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    provenance = {"status": "not_implemented", "stage": stage_name, "artifact": spec.key}

    if spec.format is ArtifactFormat.GEOJSON:
        write_geojson(path, [], pipeline=provenance)
    elif spec.format is ArtifactFormat.JSON:
        write_json(path, provenance)
    elif spec.format is ArtifactFormat.MARKER:
        # Markers are human-created gates. A stage writing one would defeat the
        # point, so this is a programming error rather than a placeholder case.
        raise ValueError(f"{spec.key} is a marker artifact and must not be written by a stage")
    else:
        # pbf/gpkg placeholders have no meaningful empty form; an empty file is
        # enough for the orchestrator's existence check.
        path.write_bytes(b"")
    return path


def is_placeholder(path: Path) -> bool:
    """True if a file is Phase A scaffolding rather than real output.

    Lets the validation stage and the tests distinguish 'this stage produced
    nothing because the AOI is empty' from 'this stage has not been written
    yet' -- two situations that look identical on disk otherwise.
    """
    if not path.exists() or path.suffix not in {".json", ".geojson"}:
        return False
    try:
        data = read_json(path)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    marker = data.get("pipeline", data)
    return isinstance(marker, dict) and marker.get("status") == "not_implemented"
