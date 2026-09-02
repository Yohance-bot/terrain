"""The interfaces every stage is written against.

This module is the contract between Phase A (this scaffold) and Phase B (the
GIS implementations). A stage author should be able to read their stage's
docstring plus this file and know exactly what they may touch.

The shape of a stage is deliberately boring: a module with four constants and a
`run` function. Not a class hierarchy, not a plugin system. The orchestrator
needs to know what a stage reads, what it writes, and how to call it -- and
nothing else, so that a stage can be rewritten from scratch without any other
file changing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from lib.config import FeatureClasses, RegionConfig, Thresholds

REPO_ROOT = Path(__file__).resolve().parents[3]


class ArtifactFormat(StrEnum):
    GEOJSON = "geojson"
    GPKG = "gpkg"
    JSON = "json"
    PBF = "pbf"
    # A file whose existence is the whole message; contents are irrelevant.
    # Used for the human `APPROVED` gate.
    MARKER = "marker"


@dataclass(frozen=True)
class ArtifactSpec:
    """One file the pipeline reads or writes.

    Paths are relative to the region's data root, so nothing in the pipeline
    ever hardcodes an absolute location and processing a second region is
    purely a config change.
    """

    key: str
    relative_path: str
    format: ArtifactFormat
    description: str

    def path(self, ctx: PipelineContext) -> Path:
        return ctx.region_root / self.relative_path


@dataclass(frozen=True)
class PipelineContext:
    """Everything a stage is allowed to know about the world.

    A stage that needs something not reachable from here is a stage that has
    grown a hidden dependency -- add it to the config and to this object rather
    than reading an environment variable or a global.
    """

    region: RegionConfig
    thresholds: Thresholds
    feature_classes: FeatureClasses
    repo_root: Path = REPO_ROOT
    force: bool = False
    dry_run: bool = False
    # Effective toggle for Stage 08's known-exceptions mechanism: the region
    # config's `allow_validation_exceptions` OR the CLI
    # `--allow-known-validation-exceptions` override. Kept on the context
    # (rather than read from `region` directly) so a one-off CLI override
    # never has to become a permanent config change.
    allow_validation_exceptions: bool = False

    @property
    def region_root(self) -> Path:
        return self.repo_root / "data" / "pipeline" / self.region.city / self.region.area

    @property
    def raw_dir(self) -> Path:
        return self.region_root / "raw"

    @property
    def intermediate_dir(self) -> Path:
        return self.region_root / "intermediate"

    @property
    def staging_dir(self) -> Path:
        return self.region_root / "staging"

    @property
    def published_dir(self) -> Path:
        return self.region_root / "published"

    @property
    def territory_export_dir(self) -> Path:
        """Where stage 09 writes the GeoJSON the backend seed script reads.

        Mirrors the Milestone 1 layout exactly -- data/territories/{city}/{area}/v{n}
        -- so publishing does not require any backend change.
        """
        return (
            self.repo_root
            / self.region.publish.territory_data_root
            / self.region.city
            / self.region.area
            / f"v{self.region.publish.version}"
        )

    def ensure_dirs(self) -> None:
        for directory in (
            self.raw_dir,
            self.intermediate_dir,
            self.staging_dir,
            self.published_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


class StageStatus(StrEnum):
    OK = "ok"
    # Phase A default: the stage wrote placeholders so the chain is runnable,
    # but no real work happened yet.
    NOT_IMPLEMENTED = "not_implemented"
    # The stage cannot proceed for a legitimate, expected reason -- currently
    # only "a human has not approved these candidates yet". Not a failure.
    BLOCKED = "blocked"


@dataclass
class StageResult:
    stage: str
    status: StageStatus
    written: list[Path] = field(default_factory=list)
    message: str = ""

    @property
    def is_failure(self) -> bool:
        """Neither placeholder output nor an approval gate is a failure.

        Real failures raise. This keeps the orchestrator's exit code meaningful:
        non-zero means something is wrong, not merely unfinished.
        """
        return False


@runtime_checkable
class Stage(Protocol):
    """The interface a `stages/0N_*.py` module must satisfy.

    Phase B may replace the entire body of `run`. Phase B must NOT change
    `NUMBER`, `NAME`, `REQUIRES` or `PRODUCES` -- those are what the
    orchestrator and the contract tests validate the pipeline against.
    """

    NUMBER: int
    NAME: str
    REQUIRES: tuple[ArtifactSpec, ...]
    PRODUCES: tuple[ArtifactSpec, ...]

    def run(self, ctx: PipelineContext) -> StageResult: ...


class MissingArtifactError(RuntimeError):
    """A stage's inputs are not on disk, or its declared outputs were not written."""


def assert_requires(
    stage_name: str, requires: tuple[ArtifactSpec, ...], ctx: PipelineContext
) -> None:
    missing = [spec for spec in requires if not spec.path(ctx).exists()]
    if missing:
        detail = "\n".join(f"  - {spec.key}: {spec.path(ctx)}" for spec in missing)
        raise MissingArtifactError(
            f"stage {stage_name} is missing required inputs:\n{detail}\n"
            "Run the earlier stages first, or pass --from-stage to start where the gap is."
        )


def assert_produces(
    stage_name: str, produces: tuple[ArtifactSpec, ...], ctx: PipelineContext
) -> None:
    missing = [spec for spec in produces if not spec.path(ctx).exists()]
    if missing:
        detail = "\n".join(f"  - {spec.key}: {spec.path(ctx)}" for spec in missing)
        raise MissingArtifactError(
            f"stage {stage_name} claims to produce artifacts it did not write:\n{detail}"
        )
