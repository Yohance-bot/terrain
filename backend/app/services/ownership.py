"""Rebuild active and Legacy standings from immutable influence grants."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import InfluenceGrant, Run, TerritoryOwnership, TerritoryStanding
from app.services.influence import InfluenceTuning, decay_active_influence, territory_is_abandoned


@dataclass(frozen=True)
class OwnershipOutcome:
    territory_id: uuid.UUID
    previous_owner_id: uuid.UUID | None
    owner_id: uuid.UUID | None
    changed: bool


def _tuning() -> InfluenceTuning:
    return InfluenceTuning(abandonment_floor=settings.abandonment_floor)


def recompute_ownership(
    session: Session, territory_id: uuid.UUID, *, as_of: datetime | None = None
) -> OwnershipOutcome:
    """Rebuild a territory's standings and ownership from applied grants.

    The standing cache is intentionally overwritten rather than incremented:
    decay and reversals make accumulation incorrect. A future materialized
    rollup can optimize this query without changing its authoritative inputs.
    """
    now = as_of or datetime.now(UTC)
    grants = session.execute(
        select(InfluenceGrant)
        .join(Run, Run.id == InfluenceGrant.run_id)
        .where(InfluenceGrant.territory_id == territory_id, Run.status == "applied")
    ).scalars()

    totals: dict[uuid.UUID, tuple[float, float, float]] = {}
    for grant in grants:
        elapsed_days = max((now - grant.granted_at).total_seconds() / 86_400, 0)
        active = decay_active_influence(
            active_influence=float(grant.active_influence),
            elapsed_days=elapsed_days,
            half_life_days=float(grant.half_life_days),
        )
        previous = totals.get(grant.device_id, (0.0, 0.0, 0.0))
        totals[grant.device_id] = (
            previous[0] + active,
            previous[1] + float(grant.legacy_influence),
            previous[2] + float(grant.distance_m),
        )

    existing = {
        standing.device_id: standing
        for standing in session.execute(
            select(TerritoryStanding).where(TerritoryStanding.territory_id == territory_id)
        ).scalars()
    }
    for device_id, (active, legacy, distance) in totals.items():
        standing = existing.pop(device_id, None)
        if standing is None:
            standing = TerritoryStanding(territory_id=territory_id, device_id=device_id)
            session.add(standing)
        standing.active_influence = active
        standing.legacy_influence = legacy
        standing.total_distance_m = distance
        standing.updated_at = now
    for standing in existing.values():
        standing.active_influence = 0
        standing.legacy_influence = 0
        standing.total_distance_m = 0
        standing.updated_at = now

    total_active = sum(active for active, _, _ in totals.values())
    leader = None
    if not territory_is_abandoned(total_active=total_active, tuning=_tuning()):
        leader = max(
            totals,
            key=lambda device_id: (totals[device_id][0], str(device_id)),
            default=None,
        )

    record = session.get(TerritoryOwnership, territory_id)
    previous_owner = record.owner_device_id if record else None

    if record is None:
        record = TerritoryOwnership(territory_id=territory_id, owner_device_id=leader)
        session.add(record)
    elif previous_owner != leader:
        record.previous_owner_id = previous_owner
        record.owner_device_id = leader
        record.since = now

    return OwnershipOutcome(
        territory_id=territory_id,
        previous_owner_id=previous_owner,
        owner_id=leader,
        changed=previous_owner != leader,
    )
