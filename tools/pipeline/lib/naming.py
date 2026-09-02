"""Territory naming for stage 07.

Assigns display names, unique slugs, Milestone 1 kinds, and stable territory
ids using source data only — no AI. Priority: place/neighbourhood, then
protected landmark names, then street-pair fallback, then unnamed + review.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely import STRtree
from shapely.geometry import LineString, MultiLineString, shape
from shapely.geometry.base import BaseGeometry

from lib import artifacts
from lib.contracts import PipelineContext
from lib.crs import to_work
from lib.determinism import slugify, stable_sort, territory_id
from lib.extract import (
    CLIP_MARGIN_M,
    _osm_tags,
    _osmium_extract,
    artifacts_manifest_path,
    clip_polygon,
)
from lib.io import read_geojson, read_json
from lib.landmarks import _primary_name

_PLACE_SUBTYPES = frozenset(
    {"neighborhood", "neighbourhood", "microhood", "macrohood", "locality"}
)
_OSM_PLACE_VALUES = frozenset(
    {"neighbourhood", "neighborhood", "suburb", "quarter", "city_block", "town"}
)
# Road classes useful for street-pair labels (skip paths people run on).
_ROAD_CLASSES = frozenset(
    {
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
        "residential",
        "unclassified",
        "living_street",
        "unknown",
    }
)
_M1_KINDS = frozenset({"park", "lake", "landmark", "block"})


@dataclass
class _NamedPlace:
    name: str
    slug: str
    geom: BaseGeometry  # work CRS
    area_m2: float


@dataclass
class _NamedRoad:
    name: str
    geom: BaseGeometry  # work CRS


@dataclass(frozen=True)
class NamingStats:
    feature_count: int
    by_name_source: dict[str, int]
    needs_review_count: int
    protected_count: int
    unique_slugs: int
    unique_ids: int


def assign_names(ctx: PipelineContext) -> tuple[list[dict[str, Any]], NamingStats]:
    """Name every Stage 06 face. Hook for tests via monkeypatch."""
    crs_work = ctx.region.crs_work
    city = ctx.region.city
    area = ctx.region.area
    road_buffer_m = max(float(ctx.thresholds.snap_m), 5.0)

    data = read_geojson(artifacts.NORMALIZED.path(ctx))
    raw_features = list(data.get("features") or [])

    places = load_places(ctx)
    roads = load_named_roads(ctx)
    place_tree = STRtree([p.geom for p in places]) if places else None
    road_tree = STRtree([r.geom for r in roads]) if roads else None

    draft: list[dict[str, Any]] = []
    for idx, feature in enumerate(raw_features):
        props = dict(feature.get("properties") or {})
        geom_json = feature.get("geometry")
        if not geom_json:
            continue
        try:
            geom_store = shape(geom_json)
        except Exception:
            continue
        if geom_store is None or geom_store.is_empty:
            continue
        work = to_work(geom_store, crs_work)
        if work.is_empty:
            continue

        named = _resolve_name(
            props=props,
            work=work,
            places=places,
            place_tree=place_tree,
            roads=roads,
            road_tree=road_tree,
            road_buffer_m=road_buffer_m,
            fallback_key=str(props.get("face_id") or f"face-{idx:05d}"),
        )
        out_props = {
            "face_id": props.get("face_id"),
            "atomic": bool(props.get("atomic")),
            "protected": bool(props.get("protected")),
            "role": props.get("role"),
            "category": props.get("category"),
            "source": props.get("source"),
            "source_id": props.get("source_id"),
            "area_m2": round(float(work.area), 3),
            "name": named["name"],
            "slug": named["slug"],
            "kind": named["kind"],
            "name_source": named["name_source"],
            "needs_review": named["needs_review"],
        }
        if props.get("atomic") is True:
            out_props["atomic_source_name"] = props.get("name")
            out_props["atomic_source_slug"] = props.get("slug")
        # Drop nullish optional fields for cleaner GeoJSON.
        for key in ("role", "category", "source", "source_id", "face_id"):
            if out_props.get(key) is None:
                out_props.pop(key, None)
        if out_props.get("name") is None:
            out_props.pop("name", None)

        draft.append(
            {
                "type": "Feature",
                "geometry": geom_json,  # pass through storage CRS
                "properties": out_props,
                "_sort": _sort_tuple(work, out_props),
            }
        )

    draft = stable_sort(draft, key=lambda f: f["_sort"])
    _uniquify_slugs(draft)
    for feature in draft:
        props = feature["properties"]
        props["territory_id"] = str(
            territory_id(city, area, props["slug"])
        )
        del feature["_sort"]

    features = [
        {"type": "Feature", "geometry": f["geometry"], "properties": f["properties"]}
        for f in draft
    ]
    stats = _stats(features)
    return features, stats


def load_places(ctx: PipelineContext) -> list[_NamedPlace]:
    """Named neighbourhood/locality polygons in the working CRS."""
    manifest = read_json(artifacts_manifest_path(ctx))
    files = {entry["key"]: entry for entry in manifest["files"]}
    clip = clip_polygon(ctx.region.bbox, CLIP_MARGIN_M, ctx.region.crs_work)
    crs_work = ctx.region.crs_work

    places: list[_NamedPlace] = []
    places.extend(_places_from_overture(ctx.raw_dir, files, clip, crs_work))
    places.extend(_places_from_osm(ctx.raw_dir, files, clip, crs_work, ctx.region.bbox))
    return stable_sort(places, key=lambda p: (p.area_m2, p.slug))


def load_named_roads(ctx: PipelineContext) -> list[_NamedRoad]:
    """Named road LineStrings in the working CRS."""
    manifest = read_json(artifacts_manifest_path(ctx))
    files = {entry["key"]: entry for entry in manifest["files"]}
    clip = clip_polygon(ctx.region.bbox, CLIP_MARGIN_M, ctx.region.crs_work)
    crs_work = ctx.region.crs_work

    roads: list[_NamedRoad] = []
    roads.extend(_roads_from_overture(ctx.raw_dir, files, clip, crs_work))
    roads.extend(_roads_from_osm(ctx.raw_dir, files, clip, crs_work, ctx.region.bbox))
    return stable_sort(roads, key=lambda r: (r.name, round(r.geom.length, 3)))


def _resolve_name(
    *,
    props: dict[str, Any],
    work: BaseGeometry,
    places: list[_NamedPlace],
    place_tree: STRtree | None,
    roads: list[_NamedRoad],
    road_tree: STRtree | None,
    road_buffer_m: float,
    fallback_key: str,
) -> dict[str, Any]:
    inherited_review = bool(props.get("needs_review"))

    # Priority 2 first for protected: landmark names must not be overwritten.
    if props.get("protected") is True and props.get("name"):
        name = str(props["name"]).strip()
        kind = str(props.get("kind") or "landmark")
        if kind not in _M1_KINDS:
            kind = "landmark"
        slug = str(props.get("slug") or slugify(name))
        return {
            "name": name,
            "slug": slug,
            "kind": kind,
            "name_source": "landmark",
            "needs_review": inherited_review,
        }

    # Priority 1 — place / neighbourhood (fabric only).
    place = _match_place(work, places, place_tree)
    if place is not None:
        return {
            "name": place.name,
            "slug": place.slug,
            "kind": "block",
            "name_source": "place",
            "needs_review": inherited_review,
        }

    # Priority 3 — street-pair.
    pair = _street_pair(work, roads, road_tree, road_buffer_m)
    if pair is not None:
        name_a, name_b = pair
        name = f"Between {name_a} and {name_b}"
        return {
            "name": name,
            "slug": slugify(name),
            "kind": "block",
            "name_source": "street_pair",
            "needs_review": True,
        }

    # Priority 4 — unnamed.
    centroid = work.representative_point()
    slug = f"unnamed-{int(round(centroid.x))}-{int(round(centroid.y))}"
    try:
        slug = slugify(slug)
    except ValueError:
        slug = slugify(f"unnamed-{fallback_key}")
    return {
        "name": None,
        "slug": slug,
        "kind": "block",
        "name_source": "unnamed",
        "needs_review": True,
    }


def _match_place(
    face: BaseGeometry,
    places: list[_NamedPlace],
    tree: STRtree | None,
) -> _NamedPlace | None:
    if not places or tree is None or face.is_empty:
        return None
    face_area = float(face.area)
    if face_area <= 0:
        return None

    hits = tree.query(face)
    candidates: list[_NamedPlace] = []
    pt = face.representative_point()
    for idx in hits:
        place = places[int(idx)]
        if place.geom.contains(pt):
            candidates.append(place)
            continue
        inter = face.intersection(place.geom)
        if inter.is_empty:
            continue
        if float(inter.area) / face_area >= 0.5:
            candidates.append(place)

    if not candidates:
        return None
    # Most specific = smallest area; ties by slug.
    candidates.sort(key=lambda p: (p.area_m2, p.slug))
    return candidates[0]


def _street_pair(
    face: BaseGeometry,
    roads: list[_NamedRoad],
    tree: STRtree | None,
    buffer_m: float,
) -> tuple[str, str] | None:
    if not roads or tree is None or face.is_empty:
        return None
    boundary = face.boundary
    if boundary is None or boundary.is_empty:
        return None
    search = boundary.buffer(buffer_m)
    hits = tree.query(search)
    lengths: dict[str, float] = {}
    for idx in hits:
        road = roads[int(idx)]
        try:
            coincidence = boundary.intersection(road.geom.buffer(buffer_m))
        except Exception:
            continue
        if coincidence is None or coincidence.is_empty:
            continue
        lengths[road.name] = lengths.get(road.name, 0.0) + float(coincidence.length)

    ranked = sorted(lengths.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) < 2:
        return None
    names = sorted([ranked[0][0], ranked[1][0]])
    if names[0] == names[1]:
        return None
    return (names[0], names[1])


def _uniquify_slugs(features: list[dict[str, Any]]) -> None:
    """Append -2, -3, … in encounter order (features must already be sorted)."""
    seen: dict[str, int] = {}
    for feature in features:
        props = feature["properties"]
        base = props["slug"]
        count = seen.get(base, 0) + 1
        seen[base] = count
        if count == 1:
            continue
        props["slug"] = f"{base}-{count}"


def _sort_tuple(work: BaseGeometry, props: dict[str, Any]) -> tuple:
    pt = work.representative_point()
    return (
        0 if props.get("protected") else 1,
        str(props.get("slug") or ""),
        str(props.get("kind") or ""),
        round(float(props.get("area_m2") or 0.0), 3),
        round(float(pt.x), 3),
        round(float(pt.y), 3),
    )


def _stats(features: list[dict[str, Any]]) -> NamingStats:
    by_source: dict[str, int] = {}
    needs_review = 0
    protected = 0
    slugs: set[str] = set()
    ids: set[str] = set()
    for feature in features:
        props = feature.get("properties") or {}
        src = str(props.get("name_source") or "?")
        by_source[src] = by_source.get(src, 0) + 1
        if props.get("needs_review"):
            needs_review += 1
        if props.get("protected"):
            protected += 1
        if props.get("slug"):
            slugs.add(str(props["slug"]))
        if props.get("territory_id"):
            ids.add(str(props["territory_id"]))
    return NamingStats(
        feature_count=len(features),
        by_name_source=dict(sorted(by_source.items())),
        needs_review_count=needs_review,
        protected_count=protected,
        unique_slugs=len(slugs),
        unique_ids=len(ids),
    )


# --- Place loaders ----------------------------------------------------------


def _places_from_overture(
    raw_dir: Path, files: dict[str, dict], clip: BaseGeometry, crs_work: str
) -> list[_NamedPlace]:
    gdf = _read_parquet(raw_dir, files, "overture_divisions_division_area")
    if gdf is None or gdf.empty:
        return []
    out: list[_NamedPlace] = []
    for _, row in gdf.iterrows():
        subtype = str(row.get("subtype") or "").lower()
        if subtype not in _PLACE_SUBTYPES:
            continue
        name = _primary_name(row.get("names"))
        if not name:
            continue
        geom = row.geometry
        if geom is None or geom.is_empty or not geom.intersects(clip):
            continue
        clipped = geom.intersection(clip)
        if clipped.is_empty:
            continue
        work = to_work(clipped, crs_work)
        if work.is_empty or float(work.area) <= 0:
            continue
        out.append(
            _NamedPlace(
                name=name,
                slug=slugify(name),
                geom=work,
                area_m2=float(work.area),
            )
        )
    return out


def _places_from_osm(
    raw_dir: Path,
    files: dict[str, dict],
    clip: BaseGeometry,
    crs_work: str,
    bbox: Any,
) -> list[_NamedPlace]:
    entry = files.get("geofabrik_extract")
    if not entry:
        return []
    src = raw_dir / entry["filename"]
    if not src.exists():
        return []
    clipped = raw_dir / f"{src.stem}.aoi.osm.pbf"
    _osmium_extract(src, clipped, bbox, CLIP_MARGIN_M)
    try:
        gdf = gpd.read_file(clipped, layer="multipolygons")
    except Exception:
        return []
    if gdf.empty:
        return []

    out: list[_NamedPlace] = []
    for _, row in gdf.iterrows():
        tags = _osm_tags(row.to_dict())
        place = tags.get("place")
        if place not in _OSM_PLACE_VALUES:
            continue
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        geom = row.geometry
        if geom is None or geom.is_empty or not geom.intersects(clip):
            continue
        clipped_geom = geom.intersection(clip)
        if clipped_geom.is_empty:
            continue
        work = to_work(clipped_geom, crs_work)
        if work.is_empty or float(work.area) <= 0:
            continue
        out.append(
            _NamedPlace(
                name=name,
                slug=slugify(name),
                geom=work,
                area_m2=float(work.area),
            )
        )
    return out


# --- Road loaders -----------------------------------------------------------


def _roads_from_overture(
    raw_dir: Path, files: dict[str, dict], clip: BaseGeometry, crs_work: str
) -> list[_NamedRoad]:
    gdf = _read_parquet(raw_dir, files, "overture_transportation_segment")
    if gdf is None or gdf.empty:
        return []
    out: list[_NamedRoad] = []
    for _, row in gdf.iterrows():
        if str(row.get("subtype") or "") != "road":
            continue
        klass = str(row.get("class") or "unknown")
        if klass not in _ROAD_CLASSES:
            continue
        name = _primary_name(row.get("names"))
        if not name:
            continue
        geom = row.geometry
        if geom is None or geom.is_empty or not geom.intersects(clip):
            continue
        clipped = geom.intersection(clip)
        for line in _explode_lines(clipped):
            work = to_work(line, crs_work)
            if work.is_empty or work.length <= 0:
                continue
            out.append(_NamedRoad(name=name, geom=work))
    return out


def _roads_from_osm(
    raw_dir: Path,
    files: dict[str, dict],
    clip: BaseGeometry,
    crs_work: str,
    bbox: Any,
) -> list[_NamedRoad]:
    entry = files.get("geofabrik_extract")
    if not entry:
        return []
    src = raw_dir / entry["filename"]
    if not src.exists():
        return []
    clipped = raw_dir / f"{src.stem}.aoi.osm.pbf"
    _osmium_extract(src, clipped, bbox, CLIP_MARGIN_M)
    try:
        gdf = gpd.read_file(clipped, layer="lines")
    except Exception:
        return []
    if gdf.empty:
        return []

    out: list[_NamedRoad] = []
    for _, row in gdf.iterrows():
        tags = _osm_tags(row.to_dict())
        highway = tags.get("highway")
        if highway not in _ROAD_CLASSES and highway not in {
            "primary",
            "secondary",
            "tertiary",
            "residential",
            "unclassified",
            "living_street",
            "trunk",
            "motorway",
        }:
            continue
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        geom = row.geometry
        if geom is None or geom.is_empty or not geom.intersects(clip):
            continue
        clipped_geom = geom.intersection(clip)
        for line in _explode_lines(clipped_geom):
            work = to_work(line, crs_work)
            if work.is_empty or work.length <= 0:
                continue
            out.append(_NamedRoad(name=name, geom=work))
    return out


def _read_parquet(
    raw_dir: Path, files: dict[str, dict], key: str
) -> gpd.GeoDataFrame | None:
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


def _explode_lines(geom: BaseGeometry | None) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return [g for g in geom.geoms if isinstance(g, LineString) and not g.is_empty]
    if geom.geom_type == "GeometryCollection":
        out: list[LineString] = []
        for part in geom.geoms:
            out.extend(_explode_lines(part))
        return out
    return []
