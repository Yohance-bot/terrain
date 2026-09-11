"""The console's test lab: disposable runners the operator can act as.

Every other admin endpoint reads or corrects the world. This one creates a
parallel set of players so a feature can be exercised end to end — and it does
that by handing the console a real player session, so the lab drives exactly the
endpoints the phone drives. A feature that works here works on the device, and a
feature that cannot be reached from here is not finished.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin_operations_token
from app.core.db import get_session
from app.models import Account, AuditEvent, Challenge, Race, SandboxAccount
from app.services.challenges import resolve_due
from app.services.races import expire_due
from app.services.sandbox import (
    create_runner,
    fast_forward_challenge,
    fast_forward_race,
    mint_session,
    require_enabled,
    require_sandbox,
    synthesise_run,
    teardown,
)
from app.services.social import handle_for

router = APIRouter(
    prefix="/admin/sandbox",
    tags=["internal-admin-sandbox"],
    dependencies=[Depends(require_admin_operations_token), Depends(require_enabled)],
)


class TestRunner(BaseModel):
    """Everything the console needs to act as this player."""

    account_id: uuid.UUID
    device_id: uuid.UUID
    display_name: str
    handle: str
    label: str
    # A real app session. The console sends it exactly as the phone would.
    token: str
    created_at: datetime


class RunnerCreate(BaseModel):
    label: str = Field(default="Test Runner", min_length=1, max_length=64)


class RunnerList(BaseModel):
    runners: list[TestRunner]


def _runner(session: Session, runner: SandboxAccount) -> TestRunner:
    account = session.get(Account, runner.account_id)
    if account is None:
        raise HTTPException(404, "That test runner no longer exists.")
    return TestRunner(
        account_id=runner.account_id,
        device_id=runner.device_id,
        display_name=account.display_name,
        handle=handle_for(session, account),
        label=runner.label,
        token=mint_session(session, runner.account_id),
        created_at=runner.created_at,
    )


@router.get("/runners", response_model=RunnerList)
def list_runners(session: Session = Depends(get_session)) -> RunnerList:
    """The roster, each with a freshly minted session.

    Tokens are reissued on every read rather than stored, so a console tab that
    has been open for a day still works and nothing long-lived sits in the table.
    """
    runners = session.execute(
        select(SandboxAccount).order_by(SandboxAccount.created_at)
    ).scalars()
    return RunnerList(runners=[_runner(session, runner) for runner in runners])


@router.post("/runners", response_model=TestRunner, status_code=201)
def add_runner(
    payload: RunnerCreate,
    request: Request,
    session: Session = Depends(get_session),
) -> TestRunner:
    runner = create_runner(session, payload.label, _operator(request))
    session.add(
        AuditEvent(
            actor_kind="admin",
            actor_ref=_operator(request) or "test-lab",
            action="sandbox.runner.created",
            target_type="account",
            target_ref=str(runner.account_id),
            reason="Console test lab runner",
        )
    )
    return _runner(session, runner)


def _operator(request: Request) -> str | None:
    user = getattr(request.state, "admin_user", None)
    return str(user.id) if user is not None else None


class TeardownResult(BaseModel):
    runners: int
    runs: int
    territories_recomputed: int


@router.delete("/runners", response_model=TeardownResult)
def reset_lab(request: Request, session: Session = Depends(get_session)) -> TeardownResult:
    """Remove every test runner and undo what they did to the shared world."""
    result = teardown(session)
    session.add(
        AuditEvent(
            actor_kind="admin",
            actor_ref=_operator(request) or "test-lab",
            action="sandbox.reset",
            target_type="sandbox",
            target_ref="all",
            reason="Console test lab reset",
            details=result,
        )
    )
    return TeardownResult(**result)


@router.delete("/runners/{account_id}", response_model=TeardownResult)
def remove_runner(
    account_id: uuid.UUID, session: Session = Depends(get_session)
) -> TeardownResult:
    require_sandbox(session, account_id)
    return TeardownResult(**teardown(session, [account_id]))


class SyntheticRun(BaseModel):
    """A run written straight to the ledger, for scoring without driving."""

    distance_m: float = Field(gt=0, le=200_000)
    duration_s: int = Field(default=1800, gt=0, le=86_400)
    # Puts the run earlier, for testing a challenge window's edge.
    minutes_ago: int = Field(default=0, ge=0, le=60 * 24 * 30)
    # Give the run a real route so it can be saved as a ghost. Claims nothing:
    # the lab never runs the matching pipeline.
    route_lon: float | None = Field(default=None, ge=-180, le=180)
    route_lat: float | None = Field(default=None, ge=-90, le=90)


class SyntheticRunResult(BaseModel):
    run_id: uuid.UUID
    distance_m: float
    ended_at: datetime


@router.post("/runners/{account_id}/runs", response_model=SyntheticRunResult, status_code=201)
def add_run(
    account_id: uuid.UUID,
    payload: SyntheticRun,
    session: Session = Depends(get_session),
) -> SyntheticRunResult:
    runner = require_sandbox(session, account_id)
    run = synthesise_run(
        session,
        runner,
        distance_m=payload.distance_m,
        duration_s=payload.duration_s,
        ended_at=datetime.now(UTC) - timedelta(minutes=payload.minutes_ago),
        route_from=(payload.route_lon, payload.route_lat)
        if payload.route_lon is not None and payload.route_lat is not None
        else None,
    )
    return SyntheticRunResult(
        run_id=run.id, distance_m=float(run.distance_m), ended_at=run.ended_at
    )


class ResolverResult(BaseModel):
    expired: int
    resolved: int


@router.post("/challenges/{challenge_id}/fast-forward", response_model=ResolverResult)
def fast_forward(
    challenge_id: uuid.UUID, session: Session = Depends(get_session)
) -> ResolverResult:
    """End a challenge's window now and settle it, without waiting days."""
    challenge = session.get(Challenge, challenge_id)
    if challenge is None:
        raise HTTPException(404, "That challenge no longer exists.")
    fast_forward_challenge(session, challenge)
    return ResolverResult(**resolve_due(session))


@router.post("/races/{race_id}/fast-forward", response_model=ResolverResult)
def fast_forward_race_endpoint(
    race_id: uuid.UUID, session: Session = Depends(get_session)
) -> ResolverResult:
    """Age a race out, to check that abandoning one ends it quietly."""
    race = session.get(Race, race_id)
    if race is None:
        raise HTTPException(404, "That race no longer exists.")
    fast_forward_race(session, race)
    return ResolverResult(expired=expire_due(session), resolved=0)
