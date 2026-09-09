"""Small, token-protected internal operations surface. No public admin UI."""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import require_admin_operations_token
from app.core.db import get_session
from app.schemas import (
    InternalRunReviewItem,
    ManualRunReversal,
    ManualRunReversalResult,
)
from app.services.review import reverse_run, review_queue

router = APIRouter(
    prefix="/admin/review",
    tags=["internal-admin"],
    dependencies=[Depends(require_admin_operations_token)],
)


@router.get("/devices/{device_id}/runs", response_model=list[InternalRunReviewItem])
def get_device_review_queue(
    device_id: uuid.UUID, session: Session = Depends(get_session)
) -> list[InternalRunReviewItem]:
    """List provisional or challenged runs for exactly one device."""

    return [
        InternalRunReviewItem(
            run_id=run.id,
            device_id=run.device_id,
            status=run.status,
            started_at=run.started_at,
            ended_at=run.ended_at,
            distance_m=float(run.distance_m),
            source=run.source,
            lifecycle_version=run.lifecycle_version,
        )
        for run in review_queue(session, device_id)
    ]


@router.post("/runs/{run_id}/reverse", response_model=ManualRunReversalResult)
def manually_reverse_run(
    run_id: uuid.UUID,
    decision: ManualRunReversal,
    request: Request,
    session: Session = Depends(get_session),
) -> ManualRunReversalResult:
    """Record an accountable reversal and rebuild derived affected territories."""

    outcome = reverse_run(
        session,
        run_id=run_id,
        operator_ref=str(request.state.admin_user.id)
        if hasattr(request.state, "admin_user")
        else decision.operator_ref,
        reason=decision.reason,
    )
    return ManualRunReversalResult(
        run_id=outcome.run_id,
        status="reversed",
        rebuilt_territory_ids=outcome.rebuilt_territory_ids,
    )
