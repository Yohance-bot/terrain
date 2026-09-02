"""Route to territory matching, Milestone 1.

Simplified on purpose, and approved as such. `03_MAP_AND_TERRITORY_PIPELINE`
requires H3 lookup, boundary hysteresis and probabilistic segment assignment for
the production system. This implements a strict subset:

    drop inaccurate samples -> build one LineString -> clip against each
    territory polygon in PostGIS -> discard anything below minimum presence

That subset is correct, just incomplete. With ten hand-picked polygons an exact
geometry clip is instantaneous, so the H3 index buys nothing yet, and hysteresis
cannot be tuned before there are real traces to tune it against. Producing those
traces is a deliverable of this milestone.

Every raw payload is retained precisely so this file can be replaced and every
run reprocessed against the better algorithm.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings


@dataclass(frozen=True)
class MatchedSegment:
    territory_id: uuid.UUID
    territory_version: int
    slug: str
    name: str
    distance_m: float
    seconds_in: int
    capture_method: str | None = None


_CLIP_SQL = text(
    """
    SELECT
        t.id       AS territory_id,
        t.version  AS territory_version,
        t.slug     AS slug,
        t.name     AS name,
        ST_Length(
            ST_Intersection(r.geom::geometry, t.geom::geometry)::geography
        ) AS distance_m
    FROM runs r
    JOIN territories t
      ON ST_Intersects(r.geom::geometry, t.geom::geometry)
    WHERE r.id = :run_id
      AND r.geom IS NOT NULL
    """
)

_LOOP_CAPTURE_SQL = text(
    """
    WITH closed_route AS (
        SELECT
            ST_MakePolygon(
                ST_AddPoint(r.geom::geometry, ST_StartPoint(r.geom::geometry))
            ) AS geom
        FROM runs r
        WHERE r.id = :run_id
          AND r.geom IS NOT NULL
          AND ST_Length(r.geom) >= :minimum_distance_m
          AND ST_Distance(
                ST_StartPoint(r.geom::geometry)::geography,
                ST_EndPoint(r.geom::geometry)::geography
              ) <= :closure_distance_m
    )
    SELECT t.id AS territory_id, t.version AS territory_version, t.slug, t.name
    FROM closed_route loop
    JOIN territories t ON ST_Intersects(t.geom::geometry, loop.geom)
    WHERE ST_Area(loop.geom::geography) >= :minimum_area_m2
    """
)

_CREATE_CAPTURED_AREA_SQL = text(
    """
    INSERT INTO captured_areas (id, run_id, owner_device_id, geom)
    SELECT :area_id, r.id, :device_id,
      ST_MakePolygon(ST_AddPoint(r.geom::geometry, ST_StartPoint(r.geom::geometry)))::geography
    FROM runs r
    WHERE r.id = :run_id
      AND r.geom IS NOT NULL
      AND ST_Length(r.geom) >= :minimum_distance_m
      AND ST_Distance(ST_StartPoint(r.geom::geometry)::geography, ST_EndPoint(r.geom::geometry)::geography)
          <= :closure_distance_m
      AND ST_Area(ST_MakePolygon(ST_AddPoint(r.geom::geometry, ST_StartPoint(r.geom::geometry)))::geography)
          >= :minimum_area_m2
    ON CONFLICT (run_id) DO NOTHING
    """
)


def match_run(session: Session, run_id: uuid.UUID, duration_s: int) -> list[MatchedSegment]:
    """Return the territories a run passed through and how far inside each it went."""
    rows = session.execute(_CLIP_SQL, {"run_id": run_id}).mappings().all()

    # This prototype apportions run time by clipped distance. The persisted raw
    # samples make replacing this with timestamped per-segment presence possible
    # without changing the downstream influence contract.
    total_inside = sum(float(r["distance_m"] or 0) for r in rows)

    segments: list[MatchedSegment] = []
    for row in rows:
        distance = float(row["distance_m"])
        seconds = int(duration_s * distance / total_inside) if total_inside > 0 else 0
        # A valid direct run earns normal standing too. These limits only filter
        # zero/near-zero geometry; a loop is not required for leaderboard
        # presence or ordinary influence.
        if distance < settings.min_presence_m or seconds < settings.min_presence_s:
            continue
        segments.append(
            MatchedSegment(
                territory_id=row["territory_id"],
                territory_version=row["territory_version"],
                slug=row["slug"],
                name=row["name"],
                distance_m=round(distance, 2),
                seconds_in=seconds,
            )
        )

    segments.sort(key=lambda s: s.distance_m, reverse=True)
    return segments


def match_loop_capture_territories(session: Session, run_id: uuid.UUID) -> list[MatchedSegment]:
    """Find territories touched by a server-validated closed route.

    This deliberately rebuilds the polygon from the stored server route rather
    than trusting the candidate IDs displayed by the phone during the run.
    """
    rows = session.execute(
        _LOOP_CAPTURE_SQL,
        {
            "run_id": run_id,
            "minimum_distance_m": settings.loop_min_distance_m,
            "closure_distance_m": settings.loop_closure_distance_m,
            "minimum_area_m2": settings.loop_min_area_m2,
        },
    ).mappings().all()
    return [
        MatchedSegment(
            territory_id=row["territory_id"],
            territory_version=row["territory_version"],
            slug=row["slug"],
            name=row["name"],
            # The route may not cross an enclosed territory. Zero accurately
            # records that fact; the capture grant is recorded separately.
            distance_m=0,
            seconds_in=0,
            capture_method="loop",
        )
        for row in rows
    ]


def create_public_captured_area(session: Session, run_id: uuid.UUID, device_id: uuid.UUID) -> None:
    """Persist one server-validated public loop polygon, idempotently."""
    session.execute(
        _CREATE_CAPTURED_AREA_SQL,
        {
            "area_id": uuid.uuid4(),
            "run_id": run_id,
            "device_id": device_id,
            "minimum_distance_m": settings.loop_min_distance_m,
            "closure_distance_m": settings.loop_closure_distance_m,
            "minimum_area_m2": settings.loop_min_area_m2,
        },
    )
