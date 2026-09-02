"""Heuristic beautification critic for Stage 11.

Emits a restricted suggestion toolbox. Never edits geometry; GIS apply does that.
"""

from __future__ import annotations

from typing import Any, Protocol

from lib.config import BeautifyThresholds, GameplayThresholds
from lib.determinism import stable_sort

ALLOWED_OPS = frozenset(
    {
        "merge",
        "reject_merge",
        "absorb_peninsula",
        "keep_standalone",
        "force_merge_landmark",
        "transfer_member_parcel",
    }
)

_LANDMARK_KINDS = frozenset({"park", "landmark", "garden", "university", "college", "lake"})
_ACTIONABLE_OPS = frozenset(
    {"merge", "absorb_peninsula", "transfer_member_parcel", "force_merge_landmark"}
)


class BeautifyCritic(Protocol):
    def suggest(
        self,
        metrics: list[dict[str, Any]],
        *,
        gp: GameplayThresholds,
        bt: BeautifyThresholds,
    ) -> list[dict[str, Any]]: ...


class LlmCritic:
    """Deferred LLM backend — same suggestion schema as HeuristicCritic."""

    def suggest(
        self,
        metrics: list[dict[str, Any]],
        *,
        gp: GameplayThresholds,
        bt: BeautifyThresholds,
    ) -> list[dict[str, Any]]:
        del metrics, gp, bt
        raise NotImplementedError(
            "beautify.critic=llm is not implemented in v1; use critic: heuristic"
        )


class HeuristicCritic:
    """Deterministic design rules → merge / peninsula / soft-flag suggestions."""

    def suggest(
        self,
        metrics: list[dict[str, Any]],
        *,
        gp: GameplayThresholds,
        bt: BeautifyThresholds,
    ) -> list[dict[str, Any]]:
        by_id = {str(m["territory_id"]): m for m in metrics}
        suggestions: list[dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()

        for m in metrics:
            tid = str(m["territory_id"])
            if m.get("protected") is True:
                # Soft keep flag only; never force-merge protected botanical / prizes.
                if m.get("kind") in _LANDMARK_KINDS:
                    suggestions.append(
                        _suggestion(
                            op="keep_standalone",
                            territory_ids=[tid],
                            reason="protected landmark stays a prize territory",
                            confidence=1.0,
                            metrics_refs=["protected", "kind"],
                        )
                    )
                continue

            kind = str(m.get("kind") or "")
            area = float(m.get("area_m2") or 0.0)
            compactness = float(m.get("compactness") or 0.0)
            complexity = float(m.get("boundary_complexity") or 0.0)
            convexity = float(m.get("convexity") or 1.0)
            aspect = float(m.get("aspect_ratio") or 0.0)
            total_border = sum(
                float(n.get("shared_border_m") or 0.0) for n in (m.get("neighbours") or [])
            )

            # 0. Below ordinary 250-acre floor — highest priority auto-merge.
            if area + 1e-6 < gp.soft_min_m2 and m.get("neighbours"):
                nbr = _longest_neighbour(m, by_id, skip_protected=True)
                if nbr is not None and _merge_fits_hard_max(tid, nbr, by_id, gp.hard_max_m2):
                    pair = _pair_key(tid, nbr)
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        suggestions.append(
                            _suggestion(
                                op="merge",
                                territory_ids=[tid, nbr],
                                reason=(
                                    f"ordinary territory below 250-acre floor "
                                    f"({area:.0f} m²); merge into neighbour"
                                ),
                                confidence=0.99,
                                metrics_refs=["area_m2", "neighbours"],
                            )
                        )

            # 1. Long strips — prefer area-safe merge, else parcel transfer.
            if aspect > bt.max_aspect_ratio + 1e-9 and m.get("neighbours"):
                nbr = _longest_neighbour(m, by_id, skip_protected=True)
                if nbr is not None and _merge_fits_hard_max(tid, nbr, by_id, gp.hard_max_m2):
                    pair = _pair_key(tid, nbr)
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        suggestions.append(
                            _suggestion(
                                op="merge",
                                territory_ids=[tid, nbr],
                                reason=(
                                    f"strip aspect {aspect:.2f} > "
                                    f"{bt.max_aspect_ratio:.1f}; merge into "
                                    "longest non-protected neighbour"
                                ),
                                confidence=0.98,
                                metrics_refs=["aspect_ratio", "neighbours"],
                            )
                        )
                elif nbr is not None:
                    members = [str(x) for x in (m.get("member_territory_ids") or [])]
                    if len(members) >= 2:
                        parcel_id = sorted(members)[0]
                        sug = _suggestion(
                            op="transfer_member_parcel",
                            territory_ids=[tid, nbr],
                            reason=(
                                f"strip aspect {aspect:.2f}; transfer boundary "
                                "parcel toward neighbour to rebalance proportions"
                            ),
                            confidence=0.95,
                            metrics_refs=["aspect_ratio", "member_territory_ids"],
                        )
                        sug["donor_territory_id"] = tid
                        sug["receiver_territory_id"] = nbr
                        sug["parcel_id"] = parcel_id
                        suggestions.append(sug)

            # 2. Weak campus leftovers still below a fraction of the floor.
            tiny_floor = gp.soft_min_m2 * 0.4
            is_weak_prize = kind in _LANDMARK_KINDS and area < tiny_floor
            if area < tiny_floor or is_weak_prize:
                nbr = _longest_neighbour(m, by_id, skip_protected=True)
                if nbr is not None and _merge_fits_hard_max(tid, nbr, by_id, gp.hard_max_m2):
                    pair = _pair_key(tid, nbr)
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        conf = 0.97 if area < tiny_floor * 0.5 else 0.90
                        suggestions.append(
                            _suggestion(
                                op="merge",
                                territory_ids=[tid, nbr],
                                reason=(
                                    f"undersized territory ({area:.0f} m²) "
                                    f"merges into longest-border neighbour"
                                ),
                                confidence=conf,
                                metrics_refs=["area_m2", "neighbours"],
                            )
                        )

            # 3. Peninsula / low compactness — absorb into longest *non-protected*
            # neighbour. Protected borders (Lalbagh, NIMHANS) must not block cleanup
            # when they happen to be the longest contact.
            if compactness < bt.min_compactness and m.get("neighbours"):
                candidates = [
                    candidate
                    for candidate in _non_protected_neighbours_ranked(m, by_id)
                    if _merge_fits_hard_max(
                        tid, candidate[0], by_id, gp.hard_max_m2
                    )
                ]
                if candidates and total_border > 0:
                    primary_id, shared_m = candidates[0]
                    share = shared_m / total_border
                    qualifies = (
                        share >= bt.peninsula_border_share
                        or shared_m >= bt.min_peninsula_shared_border_m
                    )
                    if not qualifies and convexity < 0.55 and shared_m >= 500:
                        qualifies = True
                    if qualifies:
                        pair = _pair_key(tid, primary_id)
                        if pair not in seen_pairs:
                            seen_pairs.add(pair)
                            # Mark secondary fabric targets so GIS apply can fall
                            # back when the primary pair crosses a motorway barrier.
                            alternates = [nid for nid, _ in candidates[1:4]]
                            for alt in alternates:
                                seen_pairs.add(_pair_key(tid, alt))
                            deficit = bt.min_compactness - compactness
                            conf = 0.88 + min(0.09, deficit * 0.4)
                            sug = _suggestion(
                                op="absorb_peninsula",
                                territory_ids=[tid, primary_id],
                                reason=(
                                    f"low compactness ({compactness:.3f}) / "
                                    f"convexity ({convexity:.3f}); absorb into "
                                    f"longest non-protected neighbour "
                                    f"({share:.0%} / {shared_m:.0f} m)"
                                ),
                                confidence=round(min(conf, 0.97), 3),
                                metrics_refs=[
                                    "compactness",
                                    "convexity",
                                    "neighbours",
                                ],
                            )
                            sug["absorb_from"] = tid
                            if alternates:
                                sug["alternate_territory_ids"] = alternates
                            suggestions.append(sug)

            # 4. Jagged / zig-zag borders — merge without requiring name match.
            # Name coherence only boosts confidence; jagged fabric alone is enough.
            if complexity >= bt.jagged_complexity and m.get("neighbours"):
                target = _pick_jagged_merge_target(m, by_id)
                if target is not None:
                    nbr_id, via = target
                    pair = _pair_key(tid, nbr_id)
                    if (
                        _merge_fits_hard_max(
                            tid, nbr_id, by_id, gp.hard_max_m2
                        )
                        and pair not in seen_pairs
                    ):
                        seen_pairs.add(pair)
                        # Floor at auto-apply threshold so jagged borders actually clean.
                        base = 0.87 if via == "name" else 0.86
                        conf = base + min(0.05, (complexity - bt.jagged_complexity) * 0.1)
                        suggestions.append(
                            _suggestion(
                                op="merge",
                                territory_ids=[tid, nbr_id],
                                reason=(
                                    f"jagged boundary (complexity {complexity:.2f}); "
                                    f"merge via {via}"
                                ),
                                confidence=round(min(conf, 0.92), 3),
                                metrics_refs=["boundary_complexity", "neighbours"],
                            )
                        )

            # 5. Oversize glue — soft flag only (no auto-split in v1)
            if area > gp.soft_max_m2 and not _name_coherent_self(m):
                suggestions.append(
                    _suggestion(
                        op="reject_merge",
                        territory_ids=[tid],
                        reason=(
                            f"oversized multi-place blob ({area:.0f} m²) — "
                            "consider split at human review"
                        ),
                        confidence=0.7,
                        metrics_refs=["area_m2", "name", "place_key"],
                    )
                )

        ranked = stable_sort(
            suggestions,
            key=lambda s: (
                # Prefer GIS-actionable ops over soft keep/reject flags so the
                # suggestion cap cannot drop strip cleanup.
                0 if str(s.get("op")) in _ACTIONABLE_OPS else 1,
                -float(s["confidence"]),
                str(s["op"]),
                tuple(s["territory_ids"]),
            ),
        )
        capped = ranked[: bt.max_suggestions]
        for i, sug in enumerate(capped, start=1):
            sug["id"] = f"sug-{i:04d}"
        return capped


def get_critic(name: str) -> BeautifyCritic:
    if name == "heuristic":
        return HeuristicCritic()
    if name == "llm":
        return LlmCritic()
    raise ValueError(f"unknown beautify critic: {name!r}")


def _suggestion(
    *,
    op: str,
    territory_ids: list[str],
    reason: str,
    confidence: float,
    metrics_refs: list[str],
) -> dict[str, Any]:
    if op not in ALLOWED_OPS:
        raise ValueError(f"disallowed beautify op: {op}")
    ids = [str(t) for t in territory_ids]
    if op in {"merge", "absorb_peninsula", "force_merge_landmark", "transfer_member_parcel"}:
        ids = sorted(ids)
    return {
        "id": "",  # filled after ranking
        "op": op,
        "territory_ids": ids,
        "reason": reason,
        "confidence": float(confidence),
        "metrics_refs": list(metrics_refs),
    }


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))  # type: ignore[return-value]


def _merge_fits_hard_max(
    a: str,
    b: str,
    by_id: dict[str, dict[str, Any]],
    hard_max_m2: float,
) -> bool:
    ma = by_id.get(a)
    mb = by_id.get(b)
    if ma is None or mb is None:
        return False
    area = float(ma.get("area_m2") or 0.0) + float(mb.get("area_m2") or 0.0)
    return area <= hard_max_m2 + 1e-6


def _longest_neighbour(
    m: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    *,
    skip_protected: bool,
) -> str | None:
    nid, _ = _longest_neighbour_with_length(m, by_id, skip_protected=skip_protected)
    return nid


def _longest_neighbour_with_length(
    m: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    *,
    skip_protected: bool,
) -> tuple[str | None, float]:
    ranked = _non_protected_neighbours_ranked(m, by_id) if skip_protected else []
    if skip_protected:
        if not ranked:
            return None, 0.0
        return ranked[0]
    for nbr in m.get("neighbours") or []:
        nid = str(nbr["territory_id"])
        if nid in by_id:
            return nid, float(nbr.get("shared_border_m") or 0.0)
    return None, 0.0


def _non_protected_neighbours_ranked(
    m: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for nbr in m.get("neighbours") or []:
        nid = str(nbr["territory_id"])
        other = by_id.get(nid)
        if other is None or other.get("protected") is True:
            continue
        out.append((nid, float(nbr.get("shared_border_m") or 0.0)))
    return out


def _pick_jagged_merge_target(
    m: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> tuple[str, str] | None:
    """Prefer name-coherent fabric neighbour; else longest non-protected."""
    for nbr_row in (m.get("neighbours") or [])[:4]:
        nbr_id = str(nbr_row["territory_id"])
        other = by_id.get(nbr_id)
        if other is None or other.get("protected") is True:
            continue
        if _name_coherent(m, other):
            return nbr_id, "name"
    nbr = _longest_neighbour(m, by_id, skip_protected=True)
    if nbr is None:
        return None
    return nbr, "longest_border"


def _name_stem(name: Any) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    tokens = [t for t in name.lower().replace("-", " ").split() if t]
    if not tokens:
        return None
    return "-".join(tokens[:3])


def _name_coherent(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("place_key") and a.get("place_key") == b.get("place_key"):
        return True
    sa = _name_stem(a.get("name"))
    sb = _name_stem(b.get("name"))
    if sa and sb and (sa == sb or sa.split("-")[0] == sb.split("-")[0]):
        return True
    return False


def _name_coherent_self(m: dict[str, Any]) -> bool:
    """True if territory looks like a single coherent named place."""
    if m.get("place_key"):
        return True
    name = m.get("name")
    if isinstance(name, str) and name.strip() and " / " not in name and " & " not in name:
        return True
    return False
