"""Size normalisation for stage 06.

Merges anonymous fabric scraps into the neighbour with the longest shared
border, freezes protected major landmarks, and flags oversized fabric for
human review. Does not split faces -- a giant fabric polygon almost always
means a separator is missing upstream.

Guarantees: valid polygonal output, protected byte-stability, merge area
conservation within validation.max_gap_m2, deterministic merge order.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from shapely import STRtree, is_valid, make_valid
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from lib import artifacts
from lib.contracts import PipelineContext
from lib.crs import to_store, to_work
from lib.determinism import content_hash, stable_sort
from lib.io import read_geojson

# Neighbour search buffer in metres (near-touch registration only).
_BORDER_EPS_M = 0.05
# Minimum shared border for a fabric neighbour to be merge-eligible.
_MIN_SHARED_BORDER_M = 5.0


class NormalizeError(RuntimeError):
    """Stage 06 cannot produce a safe normalized artifact."""


@dataclass
class _WorkFace:
    uid: str
    geom: BaseGeometry
    props: dict[str, Any]


@dataclass
class SafeMergeResult:
    geometry: BaseGeometry | None
    repaired: bool = False
    rejected_reason: str | None = None


@dataclass
class MergeDiagnostics:
    scrap_merges: int = 0
    orphan_scraps: int = 0
    invalid_merge_attempts: int = 0
    make_valid_repairs: int = 0
    failed_geometry_repairs: int = 0
    area_loss_rejections: int = 0
    fabric_input_repairs: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)

    def record_failure(self, scrap_uid: str, winner_uid: str, reason: str) -> None:
        self.failures.append(
            {
                "scrap_uid": scrap_uid,
                "winner_uid": winner_uid,
                "reason": reason,
            }
        )


@dataclass(frozen=True)
class NormalizeStats:
    input_face_count: int
    output_face_count: int
    protected_count: int
    fabric_count: int
    scrap_merges: int
    orphan_scraps: int
    needs_review_count: int
    below_soft_min: int
    in_soft_band: int
    above_soft_max: int
    above_review_max: int
    area_min_m2: float
    area_max_m2: float
    area_mean_m2: float
    area_total_m2: float
    input_area_total_m2: float
    invalid_merge_attempts: int = 0
    make_valid_repairs: int = 0
    failed_geometry_repairs: int = 0
    area_loss_rejections: int = 0
    fabric_input_repairs: int = 0
    input_union_area_m2: float = 0.0
    output_union_area_m2: float = 0.0
    union_delta_m2: float = 0.0
    aoi_coverage_ratio: float | None = None
    merge_failures: tuple[dict[str, Any], ...] = ()


def safe_merge_geometry(
    a: BaseGeometry,
    b: BaseGeometry,
    *,
    max_area_loss_m2: float,
) -> SafeMergeResult:
    """Union two fabric polygons; repair once; reject unsafe results.

    Never returns an invalid or non-polygonal geometry. Area after repair must
    stay within ``max_area_loss_m2`` of the pre-repair union area (and of the
    sum of input areas when the raw union was already valid).
    """
    if a is None or b is None or a.is_empty or b.is_empty:
        return SafeMergeResult(None, rejected_reason="empty_input")

    area_before = float(a.area) + float(b.area)
    try:
        merged = unary_union([a, b])
    except Exception as exc:  # noqa: BLE001
        return SafeMergeResult(None, rejected_reason=f"union_error:{exc}")

    repaired = False
    if merged is None or merged.is_empty:
        return SafeMergeResult(None, rejected_reason="empty_union")

    if not is_valid(merged):
        try:
            repaired_geom = make_valid(merged)
        except Exception as exc:  # noqa: BLE001
            return SafeMergeResult(
                None, repaired=False, rejected_reason=f"make_valid_error:{exc}"
            )
        repaired = True
        merged = repaired_geom

    polygonal = _as_polygonal(merged)
    if polygonal is None or polygonal.is_empty:
        return SafeMergeResult(
            None,
            repaired=repaired,
            rejected_reason="non_polygonal" if repaired else "empty_or_non_polygonal",
        )
    if not is_valid(polygonal):
        return SafeMergeResult(
            None, repaired=repaired, rejected_reason="still_invalid"
        )

    area_after = float(polygonal.area)
    if abs(area_before - area_after) > max_area_loss_m2:
        return SafeMergeResult(
            None, repaired=repaired, rejected_reason="area_loss"
        )

    return SafeMergeResult(polygonal, repaired=repaired, rejected_reason=None)


def normalize_faces(ctx: PipelineContext) -> tuple[list[dict[str, Any]], NormalizeStats]:
    """Normalize Stage 05 faces. Hook for tests via monkeypatch."""
    crs_work = ctx.region.crs_work
    crs_store = ctx.region.crs_store
    scrap_m2 = float(ctx.thresholds.scrap_m2)
    soft_min = float(ctx.thresholds.fabric_soft_min_m2)
    soft_max = float(ctx.thresholds.fabric_soft_max_m2)
    review_max = float(ctx.thresholds.fabric_review_max_m2)
    max_gap_m2 = float(ctx.thresholds.validation.max_gap_m2)

    data = read_geojson(artifacts.FACES.path(ctx))
    raw_features = list(data.get("features") or [])

    protected_store: list[dict[str, Any]] = []
    fabric: list[_WorkFace] = []
    input_geoms: list[BaseGeometry] = []
    input_area_total = 0.0
    fabric_input_repairs = 0
    diagnostics = MergeDiagnostics()

    for idx, feature in enumerate(raw_features):
        props = dict(feature.get("properties") or {})
        uid = str(props.get("face_id") or f"in-{idx:05d}")
        geom_json = feature.get("geometry")
        if not geom_json:
            raise NormalizeError(f"Stage 06: face {uid!r} missing geometry")
        try:
            geom4326 = shape(geom_json)
        except Exception as exc:
            raise NormalizeError(f"Stage 06: face {uid!r} unreadable geometry: {exc}") from exc
        if geom4326 is None or geom4326.is_empty:
            raise NormalizeError(f"Stage 06: face {uid!r} empty geometry")

        is_protected = props.get("protected") is True
        if is_protected:
            if not is_valid(geom4326):
                raise NormalizeError(
                    f"Stage 06: protected face {uid!r} has invalid geometry "
                    "(protected landmarks are never repaired)"
                )
            work = to_work(geom4326, crs_work)
            work = _as_polygonal(work)
            if work is None or work.is_empty or not is_valid(work):
                raise NormalizeError(
                    f"Stage 06: protected face {uid!r} invalid after to_work"
                )
            area = float(work.area)
            input_area_total += area
            input_geoms.append(work)
            frozen = deepcopy(feature)
            frozen["properties"] = dict(props)
            frozen["properties"]["protected"] = True
            frozen["properties"]["area_m2"] = round(area, 3)
            # Keep original storage geometry for byte stability.
            protected_store.append(frozen)
            continue

        # Fabric: Stage 05 must deliver valid positive-area faces. Degenerate
        # or unrepaired input is a Stage 05 bug — fail closed, do not drop.
        work = to_work(geom4326, crs_work)
        work = _as_polygonal(work)
        if work is None or work.is_empty or float(work.area) <= 0.0:
            raise NormalizeError(
                f"Stage 06: degenerate fabric face {uid!r} from Stage 05 "
                "(expected degenerate_input_count == 0)"
            )

        if not is_valid(work):
            repaired, reason = _repair_fabric_input(work, max_gap_m2)
            if repaired is None:
                raise NormalizeError(
                    f"Stage 06: fabric face {uid!r} invalid and unrepaired ({reason}); "
                    "Stage 05 should not emit this"
                )
            work = repaired
            fabric_input_repairs += 1

        if round(float(work.area), 3) == 0 or float(work.area) < 1e-3:
            raise NormalizeError(
                f"Stage 06: near-zero fabric face {uid!r} from Stage 05 "
                "(expected degenerate_input_count == 0)"
            )

        area = float(work.area)
        input_area_total += area
        input_geoms.append(work)
        # Mergeable atomics (carved whole but not standalone) join the fabric
        # merge pool while keeping landmark identity for later naming.
        fabric_props: dict[str, Any] = {
            "protected": False,
            "atomic": bool(props.get("atomic")),
            "needs_review": bool(props.get("needs_review")),
        }
        if props.get("atomic") is True and props.get("protected") is not True:
            fabric_props.update(
                {
                    "role": props.get("role") or "major",
                    "name": props.get("name"),
                    "slug": props.get("slug"),
                    "kind": props.get("kind") or "park",
                    "category": props.get("category"),
                    "source": props.get("source"),
                    "source_id": props.get("source_id"),
                }
            )
        else:
            fabric_props["role"] = None
            fabric_props["kind"] = "fabric"
        fabric.append(
            _WorkFace(
                uid=uid,
                geom=work,
                props=fabric_props,
            )
        )

    diagnostics.fabric_input_repairs = fabric_input_repairs
    protected_count_before = len(protected_store)
    protected_hashes_before = _protected_geometry_hashes(protected_store)

    input_union_area = float(unary_union(input_geoms).area) if input_geoms else 0.0

    fabric, diagnostics = _merge_scraps(fabric, scrap_m2, max_gap_m2, diagnostics)

    for face in fabric:
        area = float(face.geom.area)
        if area > review_max or area < scrap_m2:
            face.props["needs_review"] = True

    features: list[dict[str, Any]] = list(protected_store)
    for face in fabric:
        if not is_valid(face.geom) or face.geom.is_empty:
            raise NormalizeError(
                f"Stage 06: fabric face {face.uid!r} invalid before write"
            )
        area = float(face.geom.area)
        store_geom = _to_valid_store(
            face.geom, crs_work, crs_store, max_gap_m2, uid=face.uid
        )
        props = dict(face.props)
        props["area_m2"] = round(area, 3)
        if not props.get("needs_review"):
            props.pop("needs_review", None)
        else:
            props["needs_review"] = True
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(store_geom),
                "properties": props,
            }
        )

    features = stable_sort(features, key=_feature_sort_key)
    for idx, feature in enumerate(features, start=1):
        feature["properties"]["face_id"] = f"face-{idx:05d}"

    # Protected invariants (geometry untouched; count stable).
    protected_after = [
        f for f in features if (f.get("properties") or {}).get("protected") is True
    ]
    if len(protected_after) != protected_count_before:
        raise NormalizeError(
            f"Stage 06: protected count changed "
            f"{protected_count_before} -> {len(protected_after)}"
        )
    protected_hashes_after = _protected_geometry_hashes(protected_after)
    if protected_hashes_after != protected_hashes_before:
        raise NormalizeError("Stage 06: protected geometry hash changed")

    _assert_all_output_valid(features)

    output_geoms = [
        to_work(shape(f["geometry"]), crs_work) for f in features if f.get("geometry")
    ]
    output_union_area = float(unary_union(output_geoms).area) if output_geoms else 0.0
    union_delta = abs(input_union_area - output_union_area)

    aoi = to_work(box(*ctx.region.bbox.as_xy_bounds()), crs_work)
    aoi_area = float(aoi.area)
    aoi_coverage_ratio = None
    if aoi_area > 0 and output_geoms:
        covered = float(unary_union(output_geoms).intersection(aoi).area)
        aoi_coverage_ratio = covered / aoi_area

    diagnostics.failures = stable_sort(
        diagnostics.failures,
        key=lambda d: (str(d.get("scrap_uid")), str(d.get("winner_uid")), str(d.get("reason"))),
    )

    stats = _build_stats(
        features,
        input_face_count=len(raw_features),
        input_area_total_m2=input_area_total,
        scrap_merges=diagnostics.scrap_merges,
        orphan_scraps=diagnostics.orphan_scraps,
        soft_min=soft_min,
        soft_max=soft_max,
        review_max=review_max,
        invalid_merge_attempts=diagnostics.invalid_merge_attempts,
        make_valid_repairs=diagnostics.make_valid_repairs,
        failed_geometry_repairs=diagnostics.failed_geometry_repairs,
        area_loss_rejections=diagnostics.area_loss_rejections,
        fabric_input_repairs=diagnostics.fabric_input_repairs,
        input_union_area_m2=input_union_area,
        output_union_area_m2=output_union_area,
        union_delta_m2=union_delta,
        aoi_coverage_ratio=aoi_coverage_ratio,
        merge_failures=tuple(diagnostics.failures),
    )
    return features, stats


def _repair_fabric_input(
    work: BaseGeometry, max_area_loss_m2: float
) -> tuple[BaseGeometry | None, str]:
    """One-time fabric repair: make_valid, then buffer(0). Never used on protected."""
    area_before = float(work.area)
    candidates: list[BaseGeometry] = []
    try:
        candidates.append(make_valid(work))
    except Exception:
        pass
    try:
        # GEOS buffer(0) often recovers polygons make_valid reduces to lines.
        candidates.append(work.buffer(0))
    except Exception:
        pass

    last_reason = "no_repair_candidate"
    for repaired in candidates:
        polygonal = _as_polygonal(repaired)
        if polygonal is None or polygonal.is_empty:
            last_reason = "non_polygonal"
            continue
        if not is_valid(polygonal):
            last_reason = "still_invalid"
            continue
        if abs(area_before - float(polygonal.area)) > max_area_loss_m2:
            last_reason = "area_loss"
            continue
        return polygonal, "ok"
    return None, last_reason


def _protected_geometry_hashes(features: list[dict[str, Any]]) -> list[str]:
    items: list[tuple[str, str]] = []
    for feature in features:
        props = feature.get("properties") or {}
        if props.get("protected") is not True:
            continue
        key = str(props.get("slug") or props.get("face_id") or "")
        geom = feature.get("geometry")
        digest = content_hash(geom) if geom is not None else content_hash(None)
        items.append((key, digest))
    items.sort(key=lambda t: t[0])
    return [h for _, h in items]


def _to_valid_store(
    work_geom: BaseGeometry,
    crs_work: str,
    crs_store: str,
    max_area_loss_m2: float,
    *,
    uid: str,
) -> BaseGeometry:
    """Project to storage CRS; repair numerical invalidity without area loss."""
    store_geom = _as_multipolygon(to_store(work_geom, crs_work, crs_store))
    if store_geom is None or store_geom.is_empty:
        raise NormalizeError(f"Stage 06: fabric face {uid!r} empty after to_store")
    if is_valid(store_geom):
        return store_geom

    try:
        repaired = make_valid(store_geom)
    except Exception as exc:  # noqa: BLE001
        raise NormalizeError(
            f"Stage 06: fabric face {uid!r} invalid after to_store ({exc})"
        ) from exc
    polygonal = _as_polygonal(repaired)
    if polygonal is None or polygonal.is_empty or not is_valid(polygonal):
        raise NormalizeError(
            f"Stage 06: fabric face {uid!r} unrepaired after to_store"
        )
    work_after = _as_polygonal(to_work(polygonal, crs_work, crs_store))
    if work_after is None or abs(float(work_geom.area) - float(work_after.area)) > max_area_loss_m2:
        raise NormalizeError(
            f"Stage 06: fabric face {uid!r} to_store repair lost area"
        )
    return _as_multipolygon(polygonal)


def _assert_all_output_valid(features: list[dict[str, Any]]) -> None:
    for i, feature in enumerate(features):
        geom_json = feature.get("geometry")
        props = feature.get("properties") or {}
        uid = props.get("face_id") or f"out-{i}"
        if not geom_json:
            raise NormalizeError(f"Stage 06: output {uid!r} missing geometry")
        try:
            geom = shape(geom_json)
        except Exception as exc:
            raise NormalizeError(
                f"Stage 06: output {uid!r} unreadable: {exc}"
            ) from exc
        if geom is None or geom.is_empty:
            raise NormalizeError(f"Stage 06: output {uid!r} empty geometry")
        if geom.geom_type not in {"Polygon", "MultiPolygon"}:
            raise NormalizeError(
                f"Stage 06: output {uid!r} type {geom.geom_type} not polygonal"
            )
        if not is_valid(geom):
            raise NormalizeError(f"Stage 06: output {uid!r} invalid geometry")


def _merge_scraps(
    fabric: list[_WorkFace],
    scrap_m2: float,
    max_area_loss_m2: float,
    diagnostics: MergeDiagnostics,
) -> tuple[list[_WorkFace], MergeDiagnostics]:
    """Iteratively absorb scraps into longest-shared-border fabric neighbours."""
    faces = list(fabric)
    stuck: set[str] = set()

    while True:
        scraps = [
            f
            for f in faces
            if float(f.geom.area) < scrap_m2
            and f.props.get("atomic") is not True
            and f.uid not in stuck
        ]
        if not scraps:
            break

        scraps = stable_sort(scraps, key=lambda f: (float(f.geom.area), f.uid))
        scrap = scraps[0]

        winner = _best_fabric_neighbour(scrap, faces)
        if winner is None:
            stuck.add(scrap.uid)
            scrap.props["needs_review"] = True
            continue

        result = safe_merge_geometry(
            winner.geom, scrap.geom, max_area_loss_m2=max_area_loss_m2
        )
        if result.geometry is None:
            reason = result.rejected_reason or "rejected"
            diagnostics.invalid_merge_attempts += 1
            if reason == "area_loss":
                diagnostics.area_loss_rejections += 1
            if reason in {
                "still_invalid",
                "non_polygonal",
                "empty_or_non_polygonal",
                "empty_union",
            } or str(reason).startswith("make_valid"):
                diagnostics.failed_geometry_repairs += 1
            diagnostics.record_failure(scrap.uid, winner.uid, reason)
            stuck.add(scrap.uid)
            scrap.props["needs_review"] = True
            continue

        if result.repaired:
            diagnostics.make_valid_repairs += 1

        winner.geom = result.geometry
        faces = [f for f in faces if f.uid != scrap.uid]
        diagnostics.scrap_merges += 1
        stuck.discard(winner.uid)

    diagnostics.orphan_scraps = sum(
        1
        for f in faces
        if float(f.geom.area) < scrap_m2 and f.props.get("atomic") is not True
    )
    for face in faces:
        if float(face.geom.area) < scrap_m2 and face.props.get("atomic") is not True:
            face.props["needs_review"] = True
    return faces, diagnostics


def _best_fabric_neighbour(
    scrap: _WorkFace, faces: list[_WorkFace]
) -> _WorkFace | None:
    """Longest shared border (≥ min), then shortest centroid distance, then id."""
    if len(faces) <= 1:
        return None

    geoms = [f.geom for f in faces]
    tree = STRtree(geoms)
    hits = tree.query(scrap.geom.buffer(_BORDER_EPS_M))
    scrap_centroid = scrap.geom.centroid

    candidates: list[tuple[float, float, str, _WorkFace]] = []
    for idx in hits:
        other = faces[int(idx)]
        if other.uid == scrap.uid:
            continue
        shared = _shared_border_length(scrap.geom, other.geom)
        if shared < _MIN_SHARED_BORDER_M:
            continue
        dist = float(scrap_centroid.distance(other.geom.centroid))
        candidates.append((shared, dist, other.uid, other))

    if not candidates:
        return None
    # Longest border, then nearest centroid, then stable id.
    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))
    return candidates[0][3]


def _shared_border_length(a: BaseGeometry, b: BaseGeometry) -> float:
    """Approximate length of the shared perimeter between two faces (metres)."""
    if a is None or b is None or a.is_empty or b.is_empty:
        return 0.0
    try:
        if not a.buffer(_BORDER_EPS_M).intersects(b):
            return 0.0
        return float(a.boundary.intersection(b.buffer(_BORDER_EPS_M)).length)
    except Exception:
        return 0.0


def _feature_sort_key(feature: dict[str, Any]) -> tuple:
    props = feature.get("properties") or {}
    geom = feature.get("geometry") or {}
    coords = _first_coord(geom)
    return (
        0 if props.get("protected") else 1,
        str(props.get("slug") or ""),
        str(props.get("kind") or ""),
        round(float(props.get("area_m2") or 0.0), 3),
        round(coords[0], 8),
        round(coords[1], 8),
    )


def _first_coord(geom: dict[str, Any]) -> tuple[float, float]:
    coords = geom.get("coordinates")
    if not coords:
        return (0.0, 0.0)
    gtype = geom.get("type")
    try:
        if gtype == "Polygon":
            return (float(coords[0][0][0]), float(coords[0][0][1]))
        if gtype == "MultiPolygon":
            return (float(coords[0][0][0][0]), float(coords[0][0][0][1]))
    except (IndexError, TypeError, ValueError):
        return (0.0, 0.0)
    return (0.0, 0.0)


def _build_stats(
    features: list[dict[str, Any]],
    *,
    input_face_count: int,
    input_area_total_m2: float,
    scrap_merges: int,
    orphan_scraps: int,
    soft_min: float,
    soft_max: float,
    review_max: float,
    invalid_merge_attempts: int = 0,
    make_valid_repairs: int = 0,
    failed_geometry_repairs: int = 0,
    area_loss_rejections: int = 0,
    fabric_input_repairs: int = 0,
    input_union_area_m2: float = 0.0,
    output_union_area_m2: float = 0.0,
    union_delta_m2: float = 0.0,
    aoi_coverage_ratio: float | None = None,
    merge_failures: tuple[dict[str, Any], ...] = (),
) -> NormalizeStats:
    areas = [float((f.get("properties") or {}).get("area_m2") or 0.0) for f in features]
    protected_count = sum(
        1 for f in features if (f.get("properties") or {}).get("protected") is True
    )
    fabric_areas = [
        float((f.get("properties") or {}).get("area_m2") or 0.0)
        for f in features
        if (f.get("properties") or {}).get("protected") is not True
    ]
    needs_review_count = sum(
        1 for f in features if (f.get("properties") or {}).get("needs_review") is True
    )

    below = sum(1 for a in fabric_areas if a < soft_min)
    in_band = sum(1 for a in fabric_areas if soft_min <= a <= soft_max)
    above_soft = sum(1 for a in fabric_areas if a > soft_max)
    above_review = sum(1 for a in fabric_areas if a > review_max)

    if not areas:
        return NormalizeStats(
            input_face_count=input_face_count,
            output_face_count=0,
            protected_count=0,
            fabric_count=0,
            scrap_merges=scrap_merges,
            orphan_scraps=orphan_scraps,
            needs_review_count=0,
            below_soft_min=0,
            in_soft_band=0,
            above_soft_max=0,
            above_review_max=0,
            area_min_m2=0.0,
            area_max_m2=0.0,
            area_mean_m2=0.0,
            area_total_m2=0.0,
            input_area_total_m2=input_area_total_m2,
            invalid_merge_attempts=invalid_merge_attempts,
            make_valid_repairs=make_valid_repairs,
            failed_geometry_repairs=failed_geometry_repairs,
            area_loss_rejections=area_loss_rejections,
            fabric_input_repairs=fabric_input_repairs,
            input_union_area_m2=input_union_area_m2,
            output_union_area_m2=output_union_area_m2,
            union_delta_m2=union_delta_m2,
            aoi_coverage_ratio=aoi_coverage_ratio,
            merge_failures=merge_failures,
        )

    total = sum(areas)
    return NormalizeStats(
        input_face_count=input_face_count,
        output_face_count=len(areas),
        protected_count=protected_count,
        fabric_count=len(areas) - protected_count,
        scrap_merges=scrap_merges,
        orphan_scraps=orphan_scraps,
        needs_review_count=needs_review_count,
        below_soft_min=below,
        in_soft_band=in_band,
        above_soft_max=above_soft,
        above_review_max=above_review,
        area_min_m2=min(areas),
        area_max_m2=max(areas),
        area_mean_m2=total / len(areas),
        area_total_m2=total,
        input_area_total_m2=input_area_total_m2,
        invalid_merge_attempts=invalid_merge_attempts,
        make_valid_repairs=make_valid_repairs,
        failed_geometry_repairs=failed_geometry_repairs,
        area_loss_rejections=area_loss_rejections,
        fabric_input_repairs=fabric_input_repairs,
        input_union_area_m2=input_union_area_m2,
        output_union_area_m2=output_union_area_m2,
        union_delta_m2=union_delta_m2,
        aoi_coverage_ratio=aoi_coverage_ratio,
        merge_failures=merge_failures,
    )


def _explode_polygons(geom: BaseGeometry | None) -> list[BaseGeometry]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return [g for g in geom.geoms if not g.is_empty]
    if geom.geom_type == "GeometryCollection":
        out: list[BaseGeometry] = []
        for part in geom.geoms:
            out.extend(_explode_polygons(part))
        return out
    return []


def _as_polygonal(geom: BaseGeometry | None) -> BaseGeometry | None:
    polys = _explode_polygons(geom)
    if not polys:
        return None
    if len(polys) == 1:
        return polys[0]
    return MultiPolygon(polys)


def _as_multipolygon(geom: BaseGeometry) -> BaseGeometry:
    if isinstance(geom, MultiPolygon):
        return geom
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    merged = _as_polygonal(geom)
    if merged is None:
        return MultiPolygon()
    if isinstance(merged, Polygon):
        return MultiPolygon([merged])
    return merged
