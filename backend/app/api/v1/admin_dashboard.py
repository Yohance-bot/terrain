"""Read-only operational dashboard endpoints."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_operations_token
from app.core.db import get_session
from app.models import (
    Account,
    AuditEvent,
    Device,
    DeviceLink,
    Run,
    Territory,
    TerritoryOwnership,
)
from app.schemas import AuditEventRecord

router = APIRouter(
    prefix="/admin/dashboard",
    tags=["internal-admin-dashboard"],
    dependencies=[Depends(require_admin_operations_token)],
)


class DashboardStats(BaseModel):
    total_territories: int
    total_runs: int
    total_accounts: int
    total_devices: int
    active_owners: int


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(session: Session = Depends(get_session)) -> DashboardStats:
    total_territories = session.execute(select(func.count(Territory.id))).scalar() or 0
    total_runs = session.execute(select(func.count(Run.id))).scalar() or 0
    total_accounts = session.execute(select(func.count(Account.id))).scalar() or 0
    total_devices = session.execute(select(func.count(Device.id))).scalar() or 0
    active_owners = session.execute(
        select(func.count(func.distinct(TerritoryOwnership.owner_device_id)))
        .where(TerritoryOwnership.owner_device_id.is_not(None))
    ).scalar() or 0

    return DashboardStats(
        total_territories=total_territories,
        total_runs=total_runs,
        total_accounts=total_accounts,
        total_devices=total_devices,
        active_owners=active_owners,
    )


class AdminPlayerSummary(BaseModel):
    account_id: uuid.UUID
    display_name: str
    role: str
    created_at: datetime
    device_id: uuid.UUID | None
    total_distance_m: float
    territories_led: int


class AdminPlayersResponse(BaseModel):
    items: list[AdminPlayerSummary]
    total: int


@router.get("/players", response_model=AdminPlayersResponse)
def list_players(
    limit: int = 50, offset: int = 0, session: Session = Depends(get_session)
) -> AdminPlayersResponse:
    total = session.execute(select(func.count(Account.id))).scalar() or 0

    rows = session.execute(
        select(Account, DeviceLink.device_id)
        .outerjoin(DeviceLink, DeviceLink.account_id == Account.id)
        .order_by(Account.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    items = []
    for account, device_id in rows:
        distance = 0.0
        led = 0
        if device_id:
            distance = session.execute(
                select(func.coalesce(func.sum(Run.distance_m), 0)).where(Run.device_id == device_id)
            ).scalar() or 0.0
            led = session.execute(
                select(func.count(TerritoryOwnership.territory_id)).where(
                    TerritoryOwnership.owner_device_id == device_id
                )
            ).scalar() or 0

        items.append(
            AdminPlayerSummary(
                account_id=account.id,
                display_name=account.display_name,
                role=account.role,
                created_at=account.created_at,
                device_id=device_id,
                total_distance_m=float(distance),
                territories_led=int(led),
            )
        )

    return AdminPlayersResponse(items=items, total=total)


class AdminRunSummary(BaseModel):
    run_id: uuid.UUID
    device_id: uuid.UUID
    display_name: str | None
    status: str
    started_at: datetime
    distance_m: float


class AdminRunsResponse(BaseModel):
    items: list[AdminRunSummary]
    total: int


@router.get("/runs", response_model=AdminRunsResponse)
def list_runs(
    limit: int = 50, offset: int = 0, session: Session = Depends(get_session)
) -> AdminRunsResponse:
    total = session.execute(select(func.count(Run.id))).scalar() or 0

    rows = session.execute(
        select(Run, Account.display_name)
        .outerjoin(DeviceLink, DeviceLink.device_id == Run.device_id)
        .outerjoin(Account, Account.id == DeviceLink.account_id)
        .order_by(Run.started_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    items = [
        AdminRunSummary(
            run_id=run.id,
            device_id=run.device_id,
            display_name=display_name,
            status=run.status,
            started_at=run.started_at,
            distance_m=float(run.distance_m),
        )
        for run, display_name in rows
    ]

    return AdminRunsResponse(items=items, total=total)


class AuditEventResponseItem(BaseModel):
    id: int
    actor_kind: str
    actor_ref: str | None
    action: str
    target_type: str
    target_ref: str
    created_at: datetime
    reason: str | None


class AdminAuditEventsResponse(BaseModel):
    items: list[AuditEventResponseItem]
    total: int


@router.get("/audit-events", response_model=AdminAuditEventsResponse)
def list_audit_events(
    limit: int = 50, offset: int = 0, session: Session = Depends(get_session)
) -> AdminAuditEventsResponse:
    total = session.execute(select(func.count(AuditEvent.id))).scalar() or 0

    rows = session.execute(
        select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)
    ).scalars().all()

    items = [
        AuditEventResponseItem(
            id=event.id,
            actor_kind=event.actor_kind,
            actor_ref=event.actor_ref,
            action=event.action,
            target_type=event.target_type,
            target_ref=event.target_ref,
            created_at=event.created_at,
            reason=event.reason,
        )
        for event in rows
    ]

    return AdminAuditEventsResponse(items=items, total=total)
