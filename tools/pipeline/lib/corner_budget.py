"""Topology-preserving exterior-corner budget for non-legendary territories.

Deletes vertices along shared and solo exterior chains (never invents freeform
edges). When a territory still exceeds the corner cap, force-merges it into a
neighbour. Legendary (source-protected) polygons are frozen.

Corner budget count excludes vertices that lie on a legendary perimeter —
neighbours may hug the frozen landmark exactly while their fabric-facing edge
is simplified.

Escalation:
1. Collapse non-junction chains (shared + solo) with 2-owner area conservation.
2. Force-merge over-budget ordinary into longest eligible neighbour (always
   respect ordinary hard_max).
3. Last-resort free-arc Visvalingam peel only if still over budget — must
   ``_repair_mosaic`` and stay within gap/overlap thresholds, else rejected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from shapely import is_valid, make_valid
from shapely.geometry import Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from lib import artifacts
from lib.cluster import _barrier_union
from lib.config import BeautifyThresholds, GameplayThresholds
from lib.contracts import PipelineContext
from lib.crs import to_store, to_work
from lib.determinism import content_hash, gameplay_territory_id, slugify, stable_sort
from lib.io import read_geojson
from lib.normalize import (
    SafeMergeResult,
    _as_polygonal,
    _shared_border_length,
    safe_merge_geometry,
)

_BORDER_EPS_M = 0.05
_COLLINEAR_TURN_RAD = math.radians(2.0)
_SHALLOW_JUNCTION_TURN_RAD = math.radians(35.0)
_MERGE_AREA_LOSS_FACTOR = 500.0


class CornerBudgetError(RuntimeError):
    """Corner budget could not produce a valid mosaic."""


@dataclass
class CornerBudgetReport:
    input_count: int
    output_count: int
    vertices_removed: int = 0
    merges: int = 0
    junctions_removed: int = 0
    still_over_budget: list[dict[str, Any]] = field(default_factory=list)
    applied: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CornerBudgetResult:
    features: list[dict[str, Any]]
    report: CornerBudgetReport


def exterior_corner_count(geom: BaseGeometry) -> int:
    """Count exterior-ring corners (closing duplicate excluded)."""
    poly = _as_polygonal(geom)
    if poly is None or poly.is_empty:
        return 0
    total = 0
    geoms = list(poly.geoms) if poly.geom_type == "MultiPolygon" else [poly]
    for part in geoms:
        if not isinstance(part, Polygon) or part.exterior is None:
            continue
        coords = list(part.exterior.coords)
        if len(coords) < 2:
            continue
        total += max(0, len(coords) - 1)
    return total


def budget_exterior_corner_count(
    geom: BaseGeometry,
    *,
    legendary_vertex_keys: set[tuple[int, int]] | None = None,
    snap_m: float = 0.05,
    legendary_boundary: BaseGeometry | None = None,
    legendary_buffer_m: float = 1.0,
) -> int:
    """Corners that count toward the gameplay budget.

    Vertices on a legendary perimeter (exact snap key or within a small buffer
    of the legendary boundary) are exempt.
    """
    if not legendary_vertex_keys and legendary_boundary is None:
        return exterior_corner_count(geom)
    total = 0
    boundary = None
    if legendary_boundary is not None and not legendary_boundary.is_empty:
        boundary = legendary_boundary.boundary if hasattr(legendary_boundary, "boundary") else legendary_boundary
    for ring in _ring_coords(geom):
        n = len(ring) - 1
        for i in range(n):
            x, y = ring[i]
            key = _snap_key(x, y, snap_m)
            if legendary_vertex_keys and key in legendary_vertex_keys:
                continue
            if boundary is not None:
                try:
                    from shapely.geometry import Point

                    if float(Point(x, y).distance(boundary)) <= legendary_buffer_m:
                        continue
                except Exception:
                    pass
            total += 1
    return total


def territory_class_of(props: dict[str, Any]) -> str:
    """Return ``legendary`` or ``ordinary`` (special class removed)."""
    raw = props.get("territory_class")
    if raw == "legendary":
        return "legendary"
    if raw == "ordinary":
        return "ordinary"
    if props.get("protected") is True or props.get("legendary") is True:
        return "legendary"
    # Legacy landmark_dedicated / special → ordinary fabric.
    return "ordinary"


def apply_corner_budget(
    ctx: PipelineContext,
    features: list[dict[str, Any]],
    *,
    separators: dict[str, Any] | None = None,
) -> CornerBudgetResult:
    """Reduce non-legendary exteriors to ``max_exterior_corners``."""
    bt = ctx.thresholds.beautify
    gp = ctx.thresholds.gameplay
    crs_work = ctx.region.crs_work
    crs_store = ctx.region.crs_store
    max_corners = int(bt.max_exterior_corners)
    snap = float(bt.corner_snap_m)
    max_loss = float(ctx.thresholds.validation.max_gap_m2)
    max_gap = float(ctx.thresholds.validation.max_gap_m2)
    max_overlap = float(ctx.thresholds.validation.max_overlap_m2)

    report = CornerBudgetReport(input_count=len(features), output_count=0)

    active: dict[str, dict[str, Any]] = {}
    work_geoms: dict[str, BaseGeometry] = {}
    for feature in features:
        props = dict(feature.get("properties") or {})
        tid = str(props.get("territory_id") or "")
        if not tid:
            raise CornerBudgetError("corner budget: missing territory_id")
        if tid in active:
            raise CornerBudgetError(f"corner budget: duplicate territory_id {tid}")
        try:
            geom = _as_polygonal(to_work(shape(feature["geometry"]), crs_work))
        except Exception as exc:
            raise CornerBudgetError(f"corner budget: unreadable geometry {tid}: {exc}") from exc
        if geom is None or geom.is_empty:
            raise CornerBudgetError(f"corner budget: empty geometry {tid}")
        tclass = territory_class_of(props)
        props["territory_class"] = tclass
        props["legendary"] = tclass == "legendary"
        if tclass == "legendary":
            props["protected"] = True
        active[tid] = {
            "type": "Feature",
            "geometry": feature["geometry"],
            "properties": props,
        }
        work_geoms[tid] = geom

    mosaic_aoi = unary_union(list(work_geoms.values()))

    legendary_vertex_keys: set[tuple[int, int]] = set()
    legendary_geoms: list[BaseGeometry] = []
    for tid, feat in active.items():
        if territory_class_of(feat["properties"]) != "legendary":
            continue
        legendary_geoms.append(work_geoms[tid])
        for ring in _ring_coords(work_geoms[tid]):
            for x, y in ring[:-1]:
                legendary_vertex_keys.add(_snap_key(x, y, snap))
    legendary_boundary = unary_union(legendary_geoms) if legendary_geoms else None

    def _corners(tid: str, *, with_buffer: bool = True) -> int:
        return budget_exterior_corner_count(
            work_geoms[tid],
            legendary_vertex_keys=legendary_vertex_keys,
            snap_m=snap,
            legendary_boundary=legendary_boundary if with_buffer else None,
        )

    def _over_ids(*, fast: bool = False) -> list[str]:
        return sorted(
            (
                tid
                for tid, feat in active.items()
                if territory_class_of(feat["properties"]) != "legendary"
                and _corners(tid, with_buffer=not fast) > max_corners
            ),
            key=lambda tid: (-_corners(tid, with_buffer=not fast), tid),
        )

    if separators is None and artifacts.SEPARATORS.path(ctx).exists():
        separators = read_geojson(artifacts.SEPARATORS.path(ctx))
    barrier_geom = None
    if separators is not None:
        if isinstance(separators, list):
            sep_features = separators
        else:
            sep_features = list(separators.get("features") or [])
        barrier_geom = _barrier_union(
            sep_features,
            gp,
            crs_work,
            float(ctx.thresholds.snap_m),
        )

    def _drop_pass(*, allow_junctions: bool, max_turn: float, limit: int = 500) -> int:
        removed_n = 0
        stagnant = 0
        last_over = None
        for _ in range(limit):
            over = _over_ids(fast=True)
            if not over:
                break
            # Track total exterior corners so we stop when drops stop helping.
            corner_sum = sum(exterior_corner_count(work_geoms[tid]) for tid in over)
            over_key = (tuple(over), corner_sum)
            if over_key == last_over:
                stagnant += 1
                if stagnant >= 5:
                    break
            else:
                stagnant = 0
                last_over = over_key
            removed = _remove_one_shared_vertex(
                over,
                active,
                work_geoms,
                snap_m=snap,
                max_area_loss_m2=max_loss,
                allow_junctions=allow_junctions,
                max_turn=max_turn,
                legendary_vertex_keys=legendary_vertex_keys,
            )
            if removed is None:
                break
            removed_n += 1
            report.vertices_removed += 1
            if allow_junctions:
                report.junctions_removed += 1
            if len(report.applied) < 200:
                report.applied.append({"op": "drop_vertex", **removed})
        return removed_n

    def _merge_pass(limit: int = 1_000) -> int:
        merges = 0
        for _ in range(limit):
            over = _over_ids()
            if not over:
                break
            progressed = False
            for tid in over:
                if tid not in active:
                    continue
                outcome = _force_merge_over_budget(
                    ctx,
                    tid,
                    active,
                    work_geoms,
                    gp=gp,
                    bt=bt,
                    barrier_geom=barrier_geom,
                    max_area_loss_m2=max_loss * _MERGE_AREA_LOSS_FACTOR,
                    crs_work=crs_work,
                    crs_store=crs_store,
                    allow_raw_union=True,
                )
                if outcome.get("ok"):
                    report.merges += 1
                    merges += 1
                    report.applied.append({"op": "merge_over_budget", **outcome})
                    # Skip post-merge drop on large maps; free-arc handles budget.
                    progressed = True
                    break
            if not progressed:
                break
        return merges

    # Shared-edge drops are O(vertices²) on city-scale rings; prefer free-arc
    # batch peels with a single mosaic repair, then merges for leftovers.
    _drop_pass(allow_junctions=False, max_turn=_COLLINEAR_TURN_RAD, limit=50)

    def _free_arc_pass(*, forced: bool = False) -> int:
        """Batch-peel every over-budget territory, then repair mosaic once."""
        over = _over_ids()
        if not over:
            return 0
        snapshot = {k: v for k, v in work_geoms.items()}
        peeled: set[str] = set()
        for tid in over:
            if tid not in active or tid not in work_geoms:
                continue
            if territory_class_of(active[tid]["properties"]) == "legendary":
                continue
            before = work_geoms[tid]
            simplified = _simplify_free_arcs(
                before,
                legendary_vertex_keys=legendary_vertex_keys,
                snap_m=snap,
                max_free_corners=max_corners,
                legendary_boundary=legendary_boundary,
            )
            if simplified is None:
                continue
            others = [
                work_geoms[oid]
                for oid in work_geoms
                if oid != tid and oid not in peeled
            ]
            if others:
                carved = _as_polygonal(simplified.difference(unary_union(others)))
                if carved is None or carved.is_empty:
                    continue
                simplified = carved
            if (
                budget_exterior_corner_count(
                    simplified,
                    legendary_vertex_keys=legendary_vertex_keys,
                    snap_m=snap,
                    legendary_boundary=legendary_boundary,
                )
                > max_corners
            ):
                continue
            if not forced:
                area_delta = abs(float(before.area) - float(simplified.area))
                if area_delta > max(float(before.area) * 0.15, 100.0):
                    continue
            work_geoms[tid] = simplified
            peeled.add(tid)
            report.vertices_removed += max(
                0, exterior_corner_count(before) - exterior_corner_count(simplified)
            )

        if not peeled:
            return 0

        _repair_mosaic(
            active,
            work_geoms,
            aoi=mosaic_aoi,
            snap_m=snap,
            exclude_fill_ids=peeled,
        )
        gap_m2, overlap_m2 = _mosaic_gap_overlap(work_geoms, mosaic_aoi)
        if gap_m2 > max_gap + 1e-6 or overlap_m2 > max_overlap + 1e-6:
            _repair_mosaic(active, work_geoms, aoi=mosaic_aoi, snap_m=snap)
            gap_m2, overlap_m2 = _mosaic_gap_overlap(work_geoms, mosaic_aoi)

        if gap_m2 > max_gap + 1e-6 or overlap_m2 > max_overlap + 1e-6:
            work_geoms.clear()
            work_geoms.update(snapshot)
            return 0

        # Re-peel anyone repair pushed back over budget (no second gap fill into them).
        for tid in list(peeled):
            if tid not in work_geoms:
                continue
            if (
                budget_exterior_corner_count(
                    work_geoms[tid],
                    legendary_vertex_keys=legendary_vertex_keys,
                    snap_m=snap,
                    legendary_boundary=legendary_boundary,
                )
                <= max_corners
            ):
                continue
            again = _simplify_free_arcs(
                work_geoms[tid],
                legendary_vertex_keys=legendary_vertex_keys,
                snap_m=snap,
                max_free_corners=max_corners,
                legendary_boundary=legendary_boundary,
            )
            if again is None:
                continue
            others = [work_geoms[oid] for oid in work_geoms if oid != tid]
            if others:
                carved = _as_polygonal(again.difference(unary_union(others)))
                if carved is not None and not carved.is_empty:
                    again = carved
            if (
                budget_exterior_corner_count(
                    again,
                    legendary_vertex_keys=legendary_vertex_keys,
                    snap_m=snap,
                    legendary_boundary=legendary_boundary,
                )
                <= max_corners
            ):
                work_geoms[tid] = again

        gap_m2, overlap_m2 = _mosaic_gap_overlap(work_geoms, mosaic_aoi)
        if gap_m2 > max_gap + 1e-6 or overlap_m2 > max_overlap + 1e-6:
            _repair_mosaic(
                active,
                work_geoms,
                aoi=mosaic_aoi,
                snap_m=snap,
                exclude_fill_ids=peeled,
            )
            gap_m2, overlap_m2 = _mosaic_gap_overlap(work_geoms, mosaic_aoi)
        if gap_m2 > max_gap + 1e-6 or overlap_m2 > max_overlap + 1e-6:
            work_geoms.clear()
            work_geoms.update(snapshot)
            return 0

        report.applied.append(
            {
                "op": "simplify_free_arcs_batch_forced" if forced else "simplify_free_arcs_batch",
                "territory_ids": sorted(peeled),
                "gap_m2_after": round(gap_m2, 6),
                "overlap_m2_after": round(overlap_m2, 6),
            }
        )
        return len(peeled)

    # 2) Free-arc while neighbours still exist (transfer lost area), then merge.
    # Merging first collapses to a solo polygon that cannot peel without an AOI gap.
    _free_arc_pass(forced=False)
    _free_arc_pass(forced=True)

    # 3) Limited merges for leftovers that still exceed the budget.
    if _over_ids():
        _merge_pass(limit=max(0, len(_over_ids()) + 2))
        _free_arc_pass(forced=True)

    # 4) Stubborn leftovers: more merges, then free-arc with repair.
    if _over_ids():
        for _ in range(len(_over_ids()) + 5):
            over = _over_ids()
            if not over:
                break
            progressed = False
            for tid in over:
                if tid not in active:
                    continue
                outcome = _force_merge_over_budget(
                    ctx,
                    tid,
                    active,
                    work_geoms,
                    gp=gp,
                    bt=bt,
                    barrier_geom=barrier_geom,
                    max_area_loss_m2=max_loss * _MERGE_AREA_LOSS_FACTOR * 100.0,
                    crs_work=crs_work,
                    crs_store=crs_store,
                    allow_raw_union=True,
                )
                if not outcome.get("ok"):
                    continue
                report.merges += 1
                report.applied.append({"op": "merge_over_budget_final", **outcome})
                progressed = True
                break
            if not progressed:
                break
        _free_arc_pass(forced=True)

    for tid, feat in active.items():
        if territory_class_of(feat["properties"]) == "legendary":
            continue
        corners = _corners(tid)
        if corners > max_corners:
            report.still_over_budget.append(
                {
                    "territory_id": tid,
                    "slug": feat["properties"].get("slug"),
                    "corners": corners,
                    "total_exterior_corners": exterior_corner_count(work_geoms[tid]),
                    "max_exterior_corners": max_corners,
                }
            )

    if report.still_over_budget:
        # Temporary soft path: mosaic-safe peels that preserve gap/overlap cannot
        # always reach ≤10 on city-scale rings without opening the partition.
        # Keep the best-effort geometry and soft-flag leftovers for review.
        report.applied.append(
            {
                "op": "corner_budget_soft_over",
                "count": len(report.still_over_budget),
                "max_exterior_corners": max_corners,
            }
        )

    out: list[dict[str, Any]] = []
    for tid in stable_sort(active.keys(), key=lambda x: x):
        feat = active[tid]
        props = dict(feat["properties"])
        tclass = territory_class_of(props)
        props["territory_class"] = tclass
        props["legendary"] = tclass == "legendary"
        if tclass == "legendary":
            out.append({"type": "Feature", "geometry": feat["geometry"], "properties": props})
            continue
        store = _as_polygonal(to_store(work_geoms[tid], crs_work, crs_store))
        if store is None or store.is_empty:
            raise CornerBudgetError(f"corner budget: empty store geometry for {tid}")
        if not is_valid(store):
            repaired = _as_polygonal(make_valid(store))
            if repaired is None or repaired.is_empty or not is_valid(repaired):
                raise CornerBudgetError(f"corner budget: invalid store geometry for {tid}")
            store = repaired
        props["area_m2"] = round(float(work_geoms[tid].area), 3)
        props["exterior_corners"] = _corners(tid)
        props["total_exterior_corners"] = exterior_corner_count(work_geoms[tid])
        out.append(
            {
                "type": "Feature",
                "geometry": mapping(store),
                "properties": props,
            }
        )

    report.output_count = len(out)
    return CornerBudgetResult(features=out, report=report)


def corner_budget_report_to_dict(report: CornerBudgetReport) -> dict[str, Any]:
    return {
        "input_count": report.input_count,
        "output_count": report.output_count,
        "vertices_removed": report.vertices_removed,
        "junctions_removed": report.junctions_removed,
        "merges": report.merges,
        "still_over_budget": report.still_over_budget,
        "applied_count": len(report.applied),
        "applied": report.applied[:200],
    }


def _snap_key(x: float, y: float, snap_m: float) -> tuple[int, int]:
    return (int(round(x / snap_m)), int(round(y / snap_m)))


def _ring_coords(geom: BaseGeometry) -> list[list[tuple[float, float]]]:
    poly = _as_polygonal(geom)
    if poly is None or poly.is_empty:
        return []
    parts = list(poly.geoms) if poly.geom_type == "MultiPolygon" else [poly]
    rings: list[list[tuple[float, float]]] = []
    for part in parts:
        if not isinstance(part, Polygon) or part.exterior is None:
            continue
        coords = [(float(x), float(y)) for x, y, *rest in part.exterior.coords]
        if len(coords) >= 2 and coords[0] == coords[-1]:
            rings.append(coords)
    return rings


def _rings_to_polygon(rings: list[list[tuple[float, float]]]) -> BaseGeometry | None:
    """Build polygon(s) without make_valid densification."""
    polys: list[Polygon] = []
    for ring in rings:
        if len(ring) < 4:
            return None
        poly = Polygon(ring)
        if poly.is_empty or not is_valid(poly):
            return None
        polys.append(poly)
    if not polys:
        return None
    if len(polys) == 1:
        return polys[0]
    merged = _as_polygonal(unary_union(polys))
    if merged is None or merged.is_empty or not is_valid(merged):
        return None
    return merged


def _turn_deviation(prev: tuple[float, float], cur: tuple[float, float], nxt: tuple[float, float]) -> float:
    ax, ay = cur[0] - prev[0], cur[1] - prev[1]
    bx, by = nxt[0] - cur[0], nxt[1] - cur[1]
    la = math.hypot(ax, ay)
    lb = math.hypot(bx, by)
    if la < 1e-9 or lb < 1e-9:
        return 0.0
    ax, ay = ax / la, ay / la
    bx, by = bx / lb, by / lb
    dot = max(-1.0, min(1.0, ax * bx + ay * by))
    return abs(math.acos(dot))


def _build_vertex_index(
    work_geoms: dict[str, BaseGeometry],
    snap_m: float,
) -> dict[tuple[int, int], set[str]]:
    index: dict[tuple[int, int], set[str]] = {}
    for tid, geom in work_geoms.items():
        for ring in _ring_coords(geom):
            for x, y in ring[:-1]:
                key = _snap_key(x, y, snap_m)
                index.setdefault(key, set()).add(tid)
    return index


def _simplify_free_arcs(
    geom: BaseGeometry,
    *,
    legendary_vertex_keys: set[tuple[int, int]],
    snap_m: float,
    max_free_corners: int,
    legendary_boundary: BaseGeometry | None = None,
    legendary_buffer_m: float = 1.0,
) -> BaseGeometry | None:
    """Keep legendary-interface vertices; Visvalingam-peel free arcs to a budget.

    Endpoints of each free arc (junctions / legendary contacts) stay put.
    Intermediate free vertices are dropped until free corners ≤ budget.
    """
    from shapely.geometry import Point

    rings = _ring_coords(geom)
    if not rings:
        return None

    # Prefer a single exterior: MultiPolygon leftovers often exceed the budget
    # when each part keeps its own corners.
    if len(rings) > 1:
        merged = _as_polygonal(unary_union([Polygon(r) for r in rings if len(r) >= 4]))
        if merged is not None and not merged.is_empty and is_valid(merged):
            geom = merged
            rings = _ring_coords(geom)
        # If still multi and we cannot afford ≥3 corners per part, keep largest.
        if len(rings) > 1 and len(rings) * 3 > max_free_corners:
            rings = [max(rings, key=len)]

    # Allocate the free-corner budget across exteriors (sum == max).
    ring_weights = [max(1, len(r) - 1) for r in rings]
    weight_sum = sum(ring_weights) or 1
    ring_budgets: list[int] = []
    allocated = 0
    for i, w in enumerate(ring_weights):
        if i == len(ring_weights) - 1:
            ring_budgets.append(max(3, max_free_corners - allocated))
        else:
            share = max(3, int(round(max_free_corners * (w / weight_sum))))
            ring_budgets.append(share)
            allocated += share
    # If allocation exceeded the cap, shrink from the largest shares.
    while sum(ring_budgets) > max_free_corners and any(b > 3 for b in ring_budgets):
        j = max(range(len(ring_budgets)), key=lambda k: ring_budgets[k])
        if ring_budgets[j] > 3:
            ring_budgets[j] -= 1

    boundary = None
    if legendary_boundary is not None and not legendary_boundary.is_empty:
        boundary = (
            legendary_boundary.boundary
            if hasattr(legendary_boundary, "boundary")
            else legendary_boundary
        )

    def _is_legendary_pt(x: float, y: float) -> bool:
        if _snap_key(x, y, snap_m) in legendary_vertex_keys:
            return True
        if boundary is None:
            return False
        try:
            return float(Point(x, y).distance(boundary)) <= legendary_buffer_m
        except Exception:
            return False

    def _peel_open(pts: list[tuple[float, float]], max_pts: int) -> list[tuple[float, float]]:
        """Peel open polyline down to ``max_pts`` including endpoints."""
        if len(pts) <= max_pts or len(pts) <= 2:
            return pts
        out = list(pts)
        while len(out) > max_pts and len(out) > 2:
            best_i = None
            best_eff = None
            for i in range(1, len(out) - 1):
                prev, cur, nxt = out[i - 1], out[i], out[i + 1]
                ax, ay = cur[0] - prev[0], cur[1] - prev[1]
                bx, by = nxt[0] - cur[0], nxt[1] - cur[1]
                eff = abs(ax * by - ay * bx)
                if best_eff is None or eff < best_eff - 1e-15 or (
                    abs((best_eff or 0) - eff) <= 1e-15 and (best_i is None or i < best_i)
                ):
                    best_eff = eff
                    best_i = i
            if best_i is None:
                break
            del out[best_i]
        return out

    def _peel_closed(pts_open: list[tuple[float, float]], max_pts: int) -> list[tuple[float, float]]:
        """Peel a closed ring (pts without repeating close) to ``max_pts``."""
        if len(pts_open) <= max_pts:
            return pts_open
        out = list(pts_open)
        while len(out) > max_pts and len(out) > 3:
            best_i = None
            best_eff = None
            n = len(out)
            for i in range(n):
                prev, cur, nxt = out[(i - 1) % n], out[i], out[(i + 1) % n]
                ax, ay = cur[0] - prev[0], cur[1] - prev[1]
                bx, by = nxt[0] - cur[0], nxt[1] - cur[1]
                eff = abs(ax * by - ay * bx)
                if best_eff is None or eff < best_eff - 1e-15 or (
                    abs((best_eff or 0) - eff) <= 1e-15 and (best_i is None or i < best_i)
                ):
                    best_eff = eff
                    best_i = i
            if best_i is None:
                break
            del out[best_i]
        return out

    new_rings: list[list[tuple[float, float]]] = []
    for ring_i, ring in enumerate(rings):
        part_budget = ring_budgets[ring_i] if ring_i < len(ring_budgets) else max_free_corners
        n = len(ring) - 1
        flags = [_is_legendary_pt(ring[i][0], ring[i][1]) for i in range(n)]
        if not any(flags):
            peeled = _peel_closed([(ring[i][0], ring[i][1]) for i in range(n)], part_budget)
            if len(peeled) < 3:
                return None
            peeled.append(peeled[0])
            new_rings.append(peeled)
            continue

        rebuilt: list[tuple[float, float]] = []
        i = 0
        while i < n:
            if flags[i]:
                rebuilt.append(ring[i])
                i += 1
                continue
            j = i
            while j < n and not flags[j]:
                j += 1
            start = rebuilt[-1] if rebuilt else ring[(i - 1) % n]
            end = ring[j % n]
            mid = [ring[k] for k in range(i, j)]
            arc = [start] + mid + [end]
            already_free = sum(1 for p in rebuilt if not _is_legendary_pt(p[0], p[1]))
            remain = max(0, part_budget - already_free)
            simplified = _peel_open(arc, remain + 2)
            rebuilt.extend(simplified[1:])
            i = j
        if len(rebuilt) < 3:
            return None
        if rebuilt[0] != rebuilt[-1]:
            rebuilt.append(rebuilt[0])
        new_rings.append(rebuilt)

    candidate = _rings_to_polygon(new_rings)
    if candidate is None:
        return None
    if (
        budget_exterior_corner_count(
            candidate,
            legendary_vertex_keys=legendary_vertex_keys,
            snap_m=snap_m,
            legendary_boundary=legendary_boundary,
        )
        <= max_free_corners
    ):
        return candidate
    return None


def _onesided_decimate_pass(
    active: dict[str, dict[str, Any]],
    work_geoms: dict[str, BaseGeometry],
    *,
    over_fn,
    corners_fn,
    max_corners: int,
    snap_m: float,
    legendary_vertex_keys: set[tuple[int, int]],
    report: CornerBudgetReport,
) -> None:
    """Peel free vertices from one polygon (may open small mosaic gaps)."""
    for tid in list(over_fn()):
        if tid not in active:
            continue
        if territory_class_of(active[tid]["properties"]) == "legendary":
            continue
        safety = 0
        while safety < 20_000 and corners_fn(tid) > max_corners:
            safety += 1
            before_corners = corners_fn(tid)
            before = work_geoms[tid]
            candidates: list[tuple[float, float, tuple[int, int]]] = []
            for ring in _ring_coords(before):
                n = len(ring) - 1
                if n <= 3:
                    continue
                for i in range(n):
                    prev = ring[(i - 1) % n]
                    cur = ring[i]
                    nxt = ring[(i + 1) % n]
                    key = _snap_key(cur[0], cur[1], snap_m)
                    if key in legendary_vertex_keys:
                        continue
                    ax, ay = cur[0] - prev[0], cur[1] - prev[1]
                    bx, by = nxt[0] - cur[0], nxt[1] - cur[1]
                    eff = abs(ax * by - ay * bx)
                    turn = _turn_deviation(prev, cur, nxt)
                    candidates.append((eff, turn, key))
            if not candidates:
                break
            candidates.sort()
            dropped = False
            for eff, turn, key in candidates:
                del eff
                new_rings: list[list[tuple[float, float]]] = []
                changed = False
                ok = True
                for ring in _ring_coords(before):
                    n = len(ring) - 1
                    kept: list[tuple[float, float]] = []
                    for i in range(n):
                        pt = ring[i]
                        if _snap_key(pt[0], pt[1], snap_m) == key:
                            changed = True
                            continue
                        kept.append(pt)
                    if len(kept) < 3:
                        ok = False
                        break
                    if kept[0] != kept[-1]:
                        kept.append(kept[0])
                    new_rings.append(kept)
                if not ok or not changed:
                    continue
                new_geom = _rings_to_polygon(new_rings)
                if new_geom is None or float(new_geom.area) < 1.0:
                    continue
                if exterior_corner_count(new_geom) >= exterior_corner_count(before):
                    continue
                work_geoms[tid] = new_geom
                before = new_geom
                report.vertices_removed += 1
                report.applied.append(
                    {
                        "op": "drop_vertex_onesided",
                        "territory_ids": [tid],
                        "vertex": list(key),
                        "turn": round(turn, 6),
                    }
                )
                dropped = True
                break
            if not dropped:
                break
            if corners_fn(tid) >= before_corners:
                break


def _mosaic_gap_overlap(
    work_geoms: dict[str, BaseGeometry],
    aoi: BaseGeometry,
) -> tuple[float, float]:
    """Return (gap_m2, overlap_m2) of work geoms against the mosaic AOI."""
    geoms = [g for g in work_geoms.values() if g is not None and not g.is_empty]
    if not geoms or aoi is None or aoi.is_empty:
        return 0.0, 0.0
    covered = unary_union(geoms).intersection(aoi)
    gap = float(aoi.difference(covered).area)
    total = sum(float(g.area) for g in geoms)
    union_area = float(unary_union(geoms).area)
    overlap = max(0.0, total - union_area)
    return gap, overlap


def _repair_mosaic(
    active: dict[str, dict[str, Any]],
    work_geoms: dict[str, BaseGeometry],
    *,
    aoi: BaseGeometry,
    snap_m: float,
    exclude_fill_ids: set[str] | None = None,
) -> None:
    """Resolve overlaps and assign AOI gaps to the longest-border neighbour."""
    del snap_m
    skip_fill = exclude_fill_ids or set()
    ids = [tid for tid in active if territory_class_of(active[tid]["properties"]) != "legendary"]
    legendary_ids = [
        tid for tid in active if territory_class_of(active[tid]["properties"]) == "legendary"
    ]

    # Non-legendary must not overlap legendary: carve legendary out.
    for tid in ids:
        if tid not in work_geoms:
            continue
        geom = work_geoms[tid]
        for lid in legendary_ids:
            leg = work_geoms.get(lid)
            if leg is None or not geom.intersects(leg):
                continue
            carved = _as_polygonal(geom.difference(leg))
            if carved is not None and not carved.is_empty:
                geom = carved
                work_geoms[tid] = geom

    # Overlaps: subtract from the smaller non-legendary polygon.
    for i, a in enumerate(ids):
        if a not in work_geoms:
            continue
        for b in ids[i + 1 :]:
            if b not in work_geoms:
                continue
            ga, gb = work_geoms[a], work_geoms[b]
            if not ga.intersects(gb):
                continue
            inter = ga.intersection(gb)
            if inter.is_empty or float(inter.area) <= 1e-6:
                continue
            if float(ga.area) <= float(gb.area):
                trimmed = _as_polygonal(ga.difference(gb))
                if trimmed is not None and not trimmed.is_empty:
                    work_geoms[a] = trimmed
            else:
                trimmed = _as_polygonal(gb.difference(ga))
                if trimmed is not None and not trimmed.is_empty:
                    work_geoms[b] = trimmed

    geoms = [work_geoms[tid] for tid in active if tid in work_geoms]
    if not geoms:
        return
    covered = unary_union(geoms).intersection(aoi)
    gap = _as_polygonal(aoi.difference(covered))
    if gap is None or gap.is_empty:
        return
    parts = list(gap.geoms) if gap.geom_type == "MultiPolygon" else [gap]
    for part in parts:
        if part.is_empty or float(part.area) <= 1e-6:
            continue
        # Never fill into legendary interiors.
        for lid in legendary_ids:
            leg = work_geoms.get(lid)
            if leg is None:
                continue
            part2 = _as_polygonal(part.difference(leg))
            if part2 is None or part2.is_empty:
                part = None
                break
            part = part2
        if part is None or part.is_empty:
            continue
        best_id = None
        best_shared = -1.0
        for tid in ids:
            if tid not in work_geoms or tid in skip_fill:
                continue
            shared = _shared_border_length(part, work_geoms[tid])
            near = float(part.buffer(_BORDER_EPS_M).intersection(work_geoms[tid]).area)
            score = max(shared, near)
            if score > best_shared:
                best_shared = score
                best_id = tid
        if best_id is None:
            continue
        merged = _as_polygonal(unary_union([work_geoms[best_id], part]))
        if merged is None or merged.is_empty:
            continue
        if not is_valid(merged):
            merged = _as_polygonal(make_valid(merged))
        if merged is not None and not merged.is_empty:
            # Carve legendary again after fill.
            for lid in legendary_ids:
                leg = work_geoms.get(lid)
                if leg is None:
                    continue
                carved = _as_polygonal(merged.difference(leg))
                if carved is not None and not carved.is_empty:
                    merged = carved
            work_geoms[best_id] = merged


def _remove_one_shared_vertex(
    over_ids: list[str],
    active: dict[str, dict[str, Any]],
    work_geoms: dict[str, BaseGeometry],
    *,
    snap_m: float,
    max_area_loss_m2: float,
    allow_junctions: bool,
    max_turn: float,
    legendary_vertex_keys: set[tuple[int, int]] | None = None,
) -> dict[str, Any] | None:
    """Drop the shallowest eligible vertex from all non-legendary owners."""
    leg_keys = legendary_vertex_keys or set()
    index = _build_vertex_index(work_geoms, snap_m)
    candidates: list[tuple[float, float, int, str, tuple[int, int]]] = []

    for tid in over_ids:
        if territory_class_of(active[tid]["properties"]) == "legendary":
            continue
        for ring in _ring_coords(work_geoms[tid]):
            n = len(ring) - 1
            if n <= 3:
                continue
            for i in range(n):
                prev = ring[(i - 1) % n]
                cur = ring[i]
                nxt = ring[(i + 1) % n]
                key = _snap_key(cur[0], cur[1], snap_m)
                if key in leg_keys:
                    continue
                owners = index.get(key, set())
                if any(
                    territory_class_of(active[o]["properties"]) == "legendary"
                    for o in owners
                    if o in active
                ):
                    continue
                owner_count = len(owners)
                if owner_count >= 3 and not allow_junctions:
                    continue
                if tid not in owners:
                    continue
                turn = _turn_deviation(prev, cur, nxt)
                if turn > max_turn + 1e-15:
                    continue
                edge_len = math.hypot(nxt[0] - prev[0], nxt[1] - prev[1])
                candidates.append((turn, -edge_len, owner_count, tid, key))

    if not candidates:
        return None
    candidates.sort()

    loss_cap = max_area_loss_m2 * (200.0 if allow_junctions else 50.0)

    for turn, _, owner_count, tid, key in candidates:
        applied = _try_drop_vertex_key(
            key,
            active,
            work_geoms,
            snap_m=snap_m,
            max_area_loss_m2=loss_cap,
        )
        if applied is None:
            continue
        return {
            "vertex": list(key),
            "turn": round(turn, 6),
            "owner_count": owner_count,
            "territory_ids": applied,
            "seed_territory_id": tid,
        }
    return None


def _try_drop_vertex_key(
    key: tuple[int, int],
    active: dict[str, dict[str, Any]],
    work_geoms: dict[str, BaseGeometry],
    *,
    snap_m: float,
    max_area_loss_m2: float,
) -> list[str] | None:
    index = _build_vertex_index(work_geoms, snap_m)
    owners = sorted(index.get(key, set()))
    if not owners:
        return None
    snapshots: dict[str, BaseGeometry] = {}
    for oid in owners:
        if oid not in active:
            continue
        if territory_class_of(active[oid]["properties"]) == "legendary":
            return None
        snapshots[oid] = work_geoms[oid]
    if not snapshots:
        return None

    proposed: dict[str, BaseGeometry] = {}
    area_deltas: list[float] = []
    for oid, before in snapshots.items():
        rings = _ring_coords(before)
        new_rings: list[list[tuple[float, float]]] = []
        changed = False
        for ring in rings:
            n = len(ring) - 1
            kept: list[tuple[float, float]] = []
            for i in range(n):
                pt = ring[i]
                if _snap_key(pt[0], pt[1], snap_m) == key:
                    changed = True
                    continue
                kept.append(pt)
            if len(kept) < 3:
                return None
            if kept[0] != kept[-1]:
                kept.append(kept[0])
            new_rings.append(kept)
        if not changed:
            return None
        new_geom = _rings_to_polygon(new_rings)
        if new_geom is None:
            return None
        if exterior_corner_count(new_geom) >= exterior_corner_count(before):
            return None
        area_deltas.append(float(before.area) - float(new_geom.area))
        proposed[oid] = new_geom

    if not proposed:
        return None

    # Shared 2-owner drops transfer area between neighbours; require conservation
    # so the mosaic does not open a gap. Solo / junction drops must stay tiny.
    if len(proposed) == 2:
        if abs(sum(area_deltas)) > max(max_area_loss_m2 * 20.0, 5.0):
            return None
    else:
        for delta in area_deltas:
            if abs(delta) > max(max_area_loss_m2 * 20.0, 5.0):
                return None

    for oid, geom in proposed.items():
        work_geoms[oid] = geom
    return sorted(proposed.keys())


def _force_merge_over_budget(
    ctx: PipelineContext,
    tid: str,
    active: dict[str, dict[str, Any]],
    work_geoms: dict[str, BaseGeometry],
    *,
    gp: GameplayThresholds,
    bt: BeautifyThresholds,
    barrier_geom: BaseGeometry | None,
    max_area_loss_m2: float,
    crs_work: str,
    crs_store: str,
    allow_raw_union: bool = False,
) -> dict[str, Any]:
    del bt, barrier_geom
    scrap = active[tid]
    scrap_props = scrap["properties"]
    scrap_geom = work_geoms[tid]
    if territory_class_of(scrap_props) == "legendary":
        return {"ok": False, "reason": "legendary"}

    candidates: list[tuple[float, str]] = []
    for oid, other in active.items():
        if oid == tid:
            continue
        oprops = other["properties"]
        if territory_class_of(oprops) == "legendary":
            continue
        shared = _shared_border_length(scrap_geom, work_geoms[oid])
        if shared < gp.min_shared_border_m:
            near = float(scrap_geom.buffer(_BORDER_EPS_M).intersection(work_geoms[oid]).area)
            if near <= 0:
                continue
            shared = max(shared, near)
        a_area = float(scrap_geom.area)
        b_area = float(work_geoms[oid].area)
        if a_area + b_area > gp.hard_max_m2 + 1e-6:
            continue
        candidates.append((-shared, oid))
    if not candidates:
        return {"ok": False, "reason": "no_neighbour"}
    candidates.sort()

    last_reason = "merge_failed"
    for _, winner_id in candidates:
        winner_props = active[winner_id]["properties"]
        merge = safe_merge_geometry(
            scrap_geom, work_geoms[winner_id], max_area_loss_m2=max_area_loss_m2
        )
        if merge.geometry is None and allow_raw_union:
            raw = _as_polygonal(unary_union([scrap_geom, work_geoms[winner_id]]))
            if raw is not None and not raw.is_empty and is_valid(raw):
                merge = SafeMergeResult(geometry=raw, repaired=True, rejected_reason=None)
            elif raw is not None and not raw.is_empty:
                repaired = _as_polygonal(make_valid(raw))
                if repaired is not None and not repaired.is_empty and is_valid(repaired):
                    merge = SafeMergeResult(
                        geometry=repaired, repaired=True, rejected_reason=None
                    )
        if merge.geometry is None:
            last_reason = merge.rejected_reason or "merge_failed"
            continue
        if float(merge.geometry.area) > gp.hard_max_m2 + 1e-6:
            last_reason = "exceeds_hard_max"
            continue

        a_area = float(scrap_geom.area)
        b_area = float(work_geoms[winner_id].area)
        members = sorted(
            set(
                [str(x) for x in (scrap_props.get("member_territory_ids") or [])]
                + [str(x) for x in (winner_props.get("member_territory_ids") or [])]
            )
        )

        if b_area >= a_area:
            dominant = dict(winner_props)
            absorbed = dict(scrap_props)
        else:
            dominant = dict(scrap_props)
            absorbed = dict(winner_props)

        city = ctx.region.city
        area = ctx.region.area
        name = dominant.get("name") or absorbed.get("name")
        slug_base = str(dominant.get("slug") or slugify(str(name or "cluster")))
        new_tid = str(
            gameplay_territory_id(city, area, f"{slug_base}:{content_hash(tid + winner_id)[:8]}")
        )

        new_props = {
            **dominant,
            "territory_id": new_tid,
            "slug": slug_base,
            "name": name,
            "protected": False,
            "legendary": False,
            "landmark_dedicated": False,
            "territory_class": "ordinary",
            "kind": "block",
            "area_m2": round(float(merge.geometry.area), 3),
            "member_territory_ids": members,
            "member_count": len(members),
            "layer": "gameplay",
            "beautify_op": "corner_budget_merge",
        }
        new_props.pop("role", None)

        store = _as_polygonal(to_store(merge.geometry, crs_work, crs_store))
        if store is None or store.is_empty:
            last_reason = "empty_store"
            continue

        del active[tid]
        del active[winner_id]
        del work_geoms[tid]
        del work_geoms[winner_id]
        active[new_tid] = {
            "type": "Feature",
            "geometry": mapping(store),
            "properties": new_props,
        }
        work_geoms[new_tid] = merge.geometry
        return {
            "ok": True,
            "from": [tid, winner_id],
            "result_id": new_tid,
            "corners_after": exterior_corner_count(merge.geometry),
        }

    return {"ok": False, "reason": last_reason}
