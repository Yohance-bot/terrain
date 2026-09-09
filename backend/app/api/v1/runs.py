import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import device_id_header, resolve_device
from app.core.db import get_session
from app.schemas import RunResult, RunSubmission
from app.services.ingest import build_result, get_run_or_404, process_run

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunResult)
def submit_run(
    submission: RunSubmission,
    device_id: uuid.UUID = Depends(device_id_header),
    session: Session = Depends(get_session),
) -> RunResult:
    """Accept a finished run, match it, and apply the result.

    Runs synchronously. `03` and `07` both put matching in a background worker
    eventually, but clipping one route against ten polygons takes milliseconds,
    and the service boundary is drawn so moving it later is a call-site change.
    """
    device = resolve_device(session, device_id)
    return process_run(session, device, submission)


@router.get("/{run_id}", response_model=RunResult)
def get_run(
    run_id: uuid.UUID,
    device_id: uuid.UUID = Depends(device_id_header),
    session: Session = Depends(get_session),
) -> RunResult:
    run = get_run_or_404(session, run_id)
    if run.device_id != device_id:
        raise HTTPException(404, "Run not found")
    return build_result(session, run)
