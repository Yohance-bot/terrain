"""Landmark extraction and atomic/standalone classification for stage 03.

Extracts named parks, lakes, campuses and similar places from Overture + OSM.

Two flags (decoupled on purpose):

- ``atomic``: never split — Stage 05 carves the place whole and reinserts it.
  Small parks are atomic so residential cuts do not shred them.
- ``protected`` (standalone): never merge in Stage 06/10. Only landmarks at or
  above ``standalone_min_area_m2`` (plus botanical-scale exceptions) freeze as
  their own permanent territories. Smaller atomics merge into neighbours.

``role`` is ``major`` for any atomic landmark and ``minor`` otherwise. Minors
are naming/context metadata only and are not carved.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from lib.config import BBox
from lib.contracts import PipelineContext
from lib.crs import to_work
from lib.determinism import slugify, stable_sort
from lib.extract import (
    CLIP_MARGIN_M,
    _iter_source_tags,
    _osm_tags,
    _osmium_extract,
    artifacts_manifest_path,
    clip_polygon,
)
from lib.io import read_json

# Fine-grained category → (kind for M1 vocabulary, category for role rules).
# kind is what publish/naming use; category drives major vs minor.
_OVERTURE_LAND_USE = {
    "park": ("park", "park"),
    "garden": ("park", "garden"),
    "nature_reserve": ("park", "park"),
    "pitch": ("park", "pitch"),
    "stadium": ("landmark", "stadium"),
    "cemetery": ("landmark", "cemetery"),
    "university": ("landmark", "university"),
    "college": ("landmark", "college"),
}

_OVERTURE_WATER = {
    "lake": ("lake", "lake"),
    "pond": ("lake", "lake"),
    "reservoir": ("lake", "lake"),
    "water": ("lake", "lake"),
}

_OSM_TAG_TO_META = {
    "leisure=park": ("park", "park"),
    "leisure=garden": ("park", "garden"),
    "leisure=nature_reserve": ("park", "park"),
    "leisure=pitch": ("park", "pitch"),
    "leisure=playground": ("park", "playground"),
    "leisure=stadium": ("landmark", "stadium"),
    "landuse=cemetery": ("landmark", "cemetery"),
    "landuse=reservoir": ("lake", "lake"),
    "amenity=university": ("landmark", "university"),
    "amenity=college": ("landmark", "college"),
    "natural=water": ("lake", "lake"),
}

# Categories that are never carved or frozen in M2.
_ALWAYS_MINOR = frozenset({"pitch", "playground", "cemetery"})

# Named categories eligible for atomic carve at any size. Atomic means the
# source perimeter is never split; it does not imply a dedicated territory.
_ATOMIC_CATEGORIES = frozenset(
    {"park", "garden", "stadium", "university", "college", "lake"}
)

# A lake fully inside a park is absorbed into the park when it is only a small
# fraction of the park (Lalbagh Tank inside Lalbagh). When the "park" is mostly
# water (Sarakki Lake Park wrapping Sarakki Kere), keep the lake and carve the
# park instead -- otherwise the water body disappears and players get a park
# label on a lake.
_LAKE_DOMINATES_PARK_RATIO = 0.35

# After overlap carving, drop scraps smaller than this. Not a fabric size rule
# -- just geometry cleanup so a one-metre sliver left after subtraction is not
# published as a landmark candidate.
_MIN_REMAINING_M2 = 100.0

# BBMP drain codes show up in OSM as named multipolygons tagged natural=water.
_DRAIN_NAME = re.compile(r"^k?\d{2,}$", re.IGNORECASE)


@dataclass
class _Candidate:
    name: str
    slug: str
    kind: str
    category: str
    source: str
    geom: BaseGeometry
    source_id: str


@dataclass(frozen=True)
class LandmarkFlags:
    role: str
    atomic: bool
    protected: bool


def extract_landmarks(ctx: PipelineContext) -> list[dict[str, Any]]:
    """Build the landmark Feature list for the region.

    Hook point for tests: monkeypatch this to avoid reading real extracts.
    """
    manifest = read_json(artifacts_manifest_path(ctx))
    files = {entry["key"]: entry for entry in manifest["files"]}
    clip = clip_polygon(ctx.region.bbox, CLIP_MARGIN_M, ctx.region.crs_work)
    crs_work = ctx.region.crs_work
    territory_min_m2 = ctx.thresholds.territory_min_area_m2
    atomic_min_m2 = ctx.thresholds.atomic_min_area_m2
    standalone_min_m2 = ctx.thresholds.standalone_min_area_m2

    candidates: list[_Candidate] = []
    candidates.extend(_from_overture_land_use(ctx.raw_dir, files, clip))
    candidates.extend(_from_overture_water(ctx.raw_dir, files, clip))
    candidates.extend(_from_osm(ctx.raw_dir, files, clip, ctx.region.bbox))

    dissolved = _dissolve_by_slug(candidates, crs_work)
    dissolved = _reconcile_lakes_and_parks(dissolved, crs_work)
    resolved = _resolve_overlaps(dissolved, crs_work)

    features = [
        _to_feature(
            item,
            crs_work,
            territory_min_m2=territory_min_m2,
            atomic_min_m2=atomic_min_m2,
            standalone_min_m2=standalone_min_m2,
        )
        for item in resolved
    ]
    features = [f for f in features if f is not None]
    return stable_sort(features, key=_feature_sort_key)


def classify_role(
    *,
    name: str,
    kind: str,
    category: str,
    area_m2: float,
    territory_min_m2: float,
) -> str:
    """Return `major` or `minor` (legacy API used by tests).

    Prefer ``classify_flags`` for new call sites — it also returns atomic and
    protected (standalone).
    """
    return classify_flags(
        name=name,
        kind=kind,
        category=category,
        area_m2=area_m2,
        territory_min_m2=territory_min_m2,
        # Legacy callers use the fabric landmark floor for both carve and freeze.
        atomic_min_m2=territory_min_m2,
        standalone_min_m2=territory_min_m2,
    ).role


def classify_flags(
    *,
    name: str,
    kind: str,
    category: str,
    area_m2: float,
    territory_min_m2: float,
    atomic_min_m2: float,
    standalone_min_m2: float,
) -> LandmarkFlags:
    """Return role + atomic + protected (standalone) for a landmark.

    Rules, in order:
    1. Unnamed / always-minor classes → not atomic, not protected, minor.
    2. Every named eligible landmark is atomic, regardless of size.
    3. A landmark is protected (standalone) only at the standalone area floor.
       Product rule: Lalbagh-class = own territory; playground / college lawn /
       tiny lake = neighbourhood fabric. Atomic still means never split.
    """
    if not name or not name.strip():
        return LandmarkFlags(role="minor", atomic=False, protected=False)
    if category in _ALWAYS_MINOR:
        return LandmarkFlags(role="minor", atomic=False, protected=False)

    if category not in _ATOMIC_CATEGORIES:
        return LandmarkFlags(role="minor", atomic=False, protected=False)

    # All named eligible landmarks are carved whole. Only area determines
    # whether they remain standalone; botanical names receive no size bypass.
    protected = area_m2 >= standalone_min_m2
    del territory_min_m2, atomic_min_m2, kind  # signature compatibility
    return LandmarkFlags(role="major", atomic=True, protected=protected)


def _feature_sort_key(feature: dict[str, Any]) -> tuple:
    props = feature.get("properties") or {}
    return (
        str(props.get("role") or ""),
        str(props.get("slug") or ""),
        str(props.get("source") or ""),
    )


def _to_feature(
    item: _Candidate,
    crs_work: str,
    *,
    territory_min_m2: float,
    atomic_min_m2: float,
    standalone_min_m2: float,
) -> dict[str, Any] | None:
    geom = _as_multipolygon(item.geom)
    if geom is None or geom.is_empty:
        return None
    area_m2 = float(to_work(geom, crs_work).area)
    flags = classify_flags(
        name=item.name,
        kind=item.kind,
        category=item.category,
        area_m2=area_m2,
        territory_min_m2=territory_min_m2,
        atomic_min_m2=atomic_min_m2,
        standalone_min_m2=standalone_min_m2,
    )
    return {
        "type": "Feature",
        "geometry": mapping(geom),
        "properties": {
            "atomic": flags.atomic,
            "protected": flags.protected,
            "role": flags.role,
            "name": item.name,
            "slug": item.slug,
            "kind": item.kind,
            "category": item.category,
            "source": item.source,
            "source_id": item.source_id,
            "area_m2": round(area_m2, 3),
        },
    }


def _as_multipolygon(geom: BaseGeometry) -> BaseGeometry | None:
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    if isinstance(geom, MultiPolygon):
        return geom
    if geom.geom_type == "GeometryCollection":
        polys = [g for g in geom.geoms if isinstance(g, Polygon | MultiPolygon)]
        if not polys:
            return None
        return _as_multipolygon(unary_union(polys))
    return None


def _primary_name(names: Any) -> str | None:
    if names is None:
        return None
    if isinstance(names, dict):
        primary = names.get("primary")
        if primary:
            return str(primary).strip() or None
    return None


def _area_m2(geom: BaseGeometry, crs_work: str) -> float:
    if geom is None or geom.is_empty:
        return 0.0
    return float(to_work(geom, crs_work).area)


def _read_parquet(raw_dir: Path, files: dict[str, dict], key: str) -> gpd.GeoDataFrame | None:
    entry = files.get(key)
    if not entry:
        return None
    path = raw_dir / entry["filename"]
    if not path.exists():
        raise FileNotFoundError(f"manifest lists {key} but file missing: {path}")
    gdf = gpd.read_parquet(path)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    else:
        gdf = gdf.to_crs("EPSG:4326")
    return gdf


def _clip(geom: BaseGeometry, clip: BaseGeometry) -> BaseGeometry | None:
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type not in {"Polygon", "MultiPolygon"}:
        return None
    clipped = geom.intersection(clip)
    return clipped if clipped is not None and not clipped.is_empty else None


def _copy_candidate(c: _Candidate, *, geom: BaseGeometry | None = None) -> _Candidate:
    return _Candidate(
        name=c.name,
        slug=c.slug,
        kind=c.kind,
        category=c.category,
        source=c.source,
        geom=c.geom if geom is None else geom,
        source_id=c.source_id,
    )


# --- Overture ---------------------------------------------------------------


def _from_overture_land_use(
    raw_dir: Path, files: dict[str, dict], clip: BaseGeometry
) -> list[_Candidate]:
    gdf = _read_parquet(raw_dir, files, "overture_base_land_use")
    if gdf is None or gdf.empty:
        return []

    out: list[_Candidate] = []
    for idx, row in gdf.iterrows():
        meta = _land_use_meta(row)
        if meta is None:
            continue
        kind, category = meta
        name = _primary_name(row.get("names"))
        if not name:
            continue
        geom = _clip(row.geometry, clip)
        if geom is None:
            continue
        out.append(
            _Candidate(
                name=name,
                slug=slugify(name),
                kind=kind,
                category=category,
                source="overture",
                geom=geom,
                source_id=str(row.get("id") or idx),
            )
        )
    return out


def _land_use_meta(row: Any) -> tuple[str, str] | None:
    for key, value in _iter_source_tags(row.get("source_tags")):
        token = f"{key}={value}"
        if token in _OSM_TAG_TO_META:
            return _OSM_TAG_TO_META[token]
    return _OVERTURE_LAND_USE.get(str(row.get("class") or ""))


def _from_overture_water(
    raw_dir: Path, files: dict[str, dict], clip: BaseGeometry
) -> list[_Candidate]:
    gdf = _read_parquet(raw_dir, files, "overture_base_water")
    if gdf is None or gdf.empty:
        return []

    out: list[_Candidate] = []
    for idx, row in gdf.iterrows():
        klass = str(row.get("class") or "")
        meta = _OVERTURE_WATER.get(klass)
        if meta is None:
            continue
        kind, category = meta
        name = _primary_name(row.get("names"))
        if not name:
            continue
        geom = _clip(row.geometry, clip)
        if geom is None:
            continue
        out.append(
            _Candidate(
                name=name,
                slug=slugify(name),
                kind=kind,
                category=category,
                source="overture",
                geom=geom,
                source_id=str(row.get("id") or idx),
            )
        )
    return out


# --- OSM --------------------------------------------------------------------


def _from_osm(
    raw_dir: Path, files: dict[str, dict], clip: BaseGeometry, bbox: BBox
) -> list[_Candidate]:
    entry = files.get("geofabrik_extract")
    if not entry:
        return []
    src = raw_dir / entry["filename"]
    if not src.exists():
        raise FileNotFoundError(f"manifest lists geofabrik_extract but file missing: {src}")

    clipped = raw_dir / f"{src.stem}.aoi.osm.pbf"
    _osmium_extract(src, clipped, bbox, CLIP_MARGIN_M)

    gdf = gpd.read_file(clipped, layer="multipolygons")
    if gdf.empty:
        return []

    out: list[_Candidate] = []
    for idx, row in gdf.iterrows():
        tags = _osm_tags(row.to_dict())
        meta = _osm_meta(tags)
        if meta is None:
            continue
        kind, category = meta
        name = (tags.get("name") or "").strip()
        if not name or _DRAIN_NAME.match(name):
            continue
        geom = _clip(row.geometry, clip)
        if geom is None:
            continue
        out.append(
            _Candidate(
                name=name,
                slug=slugify(name),
                kind=kind,
                category=category,
                source="osm",
                geom=geom,
                source_id=str(row.get("osm_id") or row.get("osm_way_id") or idx),
            )
        )
    return out


def _osm_meta(tags: dict[str, str]) -> tuple[str, str] | None:
    if tags.get("waterway") in {"drain", "ditch", "canal"}:
        return None

    for key in ("leisure", "landuse", "amenity"):
        if key in tags:
            token = f"{key}={tags[key]}"
            if token in _OSM_TAG_TO_META:
                return _OSM_TAG_TO_META[token]

    if tags.get("landuse") == "reservoir":
        return ("lake", "lake")

    if tags.get("natural") == "water":
        if tags.get("water") in {"lake", "pond", "reservoir"}:
            return ("lake", "lake")
        name = (tags.get("name") or "").lower()
        if any(token in name for token in ("lake", "kere", "tank", "pond", "reservoir")):
            if _DRAIN_NAME.match(tags.get("name") or ""):
                return None
            return ("lake", "lake")
        return None

    return None


# --- Dissolve + overlap resolution ------------------------------------------


def _dissolve_by_slug(candidates: list[_Candidate], crs_work: str) -> list[_Candidate]:
    """Merge adjoining / overlapping parts of the same named place."""
    groups: dict[str, list[_Candidate]] = defaultdict(list)
    for candidate in candidates:
        groups[candidate.slug].append(candidate)

    dissolved: list[_Candidate] = []
    for slug, parts in groups.items():
        geom = unary_union([p.geom for p in parts])
        if geom.is_empty:
            continue
        preferred = sorted(
            parts,
            key=lambda p: (0 if p.source == "overture" else 1, -len(p.name), p.name),
        )[0]
        sources = sorted({p.source for p in parts})
        dissolved.append(
            _Candidate(
                name=preferred.name,
                slug=slug,
                kind=preferred.kind,
                category=preferred.category,
                source="+".join(sources) if len(sources) > 1 else preferred.source,
                geom=geom,
                source_id=";".join(sorted({p.source_id for p in parts})),
            )
        )

    return stable_sort(
        dissolved,
        key=lambda c: (-_area_m2(c.geom, crs_work), c.slug),
    )


def _reconcile_lakes_and_parks(
    landmarks: list[_Candidate], crs_work: str
) -> list[_Candidate]:
    """Decide lake-vs-containing-park before the generic larger-wins pass."""
    lakes = [c for c in landmarks if c.kind == "lake"]
    others = [c for c in landmarks if c.kind != "lake"]
    if not lakes:
        return landmarks

    drop_slugs: set[str] = set()
    park_updates: dict[str, BaseGeometry] = {}

    for lake in lakes:
        lake_area = _area_m2(lake.geom, crs_work)
        if lake_area <= 0:
            drop_slugs.add(lake.slug)
            continue
        for park in others:
            if park.kind != "park":
                continue
            if not park.geom.intersects(lake.geom):
                continue
            overlap = park.geom.intersection(lake.geom)
            if overlap.is_empty:
                continue
            coverage = _area_m2(overlap, crs_work) / lake_area
            if coverage < 0.9:
                continue
            park_area = _area_m2(park.geom, crs_work)
            if park_area <= 0:
                continue
            ratio = lake_area / park_area
            if ratio < _LAKE_DOMINATES_PARK_RATIO:
                drop_slugs.add(lake.slug)
            else:
                carved = park_updates.get(park.slug, park.geom).difference(lake.geom)
                park_updates[park.slug] = carved

    reconciled: list[_Candidate] = []
    for candidate in landmarks:
        if candidate.slug in drop_slugs:
            continue
        geom = park_updates.get(candidate.slug, candidate.geom)
        geom = _as_multipolygon(geom)
        if geom is None or geom.is_empty:
            continue
        if _area_m2(geom, crs_work) < _MIN_REMAINING_M2:
            continue
        reconciled.append(_copy_candidate(candidate, geom=geom))

    return stable_sort(
        reconciled,
        key=lambda c: (-_area_m2(c.geom, crs_work), c.slug),
    )


def _resolve_overlaps(landmarks: list[_Candidate], crs_work: str) -> list[_Candidate]:
    """Larger area wins; the smaller landmark loses the contested strip."""
    accepted: list[_Candidate] = []
    claimed: BaseGeometry | None = None

    for landmark in landmarks:
        remaining = landmark.geom if claimed is None else landmark.geom.difference(claimed)
        remaining = _as_multipolygon(remaining)
        if remaining is None or remaining.is_empty:
            continue
        if _area_m2(remaining, crs_work) < _MIN_REMAINING_M2:
            continue
        kept = _copy_candidate(landmark, geom=remaining)
        accepted.append(kept)
        claimed = remaining if claimed is None else unary_union([claimed, remaining])

    return accepted
