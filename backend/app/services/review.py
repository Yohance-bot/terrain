"""Restricted operations workflows for manual run review decisions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, InfluenceGrant, Run, RunLifecycleEvent
from app.services.ownership import recompute_ownership

REVIEWABLE_STATUSES = ("provisional", "challenged")
REVERSIBLE_STATUSES = ("applied", "provisional", "challenged")


@dataclass(frozen=True)
class ReversalOutcome:
    run_id: uuid.UUID
    rebuilt_territory_ids: list[uuid.UUID]


def review_queue(session: Session, device_id: uuid.UUID) -> list[Run]:
    """Return only the requested device's unresolved internal review runs."""

    return list(
        session.execute(
            select(Run)
            .where(Run.device_id == device_id, Run.status.in_(REVIEWABLE_STATUSES))
            .order_by(Run.created_at.asc(), Run.id.asc())
        ).scalars()
    )


def reverse_run(
    session: Session,
    *,
    run_id: uuid.UUID,
    operator_ref: str,
    reason: str,
) -> ReversalOutcome:
    """Reverse one run, retain its evidence, and rebuild its affected standings.

    The caller owns the database transaction. A reversal changes no immutable
    route, segment, or grant evidence; the authoritative rebuild excludes the
    reversed run by status and replaces derived standings.
    """

    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in REVERSIBLE_STATUSES:
        raise HTTPException(status_code=409, detail="Run cannot be reversed")

    before_state = {"status": run.status, "lifecycle_version": run.lifecycle_version}
    territory_ids = sorted(
        set(
            session.execute(
                select(InfluenceGrant.territory_id).where(InfluenceGrant.run_id == run.id)
            ).scalars()
        ),
        key=str,
    )
    previous_status = run.status
    run.status = "reversed"
    run.lifecycle_version += 1
    session.add(
        RunLifecycleEvent(
            run_id=run.id,
            sequence=run.lifecycle_version,
            from_status=previous_status,
            to_status="reversed",
            actor_kind="admin",
            actor_ref=operator_ref,
            reason=reason,
        )
    )
    session.add(
        AuditEvent(
            actor_kind="admin",
            actor_ref=operator_ref,
            action="run.reversed",
            target_type="run",
            target_ref=str(run.id),
            before_state=before_state,
            after_state={"status": "reversed", "lifecycle_version": run.lifecycle_version},
            reason=reason,
            details={
                "rebuilt_territory_ids": [str(territory_id) for territory_id in territory_ids]
            },
        )
    )
    session.flush()
    for territory_id in territory_ids:
        recompute_ownership(session, territory_id)
    session.flush()
    return ReversalOutcome(run_id=run.id, rebuilt_territory_ids=territory_ids)
