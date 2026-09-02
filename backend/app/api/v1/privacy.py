"""Device-scoped privacy controls for the pre-authentication prototype."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import device_id_header
from app.core.config import settings
from app.core.db import get_session
from app.schemas import DeviceDeletionSummary, PrivacyRetentionPolicy
from app.services.privacy import anonymize_device

router = APIRouter(prefix="/privacy", tags=["privacy"])


@router.get("/retention", response_model=PrivacyRetentionPolicy)
def get_retention_policy() -> PrivacyRetentionPolicy:
    """Expose the retention periods the server's scheduled job enforces."""
    return PrivacyRetentionPolicy(
        raw_trace_retention_days=settings.raw_trace_retention_days,
        route_polyline_full_precision_days=settings.route_polyline_full_precision_days,
    )


@router.delete("/device", response_model=DeviceDeletionSummary)
def delete_device_data(
    device_id: uuid.UUID = Depends(device_id_header),
    session: Session = Depends(get_session),
) -> DeviceDeletionSummary:
    """Delete this device's raw location data and personal device preferences.

    The X-Device-Id header is the available device scope, not authentication.
    Account-bound identity verification must replace it before public release.
    """
    result = anonymize_device(session, device_id=device_id)
    return DeviceDeletionSummary(
        device_id=result.device_id,
        raw_traces_deleted=result.raw_traces_deleted,
        deletion_scope="device",
    )
