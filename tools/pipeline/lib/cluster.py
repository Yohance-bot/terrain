"""Barrier-aware agglomerative clustering for Stage 10 gameplay territories.

Unions Stage 09 parcel polygons into larger playable places. Does not invent
geometry, does not merge across configured major separators, and never touches
protected landmarks.
"""

from __future__ import annotations

import heapq
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from shapely import STRtree, is_valid, make_valid
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from lib import artifacts
from lib.config import GameplayThresholds, load_validation_exceptions
from lib.contracts import PipelineContext
from lib.crs import to_store, to_work
from lib.determinism import (
    content_hash,
    gameplay_territory_id,
    slugify,
    stable_sort,
)
from lib.io import artifact_hash_input, read_geojson
from lib.normalize import (
    _as_polygonal,
    _shared_border_length,
    safe_merge_geometry,
)
from lib.shape import metrics_payload, shape_quality, shape_score

_BORDER_EPS_M = 0.05
_BARRIER_SHARED_BORDER_REFUSE = 0.35
_NAME_TOKEN_RE = re.compile(r"[a-z0-9]+")


class ClusterError(RuntimeError):
    """Stage 10 cannot produce a safe gameplay artifact."""


@dataclass
class _ClusterNode:
    uid: str
    geom: BaseGeometry
    props: dict[str, Any]
    member_ids: list[str]
    area_m2: float
    place_key: str | None
    name_stem: str | None
    needs_review: bool = False
    review_reasons: list[str] = field(default_factory=list)
    store_geometry: dict[str, Any] | None = None

    @property
    def protected(self) -> bool:
        return self.props.get("protected") is True

    @property
    def landmark_dedicated(self) -> bool:
        return self.props.get("landmark_dedicated") is True

    @property
    def frozen(self) -> bool:
        """Source-protected (legendary) landmarks never join fabric merges."""
        return self.protected


@dataclass
class ClusterReport:
    input_count: int
    output_count: int
    protected_count: int
    fabric_input_count: int
    fabric_output_count: int
    merges: int
    barrier_blocked_edges: int
    adjacency_edges: int
    undersized_stuck: int
    needs_review_count: int
    below_soft_min: int
    in_soft_band: int
    above_soft_max: int
    above_review_max: int
    area_min_m2: float
    area_max_m2: float
    area_median_m2: float
    area_mean_m2: float
    parcel_hash: str
    separators_hash: str
    merge_failures: list[dict[str, Any]] = field(default_factory=list)
    soft_flags: list[dict[str, Any]] = field(default_factory=list)
    atomic_absorptions: list[dict[str, Any]] = field(default_factory=list)
    atomic_expansions: list[dict[str, Any]] = field(default_factory=list)
    unabsorbed_atomic: list[dict[str, Any]] = field(default_factory=list)
    target_max_m2: float = 0.0
    hard_max_m2: float = 0.0
    above_hard_max: int = 0
    dedicated_landmark_count: int = 0
    max_aspect_ratio: float = 0.0
    hard_max_known_exceptions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ClusterResult:
    features: list[dict[str, Any]]
    report: ClusterReport


@dataclass
class _PlaceHint:
    key: str
    name: str
    slug: str
    geom: BaseGeometry
    area_m2: float


def cluster_parcels(
    ctx: PipelineContext,
    *,
    parcels: list[dict[str, Any]] | None = None,
    separators: list[dict[str, Any]] | None = None,
    places: list[_PlaceHint] | None = None,
    from_candidates: bool = False,
) -> ClusterResult:
    """Cluster parcel Feature dicts into gameplay territories.

    ``places`` may be injected by tests; production loads them when raw data
    is available and otherwise scores without place affinity.
    """
    gp = ctx.thresholds.gameplay
    crs_work = ctx.region.crs_work
    crs_store = ctx.region.crs_store
    max_gap = float(ctx.thresholds.validation.max_gap_m2)
    snap_m = float(ctx.thresholds.snap_m)

    if parcels is None:
        parcels = _load_parcels(ctx, from_candidates=from_candidates)
    if separators is None:
        separators = list(read_geojson(artifacts.SEPARATORS.path(ctx)).get("features") or [])

    parcel_collection = {"type": "FeatureCollection", "features": parcels}
    parcel_hash = content_hash(artifact_hash_input(parcel_collection))
    sep_collection = {"type": "FeatureCollection", "features": separators}
    separators_hash = content_hash(artifact_hash_input(sep_collection))

    barrier_geom = _barrier_union(separators, gp, crs_work, snap_m)
    if places is None:
        places = _try_load_places(ctx)

    nodes, protected_nodes = _nodes_from_parcels(parcels, places, crs_work, ctx)
    fabric = list(nodes)
    input_count = len(fabric) + len(protected_nodes)
    fabric_input = len(fabric)
    known_exceptions: dict[str, str] = (
        load_validation_exceptions(ctx.region.name) if ctx.allow_validation_exceptions else {}
    )

    oversized_inputs = [
        node
        for node in fabric
        if node.area_m2 > gp.hard_max_m2 + 1e-6
    ]
    hard_max_known_exceptions: list[dict[str, Any]] = []
    if oversized_inputs:
        unexpected_oversized: list[dict[str, Any]] = []
        for node in oversized_inputs:
            slug = str(node.props.get("slug") or "")
            entry = {
                "territory_id": node.uid,
                "slug": slug,
                "name": node.props.get("name"),
                "area_m2": round(node.area_m2, 3),
            }
            if slug in known_exceptions:
                node.needs_review = True
                if "known_mvp_hard_max_exception" not in node.review_reasons:
                    node.review_reasons.append("known_mvp_hard_max_exception")
                node.props["hard_max_exception_source_slug"] = slug
                node.props["hard_max_exception_reason"] = known_exceptions[slug]
                hard_max_known_exceptions.append(
                    {
                        **entry,
                        "hard_max_m2": round(gp.hard_max_m2, 3),
                        "reason": known_exceptions[slug],
                    }
                )
            else:
                unexpected_oversized.append(entry)

        if unexpected_oversized:
            first = unexpected_oversized[0]
            raise ClusterError(
                "Stage 10: non-protected parcel already exceeds the ordinary "
                f"{gp.hard_max_m2:.3f} m² hard cap: "
                f"{first['territory_id']} slug={first['slug']!r} ({first['area_m2']} m²). "
                "Fix upstream separators; Stage 10 will not invent a split."
            )

    # Legendary stays frozen. Non-protected atomics stay in the fabric pool and
    # are swallowed by ordinary agglomeration — absorbing them *before*
    # clustering created ~200–240 acre scraps that cannot merge under the
    # hard max. Any leftover solo atomics are mopped up after escape.
    dedicated_nodes: list[_ClusterNode] = []
    atomic_expansions: list[dict[str, Any]] = []
    atomic_absorptions: list[dict[str, Any]] = []
    unabsorbed_atomic: list[dict[str, Any]] = []
    original_atomics = [
        {
            "territory_id": n.uid,
            "name": n.props.get("atomic_source_name") or n.props.get("name"),
            "slug": n.props.get("atomic_source_slug") or n.props.get("slug"),
            "area_m2": round(n.area_m2, 3),
        }
        for n in fabric
        if n.props.get("atomic") is True and not n.protected
    ]

    adjacency, barrier_blocked = _build_adjacency(fabric, barrier_geom, gp.min_shared_border_m)
    adjacency_edges = sum(len(v) for v in adjacency.values()) // 2

    merges = 0
    merge_failures: list[dict[str, Any]] = []
    active: dict[str, _ClusterNode] = {n.uid: n for n in fabric}
    # Cached shared border length for undirected edges (uid_a < uid_b).
    shared_cache: dict[tuple[str, str], float] = {}
    for uid_a, nbrs in adjacency.items():
        for uid_b in nbrs:
            if uid_a >= uid_b:
                continue
            key = (uid_a, uid_b)
            shared_cache[key] = _shared_border_length(active[uid_a].geom, active[uid_b].geom)

    heap: list[tuple[float, str, str]] = []
    for (uid_a, uid_b), shared in shared_cache.items():
        _push_candidate(heap, active, uid_a, uid_b, shared, gp)

    while heap:
        neg_score, uid_a, uid_b = heapq.heappop(heap)
        score = -neg_score
        if uid_a not in active or uid_b not in active:
            continue
        if uid_b not in adjacency.get(uid_a, set()):
            continue
        key = (uid_a, uid_b) if uid_a < uid_b else (uid_b, uid_a)
        shared = shared_cache.get(key)
        if shared is None:
            continue
        # Re-score in case areas changed via other merges (stale heap entry).
        node_a = active[uid_a]
        node_b = active[uid_b]
        fresh = _score_pair(node_a, node_b, shared, gp)
        if abs(fresh - score) > 1e-9:
            if _merge_allowed(node_a, node_b, fresh, gp):
                heapq.heappush(heap, (-fresh, uid_a, uid_b))
            continue
        if not _merge_allowed(node_a, node_b, score, gp):
            continue

        result = safe_merge_geometry(node_a.geom, node_b.geom, max_area_loss_m2=max_gap)
        if result.geometry is None:
            merge_failures.append(
                {
                    "a": uid_a,
                    "b": uid_b,
                    "reason": result.rejected_reason or "merge_failed",
                    "score": round(score, 6),
                }
            )
            _drop_edge(adjacency, uid_a, uid_b)
            shared_cache.pop(key, None)
            node_a.needs_review = True
            node_b.needs_review = True
            for reason in ("merge_failed",):
                if reason not in node_a.review_reasons:
                    node_a.review_reasons.append(reason)
                if reason not in node_b.review_reasons:
                    node_b.review_reasons.append(reason)
            continue

        merged_area = float(result.geometry.area)
        place_aff = _place_affinity(node_a, node_b)
        max_allowed = min(
            gp.hard_max_m2,
            gp.place_max_m2 if place_aff >= 1.0 else gp.soft_max_m2,
        )
        if merged_area > max_allowed + 1e-6:
            _drop_edge(adjacency, uid_a, uid_b)
            shared_cache.pop(key, None)
            continue

        new_uid = _merged_uid(node_a, node_b)
        merged = _ClusterNode(
            uid=new_uid,
            geom=result.geometry,
            props=_merge_props(node_a, node_b),
            member_ids=sorted(set(node_a.member_ids + node_b.member_ids)),
            area_m2=merged_area,
            place_key=_dominant_place_key(node_a, node_b),
            name_stem=_dominant_name_stem(node_a, node_b),
            needs_review=node_a.needs_review or node_b.needs_review,
            review_reasons=sorted(set(node_a.review_reasons + node_b.review_reasons)),
        )
        if (
            place_aff < 1.0
            and node_a.place_key
            and node_b.place_key
            and node_a.place_key != node_b.place_key
        ):
            merged.needs_review = True
            if "multi_place" not in merged.review_reasons:
                merged.review_reasons.append("multi_place")

        neighbours = (adjacency.get(uid_a, set()) | adjacency.get(uid_b, set())) - {
            uid_a,
            uid_b,
        }
        # Drop cache entries involving either parent.
        for old in (uid_a, uid_b):
            for nbr in list(adjacency.get(old, set())):
                k = (old, nbr) if old < nbr else (nbr, old)
                shared_cache.pop(k, None)

        del active[uid_a]
        del active[uid_b]
        adjacency.pop(uid_a, None)
        adjacency.pop(uid_b, None)
        for nbr in list(neighbours):
            adjacency.setdefault(nbr, set()).discard(uid_a)
            adjacency.setdefault(nbr, set()).discard(uid_b)

        active[new_uid] = merged
        adjacency[new_uid] = set()
        for nbr_uid in sorted(neighbours):
            if nbr_uid not in active:
                continue
            nbr = active[nbr_uid]
            shared_len = _shared_border_length(merged.geom, nbr.geom)
            if shared_len < gp.min_shared_border_m:
                continue
            if _border_crosses_barrier(merged.geom, nbr.geom, barrier_geom):
                barrier_blocked += 1
                continue
            adjacency[new_uid].add(nbr_uid)
            adjacency.setdefault(nbr_uid, set()).add(new_uid)
            edge = (new_uid, nbr_uid) if new_uid < nbr_uid else (nbr_uid, new_uid)
            shared_cache[edge] = shared_len
            _push_candidate(heap, active, new_uid, nbr_uid, shared_len, gp)
        merges += 1

    # Phase 2: absorb undersized / strip ordinary nodes into neighbours.
    # Prefer barrier-safe fabric; fall back across barriers; last resort absorb
    # into an expanded dedicated landmark so dust never publishes.
    max_aspect = float(ctx.thresholds.beautify.max_aspect_ratio)
    dedicated_by_uid = {n.uid: n for n in dedicated_nodes}
    escape_merges = 0
    while True:
        stuck = [
            n
            for n in sorted(active.values(), key=lambda x: (x.area_m2, x.uid))
            if (not n.frozen)
            and (
                n.area_m2 < gp.soft_min_m2
                or float(shape_quality(n.geom)["aspect_ratio"]) > max_aspect + 1e-9
            )
        ]
        if not stuck:
            break
        progressed = False
        for scrap in stuck:
            if scrap.uid not in active:
                continue
            winner = _pick_escape_neighbour(
                scrap,
                active,
                dedicated_by_uid=dedicated_by_uid,
                barrier_geom=barrier_geom,
                gp=gp,
            )
            if winner is None:
                continue
            merged_area = scrap.area_m2 + winner.area_m2
            if merged_area > gp.hard_max_m2 + 1e-6:
                continue
            result = safe_merge_geometry(
                scrap.geom, winner.geom, max_area_loss_m2=max_gap
            )
            if result.geometry is None:
                continue

            new_uid = _merged_uid(scrap, winner)
            merged = _ClusterNode(
                uid=new_uid,
                geom=result.geometry,
                props=_merge_props(scrap, winner),
                member_ids=sorted(set(scrap.member_ids + winner.member_ids)),
                area_m2=float(result.geometry.area),
                place_key=_dominant_place_key(scrap, winner),
                name_stem=_dominant_name_stem(scrap, winner),
                needs_review=scrap.needs_review or winner.needs_review,
                review_reasons=sorted(
                    set(scrap.review_reasons + winner.review_reasons)
                ),
            )
            parents = {scrap.uid, winner.uid}
            neighbours: set[str] = set()
            for uid in parents:
                neighbours |= adjacency.get(uid, set())
            neighbours -= parents
            for uid in parents:
                for nbr in list(adjacency.get(uid, set())):
                    adjacency.setdefault(nbr, set()).discard(uid)
                    k = (uid, nbr) if uid < nbr else (nbr, uid)
                    shared_cache.pop(k, None)
                adjacency.pop(uid, None)
                del active[uid]
            active[new_uid] = merged
            adjacency[new_uid] = set()
            for nbr_uid in sorted(neighbours):
                if nbr_uid not in active:
                    continue
                shared_len = _shared_border_length(merged.geom, active[nbr_uid].geom)
                if shared_len < gp.min_shared_border_m:
                    continue
                adjacency[new_uid].add(nbr_uid)
                adjacency.setdefault(nbr_uid, set()).add(new_uid)
                edge = (new_uid, nbr_uid) if new_uid < nbr_uid else (nbr_uid, new_uid)
                shared_cache[edge] = shared_len
            merges += 1
            escape_merges += 1
            progressed = True
            break
        if not progressed:
            break

    # Phase 3: final strip sweep — any remaining ordinary corridor merges away.
    strip_merges = 0
    while True:
        strips = [
            n
            for n in sorted(
                active.values(),
                key=lambda x: (
                    -float(shape_quality(x.geom)["aspect_ratio"]),
                    x.uid,
                ),
            )
            if (not n.frozen)
            and float(shape_quality(n.geom)["aspect_ratio"]) > max_aspect + 1e-9
        ]
        if not strips:
            break
        progressed = False
        for scrap in strips:
            if scrap.uid not in active:
                continue
            winner = _pick_escape_neighbour(
                scrap,
                active,
                dedicated_by_uid=dedicated_by_uid,
                barrier_geom=barrier_geom,
                gp=gp,
            )
            if winner is None:
                continue
            if scrap.area_m2 + winner.area_m2 > gp.hard_max_m2 + 1e-6:
                continue
            result = safe_merge_geometry(
                scrap.geom, winner.geom, max_area_loss_m2=max_gap
            )
            if result.geometry is None:
                continue
            new_uid = _merged_uid(scrap, winner)
            merged = _ClusterNode(
                uid=new_uid,
                geom=result.geometry,
                props=_merge_props(scrap, winner),
                member_ids=sorted(set(scrap.member_ids + winner.member_ids)),
                area_m2=float(result.geometry.area),
                place_key=_dominant_place_key(scrap, winner),
                name_stem=_dominant_name_stem(scrap, winner),
                needs_review=scrap.needs_review or winner.needs_review,
                review_reasons=sorted(
                    set(
                        scrap.review_reasons
                        + winner.review_reasons
                        + ["strip_absorbed"]
                    )
                ),
            )
            parents = {scrap.uid, winner.uid}
            neighbours = set()
            for uid in parents:
                neighbours |= adjacency.get(uid, set())
            neighbours -= parents
            for uid in parents:
                for nbr in list(adjacency.get(uid, set())):
                    adjacency.setdefault(nbr, set()).discard(uid)
                    k = (uid, nbr) if uid < nbr else (nbr, uid)
                    shared_cache.pop(k, None)
                adjacency.pop(uid, None)
                del active[uid]
            active[new_uid] = merged
            adjacency[new_uid] = set()
            for nbr_uid in sorted(neighbours):
                if nbr_uid not in active:
                    continue
                shared_len = _shared_border_length(
                    merged.geom, active[nbr_uid].geom
                )
                if shared_len < gp.min_shared_border_m:
                    continue
                adjacency[new_uid].add(nbr_uid)
                adjacency.setdefault(nbr_uid, set()).add(new_uid)
                edge = (
                    (new_uid, nbr_uid)
                    if new_uid < nbr_uid
                    else (nbr_uid, new_uid)
                )
                shared_cache[edge] = shared_len
            merges += 1
            strip_merges += 1
            progressed = True
            break
        if not progressed:
            break

    # Phase 3b: pair-merge undersized fabric when combined area fits under hard_max.
    merges += _coalesce_undersized_fabric(
        active,
        adjacency,
        shared_cache,
        barrier_geom=barrier_geom,
        gp=gp,
        max_gap=max_gap,
    )

    # Re-run escape absorption after pair merges freed headroom.
    while True:
        stuck = [
            n
            for n in sorted(active.values(), key=lambda x: (x.area_m2, x.uid))
            if (not n.frozen)
            and (
                n.area_m2 < gp.soft_min_m2
                or float(shape_quality(n.geom)["aspect_ratio"]) > max_aspect + 1e-9
            )
        ]
        if not stuck:
            break
        progressed = False
        for scrap in stuck:
            if scrap.uid not in active:
                continue
            winner = _pick_escape_neighbour(
                scrap,
                active,
                dedicated_by_uid=dedicated_by_uid,
                barrier_geom=barrier_geom,
                gp=gp,
            )
            if winner is None:
                continue
            merged_area = scrap.area_m2 + winner.area_m2
            if merged_area > gp.hard_max_m2 + 1e-6:
                continue
            result = safe_merge_geometry(
                scrap.geom, winner.geom, max_area_loss_m2=max_gap
            )
            if result.geometry is None:
                continue
            new_uid = _merged_uid(scrap, winner)
            merged = _ClusterNode(
                uid=new_uid,
                geom=result.geometry,
                props=_merge_props(scrap, winner),
                member_ids=sorted(set(scrap.member_ids + winner.member_ids)),
                area_m2=float(result.geometry.area),
                place_key=_dominant_place_key(scrap, winner),
                name_stem=_dominant_name_stem(scrap, winner),
                needs_review=scrap.needs_review or winner.needs_review,
                review_reasons=sorted(
                    set(scrap.review_reasons + winner.review_reasons)
                ),
            )
            parents = {scrap.uid, winner.uid}
            neighbours: set[str] = set()
            for uid in parents:
                neighbours |= adjacency.get(uid, set())
            neighbours -= parents
            for uid in parents:
                for nbr in list(adjacency.get(uid, set())):
                    adjacency.setdefault(nbr, set()).discard(uid)
                    k = (uid, nbr) if uid < nbr else (nbr, uid)
                    shared_cache.pop(k, None)
                adjacency.pop(uid, None)
                del active[uid]
            active[new_uid] = merged
            adjacency[new_uid] = set()
            for nbr_uid in sorted(neighbours):
                if nbr_uid not in active:
                    continue
                shared_len = _shared_border_length(merged.geom, active[nbr_uid].geom)
                if shared_len < gp.min_shared_border_m:
                    continue
                adjacency[new_uid].add(nbr_uid)
                adjacency.setdefault(nbr_uid, set()).add(new_uid)
                edge = (new_uid, nbr_uid) if new_uid < nbr_uid else (nbr_uid, new_uid)
                shared_cache[edge] = shared_len
            merges += 1
            escape_merges += 1
            progressed = True
            break
        if not progressed:
            break

    # Mop up any leftover solo non-protected atomics into ordinary neighbours,
    # preferring undersized fabric with room under hard_max.
    post_absorbed, still_unabsorbed = _absorb_remaining_solo_atomics(
        active,
        adjacency,
        shared_cache,
        barrier_geom=barrier_geom,
        gp=gp,
        max_area_loss_m2=max_gap,
    )
    atomic_absorptions.extend(post_absorbed)
    merges += len(post_absorbed)

    # Audit every source atomic: multi-member holders count as absorbed via
    # general clustering; solo leftovers are already in still_unabsorbed.
    seen_absorbed_ids = {
        str(item.get("landmark_territory_id")) for item in atomic_absorptions
    }
    for meta in original_atomics:
        source_id = str(meta["territory_id"])
        if source_id in seen_absorbed_ids:
            continue
        holder = next(
            (
                node
                for node in active.values()
                if source_id in node.member_ids and len(node.member_ids) > 1
            ),
            None,
        )
        if holder is None:
            if not any(u.get("territory_id") == source_id for u in still_unabsorbed):
                still_unabsorbed.append(
                    {
                        "territory_id": source_id,
                        "name": meta.get("name"),
                        "area_m2": meta.get("area_m2"),
                        "reason": "solo_after_clustering",
                    }
                )
            continue
        atomic_absorptions.append(
            {
                "landmark_territory_id": source_id,
                "landmark_name": meta.get("name"),
                "landmark_slug": meta.get("slug"),
                "area_m2": meta.get("area_m2"),
                "result_id": holder.uid,
                "decision": "deferred_to_general_clustering",
                "absorbed_into_kind": "fabric",
            }
        )
    unabsorbed_atomic = still_unabsorbed

    # Flag undersized stuck fabric.
    undersized_stuck = 0
    for node in active.values():
        if node.area_m2 < gp.soft_min_m2:
            legal = False
            for nbr_uid in adjacency.get(node.uid, set()):
                if nbr_uid in active:
                    legal = True
                    break
            # Also check geometric touch for escape leftovers.
            if not legal:
                touch = _nearest_fabric_neighbour(
                    node, active, gp.min_shared_border_m, ignore_barrier=True
                )
                legal = touch is not None and touch.uid != node.uid
            if not legal:
                undersized_stuck += 1
                node.needs_review = True
                if "undersized_stuck" not in node.review_reasons:
                    node.review_reasons.append("undersized_stuck")
            elif node.area_m2 < gp.soft_min_m2:
                node.needs_review = True
                if "undersized" not in node.review_reasons:
                    node.review_reasons.append("undersized")
        if node.area_m2 > gp.soft_max_m2:
            node.needs_review = True
            if "above_300_acre_target" not in node.review_reasons:
                node.review_reasons.append("above_300_acre_target")
        if not node.place_key and not node.name_stem:
            node.needs_review = True
            if "weak_identity" not in node.review_reasons:
                node.review_reasons.append("weak_identity")

    features = _emit_features(
        list(active.values()) + dedicated_nodes + protected_nodes,
        ctx,
        crs_work,
        crs_store,
        gp,
    )

    areas = [
        float((f.get("properties") or {}).get("area_m2") or 0.0)
        for f in features
        if (f.get("properties") or {}).get("protected") is not True
        and (f.get("properties") or {}).get("landmark_dedicated") is not True
    ]
    areas_sorted = sorted(areas)
    soft_flags = [
        {
            "slug": (f.get("properties") or {}).get("slug"),
            "reasons": (f.get("properties") or {}).get("review_reasons") or [],
        }
        for f in features
        if (f.get("properties") or {}).get("needs_review") is True
    ]

    report = ClusterReport(
        input_count=input_count,
        output_count=len(features),
        protected_count=len(protected_nodes),
        fabric_input_count=fabric_input,
        fabric_output_count=len(active),
        merges=merges,
        barrier_blocked_edges=barrier_blocked,
        adjacency_edges=adjacency_edges,
        undersized_stuck=undersized_stuck,
        needs_review_count=sum(
            1 for f in features if (f.get("properties") or {}).get("needs_review")
        ),
        below_soft_min=sum(1 for a in areas if a < gp.soft_min_m2),
        in_soft_band=sum(1 for a in areas if gp.soft_min_m2 <= a <= gp.soft_max_m2),
        above_soft_max=sum(1 for a in areas if a > gp.soft_max_m2),
        above_review_max=sum(1 for a in areas if a > gp.review_max_m2),
        area_min_m2=round(min(areas), 3) if areas else 0.0,
        area_max_m2=round(max(areas), 3) if areas else 0.0,
        area_median_m2=round(_median(areas_sorted), 3) if areas_sorted else 0.0,
        area_mean_m2=round(sum(areas) / len(areas), 3) if areas else 0.0,
        parcel_hash=parcel_hash,
        separators_hash=separators_hash,
        merge_failures=merge_failures,
        soft_flags=soft_flags,
        atomic_absorptions=atomic_absorptions,
        atomic_expansions=atomic_expansions,
        unabsorbed_atomic=unabsorbed_atomic,
        target_max_m2=gp.soft_max_m2,
        hard_max_m2=gp.hard_max_m2,
        above_hard_max=sum(1 for a in areas if a > gp.hard_max_m2),
        dedicated_landmark_count=len(dedicated_nodes),
        max_aspect_ratio=float(ctx.thresholds.beautify.max_aspect_ratio),
        hard_max_known_exceptions=stable_sort(
            hard_max_known_exceptions,
            key=lambda row: (str(row.get("slug") or ""), str(row.get("territory_id") or "")),
        ),
    )
    return ClusterResult(features=features, report=report)


def report_to_dict(report: ClusterReport) -> dict[str, Any]:
    return {
        "stage": "cluster_gameplay",
        "input_count": report.input_count,
        "output_count": report.output_count,
        "protected_count": report.protected_count,
        "fabric_input_count": report.fabric_input_count,
        "fabric_output_count": report.fabric_output_count,
        "merges": report.merges,
        "barrier_blocked_edges": report.barrier_blocked_edges,
        "adjacency_edges": report.adjacency_edges,
        "undersized_stuck": report.undersized_stuck,
        "needs_review_count": report.needs_review_count,
        "size": {
            "below_soft_min": report.below_soft_min,
            "in_soft_band": report.in_soft_band,
            "above_soft_max": report.above_soft_max,
            "above_review_max": report.above_review_max,
            "area_min_m2": report.area_min_m2,
            "area_max_m2": report.area_max_m2,
            "area_median_m2": report.area_median_m2,
            "area_mean_m2": report.area_mean_m2,
        },
        "parcel_hash": report.parcel_hash,
        "separators_hash": report.separators_hash,
        "merge_failures": report.merge_failures,
        "soft_flags": report.soft_flags,
        "atomic_absorptions": report.atomic_absorptions,
        "atomic_expansions": report.atomic_expansions,
        "unabsorbed_atomic": report.unabsorbed_atomic,
        "dedicated_landmark_count": report.dedicated_landmark_count,
        "area_rules": {
            "target_max_m2": report.target_max_m2,
            "target_max_acres": round(report.target_max_m2 / 4046.8564224, 3),
            "hard_max_m2": report.hard_max_m2,
            "hard_max_acres": round(report.hard_max_m2 / 4046.8564224, 3),
            "above_hard_max": report.above_hard_max,
            "max_aspect_ratio": report.max_aspect_ratio,
            "known_hard_max_exceptions": report.hard_max_known_exceptions,
        },
    }


def _load_parcels(ctx: PipelineContext, *, from_candidates: bool) -> list[dict[str, Any]]:
    if from_candidates:
        path = artifacts.CANDIDATES.path(ctx)
    else:
        path = artifacts.PUBLISHED_TERRITORIES.path(ctx)
    if not path.exists():
        raise ClusterError(f"Stage 10: missing parcels at {path}")
    data = read_geojson(path)
    features = list(data.get("features") or [])
    if not features:
        raise ClusterError(f"Stage 10: no features in {path}")
    return features


def _try_load_places(ctx: PipelineContext) -> list[_PlaceHint]:
    """Optional place polygons for affinity scoring.

    Reloading Overture/OSM place polygons from raw extracts is too expensive for
    Stage 10 on a full AOI. Name-stem affinity from parcel properties covers the
    common case (\"Jayanagar 4th Block\" fragments). Callers/tests may inject
    ``places=`` explicitly; a future intermediate place cache can wire here.
    """
    del ctx
    return []


def _expand_or_absorb_atomic_landmarks(
    nodes: list[_ClusterNode],
    *,
    barrier_geom: BaseGeometry | None,
    gp: GameplayThresholds,
    standalone_min_m2: float,
    max_aspect_ratio: float,
    max_area_loss_m2: float,
) -> tuple[
    list[_ClusterNode],
    list[_ClusterNode],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Absorb all non-protected atomics whole into ordinary fabric.

    Product classes are legendary (source-protected) and ordinary only. There
    is no ``landmark_dedicated`` / special expansion path: sub-50-acre named
    landmarks never become standalone prizes.
    """
    del standalone_min_m2, max_aspect_ratio  # expansion removed; keep signature
    active = {node.uid: node for node in nodes}
    expansions: list[dict[str, Any]] = []  # always empty; kept for report shape
    absorbed: list[dict[str, Any]] = []
    unabsorbed: list[dict[str, Any]] = []

    atomic_ids = [
        node.uid
        for node in stable_sort(nodes, key=lambda n: (-n.area_m2, n.uid))
        if node.props.get("atomic") is True and not node.protected
    ]

    for atomic_id in atomic_ids:
        seed = active.get(atomic_id)
        if seed is None:
            continue

        decision = _absorb_one_atomic(
            seed,
            active,
            barrier_geom=barrier_geom,
            gp=gp,
            max_area_loss_m2=max_area_loss_m2,
        )
        if decision["ok"]:
            absorbed.append(
                {
                    "landmark_territory_id": seed.uid,
                    "landmark_name": seed.props.get("atomic_source_name")
                    or seed.props.get("name"),
                    "landmark_slug": seed.props.get("atomic_source_slug")
                    or seed.props.get("slug"),
                    "absorbed_into": decision["absorbed_into"],
                    "result_id": decision["result_id"],
                    "area_m2": round(seed.area_m2, 3),
                    "decision": "absorbed_into_fabric",
                    "absorbed_into_kind": decision.get("absorbed_into_kind"),
                }
            )
        else:
            seed.needs_review = True
            if "atomic_unabsorbed" not in seed.review_reasons:
                seed.review_reasons.append("atomic_unabsorbed")
            unabsorbed.append(
                {
                    "territory_id": seed.uid,
                    "name": seed.props.get("atomic_source_name")
                    or seed.props.get("name"),
                    "area_m2": round(seed.area_m2, 3),
                    "reason": decision["reason"],
                }
            )

    fabric_nodes = list(active.values())
    dedicated_nodes: list[_ClusterNode] = []
    return (
        stable_sort(fabric_nodes, key=lambda n: n.uid),
        dedicated_nodes,
        expansions,
        absorbed,
        unabsorbed,
    )


def _try_expand_landmark(
    seed: _ClusterNode,
    active: dict[str, _ClusterNode],
    *,
    barrier_geom: BaseGeometry | None,
    gp: GameplayThresholds,
    standalone_min_m2: float,
    max_aspect_ratio: float,
    max_area_loss_m2: float,
) -> tuple[_ClusterNode | None, list[str], str]:
    """Annex whole adjacent fabric parcels until >= standalone floor + compact."""
    working_geom = seed.geom
    working_members = list(seed.member_ids)
    working_area = seed.area_m2
    annexed: list[str] = []
    safety = 0
    last_reason = "no_adjacent_fabric"
    reserved = {seed.uid}

    while working_area + 1e-6 < standalone_min_m2 and safety < 200:
        safety += 1
        candidates: list[tuple[float, float, str, _ClusterNode, BaseGeometry]] = []
        blocked = 0
        oversized = 0
        for other in active.values():
            if other.uid in reserved or other.uid in annexed:
                continue
            if other.frozen or other.props.get("atomic") is True:
                continue
            shared = _shared_border_length(working_geom, other.geom)
            if shared < gp.min_shared_border_m:
                continue
            if _border_crosses_barrier(working_geom, other.geom, barrier_geom):
                blocked += 1
                continue
            if working_area + other.area_m2 > gp.hard_max_m2 + 1e-6:
                oversized += 1
                continue
            merge = safe_merge_geometry(
                working_geom, other.geom, max_area_loss_m2=max_area_loss_m2
            )
            if merge.geometry is None:
                continue
            quality = shape_score(
                merge.geometry, max_aspect_ratio=max_aspect_ratio
            )
            candidates.append((-shared, -quality, other.uid, other, merge.geometry))

        if not candidates:
            if blocked:
                last_reason = "barrier_blocked"
            elif oversized:
                last_reason = "hard_max_blocked"
            else:
                last_reason = "no_adjacent_fabric"
            break

        candidates.sort(key=lambda t: (t[0], t[1], t[2]))
        _, _, winner_uid, winner, merged_geom = candidates[0]
        working_geom = merged_geom
        working_area = float(merged_geom.area)
        working_members = sorted(set(working_members + winner.member_ids))
        annexed.append(winner_uid)
        reserved.add(winner_uid)

    # Once the floor is met, keep annexing only while aspect stays above the
    # 3:1 cap and the candidate materially improves shape without overshooting
    # the hard max.
    compact_safety = 0
    while (
        working_area + 1e-6 >= standalone_min_m2
        and compact_safety < 40
    ):
        compact_safety += 1
        current_aspect = float(shape_quality(working_geom)["aspect_ratio"])
        if current_aspect <= max_aspect_ratio + 1e-9:
            break
        current_score = shape_score(
            working_geom, max_aspect_ratio=max_aspect_ratio
        )
        improvers: list[tuple[float, float, str, _ClusterNode, BaseGeometry]] = []
        for other in active.values():
            if other.uid in reserved or other.uid in annexed:
                continue
            if other.frozen or other.props.get("atomic") is True:
                continue
            shared = _shared_border_length(working_geom, other.geom)
            if shared < gp.min_shared_border_m:
                continue
            if _border_crosses_barrier(working_geom, other.geom, barrier_geom):
                continue
            if working_area + other.area_m2 > gp.hard_max_m2 + 1e-6:
                continue
            merge = safe_merge_geometry(
                working_geom, other.geom, max_area_loss_m2=max_area_loss_m2
            )
            if merge.geometry is None:
                continue
            after_aspect = float(shape_quality(merge.geometry)["aspect_ratio"])
            after_score = shape_score(
                merge.geometry, max_aspect_ratio=max_aspect_ratio
            )
            if after_aspect + 1e-9 >= current_aspect and after_score <= current_score:
                continue
            improvers.append((-after_score, after_aspect, other.uid, other, merge.geometry))
        if not improvers:
            break
        improvers.sort(key=lambda t: (t[0], t[1], t[2]))
        _, _, winner_uid, winner, merged_geom = improvers[0]
        working_geom = merged_geom
        working_area = float(merged_geom.area)
        working_members = sorted(set(working_members + winner.member_ids))
        annexed.append(winner_uid)
        reserved.add(winner_uid)

    if working_area + 1e-6 < standalone_min_m2:
        return None, [], last_reason

    aspect = float(shape_quality(working_geom)["aspect_ratio"])
    review_reasons: list[str] = []
    # Prefer compact expansions, but once the 50-acre floor is met keep the
    # dedicated landmark even if aspect is imperfect — Stage 11 can rebalance.
    if aspect > max_aspect_ratio + 1e-9:
        review_reasons.append("expanded_aspect")

    # Build a synthetic partner only for deterministic uid minting.
    partner = _ClusterNode(
        uid=annexed[-1] if annexed else seed.uid,
        geom=working_geom,
        props={},
        member_ids=working_members,
        area_m2=working_area,
        place_key=None,
        name_stem=None,
    )
    dedicated = _ClusterNode(
        uid=_merged_uid(seed, partner) if annexed else seed.uid,
        geom=working_geom,
        props=_dedicated_landmark_props(seed),
        member_ids=working_members,
        area_m2=working_area,
        place_key=None,
        name_stem=_name_stem(
            seed.props.get("atomic_source_name") or seed.props.get("name")
        ),
        needs_review=bool(review_reasons),
        review_reasons=review_reasons,
    )
    return dedicated, annexed, "ok"


def _dedicated_landmark_props(seed: _ClusterNode) -> dict[str, Any]:
    props = deepcopy(seed.props)
    name = seed.props.get("atomic_source_name") or seed.props.get("name")
    slug = seed.props.get("atomic_source_slug") or seed.props.get("slug")
    props.update(
        {
            "name": name,
            "slug": slug,
            "kind": seed.props.get("kind") or "landmark",
            "name_source": "landmark",
            "atomic": True,
            "protected": False,
            "landmark_dedicated": True,
            "role": seed.props.get("role") or "major",
        }
    )
    return props


def _absorb_remaining_solo_atomics(
    active: dict[str, _ClusterNode],
    adjacency: dict[str, set[str]],
    shared_cache: dict[tuple[str, str], float],
    *,
    barrier_geom: BaseGeometry | None,
    gp: GameplayThresholds,
    max_area_loss_m2: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Force-absorb any territory that is still a solo non-protected atomic."""
    absorbed: list[dict[str, Any]] = []
    unabsorbed: list[dict[str, Any]] = []
    solo_ids = [
        node.uid
        for node in stable_sort(list(active.values()), key=lambda n: (-n.area_m2, n.uid))
        if (
            not node.protected
            and node.props.get("atomic") is True
            and len(set(node.member_ids)) <= 1
        )
    ]
    for atomic_id in solo_ids:
        seed = active.get(atomic_id)
        if seed is None:
            continue
        decision = _absorb_one_atomic(
            seed,
            active,
            barrier_geom=barrier_geom,
            gp=gp,
            max_area_loss_m2=max_area_loss_m2,
        )
        if not decision["ok"]:
            seed.needs_review = True
            if "atomic_unabsorbed" not in seed.review_reasons:
                seed.review_reasons.append("atomic_unabsorbed")
            unabsorbed.append(
                {
                    "territory_id": seed.uid,
                    "name": seed.props.get("atomic_source_name") or seed.props.get("name"),
                    "area_m2": round(seed.area_m2, 3),
                    "reason": decision["reason"],
                }
            )
            continue

        result_id = str(decision["result_id"])
        winner_old = str(decision["absorbed_into"])
        # Rebuild adjacency around the merged node.
        parents = {atomic_id, winner_old}
        neighbours: set[str] = set()
        for uid in parents:
            neighbours |= adjacency.get(uid, set())
        neighbours -= parents
        for uid in parents:
            for nbr in list(adjacency.get(uid, set())):
                adjacency.setdefault(nbr, set()).discard(uid)
                key = (uid, nbr) if uid < nbr else (nbr, uid)
                shared_cache.pop(key, None)
            adjacency.pop(uid, None)
        adjacency[result_id] = set()
        merged = active[result_id]
        for nbr_uid in sorted(neighbours):
            if nbr_uid not in active:
                continue
            shared_len = _shared_border_length(merged.geom, active[nbr_uid].geom)
            if shared_len < gp.min_shared_border_m:
                continue
            adjacency[result_id].add(nbr_uid)
            adjacency.setdefault(nbr_uid, set()).add(result_id)
            edge = (result_id, nbr_uid) if result_id < nbr_uid else (nbr_uid, result_id)
            shared_cache[edge] = shared_len

        absorbed.append(
            {
                "landmark_territory_id": atomic_id,
                "landmark_name": seed.props.get("atomic_source_name") or seed.props.get("name"),
                "landmark_slug": seed.props.get("atomic_source_slug") or seed.props.get("slug"),
                "absorbed_into": winner_old,
                "result_id": result_id,
                "area_m2": round(seed.area_m2, 3),
                "decision": "absorbed_into_fabric",
                "absorbed_into_kind": decision.get("absorbed_into_kind"),
            }
        )
    return absorbed, unabsorbed


def _absorb_one_atomic(
    atomic: _ClusterNode,
    active: dict[str, _ClusterNode],
    *,
    barrier_geom: BaseGeometry | None,
    gp: GameplayThresholds,
    max_area_loss_m2: float,
) -> dict[str, Any]:
    """Absorb an atomic whole into ordinary fabric (or a peer atomic as last resort)."""
    fabric_candidates: list[tuple[float, str, _ClusterNode]] = []
    atomic_candidates: list[tuple[float, str, _ClusterNode]] = []
    blocked = 0
    oversized = 0
    for other in active.values():
        if other.uid == atomic.uid:
            continue
        # Source-protected / legendary prizes stay byte-stable; never absorb into them.
        if other.protected:
            continue
        shared = _shared_border_length(atomic.geom, other.geom)
        if shared < 0.1:
            continue
        if _border_crosses_barrier(atomic.geom, other.geom, barrier_geom):
            blocked += 1
            continue
        if atomic.area_m2 + other.area_m2 > gp.hard_max_m2 + 1e-6:
            oversized += 1
            continue
        entry = (-shared, other.uid, other)
        if other.props.get("atomic") is True:
            atomic_candidates.append(entry)
        else:
            fabric_candidates.append(entry)

    # Prefer ordinary fabric that is undersized or has room under soft_max,
    # then longest shared border. Peer atomics only when no fabric neighbour.
    def _rank(entry: tuple[float, str, _ClusterNode]) -> tuple:
        neg_shared, uid, other = entry
        room = gp.hard_max_m2 - other.area_m2
        undersized = 0 if other.area_m2 + 1e-6 < gp.soft_min_m2 else 1
        fits_soft = 0 if atomic.area_m2 + other.area_m2 <= gp.soft_max_m2 + 1e-6 else 1
        return (undersized, fits_soft, neg_shared, -room, uid)

    fabric_candidates.sort(key=_rank)
    atomic_candidates.sort(key=_rank)
    candidates = fabric_candidates or atomic_candidates
    if not candidates:
        reason = (
            "barrier_blocked"
            if blocked
            else "hard_max_blocked"
            if oversized
            else "no_adjacent_fabric"
        )
        return {"ok": False, "reason": reason}

    _, _, winner = candidates[0]
    result = safe_merge_geometry(
        atomic.geom,
        winner.geom,
        max_area_loss_m2=max_area_loss_m2,
    )
    if result.geometry is None:
        return {"ok": False, "reason": result.rejected_reason or "merge_failed"}

    new_uid = _merged_uid(atomic, winner)
    merged = _ClusterNode(
        uid=new_uid,
        geom=result.geometry,
        props=_merge_props(atomic, winner),
        member_ids=sorted(set(atomic.member_ids + winner.member_ids)),
        area_m2=float(result.geometry.area),
        place_key=winner.place_key,
        name_stem=winner.name_stem,
        needs_review=atomic.needs_review or winner.needs_review,
        review_reasons=sorted(set(atomic.review_reasons + winner.review_reasons)),
    )
    del active[atomic.uid]
    del active[winner.uid]
    active[new_uid] = merged
    return {
        "ok": True,
        "absorbed_into": winner.uid,
        "result_id": new_uid,
        "absorbed_into_kind": "atomic" if winner.props.get("atomic") else "fabric",
    }



def _nodes_from_parcels(
    parcels: list[dict[str, Any]],
    places: list[_PlaceHint],
    crs_work: str,
    ctx: PipelineContext,
) -> tuple[list[_ClusterNode], list[_ClusterNode]]:
    place_tree = STRtree([p.geom for p in places]) if places else None
    fabric: list[_ClusterNode] = []
    protected: list[_ClusterNode] = []

    for idx, feature in enumerate(parcels):
        props = dict(feature.get("properties") or {})
        geom_json = feature.get("geometry")
        if not geom_json:
            raise ClusterError(f"Stage 10: feature[{idx}] missing geometry")
        try:
            geom4326 = shape(geom_json)
        except Exception as exc:
            raise ClusterError(f"Stage 10: feature[{idx}] bad geometry: {exc}") from exc
        if geom4326 is None or geom4326.is_empty:
            raise ClusterError(f"Stage 10: feature[{idx}] empty geometry")
        if not is_valid(geom4326):
            raise ClusterError(
                f"Stage 10: feature[{idx}] slug={props.get('slug')!r} invalid geometry"
            )

        work = _as_polygonal(to_work(geom4326, crs_work))
        if work is None or work.is_empty:
            raise ClusterError(f"Stage 10: feature[{idx}] empty after to_work")

        tid = str(props.get("territory_id") or f"missing-{idx:05d}")
        area = float(work.area)
        place_key = _match_place_key(work, places, place_tree)
        name_stem = _name_stem(props.get("name"))
        node = _ClusterNode(
            uid=tid,
            geom=work,
            props=props,
            member_ids=[tid],
            area_m2=area,
            place_key=place_key,
            name_stem=name_stem,
            needs_review=bool(props.get("needs_review")),
            review_reasons=[],
            store_geometry=deepcopy(geom_json),
        )
        if node.protected:
            standalone_min_m2 = float(ctx.thresholds.standalone_min_area_m2)
            if area + 1e-6 < standalone_min_m2:
                # Stage 03 may mark a landmark protected from source tags while the
                # carved parcel is still below the gameplay floor (e.g. Christ
                # University ~51 ac). Demote to fabric so it merges with neighbours.
                node.props["protected"] = False
                fabric.append(node)
            else:
                protected.append(node)
        else:
            fabric.append(node)

    fabric = stable_sort(fabric, key=lambda n: n.uid)
    protected = stable_sort(protected, key=lambda n: n.uid)
    return fabric, protected


def _match_place_key(
    geom: BaseGeometry,
    places: list[_PlaceHint],
    tree: STRtree | None,
) -> str | None:
    if not places or tree is None or geom.is_empty:
        return None
    area = float(geom.area)
    if area <= 0:
        return None
    hits = tree.query(geom)
    candidates: list[_PlaceHint] = []
    pt = geom.representative_point()
    for idx in hits:
        place = places[int(idx)]
        if place.geom.contains(pt):
            candidates.append(place)
            continue
        inter = geom.intersection(place.geom)
        if inter.is_empty:
            continue
        if float(inter.area) / area >= 0.5:
            candidates.append(place)
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p.area_m2, p.key))
    return candidates[0].key


def _nearest_fabric_neighbour(
    scrap: _ClusterNode,
    active: dict[str, _ClusterNode],
    min_shared: float,
    *,
    ignore_barrier: bool,
) -> _ClusterNode | None:
    """Longest shared-border fabric neighbour (optionally ignoring barriers)."""
    del ignore_barrier
    candidates: list[tuple[float, float, str, _ClusterNode]] = []
    scrap_c = scrap.geom.centroid
    search = scrap.geom.buffer(1.0)
    for other in active.values():
        if other.uid == scrap.uid or other.frozen:
            continue
        if not search.intersects(other.geom):
            continue
        shared = _shared_border_length(scrap.geom, other.geom)
        if shared < min_shared:
            # Near-touch fallback for micro-scraps.
            near = float(scrap.geom.buffer(1.0).intersection(other.geom).area)
            if near <= 0:
                continue
            shared = max(shared, near)
        dist = float(scrap_c.distance(other.geom.centroid))
        candidates.append((shared, dist, other.uid, other))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))
    return candidates[0][3]


def _coalesce_undersized_fabric(
    active: dict[str, _ClusterNode],
    adjacency: dict[str, set[str]],
    shared_cache: dict[tuple[str, str], float],
    *,
    barrier_geom: BaseGeometry | None,
    gp: GameplayThresholds,
    max_gap: float,
) -> int:
    """Merge undersized fabric pairs when the union fits under hard_max."""
    merges = 0
    while True:
        undersized = [
            n
            for n in active.values()
            if not n.frozen and n.area_m2 + 1e-6 < gp.soft_min_m2
        ]
        if len(undersized) < 2:
            break
        best: tuple[float, _ClusterNode, _ClusterNode] | None = None
        best_score = -1.0
        undersized_ids = {n.uid for n in undersized}
        for node_a in undersized:
            for b_uid in adjacency.get(node_a.uid, set()):
                if b_uid not in undersized_ids or b_uid not in active:
                    continue
                node_b = active[b_uid]
                if node_b.frozen or node_b.protected:
                    continue
                if node_a.uid >= node_b.uid:
                    continue
                combined = node_a.area_m2 + node_b.area_m2
                if combined > gp.hard_max_m2 + 1e-6:
                    continue
                if _border_crosses_barrier(node_a.geom, node_b.geom, barrier_geom):
                    continue
                shared = _shared_border_length(node_a.geom, node_b.geom)
                if shared < gp.min_shared_border_m:
                    continue
                score = shared
                if combined + 1e-6 >= gp.soft_min_m2:
                    score += 1_000_000.0
                if score > best_score:
                    best_score = score
                    best = (score, node_a, node_b)
        if best is None:
            break
        _, node_a, node_b = best
        if node_a.uid not in active or node_b.uid not in active:
            continue
        result = safe_merge_geometry(node_a.geom, node_b.geom, max_area_loss_m2=max_gap)
        if result.geometry is None:
            break
        merged_area = float(result.geometry.area)
        if merged_area > gp.hard_max_m2 + 1e-6:
            break
        new_uid = _merged_uid(node_a, node_b)
        merged = _ClusterNode(
            uid=new_uid,
            geom=result.geometry,
            props=_merge_props(node_a, node_b),
            member_ids=sorted(set(node_a.member_ids + node_b.member_ids)),
            area_m2=merged_area,
            place_key=_dominant_place_key(node_a, node_b),
            name_stem=_dominant_name_stem(node_a, node_b),
            needs_review=node_a.needs_review or node_b.needs_review,
            review_reasons=sorted(
                set(
                    node_a.review_reasons
                    + node_b.review_reasons
                    + ["undersized_pair_merge"]
                )
            ),
        )
        parents = {node_a.uid, node_b.uid}
        neighbours: set[str] = set()
        for uid in parents:
            neighbours |= adjacency.get(uid, set())
        neighbours -= parents
        for uid in parents:
            for nbr in list(adjacency.get(uid, set())):
                adjacency.setdefault(nbr, set()).discard(uid)
                k = (uid, nbr) if uid < nbr else (nbr, uid)
                shared_cache.pop(k, None)
            adjacency.pop(uid, None)
            del active[uid]
        active[new_uid] = merged
        adjacency[new_uid] = set()
        for nbr_uid in sorted(neighbours):
            if nbr_uid not in active:
                continue
            shared_len = _shared_border_length(merged.geom, active[nbr_uid].geom)
            if shared_len < gp.min_shared_border_m:
                continue
            adjacency[new_uid].add(nbr_uid)
            adjacency.setdefault(nbr_uid, set()).add(new_uid)
            edge = (new_uid, nbr_uid) if new_uid < nbr_uid else (nbr_uid, new_uid)
            shared_cache[edge] = shared_len
        merges += 1
    return merges


def _pick_escape_neighbour(
    scrap: _ClusterNode,
    active: dict[str, _ClusterNode],
    *,
    dedicated_by_uid: dict[str, _ClusterNode],
    barrier_geom: BaseGeometry | None,
    gp: GameplayThresholds,
) -> _ClusterNode | None:
    """Choose absorb target for undersized/strip fabric.

    Preference order:
    1. longest-border fabric neighbour that does not cross a barrier
    2. longest-border fabric neighbour even across a barrier
    """
    del dedicated_by_uid  # special class removed; no dedicated absorb targets
    fabric_safe: list[tuple[float, float, str, _ClusterNode]] = []
    fabric_any: list[tuple[float, float, str, _ClusterNode]] = []
    scrap_c = scrap.geom.centroid
    search = scrap.geom.buffer(1.0)

    def _shared(other: _ClusterNode) -> float:
        shared = _shared_border_length(scrap.geom, other.geom)
        if shared >= 0.1:
            return shared
        near = float(search.intersection(other.geom).area)
        return near if near > 0 else 0.0

    for other in active.values():
        if other.uid == scrap.uid or other.protected:
            continue
        if not search.intersects(other.geom):
            continue
        shared = _shared(other)
        if shared <= 0:
            continue
        if scrap.area_m2 + other.area_m2 > gp.hard_max_m2 + 1e-6:
            continue
        dist = float(scrap_c.distance(other.geom.centroid))
        entry = (shared, dist, other.uid, other)
        fabric_any.append(entry)
        if not _border_crosses_barrier(scrap.geom, other.geom, barrier_geom):
            fabric_safe.append(entry)

    for pool in (fabric_safe, fabric_any):
        if not pool:
            continue
        # Prefer undersized winners so escape can finish under hard_max.
        pool.sort(
            key=lambda t: (
                0 if t[3].area_m2 + 1e-6 < gp.soft_min_m2 else 1,
                -t[0],
                t[1],
                t[2],
            )
        )
        return pool[0][3]
    return None


def _barrier_union(
    separators: list[dict[str, Any]],
    gp: GameplayThresholds,
    crs_work: str,
    snap_m: float,
) -> BaseGeometry | None:
    barrier_lines: list[BaseGeometry] = []
    highway = set(gp.barrier_highway_classes)
    railway = set(gp.barrier_railway_classes)
    waterway = set(gp.barrier_waterway_classes)
    area_groups = set(gp.barrier_area_groups)

    for feature in separators:
        props = feature.get("properties") or {}
        group = str(props.get("group") or "")
        klass = str(props.get("class") or "")
        is_barrier = False
        if group == "highway" and klass in highway:
            is_barrier = True
        elif group == "railway" and klass in railway:
            is_barrier = True
        elif group == "waterway" and klass in waterway:
            is_barrier = True
        elif group in area_groups:
            is_barrier = True
        if not is_barrier:
            continue
        geom_json = feature.get("geometry")
        if not geom_json:
            continue
        try:
            g = shape(geom_json)
        except Exception:
            continue
        if g is None or g.is_empty:
            continue
        work = to_work(g, crs_work)
        if work.is_empty:
            continue
        barrier_lines.append(work)

    if not barrier_lines:
        return None
    merged = unary_union(barrier_lines)
    if merged.is_empty:
        return None
    # Buffer so shared parcel borders that coincide with the separator register.
    return merged.buffer(max(snap_m, _BORDER_EPS_M))


def _build_adjacency(
    fabric: list[_ClusterNode],
    barrier_geom: BaseGeometry | None,
    min_shared: float,
) -> tuple[dict[str, set[str]], int]:
    adjacency: dict[str, set[str]] = {n.uid: set() for n in fabric}
    barrier_blocked = 0
    if len(fabric) < 2:
        return adjacency, barrier_blocked

    geoms = [n.geom for n in fabric]
    tree = STRtree(geoms)
    for i, node in enumerate(fabric):
        hits = tree.query(node.geom.buffer(_BORDER_EPS_M))
        for j in hits:
            j = int(j)
            if j <= i:
                continue
            other = fabric[j]
            shared = _shared_border_length(node.geom, other.geom)
            if shared < min_shared:
                continue
            if _border_crosses_barrier(node.geom, other.geom, barrier_geom):
                barrier_blocked += 1
                continue
            adjacency[node.uid].add(other.uid)
            adjacency[other.uid].add(node.uid)
    return adjacency, barrier_blocked


def _border_crosses_barrier(
    a: BaseGeometry,
    b: BaseGeometry,
    barrier_geom: BaseGeometry | None,
) -> bool:
    if barrier_geom is None or barrier_geom.is_empty:
        return False
    try:
        shared = a.boundary.intersection(b.buffer(_BORDER_EPS_M))
        if shared is None or shared.is_empty:
            return False
        shared_length = float(shared.length)
        if shared_length <= 0:
            return False
        on_barrier = shared.intersection(barrier_geom)
        if on_barrier is None or on_barrier.is_empty:
            return False
        return (
            float(on_barrier.length) / shared_length
            >= _BARRIER_SHARED_BORDER_REFUSE
        )
    except Exception:
        return False


def _push_candidate(
    heap: list[tuple[float, str, str]],
    active: dict[str, _ClusterNode],
    uid_a: str,
    uid_b: str,
    shared: float,
    gp: GameplayThresholds,
) -> None:
    if uid_a not in active or uid_b not in active:
        return
    node_a = active[uid_a]
    node_b = active[uid_b]
    score = _score_pair(node_a, node_b, shared, gp)
    if not _merge_allowed(node_a, node_b, score, gp):
        return
    merged_area = node_a.area_m2 + node_b.area_m2
    place_aff = _place_affinity(node_a, node_b)
    max_allowed = min(
        gp.hard_max_m2,
        gp.place_max_m2 if place_aff >= 1.0 else gp.soft_max_m2,
    )
    if merged_area > max_allowed + 1e-6:
        return
    left, right = (uid_a, uid_b) if uid_a < uid_b else (uid_b, uid_a)
    heapq.heappush(heap, (-score, left, right))


def _best_merge(
    active: dict[str, _ClusterNode],
    adjacency: dict[str, set[str]],
    gp: GameplayThresholds,
) -> tuple[str, str, float, float] | None:
    """Legacy linear scan retained for tests; production uses the heap path."""
    best: tuple[float, str, str, float, float] | None = None
    for uid_a in sorted(active.keys()):
        node_a = active[uid_a]
        for uid_b in sorted(adjacency.get(uid_a, set())):
            if uid_b <= uid_a:
                continue
            if uid_b not in active:
                continue
            node_b = active[uid_b]
            shared = _shared_border_length(node_a.geom, node_b.geom)
            if shared < gp.min_shared_border_m:
                continue
            score = _score_pair(node_a, node_b, shared, gp)
            if not _merge_allowed(node_a, node_b, score, gp):
                continue
            merged_area = node_a.area_m2 + node_b.area_m2
            place_aff = _place_affinity(node_a, node_b)
            max_allowed = min(
                gp.hard_max_m2,
                gp.place_max_m2 if place_aff >= 1.0 else gp.soft_max_m2,
            )
            if merged_area > max_allowed + 1e-6:
                continue
            candidate = (-score, uid_a, uid_b, score, shared)
            if best is None or candidate < best:
                best = candidate
    if best is None:
        return None
    _, uid_a, uid_b, score, shared = best
    return uid_a, uid_b, score, shared


def _merge_props(a: _ClusterNode, b: _ClusterNode) -> dict[str, Any]:
    """Prefer fabric/place identity; keep landmark name only if it dominates area."""
    land_a = a.props.get("atomic") is True and a.props.get("protected") is not True
    land_b = b.props.get("atomic") is True and b.props.get("protected") is not True
    total = a.area_m2 + b.area_m2
    # If one side is a mergeable landmark under 50% of the union, keep the other.
    if land_a and not land_b and a.area_m2 < 0.5 * total:
        dominant = b
    elif land_b and not land_a and b.area_m2 < 0.5 * total:
        dominant = a
    else:
        dominant = a if a.area_m2 >= b.area_m2 else b
    props = deepcopy(dominant.props)
    props["protected"] = False
    props["atomic"] = False
    props.pop("role", None)
    if props.get("kind") in {None, "fabric"} and not land_a and not land_b:
        props["kind"] = "block"
    return props


def _merge_allowed(
    a: _ClusterNode,
    b: _ClusterNode,
    score: float,
    gp: GameplayThresholds,
) -> bool:
    # Source-protected and expanded dedicated landmarks never merge.
    if a.frozen or b.frozen:
        return False
    below = a.area_m2 < gp.soft_min_m2 or b.area_m2 < gp.soft_min_m2
    if below:
        return True
    both_under_max = a.area_m2 <= gp.soft_max_m2 and b.area_m2 <= gp.soft_max_m2
    if both_under_max and score >= gp.min_merge_score:
        return True
    return False


def _score_pair(
    a: _ClusterNode,
    b: _ClusterNode,
    shared: float,
    gp: GameplayThresholds,
) -> float:
    place = _place_affinity(a, b)
    perim = min(float(a.geom.length), float(b.geom.length))
    border_norm = (shared / perim) if perim > 0 else 0.0
    border_norm = max(0.0, min(1.0, border_norm))
    size = _size_urgency(a.area_m2, b.area_m2, gp)
    name = _name_affinity(a, b)
    return (
        gp.w_place * place
        + gp.w_border * border_norm
        + gp.w_size * size
        + gp.w_name * name
    )


def _place_affinity(a: _ClusterNode, b: _ClusterNode) -> float:
    if a.place_key and b.place_key and a.place_key == b.place_key:
        return 1.0
    return 0.0


def _size_urgency(area_a: float, area_b: float, gp: GameplayThresholds) -> float:
    soft_min = gp.soft_min_m2
    soft_max = gp.soft_max_m2
    if area_a < soft_min and area_b < soft_min:
        return 1.0
    if area_a < soft_min or area_b < soft_min:
        return 0.75
    if area_a > soft_max or area_b > soft_max:
        return 0.1
    # Prefer merging smaller pairs inside the band.
    mean = (area_a + area_b) / 2.0
    return max(0.0, 1.0 - (mean - soft_min) / max(soft_max - soft_min, 1.0))


def _name_affinity(a: _ClusterNode, b: _ClusterNode) -> float:
    if a.name_stem and b.name_stem and a.name_stem == b.name_stem:
        return 1.0
    name_a = str(a.props.get("name") or "").lower()
    name_b = str(b.props.get("name") or "").lower()
    if not name_a or not name_b:
        return 0.0
    tokens_a = set(_NAME_TOKEN_RE.findall(name_a))
    tokens_b = set(_NAME_TOKEN_RE.findall(name_b))
    if not tokens_a or not tokens_b:
        return 0.0
    inter = tokens_a & tokens_b
    if not inter:
        return 0.0
    # Shared prefix tokens like "jayanagar", "4th", "block"
    return len(inter) / max(len(tokens_a | tokens_b), 1)


def _name_stem(name: Any) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    tokens = _NAME_TOKEN_RE.findall(name.lower())
    if len(tokens) < 2:
        return tokens[0] if tokens else None
    # Drop trailing numeric fragment suffixes loosely: keep first 3 tokens.
    return "-".join(tokens[:3])


def _dominant_place_key(a: _ClusterNode, b: _ClusterNode) -> str | None:
    if a.place_key and a.place_key == b.place_key:
        return a.place_key
    if a.area_m2 >= b.area_m2:
        return a.place_key
    return b.place_key


def _dominant_name_stem(a: _ClusterNode, b: _ClusterNode) -> str | None:
    if a.name_stem and a.name_stem == b.name_stem:
        return a.name_stem
    if a.area_m2 >= b.area_m2:
        return a.name_stem
    return b.name_stem


def _merged_uid(a: _ClusterNode, b: _ClusterNode) -> str:
    left, right = sorted([a.uid, b.uid])
    digest = content_hash(f"{left}+{right}")[:16]
    return f"cluster:{digest}"


def _drop_edge(adjacency: dict[str, set[str]], a: str, b: str) -> None:
    if a in adjacency:
        adjacency[a].discard(b)
    if b in adjacency:
        adjacency[b].discard(a)


def _emit_features(
    nodes: list[_ClusterNode],
    ctx: PipelineContext,
    crs_work: str,
    crs_store: str,
    gp: GameplayThresholds,
) -> list[dict[str, Any]]:
    city = ctx.region.city
    area = ctx.region.area
    used_slugs: set[str] = set()
    features: list[dict[str, Any]] = []

    for node in stable_sort(
        nodes, key=lambda n: (0 if n.protected or n.landmark_dedicated else 1, n.uid)
    ):
        if node.protected and node.store_geometry is not None:
            # Exact parcel geometry — never reproject protected landmarks.
            geom_json = deepcopy(node.store_geometry)
        else:
            store = to_store(node.geom, crs_work, crs_store)
            polygonal = _as_polygonal(store)
            if polygonal is None or polygonal.is_empty:
                raise ClusterError(f"Stage 10: empty store geometry for {node.uid}")
            if not is_valid(polygonal):
                repaired = _as_polygonal(make_valid(polygonal))
                if repaired is None or repaired.is_empty or not is_valid(repaired):
                    raise ClusterError(
                        f"Stage 10: invalid store geometry for {node.uid}"
                    )
                repaired_work = _as_polygonal(to_work(repaired, crs_work))
                if repaired_work is None or (
                    abs(float(repaired_work.area) - node.area_m2)
                    > ctx.thresholds.validation.max_gap_m2
                ):
                    raise ClusterError(
                        "Stage 10: store-CRS geometry repair exceeds area tolerance "
                        f"for {node.uid}"
                    )
                polygonal = repaired
            geom_json = mapping(polygonal)

        if node.protected:
            name = node.props.get("name")
            slug_base = str(
                node.props.get("slug") or slugify(str(name or node.uid))
            )
            slug = slug_base
            kind = node.props.get("kind") or "landmark"
            tid = str(node.props.get("territory_id") or node.uid)
            props = {
                "territory_id": tid,
                "slug": slug,
                "name": name,
                "kind": kind,
                "protected": True,
                "legendary": True,
                "landmark_dedicated": False,
                "territory_class": "legendary",
                "atomic": True,
                "role": node.props.get("role") or "major",
                "area_m2": round(float(node.area_m2), 3),
                "member_territory_ids": list(node.member_ids),
                "member_count": len(node.member_ids),
                "layer": "gameplay",
                "name_source": node.props.get("name_source") or "landmark",
            }
            if node.props.get("atomic_source_slug"):
                props["atomic_source_slug"] = node.props.get("atomic_source_slug")
            if node.props.get("atomic_source_name"):
                props["atomic_source_name"] = node.props.get("atomic_source_name")
            if node.needs_review:
                props["needs_review"] = True
                props["review_reasons"] = list(node.review_reasons)
        else:
            name, slug, name_source = _resolve_cluster_name(node)
            slug = _unique_slug(slug, used_slugs)
            tid = str(gameplay_territory_id(city, area, slug))
            reasons = list(node.review_reasons)
            needs_review = node.needs_review
            if node.area_m2 < gp.soft_min_m2:
                needs_review = True
                if "undersized" not in reasons and "undersized_stuck" not in reasons:
                    reasons.append("undersized")
            if node.area_m2 > gp.review_max_m2:
                needs_review = True
                if "oversized" not in reasons:
                    reasons.append("oversized")
            props = {
                "territory_id": tid,
                "slug": slug,
                "name": name,
                "kind": "block",
                "protected": False,
                "legendary": False,
                "landmark_dedicated": False,
                "territory_class": "ordinary",
                "area_m2": round(float(node.area_m2), 3),
                "member_territory_ids": list(node.member_ids),
                "member_count": len(node.member_ids),
                "layer": "gameplay",
                "name_source": name_source,
            }
            if needs_review:
                props["needs_review"] = True
                props["review_reasons"] = sorted(set(reasons)) or ["needs_review"]
            if node.place_key:
                props["place_key"] = node.place_key

        used_slugs.add(props["slug"])
        features.append(
            {"type": "Feature", "geometry": geom_json, "properties": props}
        )

    return stable_sort(features, key=_feature_sort_key)


def _resolve_cluster_name(node: _ClusterNode) -> tuple[str, str, str]:
    name = node.props.get("name")
    if isinstance(name, str) and name.strip():
        try:
            display = name.strip()
            source = str(node.props.get("name_source") or "inherited")
            return display, slugify(display), source
        except ValueError:
            pass
    if node.name_stem:
        display = node.name_stem.replace("-", " ").title()
        return display, slugify(display), "name_stem"
    # Fallback from first member id fragment.
    key = node.member_ids[0] if node.member_ids else node.uid
    display = f"Cluster {key[:8]}"
    return display, slugify(display), "cluster_fallback"


def _unique_slug(slug: str, used: set[str]) -> str:
    if slug not in used:
        return slug
    n = 2
    while f"{slug}-{n}" in used:
        n += 1
    return f"{slug}-{n}"


def _feature_sort_key(feature: dict[str, Any]) -> tuple:
    props = feature.get("properties") or {}
    return (
        0 if props.get("protected") or props.get("landmark_dedicated") else 1,
        str(props.get("slug") or ""),
        str(props.get("territory_id") or ""),
    )


def _median(sorted_vals: list[float]) -> float:
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0
