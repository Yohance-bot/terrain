"""Building a ghost from a finished run, and serving it safely.

The path is derived from the server's own geometry and sample timestamps, never
from anything the client asserts — a ghost is a benchmark other people race
against, so its pacing has to come from the same evidence a run's distance does.
"""

import json
import math
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from geoalchemy2 import Geometry
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GhostAttempt, GhostRun, Run
from app.services.races import metres_between

# A public ghost starts and ends where its runner started and ended, which for
# most people is their front door. Both ends are trimmed before anyone else sees
# the route.
PUBLIC_TRIM_M = 150.0

# Bounding box for "ghosts near me". Generous enough to be useful on foot,
# small enough that the map is not a directory of everyone's routes.
MAX_NEARBY_RADIUS_M = 5_000.0
DEGREES_PER_M = 1 / 111_320.0


def build_path(session: Session, run: Run) -> list[list[float]]:
    """Positions with millisecond offsets from the start of the run.

    `sample_ts` is written alongside the line's vertices in the same order, so
    the two zip together directly.
    """
    # Read the geometry back through the column rather than the instance: the
    # attribute may still hold the WKT the ingest path assigned to it.
    geojson = session.execute(
        select(func.ST_AsGeoJSON(Run.geom.cast(Geometry(geometry_type="GEOMETRY", srid=4326))))
        .where(Run.id == run.id)
    ).scalar_one_or_none()
    if not geojson:
        raise HTTPException(422, "That run has no route to save as a ghost.")

    coordinates = json.loads(geojson).get("coordinates") or []
    stamps = run.sample_ts or []
    if len(coordinates) < 2 or len(stamps) < len(coordinates):
        raise HTTPException(422, "That run has no route to save as a ghost.")

    origin = stamps[0]
    return [
        [float(lon), float(lat), float(stamps[index] - origin)]
        for index, (lon, lat) in enumerate(coordinates)
    ]


def trim_for_public(path: list[list[float]]) -> list[list[float]]:
    """Drop the first and last stretch of a route before showing it to strangers."""
    if len(path) < 4:
        return []
    start_lon, start_lat = path[0][0], path[0][1]
    end_lon, end_lat = path[-1][0], path[-1][1]

    def near(point: list[float], lat: float, lon: float) -> bool:
        return metres_between(lat, lon, point[1], point[0]) < PUBLIC_TRIM_M

    first = 0
    while first < len(path) and near(path[first], start_lat, start_lon):
        first += 1
    last = len(path) - 1
    while last > first and near(path[last], end_lat, end_lon):
        last -= 1

    trimmed = path[first : last + 1]
    # A route shorter than the trim on both ends has nothing left to show.
    return trimmed if len(trimmed) >= 2 else []


def visible_path(ghost: GhostRun, viewer_id: uuid.UUID) -> list[list[float]]:
    """Owners see their own route in full; everyone else sees it trimmed."""
    if ghost.account_id == viewer_id:
        return ghost.path
    return trim_for_public(ghost.path)


def nearby(session: Session, lat: float, lon: float, radius_m: float) -> list[GhostRun]:
    """Public ghosts whose start lies within the radius.

    Only public ones: a ghost is opt-in to be found, and a friend's private
    benchmark is not a thing to stumble across on the map.
    """
    radius_m = min(radius_m, MAX_NEARBY_RADIUS_M)
    span = radius_m * DEGREES_PER_M
    # Longitude degrees shrink towards the poles; widening the box keeps the
    # candidate set correct before the exact distance filter below.
    lon_span = span / max(math.cos(math.radians(lat)), 0.01)

    candidates = session.execute(
        select(GhostRun).where(
            GhostRun.is_public.is_(True),
            GhostRun.start_lat.between(lat - span, lat + span),
            GhostRun.start_lon.between(lon - lon_span, lon + lon_span),
        )
    ).scalars()
    found = [
        ghost
        for ghost in candidates
        if metres_between(lat, lon, ghost.start_lat, ghost.start_lon) <= radius_m
    ]
    found.sort(key=lambda ghost: metres_between(lat, lon, ghost.start_lat, ghost.start_lon))
    return found


def best_time(session: Session, ghost_id: uuid.UUID) -> int | None:
    return session.execute(
        select(func.min(GhostAttempt.elapsed_s)).where(
            GhostAttempt.ghost_id == ghost_id, GhostAttempt.elapsed_s.is_not(None)
        )
    ).scalar_one_or_none()


def finish_attempt(
    session: Session, attempt: GhostAttempt, ghost: GhostRun, elapsed_s: int
) -> GhostAttempt:
    attempt.finished_at = datetime.now(UTC)
    attempt.elapsed_s = elapsed_s
    attempt.beat_ghost = elapsed_s < ghost.duration_s
    return attempt
