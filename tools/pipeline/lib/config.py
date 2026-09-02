"""Typed configuration loading.

Every loader here fails loud. A missing key raises immediately with the file
path and the key name, rather than defaulting to something reasonable-looking.

That strictness is deliberate. A pipeline that silently defaults `snap_m` to
zero still runs, still writes a staging file, and produces a broken street grid
that a human reviewer has to catch by eye. Failing at load time costs seconds;
failing at review costs an afternoon.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_ROOT = Path(__file__).resolve().parent.parent / "config"
REGIONS_ROOT = CONFIG_ROOT / "regions"


class ConfigError(ValueError):
    """Raised when configuration is missing, malformed, or internally inconsistent."""


def _require(mapping: Any, key: str, source: Path) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise ConfigError(f"{source}: missing required key {key!r}")
    value = mapping[key]
    if value is None:
        raise ConfigError(f"{source}: key {key!r} is null")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a YAML mapping at the top level")
    return data


@dataclass(frozen=True)
class BBox:
    """Area of interest in EPSG:4326, ordered [south, west, north, east]."""

    south: float
    west: float
    north: float
    east: float

    @classmethod
    def from_list(cls, values: Any, source: Path) -> BBox:
        if not isinstance(values, list) or len(values) != 4:
            raise ConfigError(f"{source}: bbox must be a list of four numbers [S, W, N, E]")
        south, west, north, east = (float(v) for v in values)
        if south >= north or west >= east:
            raise ConfigError(f"{source}: bbox is inverted or empty: {values}")
        return cls(south=south, west=west, north=north, east=east)

    def as_tuple(self) -> tuple[float, float, float, float]:
        """(south, west, north, east) -- the order used in the config file."""
        return (self.south, self.west, self.north, self.east)

    def as_xy_bounds(self) -> tuple[float, float, float, float]:
        """(minx, miny, maxx, maxy) -- the order shapely and geopandas expect."""
        return (self.west, self.south, self.east, self.north)


@dataclass(frozen=True)
class OvertureSource:
    release: str | None
    themes: tuple[str, ...]


@dataclass(frozen=True)
class GeofabrikSource:
    extract_url: str


@dataclass(frozen=True)
class PublishTarget:
    territory_data_root: str
    version: int


@dataclass(frozen=True)
class RegionConfig:
    name: str
    city: str
    area: str
    bbox: BBox
    crs_work: str
    crs_store: str
    overture: OvertureSource
    geofabrik: GeofabrikSource
    publish: PublishTarget
    source_path: Path
    # Opt-in, per-region escape hatch for Stage 08 "names" failures that are
    # already known, investigated, and accepted (see `load_validation_exceptions`).
    # Default False so every region behaves exactly as before unless a human
    # deliberately turns this on for one region.
    allow_validation_exceptions: bool = False

    def require_pinned_sources(self) -> None:
        """Guard called by stage 01 before any download.

        An unpinned Overture release would make the pipeline's output depend on
        the day it happened to run, which breaks the determinism guarantee that
        the whole milestone rests on.
        """
        if not self.overture.release:
            raise ConfigError(
                f"{self.source_path}: sources.overture.release is not pinned. "
                "Set it to a specific Overture release (see "
                "https://docs.overturemaps.org/release/) before running stage 01."
            )


@dataclass(frozen=True)
class FeatureClasses:
    """Which real-world features may become territory borders.

    `include` and `exclude` are kept as raw name-to-values mappings rather than
    named fields because the taxonomy differs between Overture and OSM, and
    stages 02 and 03 read different subsets of it.
    """

    include: dict[str, list[str]]
    exclude: dict[str, Any]
    source_path: Path

    def included(self, group: str) -> list[str]:
        if group not in self.include:
            raise ConfigError(f"{self.source_path}: include group {group!r} is not defined")
        return list(self.include[group])

    def excluded(self, group: str) -> list[str]:
        value = self.exclude.get(group, [])
        return list(value) if isinstance(value, list) else []

    def is_excluded_highway(self, highway_class: str) -> bool:
        return highway_class in self.excluded("highway")


@dataclass(frozen=True)
class ValidationThresholds:
    max_gap_m2: float
    max_overlap_m2: float
    min_coverage_ratio: float
    allow_unnamed_publish: bool


@dataclass(frozen=True)
class GameplayThresholds:
    soft_min_m2: float
    soft_max_m2: float
    place_max_m2: float
    review_max_m2: float
    hard_max_m2: float
    min_shared_border_m: float
    min_merge_score: float
    w_place: float
    w_border: float
    w_size: float
    w_name: float
    barrier_highway_classes: tuple[str, ...]
    barrier_railway_classes: tuple[str, ...]
    barrier_waterway_classes: tuple[str, ...]
    barrier_area_groups: tuple[str, ...]


@dataclass(frozen=True)
class BeautifyThresholds:
    critic: str
    auto_apply_min_confidence: float
    min_compactness: float
    peninsula_border_share: float
    min_peninsula_shared_border_m: float
    jagged_complexity: float
    max_aspect_ratio: float
    min_aspect_improvement: float
    min_transfer_compactness_gain: float
    max_suggestions: int
    max_exterior_corners: int
    corner_snap_m: float


@dataclass(frozen=True)
class Thresholds:
    snap_m: float
    scrap_m2: float
    fabric_soft_min_m2: float
    fabric_soft_max_m2: float
    fabric_review_max_m2: float
    territory_min_area_m2: float
    atomic_min_area_m2: float
    standalone_min_area_m2: float
    simplify_tolerance_m: float
    validation: ValidationThresholds
    gameplay: GameplayThresholds
    beautify: BeautifyThresholds
    source_path: Path


def load_region(name: str, config_root: Path | None = None) -> RegionConfig:
    """Load one region YAML by filename stem, e.g. `bengaluru_jayanagar_lalbagh`."""
    root = (config_root or CONFIG_ROOT) / "regions"
    path = root / f"{name}.yaml"
    data = _load_yaml(path)

    sources = _require(data, "sources", path)
    overture_raw = _require(sources, "overture", path)
    geofabrik_raw = _require(sources, "geofabrik", path)
    publish_raw = _require(data, "publish", path)

    # `release` is allowed to be null here on purpose -- see require_pinned_sources.
    themes = overture_raw.get("themes")
    if not themes:
        raise ConfigError(f"{path}: sources.overture.themes must list at least one theme")

    return RegionConfig(
        name=name,
        city=str(_require(data, "city", path)),
        area=str(_require(data, "area", path)),
        bbox=BBox.from_list(_require(data, "bbox", path), path),
        crs_work=str(_require(data, "crs_work", path)),
        crs_store=str(_require(data, "crs_store", path)),
        overture=OvertureSource(
            release=overture_raw.get("release"),
            themes=tuple(str(t) for t in themes),
        ),
        geofabrik=GeofabrikSource(extract_url=str(_require(geofabrik_raw, "extract_url", path))),
        publish=PublishTarget(
            territory_data_root=str(_require(publish_raw, "territory_data_root", path)),
            version=int(_require(publish_raw, "version", path)),
        ),
        source_path=path,
        allow_validation_exceptions=bool(data.get("allow_validation_exceptions", False)),
    )


def load_validation_exceptions(
    region_name: str, config_root: Path | None = None
) -> dict[str, str]:
    """Load the fixed, human-reviewed list of accepted validation exceptions.

    Only ever consulted when a region has `allow_validation_exceptions: true`
    (or the equivalent CLI flag) turned on. The file must exist and be
    non-empty once the flag is on -- fails loud rather than silently treating
    a missing/empty file as "nothing is excluded" or, worse, letting a typo'd
    path go unnoticed while a hard failure still blocks the run.

    This is deliberately a separate, explicit, versioned file rather than a
    field on the region YAML: the exact set of accepted slugs is a one-time,
    reviewed decision about *this run's* known defects, not a pipeline
    setting. Callers decide which checks can consult this map.
    """
    root = (config_root or CONFIG_ROOT) / "regions"
    path = root / f"{region_name}.exceptions.json"
    if not path.exists():
        raise ConfigError(
            f"{path}: allow_validation_exceptions is enabled for {region_name!r} "
            "but no exceptions file exists"
        )
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON ({exc})") from exc

    entries = data.get("exceptions") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{path}: 'exceptions' must be a non-empty list")

    result: dict[str, str] = {}
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: exceptions[{i}] must be an object")
        slug = entry.get("slug")
        reason = entry.get("reason")
        territory_id = entry.get("territory_id")
        if not isinstance(slug, str) or not slug.strip():
            raise ConfigError(f"{path}: exceptions[{i}] missing non-empty 'slug'")
        if not isinstance(reason, str) or not reason.strip():
            raise ConfigError(f"{path}: exceptions[{i}] missing non-empty 'reason'")
        for key, label in ((slug, "slug"), (territory_id, "territory_id")):
            if not isinstance(key, str):
                continue
            key = key.strip()
            if not key:
                continue
            if key in result and result[key] != reason:
                raise ConfigError(f"{path}: duplicate exception identifier {key!r}")
            if key in result:
                continue
            result[key] = reason
    return result


def available_regions(config_root: Path | None = None) -> list[str]:
    root = (config_root or CONFIG_ROOT) / "regions"
    return sorted(p.stem for p in root.glob("*.yaml"))


def load_feature_classes(config_root: Path | None = None) -> FeatureClasses:
    path = (config_root or CONFIG_ROOT) / "highway_classes.yaml"
    data = _load_yaml(path)
    include = _require(data, "include", path)
    exclude = _require(data, "exclude", path)

    # These four groups are what stages 02 and 04 index into. Anything else is
    # optional, but a missing one of these means the boundary graph is built
    # from an incomplete separator set and the failure would be invisible.
    for group in ("highway", "railway", "waterway", "area_boundary"):
        _require(include, group, path)
    _require(exclude, "highway", path)

    return FeatureClasses(include=include, exclude=exclude, source_path=path)


def load_thresholds(config_root: Path | None = None) -> Thresholds:
    path = (config_root or CONFIG_ROOT) / "thresholds.yaml"
    data = _load_yaml(path)
    validation = _require(data, "validation", path)
    gameplay = _require(data, "gameplay", path)
    beautify = _require(data, "beautify", path)

    def _str_tuple(key: str, *, allow_empty: bool = False) -> tuple[str, ...]:
        raw = _require(gameplay, key, path)
        if not isinstance(raw, list):
            raise ConfigError(f"{path}: gameplay.{key} must be a list")
        if not raw and not allow_empty:
            raise ConfigError(f"{path}: gameplay.{key} must be a non-empty list")
        return tuple(str(v) for v in raw)

    soft_min = float(_require(gameplay, "soft_min_m2", path))
    soft_max = float(_require(gameplay, "soft_max_m2", path))
    place_max = float(_require(gameplay, "place_max_m2", path))
    review_max = float(_require(gameplay, "review_max_m2", path))
    hard_max = float(_require(gameplay, "hard_max_m2", path))
    if soft_min >= soft_max:
        raise ConfigError(f"{path}: gameplay.soft_min_m2 must be < soft_max_m2")
    if soft_max > place_max:
        raise ConfigError(f"{path}: gameplay.soft_max_m2 must be <= place_max_m2")
    if place_max > review_max:
        raise ConfigError(f"{path}: gameplay.place_max_m2 must be <= review_max_m2")
    if hard_max < soft_max:
        raise ConfigError(f"{path}: gameplay.hard_max_m2 must be >= soft_max_m2")
    if place_max > hard_max or review_max > hard_max:
        raise ConfigError(
            f"{path}: gameplay place/review maxima must not exceed hard_max_m2"
        )

    atomic_min = float(_require(data, "atomic_min_area_m2", path))
    standalone_min = float(_require(data, "standalone_min_area_m2", path))
    if atomic_min <= 0:
        raise ConfigError(f"{path}: atomic_min_area_m2 must be > 0")
    if standalone_min < atomic_min:
        raise ConfigError(
            f"{path}: standalone_min_area_m2 must be >= atomic_min_area_m2"
        )

    critic = str(_require(beautify, "critic", path)).strip().lower()
    if critic not in {"heuristic", "llm"}:
        raise ConfigError(f"{path}: beautify.critic must be 'heuristic' or 'llm'")
    auto_apply = float(_require(beautify, "auto_apply_min_confidence", path))
    if not 0.0 <= auto_apply <= 1.0:
        raise ConfigError(
            f"{path}: beautify.auto_apply_min_confidence must be in [0, 1]"
        )
    min_compactness = float(_require(beautify, "min_compactness", path))
    if not 0.0 < min_compactness <= 1.0:
        raise ConfigError(f"{path}: beautify.min_compactness must be in (0, 1]")
    peninsula_share = float(_require(beautify, "peninsula_border_share", path))
    if not 0.0 < peninsula_share <= 1.0:
        raise ConfigError(
            f"{path}: beautify.peninsula_border_share must be in (0, 1]"
        )
    min_peninsula_border = float(
        _require(beautify, "min_peninsula_shared_border_m", path)
    )
    if min_peninsula_border < 0:
        raise ConfigError(
            f"{path}: beautify.min_peninsula_shared_border_m must be >= 0"
        )
    jagged_complexity = float(_require(beautify, "jagged_complexity", path))
    if jagged_complexity < 1.0:
        raise ConfigError(f"{path}: beautify.jagged_complexity must be >= 1.0")
    max_aspect = float(_require(beautify, "max_aspect_ratio", path))
    if max_aspect < 1.0:
        raise ConfigError(f"{path}: beautify.max_aspect_ratio must be >= 1.0")
    min_aspect_improvement = float(
        _require(beautify, "min_aspect_improvement", path)
    )
    if min_aspect_improvement < 0:
        raise ConfigError(
            f"{path}: beautify.min_aspect_improvement must be >= 0"
        )
    min_transfer_gain = float(
        _require(beautify, "min_transfer_compactness_gain", path)
    )
    if min_transfer_gain < 0:
        raise ConfigError(
            f"{path}: beautify.min_transfer_compactness_gain must be >= 0"
        )
    max_suggestions = int(_require(beautify, "max_suggestions", path))
    if max_suggestions <= 0:
        raise ConfigError(f"{path}: beautify.max_suggestions must be > 0")
    max_corners = int(_require(beautify, "max_exterior_corners", path))
    if max_corners < 3:
        raise ConfigError(f"{path}: beautify.max_exterior_corners must be >= 3")
    corner_snap = float(_require(beautify, "corner_snap_m", path))
    if corner_snap <= 0:
        raise ConfigError(f"{path}: beautify.corner_snap_m must be > 0")

    return Thresholds(
        snap_m=float(_require(data, "snap_m", path)),
        scrap_m2=float(_require(data, "scrap_m2", path)),
        fabric_soft_min_m2=float(_require(data, "fabric_soft_min_m2", path)),
        fabric_soft_max_m2=float(_require(data, "fabric_soft_max_m2", path)),
        fabric_review_max_m2=float(_require(data, "fabric_review_max_m2", path)),
        territory_min_area_m2=float(_require(data, "territory_min_area_m2", path)),
        atomic_min_area_m2=atomic_min,
        standalone_min_area_m2=standalone_min,
        simplify_tolerance_m=float(_require(data, "simplify_tolerance_m", path)),
        validation=ValidationThresholds(
            max_gap_m2=float(_require(validation, "max_gap_m2", path)),
            max_overlap_m2=float(_require(validation, "max_overlap_m2", path)),
            min_coverage_ratio=float(_require(validation, "min_coverage_ratio", path)),
            allow_unnamed_publish=bool(validation.get("allow_unnamed_publish", False)),
        ),
        gameplay=GameplayThresholds(
            soft_min_m2=soft_min,
            soft_max_m2=soft_max,
            place_max_m2=place_max,
            review_max_m2=review_max,
            hard_max_m2=hard_max,
            min_shared_border_m=float(_require(gameplay, "min_shared_border_m", path)),
            min_merge_score=float(_require(gameplay, "min_merge_score", path)),
            w_place=float(_require(gameplay, "w_place", path)),
            w_border=float(_require(gameplay, "w_border", path)),
            w_size=float(_require(gameplay, "w_size", path)),
            w_name=float(_require(gameplay, "w_name", path)),
            barrier_highway_classes=_str_tuple("barrier_highway_classes"),
            barrier_railway_classes=_str_tuple("barrier_railway_classes"),
            barrier_waterway_classes=_str_tuple("barrier_waterway_classes"),
            barrier_area_groups=_str_tuple("barrier_area_groups", allow_empty=True),
        ),
        beautify=BeautifyThresholds(
            critic=critic,
            auto_apply_min_confidence=auto_apply,
            min_compactness=min_compactness,
            peninsula_border_share=peninsula_share,
            min_peninsula_shared_border_m=min_peninsula_border,
            jagged_complexity=jagged_complexity,
            max_aspect_ratio=max_aspect,
            min_aspect_improvement=min_aspect_improvement,
            min_transfer_compactness_gain=min_transfer_gain,
            max_suggestions=max_suggestions,
            max_exterior_corners=max_corners,
            corner_snap_m=corner_snap,
        ),
        source_path=path,
    )
