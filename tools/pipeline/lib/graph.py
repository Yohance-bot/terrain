"""Boundary-graph noding and snapping for stage 04.

Takes separator LineStrings (storage CRS), projects to the working CRS, nodes
every intersection, snaps near-miss endpoints within `snap_m`, drops dangling
spurs, and returns features whose coordinates are already in metres.

Stage 04 does not re-add landmark rings -- Stage 02 already emitted
`area_boundary` outers for area features, and majors are carved in Stage 05.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from shapely.geometry import LineString, MultiLineString, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import snap, unary_union

from lib import artifacts
from lib.contracts import PipelineContext
from lib.crs import to_work
from lib.determinism import stable_sort
from lib.io import read_geojson


def build_boundary_graph(ctx: PipelineContext) -> list[dict[str, Any]]:
    """Build noded edge features in the working CRS.

    Hook point for tests: monkeypatch this to avoid reading real separators.
    """
    data = read_geojson(artifacts.SEPARATORS.path(ctx))
    crs_work = ctx.region.crs_work
    snap_m = float(ctx.thresholds.snap_m)

    lines = _collect_work_lines(data.get("features") or [], crs_work)
    if not lines:
        return []

    noded = unary_union(lines)
    # Snap the noded set to itself so near-miss endpoints collapse within snap_m.
    # Must be metres -- never call this on EPSG:4326 geometry.
    snapped = snap(noded, noded, snap_m)
    renoded = unary_union(snapped)
    edges = [line for line in _explode_lines(renoded) if line.length > 0]
    pruned = _drop_dangles(edges)

    features = [
        {
            "type": "Feature",
            "geometry": mapping(edge),
            "properties": {
                "edge_id": idx,
            },
        }
        for idx, edge in enumerate(
            stable_sort(pruned, key=_line_sort_key),
            start=1,
        )
    ]
    return features


def _collect_work_lines(
    features: list[dict[str, Any]], crs_work: str
) -> list[LineString]:
    lines: list[LineString] = []
    for feature in features:
        geom_json = feature.get("geometry")
        if not geom_json:
            continue
        try:
            geom = shape(geom_json)
        except Exception:
            continue
        if geom is None or geom.is_empty:
            continue
        if not geom.is_valid:
            geom = geom.buffer(0)
        work = to_work(geom, crs_work)
        for line in _explode_lines(work):
            if line is not None and not line.is_empty and line.length > 0:
                lines.append(line)
    return lines


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


def _line_sort_key(line: LineString) -> tuple:
    coords = list(line.coords)
    first = coords[0]
    last = coords[-1]
    # Orient so the lexicographically smaller endpoint comes first -- otherwise
    # the same undirected edge can sort differently across runs.
    if (round(last[0], 6), round(last[1], 6)) < (round(first[0], 6), round(first[1], 6)):
        first, last = last, first
    return (
        round(first[0], 6),
        round(first[1], 6),
        round(last[0], 6),
        round(last[1], 6),
        round(line.length, 6),
    )


def _endpoint_key(coord: tuple[float, float], quantize_m: float = 0.01) -> tuple[int, int]:
    """Bucket endpoints so floating noise does not invent extra nodes."""
    return (int(round(coord[0] / quantize_m)), int(round(coord[1] / quantize_m)))


def _drop_dangles(edges: Iterable[LineString]) -> list[LineString]:
    """Remove clear dangling spurs attached to a cyclic core.

    Conservative for M2: a pure cross / tree is kept (those corridors still
    divide space once stage 05 adds the AOI). Only drop a degree-1 edge when
    its other endpoint lies on a cycle -- a digitizing spur sticking off a
    finished block, not a bridge or a star of separators.
    """
    remaining = [e for e in edges if e is not None and not e.is_empty and e.length > 0]
    while True:
        node_edges = _incidence(remaining)
        on_cycle = _nodes_on_cycles(remaining)
        drop: set[int] = set()
        for idx, edge in enumerate(remaining):
            coords = list(edge.coords)
            u = _endpoint_key((float(coords[0][0]), float(coords[0][1])))
            v = _endpoint_key((float(coords[-1][0]), float(coords[-1][1])))
            deg_u = len(node_edges.get(u, ()))
            deg_v = len(node_edges.get(v, ()))
            if deg_u == 1 and v in on_cycle:
                drop.add(idx)
            elif deg_v == 1 and u in on_cycle:
                drop.add(idx)

        if not drop:
            break
        remaining = [e for i, e in enumerate(remaining) if i not in drop]

    return remaining


def _incidence(
    edges: list[LineString],
) -> dict[tuple[int, int], list[int]]:
    incidence: dict[tuple[int, int], list[int]] = {}
    for idx, edge in enumerate(edges):
        coords = list(edge.coords)
        for coord in (coords[0], coords[-1]):
            key = _endpoint_key((float(coord[0]), float(coord[1])))
            incidence.setdefault(key, []).append(idx)
    return incidence


def _nodes_on_cycles(edges: list[LineString]) -> set[tuple[int, int]]:
    """Nodes that participate in at least one simple cycle.

    Iterative DFS -- the real AOI graph is far deeper than the default
    recursion limit.
    """
    if not edges:
        return set()

    adj: dict[tuple[int, int], set[tuple[int, int]]] = {}
    for edge in edges:
        coords = list(edge.coords)
        u = _endpoint_key((float(coords[0][0]), float(coords[0][1])))
        v = _endpoint_key((float(coords[-1][0]), float(coords[-1][1])))
        if u == v:
            continue
        adj.setdefault(u, set()).add(v)
        adj.setdefault(v, set()).add(u)

    on_cycle: set[tuple[int, int]] = set()
    visited: set[tuple[int, int]] = set()

    for start in adj:
        if start in visited:
            continue
        # stack frames: (node, parent, neighbor-iterator)
        stack: list[tuple[tuple[int, int], tuple[int, int] | None, Any]] = [
            (start, None, iter(adj.get(start, ())))
        ]
        path: list[tuple[int, int]] = []
        path_index: dict[tuple[int, int], int] = {}

        while stack:
            node, parent, nbrs = stack[-1]
            if node not in path_index:
                visited.add(node)
                path_index[node] = len(path)
                path.append(node)

            advanced = False
            for nbr in nbrs:
                if nbr == parent:
                    continue
                if nbr in path_index:
                    on_cycle.update(path[path_index[nbr] :])
                    continue
                if nbr not in visited:
                    stack.append((nbr, node, iter(adj.get(nbr, ()))))
                    advanced = True
                    break
            if advanced:
                continue
            path.pop()
            path_index.pop(node, None)
            stack.pop()

    return on_cycle
