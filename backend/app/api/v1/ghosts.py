"""Ghost runs: race a recorded route, or publish yours as a benchmark.

Publishing a ghost publishes history and nothing else. Whether the runner is out
there right now stays behind `share_live_location`, a separate switch that this
endpoint never sets as a side effect.

A published ghost is permanent and reusable — racing it does not consume it, and
any number of people can attempt it any number of times.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.social import current_account, public
from app.core.db import get_session
from app.models import Account, GhostAttempt, GhostRun, Run
from app.schemas import (
    GhostAttemptFinish,
    GhostAttemptRecord,
    GhostCreate,
    GhostDetail,
    GhostSummary,
    GhostUpdate,
)
from app.services.ghosts import (
    MAX_NEARBY_RADIUS_M,
    best_time,
    build_path,
    finish_attempt,
    nearby,
    visible_path,
)
from app.services.social import account_device_ids

router = APIRouter(prefix="/social/ghosts", tags=["social"])


def summary(session: Session, ghost: GhostRun, viewer: Account) -> GhostSummary:
    owner = session.get(Account, ghost.account_id)
    return GhostSummary(
        id=ghost.id,
        name=ghost.name,
        owner=public(session, owner, viewer.id),
        distance_m=ghost.distance_m,
        duration_s=ghost.duration_s,
        start_lat=ghost.start_lat,
        start_lon=ghost.start_lon,
        is_public=ghost.is_public,
        share_live_location=ghost.share_live_location,
        is_yours=ghost.account_id == viewer.id,
        best_elapsed_s=best_time(session, ghost.id),
        created_at=ghost.created_at,
    )


def detail(session: Session, ghost: GhostRun, viewer: Account) -> GhostDetail:
    path = visible_path(ghost, viewer.id)
    if not path:
        raise HTTPException(422, "This route is too short to share publicly.")
    return GhostDetail(**summary(session, ghost, viewer).model_dump(), path=path)


def _readable(session: Session, ghost_id: uuid.UUID, viewer: Account) -> GhostRun:
    ghost = session.get(GhostRun, ghost_id)
    if ghost is None or (not ghost.is_public and ghost.account_id != viewer.id):
        raise HTTPException(404, "That ghost is not available.")
    return ghost


@router.post("", response_model=GhostSummary, status_code=201)
def create_ghost(
    payload: GhostCreate,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> GhostSummary:
    """Save one of your own applied runs as a ghost."""
    run = session.get(Run, payload.run_id)
    if run is None or run.device_id not in account_device_ids(session, account.id):
        raise HTTPException(404, "That run is not yours.")
    if run.status != "applied":
        raise HTTPException(409, "Wait until the run has been processed.")
    if session.execute(
        select(GhostRun).where(GhostRun.run_id == run.id)
    ).scalar_one_or_none():
        raise HTTPException(409, "That run is already saved as a ghost.")

    path = build_path(session, run)
    ghost = GhostRun(
        account_id=account.id,
        run_id=run.id,
        name=payload.name.strip(),
        path=path,
        distance_m=float(run.distance_m or 0),
        duration_s=int(run.duration_s or 0),
        start_lon=path[0][0],
        start_lat=path[0][1],
        is_public=payload.is_public,
    )
    session.add(ghost)
    session.flush()
    return summary(session, ghost, account)


@router.get("/mine", response_model=list[GhostSummary])
def my_ghosts(
    account: Account = Depends(current_account), session: Session = Depends(get_session)
) -> list[GhostSummary]:
    ghosts = session.execute(
        select(GhostRun)
        .where(GhostRun.account_id == account.id)
        .order_by(GhostRun.created_at.desc())
    ).scalars()
    return [summary(session, ghost, account) for ghost in ghosts]


@router.get("/nearby", response_model=list[GhostSummary])
def ghosts_nearby(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_m: float = Query(default=2000, gt=0, le=MAX_NEARBY_RADIUS_M),
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> list[GhostSummary]:
    """Public ghosts around a point.

    This is its own request, and the client puts the results behind a map layer
    the player turns on. Drawing every available ghost over the map by default
    would bury the thing the map is actually for.
    """
    return [summary(session, ghost, account) for ghost in nearby(session, lat, lon, radius_m)]


@router.get("/{ghost_id}", response_model=GhostDetail)
def read_ghost(
    ghost_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> GhostDetail:
    """The full route and pacing, so the client can replay it without polling."""
    return detail(session, _readable(session, ghost_id, account), account)


@router.put("/{ghost_id}", response_model=GhostSummary)
def update_ghost(
    ghost_id: uuid.UUID,
    update: GhostUpdate,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> GhostSummary:
    ghost = session.get(GhostRun, ghost_id)
    if ghost is None or ghost.account_id != account.id:
        raise HTTPException(404, "That ghost is not yours.")
    if update.name is not None:
        ghost.name = update.name.strip()
    if update.is_public is not None:
        ghost.is_public = update.is_public
        if not update.is_public:
            # Withdrawing the broadcast withdraws everything that hung off it.
            ghost.share_live_location = False
    if update.share_live_location is not None:
        if update.share_live_location and not ghost.is_public:
            raise HTTPException(422, "Broadcast the ghost before sharing your live position on it.")
        ghost.share_live_location = update.share_live_location
    return summary(session, ghost, account)


@router.delete("/{ghost_id}", status_code=204)
def delete_ghost(
    ghost_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> None:
    ghost = session.get(GhostRun, ghost_id)
    if ghost is None or ghost.account_id != account.id:
        raise HTTPException(404, "That ghost is not yours.")
    session.delete(ghost)


@router.post("/{ghost_id}/attempts", response_model=GhostAttemptRecord, status_code=201)
def start_attempt(
    ghost_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> GhostAttemptRecord:
    ghost = _readable(session, ghost_id, account)
    attempt = GhostAttempt(ghost_id=ghost.id, account_id=account.id, started_at=datetime.now(UTC))
    session.add(attempt)
    session.flush()
    return GhostAttemptRecord(
        id=attempt.id,
        ghost_id=ghost.id,
        started_at=attempt.started_at,
        ghost_duration_s=ghost.duration_s,
    )


@router.post("/attempts/{attempt_id}/finish", response_model=GhostAttemptRecord)
def finish(
    attempt_id: uuid.UUID,
    payload: GhostAttemptFinish,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> GhostAttemptRecord:
    attempt = session.get(GhostAttempt, attempt_id)
    if attempt is None or attempt.account_id != account.id:
        raise HTTPException(404, "That attempt no longer exists.")
    if attempt.finished_at is not None:
        raise HTTPException(409, "That attempt is already finished.")
    ghost = session.get(GhostRun, attempt.ghost_id)
    if ghost is None:
        raise HTTPException(404, "That ghost no longer exists.")

    attempt.run_id = payload.run_id
    finish_attempt(session, attempt, ghost, payload.elapsed_s)
    return GhostAttemptRecord(
        id=attempt.id,
        ghost_id=ghost.id,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        elapsed_s=attempt.elapsed_s,
        beat_ghost=attempt.beat_ghost,
        ghost_duration_s=ghost.duration_s,
    )


@router.get("/{ghost_id}/attempts", response_model=list[GhostAttemptRecord])
def list_attempts(
    ghost_id: uuid.UUID,
    account: Account = Depends(current_account),
    session: Session = Depends(get_session),
) -> list[GhostAttemptRecord]:
    """Your own attempts at this ghost. Other people's times stay theirs."""
    ghost = _readable(session, ghost_id, account)
    attempts = session.execute(
        select(GhostAttempt)
        .where(GhostAttempt.ghost_id == ghost.id, GhostAttempt.account_id == account.id)
        .order_by(GhostAttempt.started_at.desc())
    ).scalars()
    return [
        GhostAttemptRecord(
            id=attempt.id,
            ghost_id=ghost.id,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            elapsed_s=attempt.elapsed_s,
            beat_ghost=attempt.beat_ghost,
            ghost_duration_s=ghost.duration_s,
        )
        for attempt in attempts
    ]
