"""GIS apply toolbox for Stage 11 beautify suggestions.

Only executes restricted ops via safe_merge_geometry. Never moves free vertices.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from shapely import is_valid
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from lib import artifacts
from lib import validate as validate_lib
from lib.beautify_critic import ALLOWED_OPS
from lib.cluster import _barrier_union
from lib.config import BeautifyThresholds, GameplayThresholds
from lib.contracts import PipelineContext
from lib.crs import to_store, to_work
from lib.determinism import (
    content_hash,
    gameplay_territory_id,
    slugify,
    stable_sort,
)
from lib.io import artifact_hash_input, read_geojson
from lib.normalize import _as_polygonal, _shared_border_length, safe_merge_geometry
from lib.shape import shape_quality

_SOFT_OPS = frozenset({"reject_merge", "keep_standalone", "force_merge_landmark"})
_APPLY_OPS = frozenset({"merge", "absorb_peninsula", "transfer_member_parcel"})
_BORDER_EPS_M = 0.05
# Refuse only when a substantial fraction of the shared border rides a barrier.
# A 3 m motorway buffer otherwise false-positives on near-miss contacts.
_BARRIER_SHARE_REFUSE = 0.35


class BeautifyApplyError(RuntimeError):
    """Stage 11 cannot produce a safe beautified artifact."""


@dataclass
class ApplyReport:
    input_count: int
    output_count: int
    applied: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    soft_flags: list[dict[str, Any]] = field(default_factory=list)
    candidates_hash: str = ""
    suggestions_hash: str = ""
    target_max_m2: float = 0.0
    hard_max_m2: float = 0.0


@dataclass(frozen=True)
class BeautifyApplyResult:
    features: list[dict[str, Any]]
    report: ApplyReport
    validation: dict[str, Any]


def apply_beautify_suggestions(
    ctx: PipelineContext,
    features: list[dict[str, Any]],
    suggestions: list[dict[str, Any]],
    *,
    separators: dict[str, Any] | None = None,
) -> BeautifyApplyResult:
    """Apply high-confidence merge ops; return beautified features + report."""
    gp = ctx.thresholds.gameplay
    bt = ctx.thresholds.beautify
    crs_work = ctx.region.crs_work
    crs_store = ctx.region.crs_store
    max_loss = float(ctx.thresholds.validation.max_gap_m2)

    report = ApplyReport(
        input_count=len(features),
        output_count=0,
        candidates_hash=content_hash(
            artifact_hash_input({"type": "FeatureCollection", "features": features})
        ),
        suggestions_hash=content_hash(artifact_hash_input({"suggestions": suggestions})),
        target_max_m2=gp.soft_max_m2,
        hard_max_m2=gp.hard_max_m2,
    )

    # Working set keyed by territory_id
    active: dict[str, dict[str, Any]] = {}
    for feature in features:
        props = dict(feature.get("properties") or {})
        tid = str(props.get("territory_id") or "")
        if not tid:
            raise BeautifyApplyError("Stage 11: feature missing territory_id")
        if tid in active:
            raise BeautifyApplyError(f"Stage 11: duplicate territory_id {tid}")
        active[tid] = {
            "type": "Feature",
            "geometry": deepcopy(feature.get("geometry")),
            "properties": props,
        }

    barrier_geom: BaseGeometry | None = None
    sep_features: list[dict[str, Any]] | None = None
    if separators is None:
        sep_path = artifacts.SEPARATORS.path(ctx)
        if sep_path.exists():
            sep_features = list(read_geojson(sep_path).get("features") or [])
    elif isinstance(separators, dict):
        sep_features = list(separators.get("features") or [])
    else:
        sep_features = list(separators)
    if sep_features is not None:
        barrier_geom = _barrier_union(
            sep_features, gp, crs_work, float(ctx.thresholds.snap_m)
        )

    parcel_by_id: dict[str, dict[str, Any]] = {}
    parcel_path = artifacts.PUBLISHED_TERRITORIES.path(ctx)
    if parcel_path.exists():
        for feature in read_geojson(parcel_path).get("features") or []:
            props = feature.get("properties") or {}
            tid = str(props.get("territory_id") or "")
            if tid:
                parcel_by_id[tid] = feature

    ranked = stable_sort(
        suggestions,
        key=lambda s: (-float(s.get("confidence") or 0.0), str(s.get("id") or "")),
    )

    for sug in ranked:
        sid = str(sug.get("id") or "")
        op = str(sug.get("op") or "")
        conf = float(sug.get("confidence") or 0.0)
        ids = [str(t) for t in (sug.get("territory_ids") or [])]

        if op not in ALLOWED_OPS:
            report.skipped.append({"id": sid, "reason": f"disallowed_op:{op}"})
            continue

        if op in _SOFT_OPS:
            report.soft_flags.append(
                {
                    "id": sid,
                    "op": op,
                    "territory_ids": ids,
                    "reason": sug.get("reason"),
                    "confidence": conf,
                }
            )
            continue

        if op not in _APPLY_OPS:
            report.skipped.append({"id": sid, "reason": f"not_auto_applicable:{op}"})
            continue

        if conf < bt.auto_apply_min_confidence:
            report.skipped.append(
                {
                    "id": sid,
                    "reason": "below_auto_apply_confidence",
                    "confidence": conf,
                    "threshold": bt.auto_apply_min_confidence,
                }
            )
            continue

        if len(ids) != 2:
            report.skipped.append({"id": sid, "reason": "expected_two_territory_ids"})
            continue

        if op == "transfer_member_parcel":
            donor_id = str(sug.get("donor_territory_id") or ids[0])
            receiver_id = str(sug.get("receiver_territory_id") or ids[1])
            receiver_attempts = [receiver_id]
            # If the primary neighbour cannot improve shape, try other adjacent
            # fabric receivers in longest-border order.
            if donor_id in active:
                try:
                    donor_geom = _as_polygonal(
                        to_work(shape(active[donor_id]["geometry"]), crs_work)
                    )
                except Exception:
                    donor_geom = None
                if donor_geom is not None:
                    ranked: list[tuple[float, str]] = []
                    for other_id, other in active.items():
                        if other_id in {donor_id, receiver_id}:
                            continue
                        oprops = other["properties"]
                        if oprops.get("protected") is True:
                            continue
                        try:
                            other_geom = _as_polygonal(
                                to_work(shape(other["geometry"]), crs_work)
                            )
                        except Exception:
                            continue
                        if other_geom is None:
                            continue
                        shared = _shared_border_length(donor_geom, other_geom)
                        if shared < gp.min_shared_border_m:
                            continue
                        ranked.append((-shared, other_id))
                    ranked.sort()
                    receiver_attempts.extend(oid for _, oid in ranked)

            last_reason = "transfer_failed"
            applied_transfer = False
            for try_receiver in receiver_attempts:
                outcome = _try_transfer_best_parcel(
                    ctx,
                    active,
                    donor_id,
                    try_receiver,
                    parcel_by_id=parcel_by_id,
                    gp=gp,
                    bt=bt,
                    barrier_geom=barrier_geom,
                    max_area_loss_m2=max_loss,
                    crs_work=crs_work,
                    crs_store=crs_store,
                )
                if outcome.get("ok"):
                    report.applied.append(
                        {
                            "id": sid,
                            "op": op,
                            "territory_ids": [donor_id, try_receiver],
                            "parcel_id": outcome.get("parcel_id"),
                            "confidence": conf,
                            "aspect_before": outcome.get("aspect_before"),
                            "aspect_after": outcome.get("aspect_after"),
                            "fallback_receiver": try_receiver != receiver_id,
                        }
                    )
                    applied_transfer = True
                    break
                last_reason = str(outcome.get("reason") or "transfer_failed")
            if not applied_transfer:
                report.skipped.append(
                    {
                        "id": sid,
                        "op": op,
                        "territory_ids": [donor_id, receiver_id],
                        "reason": last_reason,
                    }
                )
            continue

        a_id, b_id = ids[0], ids[1]
        absorb_from = str(sug.get("absorb_from") or "")
        alternates = [str(x) for x in (sug.get("alternate_territory_ids") or [])]
        primary_pair = (a_id, b_id)

        ordered_attempts: list[tuple[str, str]] = []
        seen_attempts: set[tuple[str, str]] = set()
        attempt_pairs = [(a_id, b_id)]
        if absorb_from and absorb_from in active:
            attempt_pairs.extend((absorb_from, alt) for alt in alternates)
        for x, y in attempt_pairs:
            if x not in active or y not in active or x == y:
                continue
            key = tuple(sorted((x, y)))
            if key in seen_attempts:
                continue
            seen_attempts.add(key)  # type: ignore[arg-type]
            ordered_attempts.append((x, y))

        if not ordered_attempts:
            report.skipped.append(
                {"id": sid, "reason": "territory_already_consumed_or_missing"}
            )
            continue

        last_reason = "merge_failed"
        last_pair = ordered_attempts[0]
        applied_ok = False
        for try_a, try_b in ordered_attempts:
            last_pair = (try_a, try_b)
            outcome = _try_merge_pair(
                ctx,
                active,
                try_a,
                try_b,
                gp=gp,
                bt=bt,
                barrier_geom=barrier_geom,
                max_area_loss_m2=max_loss,
                crs_work=crs_work,
                crs_store=crs_store,
                op=op,
            )
            if outcome.get("ok"):
                report.applied.append(
                    {
                        "id": sid,
                        "op": op,
                        "territory_ids": [try_a, try_b],
                        "result_territory_id": outcome["result_id"],
                        "confidence": conf,
                        "fallback": tuple(sorted((try_a, try_b)))
                        != tuple(sorted(primary_pair)),
                    }
                )
                applied_ok = True
                break
            last_reason = str(outcome.get("reason") or "merge_failed")
            if last_reason not in {"crosses_barrier", "exceeds_hard_max"}:
                break

        if not applied_ok:
            report.skipped.append(
                {
                    "id": sid,
                    "op": op,
                    "territory_ids": list(last_pair),
                    "reason": last_reason,
                }
            )

    out_features = stable_sort(
        list(active.values()),
        key=lambda f: str((f.get("properties") or {}).get("territory_id") or ""),
    )

    # Corner budget: shared-edge vertex deletion + merge fallback for
    # ordinary. Legendary polygons stay frozen.
    from lib.corner_budget import (
        CornerBudgetError,
        apply_corner_budget,
        corner_budget_report_to_dict,
    )

    try:
        corner_result = apply_corner_budget(
            ctx, out_features, separators=separators
        )
    except CornerBudgetError as exc:
        raise BeautifyApplyError(str(exc)) from exc
    out_features = corner_result.features
    report.soft_flags.append(
        {
            "corner_budget": corner_budget_report_to_dict(corner_result.report),
        }
    )

    report.output_count = len(out_features)

    parcel_features = list(parcel_by_id.values()) if parcel_by_id else None

    validation = validate_lib.validate_gameplay_features(
        ctx, out_features, parcel_features=parcel_features, strict_shape=True
    )
    if validation.get("status") != "pass" or not (validation.get("hard") or {}).get(
        "passed", False
    ):
        raise BeautifyApplyError(
            "Stage 11: beautified gameplay failed hard validation; refusing write"
        )

    return BeautifyApplyResult(features=out_features, report=report, validation=validation)


def apply_report_to_dict(report: ApplyReport) -> dict[str, Any]:
    return {
        "input_count": report.input_count,
        "output_count": report.output_count,
        "applied_count": len(report.applied),
        "skipped_count": len(report.skipped),
        "soft_flag_count": len(report.soft_flags),
        "applied": report.applied,
        "skipped": report.skipped,
        "soft_flags": report.soft_flags,
        "candidates_hash": report.candidates_hash,
        "suggestions_hash": report.suggestions_hash,
        "area_rules": {
            "target_max_m2": report.target_max_m2,
            "target_max_acres": round(report.target_max_m2 / 4046.8564224, 3),
            "hard_max_m2": report.hard_max_m2,
            "hard_max_acres": round(report.hard_max_m2 / 4046.8564224, 3),
        },
    }


def _try_merge_pair(
    ctx: PipelineContext,
    active: dict[str, dict[str, Any]],
    a_id: str,
    b_id: str,
    *,
    gp: GameplayThresholds,
    bt: BeautifyThresholds,
    barrier_geom: BaseGeometry | None,
    max_area_loss_m2: float,
    crs_work: str,
    crs_store: str,
    op: str,
) -> dict[str, Any]:
    del bt  # reserved for future op-specific gates
    fa = active[a_id]
    fb = active[b_id]
    pa = fa["properties"]
    pb = fb["properties"]

    if pa.get("protected") is True or pb.get("protected") is True:
        return {"ok": False, "reason": "protected_merge_refused"}

    try:
        ga = _as_polygonal(to_work(shape(fa["geometry"]), crs_work))
        gb = _as_polygonal(to_work(shape(fb["geometry"]), crs_work))
    except Exception as exc:
        return {"ok": False, "reason": f"geometry_unreadable:{exc}"}
    if ga is None or gb is None or ga.is_empty or gb.is_empty:
        return {"ok": False, "reason": "empty_geometry"}

    shared = _shared_border_length(ga, gb)
    if shared < gp.min_shared_border_m:
        return {"ok": False, "reason": "not_adjacent"}

    if _shared_border_mostly_barrier(ga, gb, barrier_geom):
        return {"ok": False, "reason": "crosses_barrier"}

    merge = safe_merge_geometry(ga, gb, max_area_loss_m2=max_area_loss_m2)
    if merge.geometry is None:
        return {"ok": False, "reason": merge.rejected_reason or "merge_rejected"}

    merged_area = float(merge.geometry.area)
    if merged_area > gp.hard_max_m2:
        return {"ok": False, "reason": "exceeds_hard_max"}

    # Prefer keeping identity of the larger polygon.
    if float(ga.area) >= float(gb.area):
        keep_id, drop_id = a_id, b_id
        keep_props, drop_props = pa, pb
    else:
        keep_id, drop_id = b_id, a_id
        keep_props, drop_props = pb, pa

    members = _merged_members(keep_props, drop_props)
    name = keep_props.get("name") or drop_props.get("name")
    slug_base = str(keep_props.get("slug") or slugify(str(name or keep_id)))
    used = {
        str((f.get("properties") or {}).get("slug") or "")
        for tid, f in active.items()
        if tid not in {a_id, b_id}
    }
    slug = _unique_slug(slug_base, used)
    new_tid = str(gameplay_territory_id(ctx.region.city, ctx.region.area, slug))

    store = to_store(merge.geometry, crs_work, crs_store)
    polygonal = _as_polygonal(store)
    if polygonal is None or polygonal.is_empty:
        return {"ok": False, "reason": "empty_store_geometry"}

    new_props = {
        "territory_id": new_tid,
        "slug": slug,
        "name": name,
        "kind": keep_props.get("kind") or "block",
        "protected": False,
        "area_m2": round(merged_area, 3),
        "member_territory_ids": members,
        "member_count": len(members),
        "layer": "gameplay",
        "name_source": keep_props.get("name_source") or "beautify_merge",
        "beautify_op": op,
        "beautify_from": sorted([keep_id, drop_id]),
    }
    if keep_props.get("place_key"):
        new_props["place_key"] = keep_props["place_key"]
    elif drop_props.get("place_key"):
        new_props["place_key"] = drop_props["place_key"]

    del active[a_id]
    del active[b_id]
    active[new_tid] = {
        "type": "Feature",
        "geometry": mapping(polygonal),
        "properties": new_props,
    }
    return {"ok": True, "result_id": new_tid}


def _try_transfer_best_parcel(
    ctx: PipelineContext,
    active: dict[str, dict[str, Any]],
    donor_id: str,
    receiver_id: str,
    *,
    parcel_by_id: dict[str, dict[str, Any]],
    gp: GameplayThresholds,
    bt: BeautifyThresholds,
    barrier_geom: BaseGeometry | None,
    max_area_loss_m2: float,
    crs_work: str,
    crs_store: str,
) -> dict[str, Any]:
    """Move one Stage 09 member parcel from donor to receiver if shape improves."""
    if donor_id not in active or receiver_id not in active:
        return {"ok": False, "reason": "territory_missing"}
    donor = active[donor_id]
    receiver = active[receiver_id]
    dprops = donor["properties"]
    rprops = receiver["properties"]
    if dprops.get("protected") is True or rprops.get("protected") is True:
        return {"ok": False, "reason": "frozen_territory"}

    members = [str(x) for x in (dprops.get("member_territory_ids") or [])]
    if len(members) < 2:
        return {"ok": False, "reason": "donor_has_no_transferable_parcel"}

    # Prefer not transferring the sole atomic landmark seed parcel when others exist.
    reserved_seed_ids = {
        str((parcel_by_id[mid].get("properties") or {}).get("territory_id") or mid)
        for mid in members
        if mid in parcel_by_id
        and (parcel_by_id[mid].get("properties") or {}).get("atomic") is True
    }

    try:
        donor_geom = _as_polygonal(to_work(shape(donor["geometry"]), crs_work))
        receiver_geom = _as_polygonal(to_work(shape(receiver["geometry"]), crs_work))
    except Exception as exc:
        return {"ok": False, "reason": f"geometry_unreadable:{exc}"}
    if donor_geom is None or receiver_geom is None:
        return {"ok": False, "reason": "empty_geometry"}

    aspect_before = float(shape_quality(donor_geom)["aspect_ratio"])
    best: dict[str, Any] | None = None

    for parcel_id in sorted(members):
        if parcel_id in reserved_seed_ids:
            continue
        parcel = parcel_by_id.get(parcel_id)
        if parcel is None or not parcel.get("geometry"):
            continue
        try:
            parcel_geom = _as_polygonal(to_work(shape(parcel["geometry"]), crs_work))
        except Exception:
            continue
        if parcel_geom is None or parcel_geom.is_empty:
            continue
        # Boundary parcel: must touch the receiver.
        shared = _shared_border_length(parcel_geom, receiver_geom)
        if shared < gp.min_shared_border_m:
            continue
        if _shared_border_mostly_barrier(parcel_geom, receiver_geom, barrier_geom):
            continue

        remainder = _as_polygonal(donor_geom.difference(parcel_geom.buffer(0)))
        if remainder is None or remainder.is_empty:
            continue
        if not is_valid(remainder):
            continue
        # Donor must remain a single connected piece.
        if getattr(remainder, "geom_type", "") == "MultiPolygon":
            if len(list(remainder.geoms)) != 1:
                continue
            remainder = remainder.geoms[0]
        if float(remainder.area) < float(ctx.thresholds.standalone_min_area_m2) * 0.05:
            # Avoid leaving a tiny scrap donor; use soft scrap threshold instead.
            if float(remainder.area) < float(ctx.thresholds.scrap_m2):
                continue

        grown = safe_merge_geometry(
            receiver_geom, parcel_geom, max_area_loss_m2=max_area_loss_m2
        )
        if grown.geometry is None:
            continue
        if float(grown.geometry.area) > gp.hard_max_m2 + 1e-6:
            continue

        donor_after = shape_quality(remainder)
        aspect_after = float(donor_after["aspect_ratio"])
        compact_before = float(shape_quality(donor_geom)["compactness"])
        compact_after = float(donor_after["compactness"])
        improved_aspect = (
            aspect_after + 1e-9 < aspect_before - bt.min_aspect_improvement
            or aspect_after <= bt.max_aspect_ratio + 1e-9 < aspect_before
        )
        improved_compact = compact_after >= compact_before + bt.min_transfer_compactness_gain
        if not (improved_aspect or improved_compact):
            continue

        score = (
            -aspect_after,
            compact_after,
            shared,
            parcel_id,
        )
        candidate = {
            "score": score,
            "parcel_id": parcel_id,
            "remainder": remainder,
            "grown": grown.geometry,
            "aspect_before": aspect_before,
            "aspect_after": aspect_after,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate

    if best is None:
        return {"ok": False, "reason": "no_improving_transfer"}

    parcel_id = str(best["parcel_id"])
    donor_members = sorted(m for m in members if m != parcel_id)
    receiver_members = sorted(
        set([str(x) for x in (rprops.get("member_territory_ids") or [])] + [parcel_id])
    )

    donor_store = _as_polygonal(to_store(best["remainder"], crs_work, crs_store))
    receiver_store = _as_polygonal(to_store(best["grown"], crs_work, crs_store))
    if donor_store is None or receiver_store is None:
        return {"ok": False, "reason": "empty_store_geometry"}

    active[donor_id] = {
        "type": "Feature",
        "geometry": mapping(donor_store),
        "properties": {
            **dprops,
            "area_m2": round(float(best["remainder"].area), 3),
            "member_territory_ids": donor_members,
            "member_count": len(donor_members),
            "beautify_op": "transfer_member_parcel",
            "beautify_transferred_parcel": parcel_id,
        },
    }
    active[receiver_id] = {
        "type": "Feature",
        "geometry": mapping(receiver_store),
        "properties": {
            **rprops,
            "area_m2": round(float(best["grown"].area), 3),
            "member_territory_ids": receiver_members,
            "member_count": len(receiver_members),
            "beautify_op": "transfer_member_parcel",
            "beautify_received_parcel": parcel_id,
        },
    }
    return {
        "ok": True,
        "parcel_id": parcel_id,
        "aspect_before": best["aspect_before"],
        "aspect_after": best["aspect_after"],
    }


def _shared_border_mostly_barrier(
    a: BaseGeometry,
    b: BaseGeometry,
    barrier_geom: BaseGeometry | None,
) -> bool:
    """True when the contact edge substantially coincides with a hard barrier."""
    if barrier_geom is None or barrier_geom.is_empty:
        return False
    try:
        shared = a.boundary.intersection(b.buffer(_BORDER_EPS_M))
        if shared is None or shared.is_empty:
            return False
        shared_len = float(shared.length)
        if shared_len <= 0:
            return False
        on_barrier = shared.intersection(barrier_geom)
        if on_barrier is None or on_barrier.is_empty:
            return False
        return float(on_barrier.length) / shared_len >= _BARRIER_SHARE_REFUSE
    except Exception:
        return False


def _merged_members(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    members: list[str] = []
    for props in (a, b):
        raw = props.get("member_territory_ids")
        if isinstance(raw, list) and raw:
            members.extend(str(x) for x in raw)
        else:
            tid = props.get("territory_id")
            if tid:
                members.append(str(tid))
    return sorted(set(members))


def _unique_slug(slug: str, used: set[str]) -> str:
    if slug not in used:
        return slug
    for i in range(2, 10_000):
        candidate = f"{slug}-{i}"
        if candidate not in used:
            return candidate
    raise BeautifyApplyError(f"could not uniquify slug {slug!r}")
