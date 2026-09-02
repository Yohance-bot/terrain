"""Coordinate reference system handling.

Implemented in Phase A rather than stubbed, because getting this wrong is the
single easiest way to produce territories that look plausible and are quietly
nonsense.

The rule, from `03_MAP_AND_TERRITORY_PIPELINE`: measurement happens in a
projected CRS in metres. Storage happens in EPSG:4326. A degree of longitude at
Bengaluru's latitude is about 108 km and a degree of latitude is about 110.6 km,
so `shapely_geometry.area` on 4326 coordinates returns a number in square
degrees that is neither square metres nor consistently scaled. Any threshold in
`thresholds.yaml` compared against such a number is meaningless.

Use `to_work` before measuring anything, and `to_store` before writing anything.
"""

from __future__ import annotations

from functools import lru_cache

from pyproj import CRS, Geod, Transformer
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

# WGS84 ellipsoid, used for area/length on unprojected geometry. Slower than
# working in UTM but exact regardless of zone, so it is the reference the
# validation stage checks the projected numbers against.
_GEOD = Geod(ellps="WGS84")


@lru_cache(maxsize=32)
def _transformer(source: str, target: str) -> Transformer:
    """Transformers are expensive to build and cheap to reuse.

    `always_xy` forces longitude/latitude ordering. Without it pyproj honours
    the axis order declared by the CRS authority, which for EPSG:4326 is
    latitude first -- silently swapping every coordinate in the pipeline.
    """
    return Transformer.from_crs(
        CRS.from_user_input(source), CRS.from_user_input(target), always_xy=True
    )


def project(geometry: BaseGeometry, source: str, target: str) -> BaseGeometry:
    """Reproject a shapely geometry between two CRS identifiers."""
    return transform(_transformer(source, target).transform, geometry)


def to_work(geometry: BaseGeometry, crs_work: str, crs_store: str = "EPSG:4326") -> BaseGeometry:
    """Storage CRS to working CRS. Call this before measuring."""
    return project(geometry, crs_store, crs_work)


def to_store(geometry: BaseGeometry, crs_work: str, crs_store: str = "EPSG:4326") -> BaseGeometry:
    """Working CRS back to storage CRS. Call this before writing."""
    return project(geometry, crs_work, crs_store)


def geodesic_area_m2(geometry: BaseGeometry) -> float:
    """Area in square metres of a geometry given in EPSG:4326.

    Independent of the UTM path, which is why stage 08 uses it to sanity-check
    projected areas. A large disagreement between the two means something was
    measured in the wrong CRS.
    """
    if geometry.is_empty:
        return 0.0
    area, _perimeter = _GEOD.geometry_area_perimeter(geometry)
    return abs(area)


def geodesic_length_m(geometry: BaseGeometry) -> float:
    """Length in metres of a line given in EPSG:4326."""
    if geometry.is_empty:
        return 0.0
    _area, perimeter = _GEOD.geometry_area_perimeter(geometry)
    return abs(perimeter)
