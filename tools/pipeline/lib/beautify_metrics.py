"""Deterministic design metrics for Stage 11 gameplay beautification."""

from __future__ import annotations

from typing import Any

from shapely import STRtree
from shapely.geometry import Polygon, shape
from shapely.geometry.base import BaseGeometry

from lib.contracts import PipelineContext
from lib.crs import to_work
from lib.determinism import stable_sort
from lib.normalize import _as_polygonal, _shared_border_length
from lib.shape import shape_quality

_BORDER_EPS_M = 0.05
_CORNER_SIMPLIFY_M = 5.0


def compute_gameplay_metrics(
    features: list[dict[str, Any]],
    ctx: PipelineContext,
) -> list[dict[str, Any]]:
    """Return per-territory design metrics sorted by territory_id."""
    crs_work = ctx.region.crs_work
    min_shared = float(ctx.thresholds.gameplay.min_shared_border_m)
    max_aspect = float(ctx.thresholds.beautify.max_aspect_ratio)

    entries: list[dict[str, Any]] = []
    geoms: list[BaseGeometry] = []
    for feature in features:
        props = dict(feature.get("properties") or {})
        tid = str(props.get("territory_id") or "")
        geom_json = feature.get("geometry")
        if not tid or not geom_json:
            continue
        try:
            store = shape(geom_json)
        except Exception:
            continue
        work = _as_polygonal(to_work(store, crs_work))
        if work is None or work.is_empty:
            continue
        entries.append({"feature": feature, "props": props, "tid": tid, "geom": work})
        geoms.append(work)

    if not entries:
        return []

    tree = STRtree(geoms)
    metrics: list[dict[str, Any]] = []
    for i, entry in enumerate(entries):
        geom: BaseGeometry = entry["geom"]
        props = entry["props"]
        quality = shape_quality(geom)
        area = float(quality["area_m2"])
        convex = geom.convex_hull
        convex_area = float(convex.area) if convex is not None and not convex.is_empty else 0.0
        convex_peri = float(convex.length) if convex is not None and not convex.is_empty else 0.0
        convexity = (area / convex_area) if convex_area > 0 else 0.0
        boundary_complexity = (
            (float(quality["perimeter_m"]) / convex_peri) if convex_peri > 0 else 0.0
        )
        corner_count = _corner_count(geom)
        aspect = float(quality["aspect_ratio"])

        neighbours: list[dict[str, Any]] = []
        candidate_idxs = tree.query(geom.buffer(_BORDER_EPS_M))
        for j in candidate_idxs:
            j = int(j)
            if j == i:
                continue
            other = entries[j]
            shared = _shared_border_length(geom, other["geom"])
            if shared < min_shared:
                continue
            neighbours.append(
                {
                    "territory_id": other["tid"],
                    "shared_border_m": round(shared, 3),
                }
            )
        neighbours = stable_sort(
            neighbours,
            key=lambda n: (-float(n["shared_border_m"]), str(n["territory_id"])),
        )

        metrics.append(
            {
                "territory_id": entry["tid"],
                "name": props.get("name"),
                "slug": props.get("slug"),
                "kind": props.get("kind"),
                "protected": props.get("protected") is True,
                "landmark_dedicated": props.get("landmark_dedicated") is True,
                "atomic": props.get("atomic") is True,
                "member_count": int(props.get("member_count") or 0),
                "member_territory_ids": list(props.get("member_territory_ids") or []),
                "place_key": props.get("place_key"),
                "area_m2": quality["area_m2"],
                "area_acres": quality["area_acres"],
                "above_target_area": area > ctx.thresholds.gameplay.soft_max_m2,
                "above_hard_max_area": area > ctx.thresholds.gameplay.hard_max_m2,
                "perimeter_m": quality["perimeter_m"],
                "compactness": quality["compactness"],
                "length_m": quality["length_m"],
                "breadth_m": quality["breadth_m"],
                "aspect_ratio": quality["aspect_ratio"],
                "is_strip": aspect > max_aspect + 1e-9,
                "convexity": round(convexity, 6),
                "corner_count": corner_count,
                "boundary_complexity": round(boundary_complexity, 6),
                "neighbour_count": len(neighbours),
                "neighbours": neighbours,
                "park_area_ratio": None,
                "road_hierarchy_score": None,
            }
        )

    return stable_sort(metrics, key=lambda m: str(m["territory_id"]))


def _corner_count(geom: BaseGeometry) -> int:
    """Approx exterior-ring vertex count after light simplify."""
    simplified = geom.simplify(_CORNER_SIMPLIFY_M, preserve_topology=True)
    poly = _as_polygonal(simplified)
    if poly is None or poly.is_empty:
        return 0
    if isinstance(poly, Polygon):
        coords = list(poly.exterior.coords) if poly.exterior else []
        # Ring is closed; drop duplicate last vertex.
        return max(0, len(coords) - 1) if len(coords) > 1 else len(coords)
    total = 0
    for part in getattr(poly, "geoms", ()):
        if isinstance(part, Polygon) and part.exterior:
            coords = list(part.exterior.coords)
            total += max(0, len(coords) - 1) if len(coords) > 1 else len(coords)
    return total
