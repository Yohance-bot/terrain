"""Separator feature extraction for stage 02.

Reads the raw extracts stage 01 fetched, keeps only classes allowed by
`highway_classes.yaml`, and emits linework. Overture is primary; Geofabrik OSM
is the fallback for the same classes. Both are tagged with `source` so a
reviewer can see where a border came from.

This module does no noding or polygon building -- that is stage 04.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, MultiPolygon, box, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from lib.config import BBox, FeatureClasses
from lib.contracts import PipelineContext
from lib.crs import to_store, to_work
from lib.determinism import stable_sort
from lib.io import read_json

# How far past the AOI edge separators are kept. Cutting exactly at the bbox
# leaves outermost faces open; polygonization then drops them and the AOI
# gains a silent hole around its rim.
CLIP_MARGIN_M = 50.0

_OTHER_TAGS_RE = re.compile(r'"([^"]+)"=>"([^"]*)"')

# Overture land_use / water `class` values that correspond to area_boundary
# include tokens. source_tags are preferred when present; this is the fallback.
_OVERTURE_CLASS_TO_AREA_TAG = {
    "park": "leisure=park",
    "garden": "leisure=garden",
    "nature_reserve": "leisure=nature_reserve",
    "pitch": "leisure=pitch",
    "stadium": "leisure=stadium",
    "cemetery": "landuse=cemetery",
    "university": "amenity=university",
    "college": "amenity=college",
    "reservoir": "landuse=reservoir",
    "lake": "natural=water",
    "pond": "natural=water",
    "water": "natural=water",
}

# Overture transportation rail `class` -> railway include token.
_OVERTURE_RAIL_CLASS = {
    "standard_gauge": "rail",
    "narrow_gauge": "narrow_gauge",
    "subway": "subway",
    "light_rail": "light_rail",
    "unknown": "rail",
}


def extract_separators(ctx: PipelineContext) -> list[dict[str, Any]]:
    """Build the separator Feature list for the region.

    Hook point for tests: monkeypatch this to avoid reading real extracts.
    """
    manifest = read_json(artifacts_manifest_path(ctx))
    files = {entry["key"]: entry for entry in manifest["files"]}

    clip = clip_polygon(ctx.region.bbox, CLIP_MARGIN_M, ctx.region.crs_work)
    classes = ctx.feature_classes
    features: list[dict[str, Any]] = []

    features.extend(_from_overture(ctx.raw_dir, files, classes, clip))
    features.extend(_from_osm(ctx.raw_dir, files, classes, clip, ctx.region.bbox))

    # Drop empties / invalids, then stable order so two runs write the same bytes.
    usable = [f for f in features if f.get("geometry") is not None]
    return stable_sort(usable, key=_sort_key)


def artifacts_manifest_path(ctx: PipelineContext) -> Path:
    from lib import artifacts

    return artifacts.RAW_MANIFEST.path(ctx)


def clip_polygon(bbox: BBox, margin_m: float, crs_work: str) -> BaseGeometry:
    """AOI rectangle expanded by margin_m in the working CRS, returned in 4326."""
    core = box(*bbox.as_xy_bounds())
    expanded = to_work(core, crs_work).buffer(margin_m, join_style=2)
    return to_store(expanded, crs_work)


def _sort_key(feature: dict[str, Any]) -> tuple:
    props = feature.get("properties") or {}
    geom = feature.get("geometry") or {}
    coords = geom.get("coordinates") or []
    first = _first_coordinate(coords)
    return (
        str(props.get("source") or ""),
        str(props.get("group") or ""),
        str(props.get("class") or ""),
        str(props.get("id") or ""),
        first,
    )


def _first_coordinate(coords: Any) -> tuple[float, float]:
    if not coords:
        return (0.0, 0.0)
    if isinstance(coords[0], (int, float)):
        return (float(coords[0]), float(coords[1]))
    return _first_coordinate(coords[0])


def _line_feature(
    geom: BaseGeometry,
    *,
    source: str,
    group: str,
    class_name: str,
    feature_id: str,
    clip: BaseGeometry,
) -> dict[str, Any] | None:
    if geom is None or geom.is_empty:
        return None
    clipped = geom.intersection(clip)
    if clipped.is_empty:
        return None
    line = _as_lines(clipped)
    if line is None or line.is_empty:
        return None
    return {
        "type": "Feature",
        "geometry": mapping(line),
        "properties": {
            "source": source,
            "group": group,
            "class": class_name,
            "id": feature_id,
        },
    }


def _as_lines(geom: BaseGeometry) -> BaseGeometry | None:
    """Force any geometry to LineString / MultiLineString for separator output."""
    if geom.is_empty:
        return None
    if isinstance(geom, LineString | MultiLineString):
        return geom
    if isinstance(geom, MultiPolygon):
        rings = [LineString(poly.exterior.coords) for poly in geom.geoms if not poly.is_empty]
        return MultiLineString(rings) if rings else None
    if geom.geom_type == "Polygon":
        return LineString(geom.exterior.coords)
    if geom.geom_type == "GeometryCollection":
        parts = [_as_lines(part) for part in geom.geoms]
        parts = [p for p in parts if p is not None and not p.is_empty]
        if not parts:
            return None
        return unary_union(parts)
    return None


def _outer_rings(geom: BaseGeometry) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [LineString(geom.exterior.coords)]
    if geom.geom_type == "MultiPolygon":
        return [LineString(poly.exterior.coords) for poly in geom.geoms if not poly.is_empty]
    return []


# --- Overture ---------------------------------------------------------------


def _from_overture(
    raw_dir: Path,
    files: dict[str, dict],
    classes: FeatureClasses,
    clip: BaseGeometry,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    out.extend(_overture_segments(raw_dir, files, classes, clip))
    out.extend(_overture_water(raw_dir, files, classes, clip))
    out.extend(_overture_land_use(raw_dir, files, classes, clip))
    out.extend(_overture_divisions(raw_dir, files, classes, clip))
    return out


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


def _overture_segments(
    raw_dir: Path, files: dict[str, dict], classes: FeatureClasses, clip: BaseGeometry
) -> list[dict[str, Any]]:
    gdf = _read_parquet(raw_dir, files, "overture_transportation_segment")
    if gdf is None or gdf.empty:
        return []

    include_highway = set(classes.included("highway"))
    exclude_highway = set(classes.excluded("highway"))
    include_railway = set(classes.included("railway"))
    out: list[dict[str, Any]] = []

    for idx, row in gdf.iterrows():
        subtype = row.get("subtype")
        klass = row.get("class")
        fid = str(row.get("id") or idx)
        geom = row.geometry

        if subtype == "road":
            if klass in exclude_highway or klass not in include_highway:
                continue
            if _overture_road_excluded_by_service(row, classes):
                continue
            feature = _line_feature(
                geom,
                source="overture",
                group="highway",
                class_name=str(klass),
                feature_id=fid,
                clip=clip,
            )
            if feature:
                out.append(feature)
        elif subtype == "rail":
            mapped = _OVERTURE_RAIL_CLASS.get(str(klass), "rail")
            if mapped not in include_railway:
                continue
            feature = _line_feature(
                geom,
                source="overture",
                group="railway",
                class_name=mapped,
                feature_id=fid,
                clip=clip,
            )
            if feature:
                out.append(feature)

    return out


def _overture_road_excluded_by_service(row: Any, classes: FeatureClasses) -> bool:
    """Exclusion beats inclusion: driveway-like service tags kill a road.

    Overture exposes these via subclass / road_flags rather than OSM's
    `service=*` tag. Treat known parking/driveway markers as excluded.
    """
    excluded = set(classes.excluded("service"))
    subclass = str(row.get("subclass") or "")
    if subclass in excluded or subclass in {"parking_aisle", "driveway", "alley"}:
        return True
    return False


def _overture_water(
    raw_dir: Path, files: dict[str, dict], classes: FeatureClasses, clip: BaseGeometry
) -> list[dict[str, Any]]:
    gdf = _read_parquet(raw_dir, files, "overture_base_water")
    if gdf is None or gdf.empty:
        return []

    include_waterway = set(classes.included("waterway"))
    area_tags = set(classes.included("area_boundary"))
    out: list[dict[str, Any]] = []

    for idx, row in gdf.iterrows():
        klass = str(row.get("class") or "")
        subtype = str(row.get("subtype") or "")
        fid = str(row.get("id") or idx)
        geom = row.geometry
        geom_type = geom.geom_type if geom is not None else ""

        if geom_type in {"LineString", "MultiLineString"}:
            # Overture uses class=drain for canals/drains; subtype may say canal.
            waterway_class = klass if klass in include_waterway else (
                subtype if subtype in include_waterway else None
            )
            if waterway_class is None:
                continue
            feature = _line_feature(
                geom,
                source="overture",
                group="waterway",
                class_name=waterway_class,
                feature_id=fid,
                clip=clip,
            )
            if feature:
                out.append(feature)
        elif geom_type in {"Polygon", "MultiPolygon"}:
            tag = _OVERTURE_CLASS_TO_AREA_TAG.get(klass)
            if tag is None or tag not in area_tags:
                continue
            for ring in _outer_rings(geom):
                feature = _line_feature(
                    ring,
                    source="overture",
                    group="area_boundary",
                    class_name=tag,
                    feature_id=fid,
                    clip=clip,
                )
                if feature:
                    out.append(feature)

    return out


def _overture_land_use(
    raw_dir: Path, files: dict[str, dict], classes: FeatureClasses, clip: BaseGeometry
) -> list[dict[str, Any]]:
    gdf = _read_parquet(raw_dir, files, "overture_base_land_use")
    if gdf is None or gdf.empty:
        return []

    area_tags = set(classes.included("area_boundary"))
    out: list[dict[str, Any]] = []

    for idx, row in gdf.iterrows():
        fid = str(row.get("id") or idx)
        geom = row.geometry
        tag = _match_area_tag(row.get("source_tags"), row.get("class"), area_tags)
        if tag is None:
            continue
        for ring in _outer_rings(geom):
            feature = _line_feature(
                ring,
                source="overture",
                group="area_boundary",
                class_name=tag,
                feature_id=fid,
                clip=clip,
            )
            if feature:
                out.append(feature)

    return out


def _match_area_tag(source_tags: Any, klass: Any, area_tags: set[str]) -> str | None:
    for key, value in _iter_source_tags(source_tags):
        token = f"{key}={value}"
        if token in area_tags:
            return token
    mapped = _OVERTURE_CLASS_TO_AREA_TAG.get(str(klass or ""))
    if mapped in area_tags:
        return mapped
    return None


def _iter_source_tags(source_tags: Any) -> list[tuple[str, str]]:
    if source_tags is None:
        return []
    pairs: list[tuple[str, str]] = []
    try:
        for item in source_tags:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                pairs.append((str(item[0]), str(item[1])))
            elif isinstance(item, dict) and "key" in item and "value" in item:
                pairs.append((str(item["key"]), str(item["value"])))
    except TypeError:
        return []
    return pairs


def _overture_divisions(
    raw_dir: Path, files: dict[str, dict], classes: FeatureClasses, clip: BaseGeometry
) -> list[dict[str, Any]]:
    include_div = set(classes.included("division"))
    out: list[dict[str, Any]] = []

    areas = _read_parquet(raw_dir, files, "overture_divisions_division_area")
    if areas is not None and not areas.empty:
        for idx, row in areas.iterrows():
            subtype = str(row.get("subtype") or "")
            if subtype not in include_div:
                continue
            fid = str(row.get("id") or idx)
            for ring in _outer_rings(row.geometry):
                feature = _line_feature(
                    ring,
                    source="overture",
                    group="division",
                    class_name=subtype,
                    feature_id=fid,
                    clip=clip,
                )
                if feature:
                    out.append(feature)

    boundaries = _read_parquet(raw_dir, files, "overture_divisions_division_boundary")
    if boundaries is not None and not boundaries.empty:
        for idx, row in boundaries.iterrows():
            subtype = str(row.get("subtype") or "")
            if subtype not in include_div:
                continue
            fid = str(row.get("id") or idx)
            feature = _line_feature(
                row.geometry,
                source="overture",
                group="division",
                class_name=subtype,
                feature_id=fid,
                clip=clip,
            )
            if feature:
                out.append(feature)

    return out


# --- OSM / Geofabrik --------------------------------------------------------


def _from_osm(
    raw_dir: Path,
    files: dict[str, dict],
    classes: FeatureClasses,
    clip: BaseGeometry,
    bbox: BBox,
) -> list[dict[str, Any]]:
    entry = files.get("geofabrik_extract")
    if not entry:
        return []
    src = raw_dir / entry["filename"]
    if not src.exists():
        raise FileNotFoundError(f"manifest lists geofabrik_extract but file missing: {src}")

    clipped = raw_dir / f"{src.stem}.aoi.osm.pbf"
    _osmium_extract(src, clipped, bbox, CLIP_MARGIN_M)

    out: list[dict[str, Any]] = []
    out.extend(_osm_lines(clipped, classes, clip))
    out.extend(_osm_area_boundaries(clipped, classes, clip))
    return out


def _osmium_extract(src: Path, dest: Path, bbox: BBox, margin_m: float) -> None:
    """Clip a regional PBF down to the AOI so GDAL can read it quickly.

    Relies on the `osmium` CLI (`brew install osmium-tool`). Without it, stage
    02 would have to scan half a gigabyte of southern-India OSM on every run.
    """
    osmium = shutil.which("osmium")
    if osmium is None:
        raise RuntimeError(
            "osmium CLI not found on PATH. Install osmium-tool "
            "(e.g. `brew install osmium-tool`) so stage 02 can clip the Geofabrik extract."
        )

    # Approximate degree margin from metres at Bengaluru latitude (~111 km/deg).
    pad = margin_m / 111_320.0
    west = bbox.west - pad
    south = bbox.south - pad
    east = bbox.east + pad
    north = bbox.north + pad

    if dest.exists() and dest.stat().st_mtime >= src.stat().st_mtime:
        return

    subprocess.run(
        [
            osmium,
            "extract",
            "--strategy=complete_ways",
            f"--bbox={west},{south},{east},{north}",
            f"--output={dest}",
            "--overwrite",
            str(src),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _parse_other_tags(other_tags: Any) -> dict[str, str]:
    if not isinstance(other_tags, str) or not other_tags:
        return {}
    return {k: v for k, v in _OTHER_TAGS_RE.findall(other_tags)}


def _osm_tags(row: dict[str, Any]) -> dict[str, str]:
    tags = _parse_other_tags(row.get("other_tags"))
    for key in (
        "highway",
        "railway",
        "waterway",
        "leisure",
        "landuse",
        "amenity",
        "natural",
        "name",
    ):
        value = row.get(key)
        if value is not None and str(value) not in {"", "None", "nan"}:
            tags[key] = str(value)
    return tags


def _osm_lines(path: Path, classes: FeatureClasses, clip: BaseGeometry) -> list[dict[str, Any]]:
    gdf = gpd.read_file(path, layer="lines")
    if gdf.empty:
        return []

    include_highway = set(classes.included("highway"))
    exclude_highway = set(classes.excluded("highway"))
    include_railway = set(classes.included("railway"))
    include_waterway = set(classes.included("waterway"))
    exclude_service = set(classes.excluded("service"))
    out: list[dict[str, Any]] = []

    for idx, row in gdf.iterrows():
        tags = _osm_tags(row.to_dict())
        fid = str(row.get("osm_id") or idx)
        geom = row.geometry

        highway = tags.get("highway")
        if highway is not None:
            if highway in exclude_highway or highway not in include_highway:
                continue
            if tags.get("service") in exclude_service:
                continue
            feature = _line_feature(
                geom, source="osm", group="highway", class_name=highway, feature_id=fid, clip=clip
            )
            if feature:
                out.append(feature)
            continue

        railway = tags.get("railway")
        if railway is not None and railway in include_railway:
            feature = _line_feature(
                geom, source="osm", group="railway", class_name=railway, feature_id=fid, clip=clip
            )
            if feature:
                out.append(feature)
            continue

        waterway = tags.get("waterway")
        if waterway is not None and waterway in include_waterway:
            feature = _line_feature(
                geom, source="osm", group="waterway", class_name=waterway, feature_id=fid, clip=clip
            )
            if feature:
                out.append(feature)

    return out


def _osm_area_boundaries(
    path: Path, classes: FeatureClasses, clip: BaseGeometry
) -> list[dict[str, Any]]:
    gdf = gpd.read_file(path, layer="multipolygons")
    if gdf.empty:
        return []

    area_tags = set(classes.included("area_boundary"))
    out: list[dict[str, Any]] = []

    for idx, row in gdf.iterrows():
        tags = _osm_tags(row.to_dict())
        matched = None
        for key in ("leisure", "landuse", "amenity", "natural"):
            if key in tags:
                token = f"{key}={tags[key]}"
                if token in area_tags:
                    matched = token
                    break
        if matched is None:
            continue
        fid = str(row.get("osm_id") or idx)
        for ring in _outer_rings(row.geometry):
            feature = _line_feature(
                ring,
                source="osm",
                group="area_boundary",
                class_name=matched,
                feature_id=fid,
                clip=clip,
            )
            if feature:
                out.append(feature)

    return out
