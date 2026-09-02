import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import device_id_header, resolve_device
from app.core.db import get_session
from app.schemas import HomeTerritoryUpdate, ProfileSummary
from app.services.progression import profile_summary, set_home

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileSummary)
def get_profile(
    device_id: uuid.UUID = Depends(device_id_header),
    session: Session = Depends(get_session),
) -> ProfileSummary:
    """Return device-scoped Home and transparent derived progression."""

    resolve_device(session, device_id)
    return profile_summary(session, device_id)


@router.put("/home", response_model=ProfileSummary)
def update_home(
    update: HomeTerritoryUpdate,
    device_id: uuid.UUID = Depends(device_id_header),
    session: Session = Depends(get_session),
) -> ProfileSummary:
    """Choose or change Home; this has no ownership or influence side effects."""

    resolve_device(session, device_id)
    set_home(
        session,
        device_id=device_id,
        territory_id=update.territory_id,
        metadata=update.metadata,
    )
    return profile_summary(session, device_id)
