"""Shared shape quality helpers for Stage 10 expansion and Stage 11 beautify."""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry.base import BaseGeometry

from lib.normalize import _as_polygonal

_M2_PER_ACRE = 4046.8564224


def shape_quality(geom: BaseGeometry) -> dict[str, float]:
    """Return compactness and min-rotated-rectangle aspect metrics."""
    poly = _as_polygonal(geom)
    if poly is None or poly.is_empty:
        return {
            "area_m2": 0.0,
            "area_acres": 0.0,
            "perimeter_m": 0.0,
            "compactness": 0.0,
            "length_m": 0.0,
            "breadth_m": 0.0,
            "aspect_ratio": 0.0,
        }

    area = float(poly.area)
    perimeter = float(poly.length)
    compactness = (
        (4.0 * math.pi * area / (perimeter * perimeter)) if perimeter > 0 else 0.0
    )

    length_m = 0.0
    breadth_m = 0.0
    aspect = 0.0
    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mrr = poly.minimum_rotated_rectangle
        if mrr is not None and not mrr.is_empty:
            coords = list(mrr.exterior.coords) if hasattr(mrr, "exterior") else []
            if len(coords) >= 4:
                edges = [
                    math.hypot(coords[i + 1][0] - coords[i][0], coords[i + 1][1] - coords[i][1])
                    for i in range(4)
                ]
                # Adjacent edges of the rectangle: take the first two sides.
                side_a = edges[0]
                side_b = edges[1]
                length_m = max(side_a, side_b)
                breadth_m = min(side_a, side_b)
                aspect = (length_m / breadth_m) if breadth_m > 1e-9 else float("inf")
    except Exception:
        length_m = 0.0
        breadth_m = 0.0
        aspect = float("inf")

    return {
        "area_m2": round(area, 3),
        "area_acres": round(area / _M2_PER_ACRE, 3),
        "perimeter_m": round(perimeter, 3),
        "compactness": round(compactness, 6),
        "length_m": round(length_m, 3),
        "breadth_m": round(breadth_m, 3),
        "aspect_ratio": round(aspect, 6) if math.isfinite(aspect) else 1e9,
    }


def shape_score(
    geom: BaseGeometry,
    *,
    max_aspect_ratio: float,
) -> float:
    """Higher is better: prefer low aspect and high compactness under the cap."""
    metrics = shape_quality(geom)
    aspect = float(metrics["aspect_ratio"])
    compactness = float(metrics["compactness"])
    # Soft penalty above the aspect cap; still rankable when all candidates exceed.
    aspect_penalty = max(0.0, aspect - max_aspect_ratio)
    return compactness - 0.15 * aspect_penalty - 0.05 * max(0.0, aspect - 1.0)


def is_strip(
    geom: BaseGeometry,
    *,
    max_aspect_ratio: float,
) -> bool:
    return float(shape_quality(geom)["aspect_ratio"]) > max_aspect_ratio + 1e-9


def metrics_payload(geom: BaseGeometry) -> dict[str, Any]:
    return shape_quality(geom)
