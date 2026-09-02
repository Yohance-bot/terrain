"""Measurement happens in metres, never in degrees.

The failure this guards against is quiet: `polygon.area` on EPSG:4326
coordinates returns a number, that number gets compared against a threshold in
square metres, and the pipeline produces a plausible-looking map built on
nonsense. These tests pin the conversion helpers so that never depends on a
stage author remembering.
"""

from __future__ import annotations

import pytest
from shapely.geometry import Polygon, box

from lib.crs import geodesic_area_m2, geodesic_length_m, to_store, to_work

WORK = "EPSG:32643"

# A square kilometre in UTM 43N, positioned over Bengaluru.
UTM_SQUARE_KM = box(780_000, 1_430_000, 781_000, 1_431_000)


def test_roundtrip_returns_the_original_geometry():
    wgs84 = to_store(UTM_SQUARE_KM, WORK)
    back = to_work(wgs84, WORK)
    assert back.equals_exact(UTM_SQUARE_KM, tolerance=1e-6)


def test_projected_and_geodesic_area_agree():
    """Cross-check that stage 08 relies on.

    Two independent paths to the same number. When they disagree by more than
    UTM's own distortion, something was measured in the wrong CRS.
    """
    wgs84 = to_store(UTM_SQUARE_KM, WORK)
    assert geodesic_area_m2(wgs84) == pytest.approx(UTM_SQUARE_KM.area, rel=0.01)


def test_degree_area_is_not_square_metres():
    """The mistake this module exists to prevent.

    A one-square-kilometre polygon has an area of roughly 0.00008 in degrees.
    Compared against `scrap_m2` of 5000 it would be merged away as a sliver.
    """
    wgs84 = to_store(UTM_SQUARE_KM, WORK)
    assert wgs84.area < 1.0
    assert geodesic_area_m2(wgs84) == pytest.approx(1_000_000, rel=0.01)


def test_geodesic_length_measures_a_perimeter_in_metres():
    wgs84 = to_store(UTM_SQUARE_KM, WORK)
    assert geodesic_length_m(wgs84) == pytest.approx(4_000, rel=0.01)


def test_empty_geometry_measures_zero():
    assert geodesic_area_m2(Polygon()) == 0.0
    assert geodesic_length_m(Polygon()) == 0.0


def test_longitude_latitude_order_is_preserved():
    """Guards the `always_xy` setting in lib/crs.

    EPSG:4326 declares latitude first. Without `always_xy` pyproj honours that
    and silently swaps every coordinate in the pipeline, putting Bengaluru in
    the Indian Ocean.
    """
    wgs84 = to_store(UTM_SQUARE_KM, WORK)
    minx, miny, maxx, maxy = wgs84.bounds
    assert 77.0 < minx < 78.5, "x should be longitude"
    assert 12.0 < miny < 14.0, "y should be latitude"
    assert maxx > minx and maxy > miny
