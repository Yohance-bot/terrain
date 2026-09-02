"""Fail-closed validation for stage 08.

Gatekeeper only: report topology and identity defects; never repair geometry.
Hard failures block `candidates.geojson`. Soft findings are listed for humans.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shapely import STRtree, is_valid
from shapely.geometry import box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from lib import artifacts
from lib.config import load_validation_exceptions
from lib.contracts import PipelineContext
from lib.corner_budget import (
    budget_exterior_corner_count,
    exterior_corner_count,
    territory_class_of,
)
from lib.crs import geodesic_area_m2, to_store, to_work
from lib.determinism import content_hash, stable_sort
from lib.io import artifact_hash_input, read_geojson, read_json, write_json
from lib.shape import shape_quality

# Relative + absolute bound for projected vs geodesic area disagreement.
_CRS_ABS_M2 = 1000.0
_CRS_REL = 0.01
_M2_PER_ACRE = 4046.8564224

_M1_KINDS = frozenset({"park", "lake", "landmark", "block"})

CHAIN_FINGERPRINT_NAME = "chain_fingerprint.json"

_FINGERPRINT_SPECS = (
    ("raw_manifest", artifacts.RAW_MANIFEST),
    ("separators", artifacts.SEPARATORS),
    ("landmarks", artifacts.LANDMARKS),
    ("boundary_graph", artifacts.BOUNDARY_GRAPH),
    ("faces", artifacts.FACES),
    ("normalized", artifacts.NORMALIZED),
    ("named", artifacts.NAMED),
)


class ValidationFailedError(RuntimeError):
    """Hard validation failed; report is on disk, candidates were not written."""


@dataclass
class ValidationResult:
    passed: bool
    report: dict[str, Any]
    candidates: list[dict[str, Any]] | None
    fingerprint_path: Path
    failures: list[dict[str, Any]] = field(default_factory=list)


def chain_fingerprint_path(ctx: PipelineContext) -> Path:
    return ctx.staging_dir / CHAIN_FINGERPRINT_NAME


def write_chain_fingerprint(ctx: PipelineContext) -> Path:
    """Snapshot content hashes of stages 01–07 artifacts (no timestamps)."""
    artifacts_block: dict[str, Any] = {}
    for key, spec in _FINGERPRINT_SPECS:
        path = spec.path(ctx)
        entry: dict[str, Any] = {
            "path": str(path.relative_to(ctx.repo_root)) if path.exists() else None,
            "present": path.exists(),
            "sha256": None,
        }
        if path.exists():
            try:
                data = read_json(path)
                if isinstance(data, dict) and data.get("type") == "FeatureCollection":
                    digest = content_hash(artifact_hash_input(data))
                else:
                    digest = content_hash(data)
                entry["sha256"] = digest
            except Exception as exc:  # noqa: BLE001 — fingerprint must not crash validation
                entry["error"] = str(exc)
        artifacts_block[key] = entry

    payload = {
        "pipeline_stages": "01-07",
        "region": ctx.region.name,
        "city": ctx.region.city,
        "area": ctx.region.area,
        "artifacts": artifacts_block,
    }
    path = chain_fingerprint_path(ctx)
    write_json(path, payload)
    return path


def validate_named(ctx: PipelineContext) -> ValidationResult:
    """Run hard + soft checks. Does not write candidates/report — stage does."""
    fingerprint = write_chain_fingerprint(ctx)
    named = read_geojson(artifacts.NAMED.path(ctx))
    all_features = list(named.get("features") or [])
    thresholds = ctx.thresholds.validation
    crs_work = ctx.region.crs_work

    # --- known-exceptions partition (opt-in, off by default) ----------------
    # When disabled, `known_exceptions` is empty, `excluded_features` is
    # always empty and `features` is exactly `all_features` -- every line
    # below this behaves byte-for-byte as it did before this mechanism
    # existed. When enabled, a fixed, reviewed slug list lets a specific,
    # already-investigated "names" failure be excluded from candidates
    # instead of hard-failing the whole run. Exclusion never rewrites a name;
    # it removes the feature from candidates.geojson entirely and records it
    # separately in the report so nothing about the exclusion is silent.
    known_exceptions: dict[str, str] = (
        load_validation_exceptions(ctx.region.name) if ctx.allow_validation_exceptions else {}
    )
    excluded_features: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    for feature in all_features:
        props = feature.get("properties") or {}
        slug = props.get("slug")
        name = props.get("name")
        is_missing_name = not isinstance(name, str) or not name.strip()
        if isinstance(slug, str) and slug in known_exceptions and is_missing_name:
            excluded_features.append(feature)
        else:
            features.append(feature)

    failures: list[dict[str, Any]] = []
    work_geoms: list[BaseGeometry] = []
    props_list: list[dict[str, Any]] = []

    # --- parse + validity ---------------------------------------------------
    for i, feature in enumerate(features):
        props = dict(feature.get("properties") or {})
        geom_json = feature.get("geometry")
        if not geom_json:
            failures.append(
                _fail("valid_geometry", f"feature[{i}] missing geometry", None, None)
            )
            continue
        try:
            geom = shape(geom_json)
        except Exception as exc:
            failures.append(
                _fail("valid_geometry", f"feature[{i}] unreadable: {exc}", None, None)
            )
            continue
        if geom is None or geom.is_empty:
            failures.append(
                _fail(
                    "valid_geometry",
                    f"feature[{i}] slug={props.get('slug')!r} empty geometry",
                    None,
                    None,
                )
            )
            continue
        if not is_valid(geom):
            failures.append(
                _fail(
                    "valid_geometry",
                    f"feature[{i}] slug={props.get('slug')!r} invalid geometry",
                    False,
                    True,
                )
            )
            continue
        work = to_work(geom, crs_work)
        if work.is_empty:
            failures.append(
                _fail(
                    "valid_geometry",
                    f"feature[{i}] slug={props.get('slug')!r} empty after to_work",
                    None,
                    None,
                )
            )
            continue
        work_geoms.append(work)
        props_list.append(props)

    # Identity / names (use all features' props, including invalid ones)
    all_props = [dict(f.get("properties") or {}) for f in features]
    failures.extend(_check_unique(all_props, "territory_id"))
    failures.extend(_check_unique(all_props, "slug"))
    if not thresholds.allow_unnamed_publish:
        for props in all_props:
            name = props.get("name")
            if not isinstance(name, str) or not name.strip():
                failures.append(
                    _fail(
                        "names",
                        f"slug={props.get('slug')!r} missing name",
                        name,
                        "non-empty string",
                    )
                )

    aoi_full = to_work(box(*ctx.region.bbox.as_xy_bounds()), crs_work)
    # Known, accepted exclusions are treated as intentional holes in the AOI
    # for gap/coverage purposes, not as unexplained missing area: a slug we
    # deliberately dropped from candidates should not also make the run fail
    # closed on "gap" for the exact same footprint. Overlap is unaffected
    # because it is computed from `work_geoms`, which never includes excluded
    # features. When there are no exclusions this is `aoi_full` unchanged, so
    # disabled-flag behaviour is untouched.
    excluded_work_geoms: list[BaseGeometry] = []
    for feature in excluded_features:
        geom_json = feature.get("geometry")
        if not geom_json:
            continue
        try:
            excluded_geom = to_work(shape(geom_json), crs_work)
        except Exception:  # noqa: BLE001 — a bad excluded geometry must not crash validation
            continue
        if excluded_geom is not None and not excluded_geom.is_empty:
            excluded_work_geoms.append(excluded_geom)
    aoi = (
        aoi_full.difference(unary_union(excluded_work_geoms))
        if excluded_work_geoms
        else aoi_full
    )
    aoi_area = float(aoi.area)

    overlap_m2 = 0.0
    gap_m2 = aoi_area
    coverage_ratio = 0.0
    projected_area_m2 = 0.0
    geodesic_total = 0.0

    if work_geoms:
        overlap_m2 = _total_overlap_m2(work_geoms)
        if overlap_m2 > thresholds.max_overlap_m2:
            failures.append(
                _fail(
                    "overlap",
                    "total pairwise overlap exceeds threshold",
                    round(overlap_m2, 6),
                    thresholds.max_overlap_m2,
                )
            )

        union = unary_union(work_geoms)
        covered = union.intersection(aoi)
        covered_area = float(covered.area) if covered is not None and not covered.is_empty else 0.0
        gap_m2 = max(0.0, aoi_area - covered_area)
        coverage_ratio = covered_area / aoi_area if aoi_area > 0 else 0.0

        if gap_m2 > thresholds.max_gap_m2:
            failures.append(
                _fail(
                    "gap",
                    "AOI gap exceeds threshold",
                    round(gap_m2, 6),
                    thresholds.max_gap_m2,
                )
            )
        if coverage_ratio < thresholds.min_coverage_ratio:
            failures.append(
                _fail(
                    "coverage",
                    "coverage ratio below threshold",
                    round(coverage_ratio, 9),
                    thresholds.min_coverage_ratio,
                )
            )

        projected_area_m2 = sum(float(g.area) for g in work_geoms)
        union_store = to_store(union, crs_work, ctx.region.crs_store)
        geodesic_total = geodesic_area_m2(union_store)
        crs_limit = max(_CRS_ABS_M2, _CRS_REL * projected_area_m2)
        crs_delta = abs(projected_area_m2 - geodesic_total)
        if crs_delta > crs_limit:
            failures.append(
                _fail(
                    "crs_sanity",
                    "projected vs geodesic area disagree (possible degree measurement)",
                    round(crs_delta, 3),
                    round(crs_limit, 3),
                )
            )

    failures.extend(_check_protected_majors(ctx, props_list, work_geoms))

    soft = _soft_checks(ctx, props_list, work_geoms)
    passed = len(failures) == 0

    report = {
        "status": "pass" if passed else "fail",
        "stage": "validate",
        "hard": {"passed": passed, "failures": failures},
        "metrics": {
            "feature_count": len(features),
            "protected_count": sum(1 for p in props_list if p.get("protected")),
            "coverage_ratio": round(coverage_ratio, 9),
            "gap_m2": round(gap_m2, 6),
            "overlap_m2": round(overlap_m2, 6),
            "projected_area_m2": round(projected_area_m2, 3),
            "geodesic_area_m2": round(geodesic_total, 3),
            "aoi_area_m2": round(aoi_area, 3),
        },
        "soft": soft,
        "fingerprint_path": str(fingerprint.relative_to(ctx.repo_root)),
    }
    # Only present when the mechanism is actually on -- a disabled region's
    # report has exactly the same keys it always had.
    if ctx.allow_validation_exceptions:
        report["excluded_known_exceptions"] = _excluded_known_exceptions_block(
            excluded_features, known_exceptions, crs_work
        )

    candidates: list[dict[str, Any]] | None = None
    if passed:
        candidates = [
            {
                "type": "Feature",
                "geometry": f["geometry"],
                "properties": dict(f.get("properties") or {}),
            }
            for f in features
        ]
        candidates = stable_sort(candidates, key=_candidate_sort_key)

    return ValidationResult(
        passed=passed,
        report=report,
        candidates=candidates,
        fingerprint_path=fingerprint,
        failures=failures,
    )


def _excluded_known_exceptions_block(
    excluded_features: list[dict[str, Any]],
    known_exceptions: dict[str, str],
    crs_work: str,
) -> dict[str, Any]:
    """Full transparency record for what the exception mechanism removed.

    Deliberately separate from `hard.failures` and `soft.needs_review`: this
    is not "these are fine" and not "these need a human's attention on the
    next pass" -- it is "we know these are bad and intentionally excluded".
    """
    entries: list[dict[str, Any]] = []
    for feature in excluded_features:
        props = feature.get("properties") or {}
        slug = str(props.get("slug") or "")
        area_m2 = None
        geom_json = feature.get("geometry")
        if geom_json:
            try:
                area_m2 = round(float(to_work(shape(geom_json), crs_work).area), 3)
            except Exception:  # noqa: BLE001 — reporting must not crash on bad geometry
                area_m2 = None
        entries.append(
            {
                "slug": slug,
                "territory_id": props.get("territory_id"),
                "name_source": props.get("name_source"),
                "area_m2": area_m2,
                "reason": known_exceptions.get(slug),
            }
        )
    entries = stable_sort(entries, key=lambda e: str(e.get("slug") or ""))
    excluded_slugs = {e["slug"] for e in entries}
    unused = sorted(set(known_exceptions) - excluded_slugs)
    return {
        "count": len(entries),
        "features": entries,
        # Slugs in the exceptions file that were not actually excluded this
        # run (e.g. already fixed upstream, or removed from `named`) -- kept
        # visible so a stale exceptions list gets noticed, not just ignored.
        "unused_exceptions": unused,
    }


def _fail(check: str, detail: str, value: Any, threshold: Any) -> dict[str, Any]:
    return {
        "check": check,
        "detail": detail,
        "value": value,
        "threshold": threshold,
    }


def _matches_known_exception(props: dict[str, Any], known_exceptions: dict[str, str]) -> bool:
    """True when a feature's current identity still resolves to a reviewed exception.

    Stage 10 can rename or merge original parcel slugs after clustering, so the
    coverage/gap filter must match both the live feature identity and the
    source identity recorded on the oversized or atomic parcel before the merge.
    """
    if not known_exceptions:
        return False
    for key in (
        props.get("slug"),
        props.get("atomic_source_slug"),
        props.get("territory_id"),
        props.get("hard_max_exception_source_slug"),
    ):
        if isinstance(key, str) and key.strip() and key.strip() in known_exceptions:
            return True
    member_ids = props.get("member_territory_ids") or []
    if isinstance(member_ids, list):
        for value in member_ids:
            if isinstance(value, str) and value.strip() and value.strip() in known_exceptions:
                return True
    return False


def _check_unique(props_list: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    failures: list[dict[str, Any]] = []
    for props in props_list:
        raw = props.get(field)
        if raw is None or raw == "":
            failures.append(
                _fail(field, f"missing {field}", raw, "unique non-empty")
            )
            continue
        key = str(raw)
        seen[key] = seen.get(key, 0) + 1
    for key, count in sorted(seen.items()):
        if count > 1:
            failures.append(
                _fail(field, f"duplicate {field}={key!r}", count, 1)
            )
    return failures


def _total_overlap_m2(geoms: list[BaseGeometry]) -> float:
    if len(geoms) < 2:
        return 0.0
    tree = STRtree(geoms)
    total = 0.0
    seen_pairs: set[tuple[int, int]] = set()
    for i, geom in enumerate(geoms):
        for j in tree.query(geom):
            j = int(j)
            if j <= i:
                continue
            pair = (i, j)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            other = geoms[j]
            if not geom.intersects(other):
                continue
            inter = geom.intersection(other)
            if inter is None or inter.is_empty:
                continue
            # Ignore pure boundary touches (zero area).
            total += float(inter.area)
    return total


def _check_protected_majors(
    ctx: PipelineContext,
    named_props: list[dict[str, Any]],
    named_geoms: list[BaseGeometry],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    landmarks_path = artifacts.LANDMARKS.path(ctx)
    normalized_path = artifacts.NORMALIZED.path(ctx)
    if not landmarks_path.exists():
        failures.append(
            _fail(
                "protected_majors",
                "landmarks artifact missing; cannot verify protected set",
                None,
                None,
            )
        )
        return failures

    landmarks = read_geojson(landmarks_path)
    # Standalone freeze set only — atomic-but-mergeable landmarks may merge.
    majors = [
        f
        for f in landmarks.get("features") or []
        if (f.get("properties") or {}).get("protected") is True
    ]
    major_slugs = {
        str((f.get("properties") or {}).get("slug"))
        for f in majors
        if (f.get("properties") or {}).get("slug")
    }

    named_protected = [
        (p, g)
        for p, g in zip(named_props, named_geoms, strict=False)
        if p.get("protected") is True
    ]
    named_slugs = [str(p.get("slug")) for p, _ in named_protected if p.get("slug")]

    if len(named_protected) != len(majors):
        failures.append(
            _fail(
                "protected_majors",
                "protected count in named != standalone count in landmarks",
                len(named_protected),
                len(majors),
            )
        )

    from collections import Counter

    counts = Counter(named_slugs)
    for slug, n in sorted(counts.items()):
        if n != 1:
            failures.append(
                _fail(
                    "protected_majors",
                    f"protected slug {slug!r} appears {n} times",
                    n,
                    1,
                )
            )
    missing = sorted(major_slugs - set(named_slugs))
    for slug in missing:
        failures.append(
            _fail(
                "protected_majors",
                f"major landmark slug {slug!r} missing from named",
                None,
                slug,
            )
        )

    # Area vs Stage 06 protected faces (geometry must survive naming).
    if normalized_path.exists():
        normalized = read_geojson(normalized_path)
        norm_by_slug: dict[str, float] = {}
        for feature in normalized.get("features") or []:
            props = feature.get("properties") or {}
            if props.get("protected") is not True:
                continue
            slug = props.get("slug")
            if not slug:
                continue
            try:
                geom = shape(feature["geometry"])
                area = float(to_work(geom, ctx.region.crs_work).area)
            except Exception:
                area = float(props.get("area_m2") or 0.0)
            norm_by_slug[str(slug)] = area

        max_gap = float(ctx.thresholds.validation.max_gap_m2)
        for props, geom in named_protected:
            slug = str(props.get("slug") or "")
            if slug not in norm_by_slug:
                continue
            delta = abs(float(geom.area) - norm_by_slug[slug])
            if delta > max_gap:
                failures.append(
                    _fail(
                        "protected_majors",
                        f"protected {slug!r} area changed vs normalized",
                        round(delta, 6),
                        max_gap,
                    )
                )

    return failures


def _soft_checks(
    ctx: PipelineContext,
    props_list: list[dict[str, Any]],
    work_geoms: list[BaseGeometry],
) -> dict[str, Any]:
    soft_min = float(ctx.thresholds.fabric_soft_min_m2)
    soft_max = float(ctx.thresholds.fabric_soft_max_m2)
    review_max = float(ctx.thresholds.fabric_review_max_m2)

    below = in_band = above_soft = above_review = 0
    by_source: dict[str, int] = {}
    needs_review: list[dict[str, Any]] = []
    kind_warnings: list[str] = []

    for props, geom in zip(props_list, work_geoms, strict=False):
        src = str(props.get("name_source") or "?")
        by_source[src] = by_source.get(src, 0) + 1
        kind = props.get("kind")
        if kind not in _M1_KINDS:
            kind_warnings.append(str(props.get("slug")))

        if props.get("needs_review") is True:
            needs_review.append(
                {
                    "slug": props.get("slug"),
                    "name": props.get("name"),
                    "name_source": props.get("name_source"),
                    "area_m2": round(float(geom.area), 3),
                }
            )

        if props.get("protected") is True:
            continue
        area = float(geom.area)
        if area < soft_min:
            below += 1
        elif area <= soft_max:
            in_band += 1
        else:
            above_soft += 1
        if area > review_max:
            above_review += 1

    needs_review = stable_sort(
        needs_review, key=lambda r: (str(r.get("slug") or ""), float(r.get("area_m2") or 0))
    )

    return {
        "needs_review": needs_review,
        "needs_review_count": len(needs_review),
        "by_name_source": dict(sorted(by_source.items())),
        "size_bands": {
            "fabric_below_soft_min": below,
            "fabric_in_soft_band": in_band,
            "fabric_above_soft_max": above_soft,
            "fabric_above_review_max": above_review,
        },
        "unexpected_kinds": stable_sort(kind_warnings, key=lambda s: s),
    }


def _candidate_sort_key(feature: dict[str, Any]) -> tuple:
    props = feature.get("properties") or {}
    return (
        0 if props.get("protected") else 1,
        str(props.get("slug") or ""),
        str(props.get("territory_id") or ""),
    )


def validate_gameplay_features(
    ctx: PipelineContext,
    features: list[dict[str, Any]],
    *,
    parcel_features: list[dict[str, Any]] | None = None,
    strict_shape: bool = False,
) -> dict[str, Any]:
    """Hard + soft checks for Stage 10 gameplay candidates.

    Protected majors must match the parcel input 1:1 (slug + geometry hash).
    Topology uses the same gap/overlap/coverage thresholds as Stage 08.
    When ``strict_shape`` is True (Stage 11), aspect-ratio strips hard-fail.
    """
    thresholds = ctx.thresholds.validation
    gp = ctx.thresholds.gameplay
    crs_work = ctx.region.crs_work
    known_exceptions: dict[str, str] = (
        load_validation_exceptions(ctx.region.name) if ctx.allow_validation_exceptions else {}
    )
    failures: list[dict[str, Any]] = []
    work_geoms: list[BaseGeometry] = []
    props_list: list[dict[str, Any]] = []

    for i, feature in enumerate(features):
        props = dict(feature.get("properties") or {})
        geom_json = feature.get("geometry")
        if not geom_json:
            failures.append(_fail("valid_geometry", f"feature[{i}] missing geometry", None, None))
            continue
        try:
            geom = shape(geom_json)
        except Exception as exc:
            failures.append(_fail("valid_geometry", f"feature[{i}] unreadable: {exc}", None, None))
            continue
        if geom is None or geom.is_empty or not is_valid(geom):
            failures.append(
                _fail(
                    "valid_geometry",
                    f"feature[{i}] slug={props.get('slug')!r} invalid/empty",
                    None,
                    None,
                )
            )
            continue
        work = to_work(geom, crs_work)
        if work.is_empty:
            failures.append(
                _fail(
                    "valid_geometry",
                    f"feature[{i}] slug={props.get('slug')!r} empty after to_work",
                    None,
                    None,
                )
            )
            continue
        work_geoms.append(work)
        props_list.append(props)

    all_props = [dict(f.get("properties") or {}) for f in features]
    failures.extend(_check_unique(all_props, "territory_id"))
    failures.extend(_check_unique(all_props, "slug"))
    if not thresholds.allow_unnamed_publish:
        for props in all_props:
            name = props.get("name")
            if not isinstance(name, str) or not name.strip():
                failures.append(
                    _fail(
                        "names",
                        f"slug={props.get('slug')!r} missing name",
                        name,
                        "non-empty string",
                    )
                )

    if parcel_features is None and artifacts.PUBLISHED_TERRITORIES.path(ctx).exists():
        parcel_features = list(
            read_geojson(artifacts.PUBLISHED_TERRITORIES.path(ctx)).get("features") or []
        )

    # Stage 10 may rename/dedupe output slugs after merges. To keep known
    # hard-max exceptions auditable and effective without touching thresholds,
    # resolve exception source territory IDs from Stage 09 parcels as a stable
    # identity alongside slug matching.
    known_exception_ids: set[str] = set()
    known_exception_by_id: dict[str, tuple[str, str]] = {}
    known_exceptions_expanded = dict(known_exceptions)
    if parcel_features is not None and known_exceptions:
        for feature in parcel_features:
            props = dict(feature.get("properties") or {})
            source_slug = str(props.get("slug") or "")
            tid = props.get("territory_id")
            if source_slug in known_exceptions and tid:
                tid_s = str(tid)
                known_exception_ids.add(tid_s)
                known_exception_by_id[tid_s] = (source_slug, known_exceptions[source_slug])
                known_exceptions_expanded[tid_s] = known_exceptions[source_slug]

    aoi_full = to_work(box(*ctx.region.bbox.as_xy_bounds()), crs_work)
    excluded_work_geoms: list[BaseGeometry] = []
    if ctx.allow_validation_exceptions and known_exceptions and artifacts.NAMED.path(ctx).exists():
        named = read_geojson(artifacts.NAMED.path(ctx))
        for feature in named.get("features") or []:
            props = feature.get("properties") or {}
            slug = props.get("slug")
            name = props.get("name")
            is_missing_name = not isinstance(name, str) or not name.strip()
            if isinstance(slug, str) and slug in known_exceptions and is_missing_name:
                geom_json = feature.get("geometry")
                if geom_json:
                    try:
                        excluded_geom = to_work(shape(geom_json), crs_work)
                        if excluded_geom is not None and not excluded_geom.is_empty:
                            excluded_work_geoms.append(excluded_geom)
                    except Exception:
                        pass
    aoi = (
        aoi_full.difference(unary_union(excluded_work_geoms))
        if excluded_work_geoms
        else aoi_full
    )
    aoi_area = float(aoi.area)
    overlap_m2 = 0.0
    gap_m2 = aoi_area
    coverage_ratio = 0.0
    coverage_geoms = [
        (props, geom)
        for props, geom in zip(props_list, work_geoms, strict=False)
    ]

    if coverage_geoms:
        fit_geoms = [geom for _, geom in coverage_geoms]
        overlap_m2 = _total_overlap_m2(fit_geoms)
        if overlap_m2 > thresholds.max_overlap_m2:
            failures.append(
                _fail(
                    "overlap",
                    "total pairwise overlap exceeds threshold",
                    round(overlap_m2, 6),
                    thresholds.max_overlap_m2,
                )
            )
        union = unary_union(fit_geoms)
        covered = union.intersection(aoi)
        covered_area = float(covered.area) if covered is not None and not covered.is_empty else 0.0
        gap_m2 = max(0.0, aoi_area - covered_area)
        coverage_ratio = covered_area / aoi_area if aoi_area > 0 else 0.0
        if gap_m2 > thresholds.max_gap_m2:
            failures.append(
                _fail(
                    "gap",
                    "AOI gap exceeds threshold",
                    round(gap_m2, 6),
                    thresholds.max_gap_m2,
                )
            )
        if coverage_ratio < thresholds.min_coverage_ratio:
            failures.append(
                _fail(
                    "coverage",
                    "coverage ratio below threshold",
                    round(coverage_ratio, 9),
                    thresholds.min_coverage_ratio,
                )
            )


    if parcel_features is not None:
        failures.extend(
            _check_protected_vs_parcels(
                parcel_features,
                features,
                crs_work,
                standalone_min_m2=float(ctx.thresholds.standalone_min_area_m2),
            )
        )
        failures.extend(
            _check_atomic_landmark_integrity(
                parcel_features,
                features,
                crs_work,
                max_missing_m2=thresholds.max_gap_m2,
                standalone_min_m2=float(ctx.thresholds.standalone_min_area_m2),
                known_exception_keys=set(known_exceptions),
            )
        )

    ordinary_above_hard: list[dict[str, Any]] = []
    ordinary_above_target: list[dict[str, Any]] = []
    ordinary_below_floor: list[dict[str, Any]] = []
    below_floor_soft: list[dict[str, Any]] = []
    hard_max_exception_soft: list[dict[str, Any]] = []
    hard_max_exception_details: list[dict[str, Any]] = []
    strip_failures: list[dict[str, Any]] = []
    protected_strips: list[dict[str, Any]] = []
    enclave_failures: list[dict[str, Any]] = []
    corner_failures: list[dict[str, Any]] = []
    max_aspect = float(ctx.thresholds.beautify.max_aspect_ratio)
    max_corners = int(ctx.thresholds.beautify.max_exterior_corners)
    corner_snap = float(ctx.thresholds.beautify.corner_snap_m)

    legendary_vertex_keys: set[tuple[int, int]] = set()
    legendary_geoms: list[BaseGeometry] = []
    for props, geom in zip(props_list, work_geoms, strict=False):
        if territory_class_of(props) != "legendary" and props.get("protected") is not True:
            continue
        legendary_geoms.append(geom)
        poly = geom
        parts = list(poly.geoms) if poly.geom_type == "MultiPolygon" else [poly]
        for part in parts:
            if not hasattr(part, "exterior") or part.exterior is None:
                continue
            for x, y, *rest in part.exterior.coords[:-1]:
                legendary_vertex_keys.add(
                    (int(round(float(x) / corner_snap)), int(round(float(y) / corner_snap)))
                )
    legendary_boundary = unary_union(legendary_geoms) if legendary_geoms else None

    for props, geom in zip(props_list, work_geoms, strict=False):
        quality = shape_quality(geom)
        aspect = float(quality["aspect_ratio"])
        area_m2 = float(geom.area)
        tclass = territory_class_of(props)
        total_corners = exterior_corner_count(geom)
        corners = budget_exterior_corner_count(
            geom,
            legendary_vertex_keys=legendary_vertex_keys,
            snap_m=corner_snap,
            legendary_boundary=legendary_boundary,
        )
        row = {
            "territory_id": props.get("territory_id"),
            "slug": props.get("slug"),
            "name": props.get("name"),
            "area_m2": round(area_m2, 3),
            "area_acres": round(area_m2 / _M2_PER_ACRE, 3),
            "aspect_ratio": aspect,
            "exterior_corners": corners,
            "total_exterior_corners": total_corners,
            "territory_class": tclass,
        }

        if tclass == "legendary" or props.get("protected") is True:
            if props.get("protected") is not True:
                failures.append(
                    _fail(
                        "legendary_integrity",
                        f"legendary territory {props.get('slug')!r} must be protected",
                        props.get("protected"),
                        True,
                    )
                )
            members = props.get("member_territory_ids") or []
            if isinstance(members, list) and len(set(str(m) for m in members)) > 1:
                failures.append(
                    _fail(
                        "legendary_integrity",
                        f"legendary territory {props.get('slug')!r} must not annex "
                        "outside parcels",
                        len(set(str(m) for m in members)),
                        1,
                    )
                )
            if aspect > max_aspect + 1e-9:
                protected_strips.append(row)
            continue

        if area_m2 + 1e-6 < gp.soft_min_m2:
            ordinary_below_floor.append(row)
            # With a 350-acre hard cap, some fabric pockets cannot reach the
            # 250-acre floor without splitting a neighbour. Flag for review
            # instead of blocking publish.
            below_floor_soft.append(
                {
                    "slug": props.get("slug"),
                    "reasons": ["below_250_acre_target"],
                    "area_m2": round(area_m2, 3),
                    "area_acres": round(area_m2 / _M2_PER_ACRE, 3),
                }
            )
            continue

        if area_m2 > gp.hard_max_m2 + 1e-6:
            ordinary_above_hard.append(row)
            slug = str(props.get("slug") or "")
            source_exception_slug = slug if slug in known_exceptions else None
            source_exception_reason = (
                known_exceptions[source_exception_slug] if source_exception_slug else None
            )

            if source_exception_slug is None:
                inherited_slug = props.get("hard_max_exception_source_slug")
                inherited_reason = props.get("hard_max_exception_reason")
                if isinstance(inherited_slug, str) and inherited_slug.strip():
                    source_exception_slug = inherited_slug
                    if isinstance(inherited_reason, str) and inherited_reason.strip():
                        source_exception_reason = inherited_reason
                    elif inherited_slug in known_exceptions:
                        source_exception_reason = known_exceptions[inherited_slug]

            if source_exception_slug is None:
                member_ids = props.get("member_territory_ids") or []
                if isinstance(member_ids, list):
                    for raw in member_ids:
                        mid = str(raw)
                        if mid in known_exception_ids:
                            source_exception_slug, source_exception_reason = known_exception_by_id[mid]
                            break

            if source_exception_slug is not None and source_exception_reason is not None:
                hard_max_exception_soft.append(
                    {
                        "slug": slug,
                        "exception_source_slug": source_exception_slug,
                        "reasons": ["known_mvp_hard_max_exception"],
                        "area_m2": round(area_m2, 3),
                        "area_acres": round(area_m2 / _M2_PER_ACRE, 3),
                    }
                )
                hard_max_exception_details.append(
                    {
                        "territory_id": props.get("territory_id"),
                        "slug": slug,
                        "exception_source_slug": source_exception_slug,
                        "name": props.get("name"),
                        "area_m2": round(area_m2, 3),
                        "hard_max_m2": round(gp.hard_max_m2, 3),
                        "reason": source_exception_reason,
                    }
                )
            else:
                failures.append(
                    _fail(
                        "ordinary_hard_max",
                        f"ordinary territory {props.get('slug')!r} exceeds hard maximum",
                        round(area_m2, 3),
                        gp.hard_max_m2,
                    )
                )
        elif area_m2 > gp.soft_max_m2 + 1e-6:
            ordinary_above_target.append(row)

        if aspect > max_aspect + 1e-9:
            strip_failures.append(row)
            # Soft-review strips at Stage 10 and Stage 11; force-merge attempts
            # happen in clustering/beautify, but some corridors remain until
            # separators improve.

        if strict_shape and corners > max_corners:
            corner_failures.append(row)
            # Temporary soft: hard mosaic peels cannot always hit ≤10 without
            # opening gaps. Soft-review until shared-edge peels catch up.
            soft_needs_corner = {
                "slug": props.get("slug"),
                "reasons": ["exterior_corner_budget"],
                "exterior_corners": corners,
                "max_exterior_corners": max_corners,
            }
            # Defer append until soft_needs exists — stash on row for now.
            row["soft_corner_budget"] = soft_needs_corner

    # Near-enclave / island check: a small ordinary polygon almost contained by
    # another territory means borders are not a touching mosaic.
    for i, (props_i, geom_i) in enumerate(zip(props_list, work_geoms, strict=False)):
        if props_i.get("protected") is True:
            continue
        if float(geom_i.area) <= 0:
            continue
        try:
            core = geom_i.buffer(-1.0)
        except Exception:
            continue
        if core is None or core.is_empty:
            # Extremely thin strip — already caught by aspect/area rules.
            continue
        for j, (props_j, geom_j) in enumerate(zip(props_list, work_geoms, strict=False)):
            if i == j:
                continue
            try:
                if geom_j.buffer(2.0).contains(core):
                    enclave_failures.append(
                        {
                            "territory_id": props_i.get("territory_id"),
                            "slug": props_i.get("slug"),
                            "container_slug": props_j.get("slug"),
                            "area_m2": round(float(geom_i.area), 3),
                        }
                    )
                    # Temporary soft: keep gap/overlap/coverage hard.
                    break
            except Exception:
                continue

    soft_needs = [
        {
            "slug": p.get("slug"),
            "reasons": p.get("review_reasons") or [],
            "area_m2": p.get("area_m2"),
        }
        for p in props_list
        if p.get("needs_review") is True
    ]
    soft_needs.extend(below_floor_soft)
    soft_needs.extend(hard_max_exception_soft)
    for row in strip_failures:
        slug = row.get("slug")
        if any(
            f.get("check") == "ordinary_strip_aspect" and f.get("detail", "").find(repr(slug)) >= 0
            for f in failures
        ):
            continue
        soft_needs.append(
            {
                "slug": slug,
                "reasons": ["strip_aspect"],
                "area_m2": row.get("area_m2"),
                "aspect_ratio": row.get("aspect_ratio"),
            }
        )
    for row in corner_failures:
        soft = row.get("soft_corner_budget")
        if soft:
            soft_needs.append(soft)
    for enc in enclave_failures:
        soft_needs.append(
            {
                "slug": enc.get("slug"),
                "reasons": ["ordinary_enclave"],
                "container_slug": enc.get("container_slug"),
            }
        )
    fabric_areas = [
        float(p.get("area_m2") or g.area)
        for p, g in zip(props_list, work_geoms, strict=False)
        if p.get("protected") is not True
    ]
    passed = len(failures) == 0
    return {
        "status": "pass" if passed else "fail",
        "stage": "cluster_gameplay",
        "hard": {"passed": passed, "failures": failures},
        "metrics": {
            "feature_count": len(features),
            "protected_count": sum(1 for p in props_list if p.get("protected")),
            "legendary_count": sum(
                1
                for p in props_list
                if territory_class_of(p) == "legendary" or p.get("protected")
            ),
            "ordinary_count": sum(
                1
                for p in props_list
                if territory_class_of(p) != "legendary" and p.get("protected") is not True
            ),
            "coverage_ratio": round(coverage_ratio, 9),
            "gap_m2": round(gap_m2, 6),
            "overlap_m2": round(overlap_m2, 6),
            "aoi_area_m2": round(aoi_area, 3),
            "max_aspect_ratio": max_aspect,
            "max_exterior_corners": max_corners,
            "ordinary_below_floor": ordinary_below_floor,
            "enclave_failures": enclave_failures,
            "corner_budget_failures": corner_failures,
        },
        "soft": {
            "needs_review": soft_needs,
            "needs_review_count": len(soft_needs),
            "size_bands": {
                "fabric_below_soft_min": sum(1 for a in fabric_areas if a < gp.soft_min_m2),
                "fabric_in_soft_band": sum(
                    1 for a in fabric_areas if gp.soft_min_m2 <= a <= gp.soft_max_m2
                ),
                "fabric_above_soft_max": sum(1 for a in fabric_areas if a > gp.soft_max_m2),
                "fabric_above_review_max": sum(1 for a in fabric_areas if a > gp.review_max_m2),
            },
            "ordinary_above_300_acre_target": ordinary_above_target,
            "ordinary_above_hard_max": ordinary_above_hard,
            "known_hard_max_exceptions": stable_sort(
                hard_max_exception_details,
                key=lambda row: (str(row.get("slug") or ""), str(row.get("territory_id") or "")),
            ),
            "strip_violations": strip_failures,
            "protected_natural_strips": protected_strips,
        },
    }


def _check_atomic_landmark_integrity(
    parcels: list[dict[str, Any]],
    gameplay: list[dict[str, Any]],
    crs_work: str,
    *,
    max_missing_m2: float,
    standalone_min_m2: float,
    known_exception_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Every mergeable atomic landmark must survive whole in one territory."""
    failures: list[dict[str, Any]] = []
    atomic = [
        feature
        for feature in parcels
        if (feature.get("properties") or {}).get("atomic") is True
        and (feature.get("properties") or {}).get("protected") is not True
    ]
    if not atomic:
        return failures

    outputs: list[tuple[dict[str, Any], BaseGeometry]] = []
    for feature in gameplay:
        geom_json = feature.get("geometry")
        if not geom_json:
            continue
        try:
            geom = to_work(shape(geom_json), crs_work)
        except Exception:
            continue
        outputs.append((dict(feature.get("properties") or {}), geom))

    for feature in atomic:
        props = dict(feature.get("properties") or {})
        landmark_slug = props.get("atomic_source_slug") or props.get("slug")
        tid = str(props.get("territory_id") or "")
        if known_exception_keys and (
            (isinstance(landmark_slug, str) and landmark_slug in known_exception_keys)
            or (tid and tid in known_exception_keys)
        ):
            continue
        if not tid:
            failures.append(
                _fail(
                    "atomic_integrity",
                    "atomic parcel is missing territory_id",
                    landmark_slug,
                    "territory_id",
                )
            )
            continue
        holders = [
            (out_props, out_geom)
            for out_props, out_geom in outputs
            if tid
            in {str(member) for member in (out_props.get("member_territory_ids") or [])}
        ]
        if len(holders) != 1:
            failures.append(
                _fail(
                    "atomic_integrity",
                    f"atomic landmark {landmark_slug!r} must belong to exactly one "
                    "gameplay territory",
                    len(holders),
                    1,
                )
            )
            continue
        out_props, out_geom = holders[0]
        members = [str(v) for v in (out_props.get("member_territory_ids") or [])]
        if len(set(members)) <= 1 and out_props.get("protected") is not True:
            failures.append(
                _fail(
                    "atomic_absorption",
                    f"small landmark {landmark_slug!r} remained standalone",
                    members,
                    "merged with adjacent fabric",
                )
            )
        try:
            source_geom = to_work(shape(feature["geometry"]), crs_work)
            missing_m2 = float(source_geom.difference(out_geom).area)
        except Exception as exc:
            failures.append(
                _fail(
                    "atomic_integrity",
                    f"atomic landmark {landmark_slug!r} geometry unreadable: {exc}",
                    None,
                    "valid geometry",
                )
            )
            continue
        if missing_m2 > max_missing_m2:
            failures.append(
                _fail(
                    "atomic_integrity",
                    f"atomic landmark {landmark_slug!r} was cut or lost",
                    round(missing_m2, 6),
                    max_missing_m2,
                )
            )
    return failures


def _check_protected_vs_parcels(
    parcels: list[dict[str, Any]],
    gameplay: list[dict[str, Any]],
    crs_work: str,
    *,
    standalone_min_m2: float,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []

    def _eligible_protected(feature: dict[str, Any]) -> bool:
        props = feature.get("properties") or {}
        if props.get("protected") is not True or not props.get("slug"):
            return False
        area = float(props.get("area_m2") or 0.0)
        return area + 1e-6 >= standalone_min_m2

    parcel_prot = {
        str((f.get("properties") or {}).get("slug")): f
        for f in parcels
        if _eligible_protected(f)
    }
    game_prot = {
        str((f.get("properties") or {}).get("slug")): f
        for f in gameplay
        if (f.get("properties") or {}).get("protected") is True
        and (f.get("properties") or {}).get("slug")
    }
    if len(parcel_prot) != len(game_prot):
        failures.append(
            _fail(
                "protected_freeze",
                "protected count changed during clustering",
                len(game_prot),
                len(parcel_prot),
            )
        )
    for slug in sorted(set(parcel_prot) | set(game_prot)):
        if slug not in parcel_prot:
            failures.append(
                _fail("protected_freeze", f"unexpected protected slug {slug!r}", slug, None)
            )
            continue
        if slug not in game_prot:
            failures.append(
                _fail("protected_freeze", f"missing protected slug {slug!r}", None, slug)
            )
            continue
        p_hash = content_hash(parcel_prot[slug].get("geometry"))
        g_hash = content_hash(game_prot[slug].get("geometry"))
        if p_hash != g_hash:
            failures.append(
                _fail(
                    "protected_freeze",
                    f"protected geometry drifted for {slug!r}",
                    g_hash[:12],
                    p_hash[:12],
                )
            )
        p_id = (parcel_prot[slug].get("properties") or {}).get("territory_id")
        g_id = (game_prot[slug].get("properties") or {}).get("territory_id")
        if p_id != g_id:
            failures.append(
                _fail(
                    "protected_freeze",
                    f"protected territory_id changed for {slug!r}",
                    g_id,
                    p_id,
                )
            )
    return failures
