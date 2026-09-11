"""Territory standings, and the operator's ability to change who holds ground.

Ownership is derived, not stored: `services/ownership.recompute_ownership`
rebuilds `territory_ownership` from the influence ledger every time a run lands
there. So an operator handing a territory to someone cannot simply write the
owner row — the next applied run in that territory would quietly undo it.

Assignment therefore writes to the ledger itself, through a synthetic run that
carries no geometry. It is durable for the same reason a real capture is, it is
visible in the same places a real capture is, and it is audited.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_operations_token
from app.core.config import settings
from app.core.db import get_session
from app.models import (
    Account,
    AuditEvent,
    DeviceLink,
    InfluenceGrant,
    Run,
    RunLifecycleEvent,
    SandboxAccount,
    Territory,
    TerritoryOwnership,
    TerritoryStanding,
)
from app.services.ownership import recompute_ownership

router = APIRouter(
    prefix="/admin/territory",
    tags=["internal-admin-territory"],
    dependencies=[Depends(require_admin_operations_token)],
)


class TerritoryStandingSummary(BaseModel):
    territory_id: uuid.UUID
    name: str
    slug: str
    kind: str
    owner_device_id: uuid.UUID | None
    owner_name: str | None
    contenders: int
    leader_distance_m: float
    total_active_influence: float


class StandingsPage(BaseModel):
    items: list[TerritoryStandingSummary]
    total: int
    contested: int


@router.get("/standings", response_model=StandingsPage)
def standings(
    only_contested: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
) -> StandingsPage:
    """Territories that actually have someone standing in them.

    Most of a city has never been run through. Listing all several hundred
    territories buries the handful that are live, which is why the default hides
    the empty ones — the console's problem was never that standings were
    missing, it was that you had to guess which territory had any.
    """
    aggregate = (
        select(
            TerritoryStanding.territory_id.label("territory_id"),
            func.count().label("contenders"),
            func.max(TerritoryStanding.total_distance_m).label("leader_distance_m"),
            func.sum(TerritoryStanding.active_influence).label("total_active_influence"),
        )
        .where(TerritoryStanding.total_distance_m > 0)
        .group_by(TerritoryStanding.territory_id)
        .subquery()
    )

    statement = (
        select(
            Territory,
            TerritoryOwnership.owner_device_id,
            Account.display_name,
            aggregate.c.contenders,
            aggregate.c.leader_distance_m,
            aggregate.c.total_active_influence,
        )
        .outerjoin(TerritoryOwnership, TerritoryOwnership.territory_id == Territory.id)
        .outerjoin(DeviceLink, DeviceLink.device_id == TerritoryOwnership.owner_device_id)
        .outerjoin(Account, Account.id == DeviceLink.account_id)
        .where(Territory.city == settings.territory_city, Territory.area == settings.territory_area)
    )
    join_type = statement.join(aggregate, aggregate.c.territory_id == Territory.id)
    statement = (
        join_type
        if only_contested
        else statement.outerjoin(aggregate, aggregate.c.territory_id == Territory.id)
    )

    rows = session.execute(
        statement.order_by(aggregate.c.leader_distance_m.desc().nullslast(), Territory.name).limit(
            limit
        )
    ).all()

    total = session.execute(
        select(func.count())
        .select_from(Territory)
        .where(Territory.city == settings.territory_city, Territory.area == settings.territory_area)
    ).scalar_one()
    contested = session.execute(select(func.count()).select_from(aggregate)).scalar_one()

    return StandingsPage(
        items=[
            TerritoryStandingSummary(
                territory_id=territory.id,
                name=territory.name,
                slug=territory.slug,
                kind=territory.kind,
                owner_device_id=owner_id,
                owner_name=owner_name,
                contenders=int(contenders or 0),
                leader_distance_m=float(leader or 0),
                total_active_influence=round(float(influence or 0), 2),
            )
            for territory, owner_id, owner_name, contenders, leader, influence in rows
        ],
        total=int(total or 0),
        contested=int(contested or 0),
    )


class TerritoryAssignment(BaseModel):
    """Hand a territory to an account, or clear it entirely."""

    account_id: uuid.UUID | None = None
    reason: str = Field(min_length=3, max_length=512)


class AssignmentResult(BaseModel):
    territory_id: uuid.UUID
    previous_owner_id: uuid.UUID | None
    owner_device_id: uuid.UUID | None
    changed: bool


def _operator(request: Request) -> str:
    user = getattr(request.state, "admin_user", None)
    return str(user.id) if user is not None else "admin-console"


@router.post("/{territory_id}/assign", response_model=AssignmentResult)
def assign(
    territory_id: uuid.UUID,
    payload: TerritoryAssignment,
    request: Request,
    session: Session = Depends(get_session),
) -> AssignmentResult:
    """Make an account the holder of a territory, durably.

    Passing no account clears the ledger for this territory instead, which
    returns it to unclaimed.
    """
    territory = session.get(Territory, territory_id)
    if territory is None:
        raise HTTPException(404, "No such territory.")

    if payload.account_id is None:
        for grant in session.execute(
            select(InfluenceGrant).where(InfluenceGrant.territory_id == territory_id)
        ).scalars():
            session.delete(grant)
        session.flush()
        outcome = recompute_ownership(session, territory_id)
        _audit(session, request, territory_id, None, payload.reason, "territory.cleared")
        return AssignmentResult(
            territory_id=territory_id,
            previous_owner_id=outcome.previous_owner_id,
            owner_device_id=outcome.owner_id,
            changed=outcome.changed,
        )

    device_id = session.execute(
        select(DeviceLink.device_id)
        .where(DeviceLink.account_id == payload.account_id)
        .order_by(DeviceLink.linked_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if device_id is None:
        raise HTTPException(422, "That account has no device to hold ground with.")

    # Enough to lead whoever is currently ahead, with headroom so decay on the
    # existing leader does not flip it back within the hour.
    leading = session.execute(
        select(func.coalesce(func.max(TerritoryStanding.active_influence), 0)).where(
            TerritoryStanding.territory_id == territory_id
        )
    ).scalar_one()
    influence = float(leading or 0) * 1.5 + 100

    now = datetime.now(UTC)
    run = Run(
        id=uuid.uuid4(),
        device_id=device_id,
        started_at=now - timedelta(minutes=30),
        ended_at=now,
        duration_s=1800,
        distance_m=0,
        raw_payload={"operator_assignment": True, "territory_id": str(territory_id)},
        status="applied",
        source="tracked",
        pipeline_version=settings.pipeline_version,
    )
    session.add(run)
    session.flush()
    session.add(
        RunLifecycleEvent(
            run_id=run.id,
            sequence=1,
            from_status=None,
            to_status="applied",
            actor_kind="admin",
            actor_ref=_operator(request),
            reason=payload.reason,
        )
    )
    session.add(
        InfluenceGrant(
            run_id=run.id,
            device_id=device_id,
            territory_id=territory_id,
            territory_version=territory.version,
            pipeline_version=settings.pipeline_version,
            ruleset_version=settings.ruleset_version,
            activity="operator",
            distance_m=0,
            moving_time_s=0,
            effort=influence,
            active_influence=influence,
            legacy_influence=0,
            half_life_days=settings.default_decay_half_life_days,
            granted_at=now,
        )
    )
    session.flush()
    outcome = recompute_ownership(session, territory_id)
    _audit(session, request, territory_id, device_id, payload.reason, "territory.assigned")

    return AssignmentResult(
        territory_id=territory_id,
        previous_owner_id=outcome.previous_owner_id,
        owner_device_id=outcome.owner_id,
        changed=outcome.changed,
    )


def _audit(
    session: Session,
    request: Request,
    territory_id: uuid.UUID,
    device_id: uuid.UUID | None,
    reason: str,
    action: str,
) -> None:
    session.add(
        AuditEvent(
            actor_kind="admin",
            actor_ref=_operator(request),
            action=action,
            target_type="territory",
            target_ref=str(territory_id),
            reason=reason,
            details={"owner_device_id": str(device_id) if device_id else None},
        )
    )


class AssignableAccount(BaseModel):
    account_id: uuid.UUID
    display_name: str
    is_test_runner: bool


@router.get("/assignable", response_model=list[AssignableAccount])
def assignable(session: Session = Depends(get_session)) -> list[AssignableAccount]:
    """Accounts an operator can hand a territory to: anyone with a device."""
    sandbox = set(session.execute(select(SandboxAccount.account_id)).scalars())
    rows = session.execute(
        select(Account.id, Account.display_name)
        .join(DeviceLink, DeviceLink.account_id == Account.id)
        .group_by(Account.id, Account.display_name)
        .order_by(Account.display_name)
    ).all()
    return [
        AssignableAccount(
            account_id=account_id, display_name=name, is_test_runner=account_id in sandbox
        )
        for account_id, name in rows
    ]
