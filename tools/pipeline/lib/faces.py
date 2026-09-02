"""Polygonize the boundary graph and carve protected major landmarks (stage 05).

Produces the first exhaustive partition of the AOI. Fabric faces come from
noded separators; major landmarks are subtracted from fabric and reinserted
whole. Minor landmarks are ignored here -- they stay inside surrounding fabric
for later naming hints.

Before writing, every face is validated in the working CRS and again after a
storage-CRS round-trip. Degenerate fabric is dropped; invalid protected majors
fail the stage. Fabric may be repaired once under the same polygonal + area
conservation contract as stage 06.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from shapely import is_valid, make_valid
from shapely.geometry import LineString, MultiPolygon, Polygon, box, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from lib import artifacts
from lib.contracts import PipelineContext
from lib.crs import to_store, to_work
from lib.determinism import stable_sort
from lib.io import read_geojson

# Faces at or below this area (m² in work CRS) are numerical junk, not places.
FACE_AREA_EPSILON_M2 = 0.001

Source = Literal["polygonize", "carve", "post_store", "landmark"]


class FaceBuildError(RuntimeError):
    """Stage 05 cannot produce a safe faces artifact."""


@dataclass
class CleanupCounters:
    faces_generated: int = 0
    dropped_empty: int = 0
    dropped_zero_area: int = 0
    invalid_repaired: int = 0
    invalid_failed: int = 0
    post_store_invalid: int = 0
    dropped_polygonize: int = 0
    dropped_carve: int = 0
    dropped_post_store: int = 0


@dataclass(frozen=True)
class FaceBuildStats:
    """Diagnostic totals for the stage log / pipeline foreign members."""

    face_count: int
    protected_count: int
    fabric_count: int
    area_min_m2: float
    area_max_m2: float
    area_mean_m2: float
    area_total_m2: float
    scrap_count: int
    aoi_area_m2: float
    faces_generated: int = 0
    dropped_empty: int = 0
    dropped_zero_area: int = 0
    invalid_repaired: int = 0
    invalid_failed: int = 0
    post_store_invalid: int = 0
    dropped_polygonize: int = 0
    dropped_carve: int = 0
    dropped_post_store: int = 0


def build_faces(ctx: PipelineContext) -> tuple[list[dict[str, Any]], FaceBuildStats]:
    """Build face features in storage CRS, with work-CRS diagnostics.

    Hook point for tests: monkeypatch this to avoid real polygonization.
    """
    crs_work = ctx.region.crs_work
    crs_store = ctx.region.crs_store
    scrap_m2 = float(ctx.thresholds.scrap_m2)
    max_gap_m2 = float(ctx.thresholds.validation.max_gap_m2)
    counters = CleanupCounters()

    aoi = to_work(box(*ctx.region.bbox.as_xy_bounds()), crs_work)
    lines = _graph_lines_work(ctx)
    fabric_raw = _polygonize_aoi(lines, aoi)
    majors = _atomic_landmarks_work(ctx, aoi)

    fabric_work: list[BaseGeometry] = []
    for geom in fabric_raw:
        counters.faces_generated += 1
        cleaned = _accept_work_geom(
            geom,
            protected=False,
            counters=counters,
            source="polygonize",
            max_area_loss_m2=max_gap_m2,
        )
        if cleaned is not None:
            fabric_work.append(cleaned)

    fabric_after, landmark_faces = _carve_majors(
        fabric_work, majors, counters=counters, max_area_loss_m2=max_gap_m2
    )

    features: list[dict[str, Any]] = []
    for landmark in landmark_faces:
        props = dict(landmark["properties"])
        # Never repair atomic landmark geometry (carve-whole invariant).
        feature = _finalize_feature(
            landmark["geometry"],
            props=props,
            protected=True,
            crs_work=crs_work,
            crs_store=crs_store,
            counters=counters,
            max_area_loss_m2=max_gap_m2,
        )
        if feature is None:
            raise FaceBuildError(
                f"Stage 05: atomic landmark "
                f"{landmark['properties'].get('slug')!r} failed post-store validation"
            )
        # Restore standalone vs mergeable: finalize forced protected=True for
        # geometry safety; overwrite with the landmark's actual flags.
        feature["properties"]["atomic"] = True
        feature["properties"]["protected"] = bool(props.get("protected"))
        feature["properties"]["role"] = props.get("role") or "major"
        features.append(feature)

    for geom in fabric_after:
        feature = _finalize_feature(
            geom,
            props={
                "protected": False,
                "role": None,
                "kind": "fabric",
            },
            protected=False,
            crs_work=crs_work,
            crs_store=crs_store,
            counters=counters,
            max_area_loss_m2=max_gap_m2,
        )
        if feature is not None:
            features.append(feature)

    features = stable_sort(features, key=_feature_sort_key)
    for idx, feature in enumerate(features, start=1):
        feature["properties"]["face_id"] = f"face-{idx:05d}"

    _assert_artifact_faces_clean(features, crs_work)

    stats = _stats(
        features,
        aoi_area_m2=float(aoi.area),
        scrap_m2=scrap_m2,
        counters=counters,
    )
    return features, stats


def _graph_lines_work(ctx: PipelineContext) -> list[LineString]:
    data = read_geojson(artifacts.BOUNDARY_GRAPH.path(ctx))
    pipeline = data.get("pipeline") or {}
    declared = pipeline.get("crs")
    crs_work = ctx.region.crs_work

    lines: list[LineString] = []
    for feature in data.get("features") or []:
        geom_json = feature.get("geometry")
        if not geom_json:
            continue
        try:
            geom = shape(geom_json)
        except Exception:
            continue
        if geom is None or geom.is_empty:
            continue
        # Stage 04 writes working CRS. If a test fixture left degrees, project.
        if declared == crs_work:
            work = geom
        else:
            work = to_work(geom, crs_work)
        lines.extend(_explode_lines(work))
    return [line for line in lines if line.length > 0]


def _atomic_landmarks_work(
    ctx: PipelineContext, aoi: BaseGeometry
) -> list[dict[str, Any]]:
    """Return atomic landmarks as work-CRS dicts with props + geometry.

    Carves every ``atomic: true`` landmark (and legacy ``protected`` majors
    without an atomic flag) so places stay whole. ``protected`` on the props
    still means standalone / never-merge for later stages.
    """
    data = read_geojson(artifacts.LANDMARKS.path(ctx))
    majors: list[dict[str, Any]] = []
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        atomic = props.get("atomic")
        if atomic is None:
            # Legacy landmarks: protected majors were both carved and frozen.
            atomic = props.get("protected") is True and props.get("role") == "major"
        if atomic is not True:
            continue
        slug = props.get("slug")
        geom_json = feature.get("geometry")
        if not geom_json:
            raise FaceBuildError(f"Stage 05: atomic landmark {slug!r} missing geometry")
        try:
            geom = shape(geom_json)
        except Exception as exc:
            raise FaceBuildError(
                f"Stage 05: atomic landmark {slug!r} unreadable: {exc}"
            ) from exc
        if not is_valid(geom):
            raise FaceBuildError(
                f"Stage 05: atomic landmark {slug!r} has invalid geometry"
            )
        projected = to_work(geom, ctx.region.crs_work)
        clipped = projected.intersection(aoi)
        # Stage 03 intentionally extracts through a clip margin. Atomic source
        # features wholly outside the playable AOI are not carving defects.
        if clipped.is_empty or float(clipped.area) <= FACE_AREA_EPSILON_M2:
            continue
        work = clipped
        work = _as_polygonal(work)
        if work is None or work.is_empty or _is_degenerate(work):
            raise FaceBuildError(
                f"Stage 05: atomic landmark {slug!r} empty/degenerate after clip"
            )
        if not is_valid(work):
            raise FaceBuildError(
                f"Stage 05: atomic landmark {slug!r} invalid after to_work"
            )
        majors.append(
            {
                "geometry": work,
                "properties": {
                    "atomic": True,
                    "protected": bool(props.get("protected")),
                    "role": props.get("role") or "major",
                    "name": props.get("name"),
                    "slug": props.get("slug"),
                    "kind": props.get("kind"),
                    "category": props.get("category"),
                    "source": props.get("source"),
                    "source_id": props.get("source_id"),
                },
            }
        )
    return stable_sort(majors, key=lambda m: str(m["properties"].get("slug") or ""))


def _major_landmarks_work(
    ctx: PipelineContext, aoi: BaseGeometry
) -> list[dict[str, Any]]:
    """Alias kept for tests that monkeypatch the old name."""
    return _atomic_landmarks_work(ctx, aoi)

def _polygonize_aoi(lines: list[LineString], aoi: BaseGeometry) -> list[BaseGeometry]:
    """Close the graph against the AOI ring and keep faces inside the AOI."""
    boundary = LineString(list(aoi.exterior.coords))
    parts: list[BaseGeometry] = list(lines)
    parts.append(boundary)
    if not parts:
        return [_as_polygonal(aoi)] if not aoi.is_empty else []

    noded = unary_union(parts)
    raw_faces = list(polygonize(noded))
    kept: list[BaseGeometry] = []
    for face in raw_faces:
        if face is None or face.is_empty:
            continue
        if not face.intersects(aoi):
            continue
        clipped = face.intersection(aoi)
        for poly in _explode_polygons(clipped):
            if poly.is_empty or _is_degenerate(poly):
                continue
            # Drop exterior leftovers whose mass lies outside the AOI.
            if not aoi.contains(poly.representative_point()):
                continue
            kept.append(poly)

    if not kept:
        # Degenerate graph (no closed rings): the AOI itself is the only face.
        poly = _as_polygonal(aoi)
        return [poly] if poly is not None else []
    return kept


def _carve_majors(
    fabric: list[BaseGeometry],
    majors: list[dict[str, Any]],
    *,
    counters: CleanupCounters,
    max_area_loss_m2: float,
) -> tuple[list[BaseGeometry], list[dict[str, Any]]]:
    """Subtract each major from fabric and collect landmark faces (whole)."""
    remaining = list(fabric)
    landmark_faces: list[dict[str, Any]] = []

    for major in majors:
        landmark_geom = major["geometry"]
        next_remaining: list[BaseGeometry] = []
        for face in remaining:
            if not face.intersects(landmark_geom):
                next_remaining.append(face)
                continue
            diff = face.difference(landmark_geom)
            for piece in _explode_polygons(diff):
                counters.faces_generated += 1
                cleaned = _accept_work_geom(
                    piece,
                    protected=False,
                    counters=counters,
                    source="carve",
                    max_area_loss_m2=max_area_loss_m2,
                )
                if cleaned is not None:
                    next_remaining.append(cleaned)
        remaining = next_remaining
        landmark_faces.append(major)

    return remaining, landmark_faces


def _finalize_feature(
    work_geom: BaseGeometry,
    *,
    props: dict[str, Any],
    protected: bool,
    crs_work: str,
    crs_store: str,
    counters: CleanupCounters,
    max_area_loss_m2: float,
) -> dict[str, Any] | None:
    """Validate work geom, round-trip through storage CRS, validate again."""
    cleaned = _accept_work_geom(
        work_geom,
        protected=protected,
        counters=counters,
        source="landmark" if protected else "carve",
        max_area_loss_m2=max_area_loss_m2,
        count_generated=False,
    )
    if cleaned is None:
        return None

    store = _as_multipolygon(to_store(cleaned, crs_work, crs_store))
    if store is None or store.is_empty:
        if protected:
            raise FaceBuildError("Stage 05: protected landmark empty after to_store")
        counters.post_store_invalid += 1
        counters.dropped_post_store += 1
        counters.dropped_empty += 1
        return None

    # Artifact contract: what we would write must survive read-back.
    try:
        roundtrip = shape(mapping(store))
    except Exception as exc:
        if protected:
            raise FaceBuildError(
                f"Stage 05: protected landmark unreadable after to_store: {exc}"
            ) from exc
        counters.post_store_invalid += 1
        counters.dropped_post_store += 1
        return None

    work_back = to_work(roundtrip, crs_work, crs_store)
    accepted = _accept_work_geom(
        work_back,
        protected=protected,
        counters=counters,
        source="post_store",
        max_area_loss_m2=max_area_loss_m2,
        count_generated=False,
    )
    if accepted is None:
        if protected:
            raise FaceBuildError(
                "Stage 05: protected landmark failed post-store validation"
            )
        counters.post_store_invalid += 1
        return None

    # If round-trip altered the work geom slightly, re-store from accepted.
    if not accepted.equals_exact(cleaned, tolerance=1e-6):
        store = _as_multipolygon(to_store(accepted, crs_work, crs_store))
        if store is None or store.is_empty or not is_valid(store):
            # Prefer writing a valid store geom; repair store without touching protected work.
            if protected:
                raise FaceBuildError(
                    "Stage 05: protected landmark store geometry invalid"
                )
            repaired_store = _repair_polygonal(store or roundtrip, max_area_loss_m2)
            if repaired_store is None:
                counters.post_store_invalid += 1
                counters.dropped_post_store += 1
                return None
            store = _as_multipolygon(repaired_store)
            counters.invalid_repaired += 1

    if not is_valid(store):
        if protected:
            raise FaceBuildError(
                "Stage 05: protected landmark store geometry invalid"
            )
        repaired_store = _repair_polygonal(store, max_area_loss_m2)
        if repaired_store is None or not is_valid(repaired_store):
            counters.post_store_invalid += 1
            counters.dropped_post_store += 1
            counters.invalid_failed += 1
            return None
        store = _as_multipolygon(repaired_store)
        counters.invalid_repaired += 1
        # Confirm work area still sane.
        check = to_work(store, crs_work, crs_store)
        if _is_degenerate(check) or not is_valid(check):
            counters.post_store_invalid += 1
            counters.dropped_post_store += 1
            return None
        accepted = _as_polygonal(check) or accepted

    out_props = dict(props)
    out_props["area_m2"] = round(float(accepted.area), 3)
    if protected:
        out_props["protected"] = True
        out_props["role"] = "major"
    else:
        out_props["protected"] = False
        out_props["kind"] = "fabric"

    return {
        "type": "Feature",
        "geometry": mapping(_as_multipolygon(store)),
        "properties": out_props,
    }


def _accept_work_geom(
    geom: BaseGeometry | None,
    *,
    protected: bool,
    counters: CleanupCounters,
    source: Source,
    max_area_loss_m2: float,
    count_generated: bool = False,
) -> BaseGeometry | None:
    if count_generated:
        counters.faces_generated += 1

    if geom is None or geom.is_empty:
        counters.dropped_empty += 1
        _bump_source_drop(counters, source)
        if protected:
            raise FaceBuildError("Stage 05: protected landmark empty geometry")
        return None

    polygonal = _as_polygonal(geom)
    if polygonal is None or polygonal.is_empty:
        counters.dropped_empty += 1
        _bump_source_drop(counters, source)
        if protected:
            raise FaceBuildError(
                "Stage 05: protected landmark non-polygonal geometry"
            )
        return None

    if _is_degenerate(polygonal):
        counters.dropped_zero_area += 1
        _bump_source_drop(counters, source)
        if protected:
            raise FaceBuildError(
                "Stage 05: protected landmark degenerate (zero-area)"
            )
        return None

    if is_valid(polygonal):
        return polygonal

    if protected:
        counters.invalid_failed += 1
        raise FaceBuildError(
            "Stage 05: protected landmark has invalid geometry "
            "(protected landmarks are never repaired)"
        )

    repaired = _repair_polygonal(polygonal, max_area_loss_m2)
    if repaired is None:
        counters.invalid_failed += 1
        _bump_source_drop(counters, source)
        raise FaceBuildError(
            f"Stage 05: fabric face invalid and unrepaired (source={source})"
        )
    if _is_degenerate(repaired):
        counters.dropped_zero_area += 1
        _bump_source_drop(counters, source)
        return None
    counters.invalid_repaired += 1
    return repaired


def _repair_polygonal(
    work: BaseGeometry, max_area_loss_m2: float
) -> BaseGeometry | None:
    """One-time fabric repair: make_valid, then buffer(0). Area conserved."""
    area_before = float(work.area)
    candidates: list[BaseGeometry] = []
    try:
        candidates.append(make_valid(work))
    except Exception:
        pass
    try:
        candidates.append(work.buffer(0))
    except Exception:
        pass

    for repaired in candidates:
        polygonal = _as_polygonal(repaired)
        if polygonal is None or polygonal.is_empty:
            continue
        if not is_valid(polygonal):
            continue
        if abs(area_before - float(polygonal.area)) > max_area_loss_m2:
            continue
        return polygonal
    return None


def _is_degenerate(geom: BaseGeometry) -> bool:
    if geom is None or geom.is_empty:
        return True
    area = float(geom.area)
    return area <= FACE_AREA_EPSILON_M2 or round(area, 3) == 0


def _bump_source_drop(counters: CleanupCounters, source: Source) -> None:
    if source == "polygonize":
        counters.dropped_polygonize += 1
    elif source == "carve":
        counters.dropped_carve += 1
    elif source == "post_store":
        counters.dropped_post_store += 1


def _assert_artifact_faces_clean(
    features: list[dict[str, Any]], crs_work: str
) -> None:
    for feature in features:
        props = feature.get("properties") or {}
        uid = props.get("face_id") or props.get("slug")
        geom_json = feature.get("geometry")
        if not geom_json:
            raise FaceBuildError(f"Stage 05: output {uid!r} missing geometry")
        geom = shape(geom_json)
        if geom.geom_type not in {"Polygon", "MultiPolygon"}:
            raise FaceBuildError(
                f"Stage 05: output {uid!r} type {geom.geom_type} not polygonal"
            )
        if geom.is_empty or not is_valid(geom):
            raise FaceBuildError(f"Stage 05: output {uid!r} empty/invalid")
        work = to_work(geom, crs_work)
        if _is_degenerate(work) or not is_valid(work):
            raise FaceBuildError(
                f"Stage 05: output {uid!r} degenerate/invalid after to_work"
            )


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


def _stats(
    features: list[dict[str, Any]],
    *,
    aoi_area_m2: float,
    scrap_m2: float,
    counters: CleanupCounters,
) -> FaceBuildStats:
    areas = [float((f.get("properties") or {}).get("area_m2") or 0.0) for f in features]
    protected_count = sum(
        1 for f in features if (f.get("properties") or {}).get("protected") is True
    )
    common = dict(
        faces_generated=counters.faces_generated,
        dropped_empty=counters.dropped_empty,
        dropped_zero_area=counters.dropped_zero_area,
        invalid_repaired=counters.invalid_repaired,
        invalid_failed=counters.invalid_failed,
        post_store_invalid=counters.post_store_invalid,
        dropped_polygonize=counters.dropped_polygonize,
        dropped_carve=counters.dropped_carve,
        dropped_post_store=counters.dropped_post_store,
    )
    if not areas:
        return FaceBuildStats(
            face_count=0,
            protected_count=0,
            fabric_count=0,
            area_min_m2=0.0,
            area_max_m2=0.0,
            area_mean_m2=0.0,
            area_total_m2=0.0,
            scrap_count=0,
            aoi_area_m2=aoi_area_m2,
            **common,
        )
    total = sum(areas)
    return FaceBuildStats(
        face_count=len(areas),
        protected_count=protected_count,
        fabric_count=len(areas) - protected_count,
        area_min_m2=min(areas),
        area_max_m2=max(areas),
        area_mean_m2=total / len(areas),
        area_total_m2=total,
        scrap_count=sum(1 for a in areas if a < scrap_m2),
        aoi_area_m2=aoi_area_m2,
        **common,
    )


def _explode_lines(geom: BaseGeometry) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if geom.geom_type == "MultiLineString":
        return [g for g in geom.geoms if isinstance(g, LineString) and not g.is_empty]
    if geom.geom_type == "GeometryCollection":
        out: list[LineString] = []
        for part in geom.geoms:
            out.extend(_explode_lines(part))
        return out
    return []


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
