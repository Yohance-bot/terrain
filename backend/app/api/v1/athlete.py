"""The signed-in athlete's own training: stats, the log, goals, settings, shoes.

Everything here is scoped to the caller's account. A friend's view of the same
data goes through `/social/accounts/{id}/profile`, which strips what places a
person — notes, shoes — and requires an accepted friendship.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.social import current_account
from app.core.db import get_session
from app.models import Account
from app.schemas import (
    AthleteSettingsRecord,
    AthleteStats,
    GoalProgress,
    RunActivity,
    RunAnnotationUpdate,
    RunPage,
    RunSummary,
    ShoeCreate,
    ShoeRecord,
    ShoeUpdate,
    WeeklyGoalUpdate,
)
from app.services import athlete

router = APIRouter(prefix="/athlete", tags=["athlete"])

Timezone = Query(default=None, max_length=64, description="IANA zone, e.g. Asia/Kolkata")


@router.get("/stats", response_model=AthleteStats)
def get_stats(
    tz: str | None = Timezone,
    weeks: int = Query(default=12, ge=1, le=104),
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> AthleteStats:
    return athlete.athlete_stats(session, account, tz, weeks=weeks)


@router.get("/runs", response_model=RunPage)
def get_runs(
    tz: str | None = Timezone,
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    before: datetime | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> RunPage:
    return athlete.runs_page(session, account, tz_name=tz, month=month, before=before, limit=limit)


@router.get("/runs/{run_id}", response_model=RunActivity)
def get_activity(
    run_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> RunActivity:
    return athlete.run_activity(session, account, run_id)


@router.patch("/runs/{run_id}", response_model=RunSummary)
def annotate_run(
    run_id: uuid.UUID,
    change: RunAnnotationUpdate,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> RunSummary:
    return athlete.update_annotation(session, account, run_id, change)


@router.get("/goal", response_model=GoalProgress | None)
def get_goal(
    tz: str | None = Timezone,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> GoalProgress | None:
    return athlete.goal_progress(session, account, tz)


@router.put("/goal", response_model=GoalProgress)
def put_goal(
    change: WeeklyGoalUpdate,
    tz: str | None = Timezone,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> GoalProgress:
    return athlete.set_goal(session, account, change, tz)


@router.delete("/goal", status_code=204)
def delete_goal(
    account: Account = Depends(current_account), session: Session = Depends(get_session)
) -> None:
    athlete.clear_goal(session, account)


@router.get("/settings", response_model=AthleteSettingsRecord)
def get_settings(
    account: Account = Depends(current_account), session: Session = Depends(get_session)
) -> AthleteSettingsRecord:
    return athlete.get_settings(session, account)


@router.put("/settings", response_model=AthleteSettingsRecord)
def put_settings(
    change: AthleteSettingsRecord,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> AthleteSettingsRecord:
    return athlete.put_settings(session, account, change)


@router.get("/shoes", response_model=list[ShoeRecord])
def get_shoes(
    account: Account = Depends(current_account), session: Session = Depends(get_session)
) -> list[ShoeRecord]:
    return athlete.list_shoes(session, account)


@router.post("/shoes", response_model=ShoeRecord, status_code=201)
def add_shoe(
    change: ShoeCreate,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> ShoeRecord:
    return athlete.create_shoe(session, account, change)


@router.patch("/shoes/{shoe_id}", response_model=ShoeRecord)
def edit_shoe(
    shoe_id: uuid.UUID,
    change: ShoeUpdate,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> ShoeRecord:
    return athlete.update_shoe(session, account, shoe_id, change)


@router.delete("/shoes/{shoe_id}", status_code=204)
def remove_shoe(
    shoe_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> None:
    athlete.delete_shoe(session, account, shoe_id)
