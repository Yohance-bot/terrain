"""Read-only operational dashboard endpoints."""

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import require_admin_operations_token, resolve_device
from app.api.v1.accounts import DEVELOPER_DEVICE_IDS, account_for_device
from app.core.config import settings
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
from app.schemas import ManualRunReversal, RunResult, RunSubmission
from app.services.ingest import build_result, process_run
from app.services.ownership import recompute_ownership

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
    active_owners = (
        session.execute(
            select(func.count(func.distinct(TerritoryOwnership.owner_device_id))).where(
                TerritoryOwnership.owner_device_id.is_not(None)
            )
        ).scalar()
        or 0
    )

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
    device_ids: list[uuid.UUID]
    total_distance_m: float
    territories_led: int


class AdminPlayersResponse(BaseModel):
    items: list[AdminPlayerSummary]
    total: int


@router.get("/players", response_model=AdminPlayersResponse)
def list_players(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> AdminPlayersResponse:
    total = session.execute(select(func.count(Account.id))).scalar() or 0

    # Page accounts first. Joining devices before LIMIT duplicates multi-device
    # runners and silently drops accounts from pages. Aggregate each ledger once.
    accounts = session.scalars(
        select(Account).order_by(Account.created_at.desc(), Account.id).limit(limit).offset(offset)
    ).all()
    ids = [account.id for account in accounts]
    links = session.execute(
        select(DeviceLink.account_id, DeviceLink.device_id).where(DeviceLink.account_id.in_(ids))
    ).all()
    distances = dict(
        session.execute(
            select(DeviceLink.account_id, func.sum(Run.distance_m))
            .join(Run, Run.device_id == DeviceLink.device_id)
            .where(DeviceLink.account_id.in_(ids))
            .group_by(DeviceLink.account_id)
        ).all()
    )
    leaders = dict(
        session.execute(
            select(DeviceLink.account_id, func.count(TerritoryOwnership.territory_id))
            .join(TerritoryOwnership, TerritoryOwnership.owner_device_id == DeviceLink.device_id)
            .where(DeviceLink.account_id.in_(ids))
            .group_by(DeviceLink.account_id)
        ).all()
    )
    devices: dict[uuid.UUID, list[uuid.UUID]] = {}
    for account_id, device_id in links:
        devices.setdefault(account_id, []).append(device_id)
    items = [
        AdminPlayerSummary(
            account_id=account.id,
            display_name=account.display_name,
            role=account.role,
            created_at=account.created_at,
            device_id=next(iter(devices.get(account.id, [])), None),
            device_ids=devices.get(account.id, []),
            total_distance_m=float(distances.get(account.id, 0)),
            territories_led=leaders.get(account.id, 0),
        )
        for account in accounts
    ]

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
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
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
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> AdminAuditEventsResponse:
    total = session.execute(select(func.count(AuditEvent.id))).scalar() or 0

    rows = (
        session.execute(
            select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)
        )
        .scalars()
        .all()
    )

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


@router.get("/system")
def system_status(session: Session = Depends(get_session)) -> dict:
    session.execute(text("SELECT 1"))
    fields = (
        "developer_mode_enabled",
        "local_accounts_enabled",
        "territory_city",
        "territory_area",
        "max_accuracy_m",
        "min_presence_m",
        "loop_min_distance_m",
        "loop_closure_distance_m",
        "loop_min_area_m2",
        "pipeline_version",
        "ruleset_version",
        "raw_trace_retention_days",
    )
    return {
        "database": "connected",
        "configuration": {key: getattr(settings, key) for key in fields},
        "simulation_slots": [
            {"slot": i + 1, "device_id": str(device_id)}
            for i, device_id in enumerate(DEVELOPER_DEVICE_IDS)
        ],
    }


@router.get("/runs/{run_id}")
def run_detail(run_id: uuid.UUID, session: Session = Depends(get_session)) -> dict:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    geometry = session.scalar(select(func.ST_AsGeoJSON(Run.geom)).where(Run.id == run_id))
    return {
        "result": build_result(session, run).model_dump(mode="json"),
        "geometry": json.loads(geometry) if geometry else None,
        "device_id": str(run.device_id),
        "source": run.source,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "route_reduced": run.route_reduced_at is not None,
        "simulation": bool(
            session.scalar(
                select(AuditEvent.id)
                .where(AuditEvent.action == "run.simulated", AuditEvent.target_ref == str(run.id))
                .limit(1)
            )
        ),
    }


class AdminSimulation(BaseModel):
    slot: int = Field(ge=1, le=3)
    operator_ref: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=512)
    run: RunSubmission


@router.post("/simulate", response_model=RunResult)
def simulate_run(
    payload: AdminSimulation, request: Request, session: Session = Depends(get_session)
) -> RunResult:
    if not settings.developer_mode_enabled:
        raise HTTPException(403, "Developer simulation is disabled")
    device_id = DEVELOPER_DEVICE_IDS[payload.slot - 1]
    account = account_for_device(session, device_id)
    if account is None or account.role != "developer":
        raise HTTPException(409, "Sign in to this developer slot in the app first")
    if not 2 <= len(payload.run.samples) <= 3600:
        raise HTTPException(422, "Simulation requires 2–3600 samples")
    samples = payload.run.samples
    if any(a.ts >= b.ts for a, b in zip(samples, samples[1:], strict=False)):
        raise HTTPException(422, "Simulation timestamps must increase")
    if payload.run.ended_at <= payload.run.started_at:
        raise HTTPException(422, "Simulation end must follow its start")
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(str(payload.run.run_id)))))
    existing = session.get(Run, payload.run.run_id)
    if existing is not None:
        audited = session.scalar(
            select(AuditEvent.id)
            .where(AuditEvent.action == "run.simulated", AuditEvent.target_ref == str(existing.id))
            .limit(1)
        )
        if existing.device_id != device_id or not audited:
            raise HTTPException(409, "Run ID is already in use")
        return build_result(session, existing)
    # The authenticated developer fixture uses the same scoring pipeline as the
    # phone joystick. Preserve explicit provenance; public mock rejection is unchanged.
    submission = payload.run.model_copy(
        update={
            "source": "tracked",
            "samples": [
                sample.model_copy(update={"provider": "admin-joystick", "is_mock": False})
                for sample in samples
            ],
        }
    )
    result = process_run(session, resolve_device(session, device_id), submission)
    session.add(
        AuditEvent(
            actor_kind="admin",
            actor_ref=str(request.state.admin_user.id)
            if hasattr(request.state, "admin_user")
            else payload.operator_ref,
            action="run.simulated",
            target_type="run",
            target_ref=str(result.run_id),
            reason=payload.reason,
            details={"developer_slot": payload.slot, "sample_count": len(samples)},
        )
    )
    session.flush()
    return result


@router.post("/territories/{territory_id}/rebuild")
def rebuild_territory(
    territory_id: uuid.UUID,
    decision: ManualRunReversal,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    if session.get(Territory, territory_id) is None:
        raise HTTPException(404, "Territory not found")
    recompute_ownership(session, territory_id)
    session.add(
        AuditEvent(
            actor_kind="admin",
            actor_ref=str(request.state.admin_user.id)
            if hasattr(request.state, "admin_user")
            else decision.operator_ref,
            action="territory.rebuilt",
            target_type="territory",
            target_ref=str(territory_id),
            reason=decision.reason,
        )
    )
    return {"territory_id": str(territory_id), "status": "rebuilt"}
