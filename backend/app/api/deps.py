import uuid
from secrets import compare_digest

from fastapi import Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Device


def resolve_device(session: Session, device_id: uuid.UUID) -> Device:
    """Find or create the calling device.

    This is not authentication and makes no attempt to be. The header is trusted
    completely, because in this milestone there is nothing worth stealing and
    accounts are explicitly out of scope.
    """
    device = session.get(Device, device_id)
    if device is None:
        device = Device(id=device_id)
        session.add(device)
        session.flush()
    elif device.privacy_deleted_at is not None:
        raise HTTPException(status_code=410, detail="Device data has been deleted")
    return device


def device_id_header(x_device_id: str = Header(..., alias="X-Device-Id")) -> uuid.UUID:
    try:
        return uuid.UUID(x_device_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Device-Id must be a UUID") from exc


def require_admin_operations_token(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """Temporary explicit-token boundary for internal operations only."""

    configured_token = settings.admin_operations_token
    expected = configured_token.get_secret_value() if configured_token is not None else ""
    if not expected or x_admin_token is None or not compare_digest(x_admin_token, expected):
        # Do not reveal whether operations are disabled or a supplied token was wrong.
        raise HTTPException(status_code=403, detail="Not authorized")
