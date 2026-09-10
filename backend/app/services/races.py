"""Starting, watching and ending a pin-drop race.

Arrival is detected from the position a player is already reporting, so nobody
has to press anything on arrival — and nobody has to look at their phone to win.
"""

import math
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Account, Race
from app.services.social import (
    grant_temporary_location,
    record_event,
    revoke_temporary_location,
)

# Close enough counts. A tighter radius would have people circling a lamp post
# staring at a screen, which is exactly what the safety rules forbid.
DEFAULT_ARRIVAL_RADIUS_M = 25.0

# How long a race stays live once accepted. Past this it lapses quietly: an
# abandoned race must never turn into a loss notification.
RACE_DURATION = timedelta(hours=2)
DEFAULT_ACCEPT_WINDOW = timedelta(minutes=30)

EARTH_RADIUS_M = 6_371_000.0


def metres_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance. Exact enough at the scale of a city block."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def open_races_for(session: Session, account_id: uuid.UUID) -> list[Race]:
    return list(
        session.execute(
            select(Race).where(
                Race.status == "running",
                or_(Race.challenger_id == account_id, Race.opponent_id == account_id),
            )
        ).scalars()
    )


def start(session: Session, race: Race, *, now: datetime | None = None) -> Race:
    """Accept a race: both sides can see each other until it ends."""
    now = now or datetime.now(UTC)
    race.status = "running"
    race.started_at = now
    race.expires_at = now + RACE_DURATION
    race.updated_at = now
    grant_temporary_location(session, race.challenger_id, race.opponent_id, race.expires_at)
    grant_temporary_location(session, race.opponent_id, race.challenger_id, race.expires_at)
    return race


def _end_sharing(session: Session, race: Race) -> None:
    revoke_temporary_location(session, race.challenger_id, race.opponent_id)
    revoke_temporary_location(session, race.opponent_id, race.challenger_id)


def finish(
    session: Session, race: Race, winner_id: uuid.UUID, *, now: datetime | None = None
) -> Race:
    now = now or datetime.now(UTC)
    race.status = "finished"
    race.winner_id = winner_id
    race.finished_at = now
    race.updated_at = now
    _end_sharing(session, race)

    winner = session.get(Account, winner_id)
    loser_id = race.opponent_id if winner_id == race.challenger_id else race.challenger_id
    if winner is not None:
        record_event(
            session,
            loser_id,
            "race_finished",
            f"{winner.display_name} reached the pin first.",
            actor_id=winner_id,
            subject_id=race.id,
        )
        record_event(
            session,
            winner_id,
            "race_finished",
            "You reached the pin first.",
            subject_id=race.id,
        )
    return race


def abandon(session: Session, race: Race, status: str, *, now: datetime | None = None) -> Race:
    """End a race without a winner. Used for expiry, decline and cancellation."""
    race.status = status
    race.updated_at = now or datetime.now(UTC)
    _end_sharing(session, race)
    return race


def check_arrival(
    session: Session, account_id: uuid.UUID, lat: float, lon: float
) -> Race | None:
    """Settle any running race this position wins.

    Called from the position report the client already sends, so arriving is
    something that happens to a runner rather than something they must do.
    """
    for race in open_races_for(session, account_id):
        if metres_between(lat, lon, race.pin_lat, race.pin_lon) <= race.radius_m:
            return finish(session, race, account_id)
    return None


def expire_due(session: Session, *, now: datetime | None = None) -> int:
    """Lapse unanswered and abandoned races. Nobody is told they lost."""
    now = now or datetime.now(UTC)
    stale = list(
        session.execute(
            select(Race).where(
                or_(
                    (Race.status == "pending") & (Race.accept_deadline <= now),
                    (Race.status == "running") & (Race.expires_at <= now),
                )
            )
        ).scalars()
    )
    for race in stale:
        abandon(session, race, "expired", now=now)
    return len(stale)
