import uuid
from secrets import compare_digest

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.authentication import resolve_session
from app.core.config import settings
from app.core.db import get_session
from app.models import ConsoleUser, Device, DeviceLink


def resolve_device(session: Session, device_id: uuid.UUID) -> Device:
    """Find or create a device after the caller dependency authorizes it."""
    device = session.get(Device, device_id)
    if device is None:
        device = Device(id=device_id)
        session.add(device)
        session.flush()
    elif device.privacy_deleted_at is not None:
        raise HTTPException(status_code=410, detail="Device data has been deleted")
    return device


def public_device_id(x_device_id: str = Header(..., alias="X-Device-Id")) -> uuid.UUID:
    try:
        return uuid.UUID(x_device_id)
    except ValueError as exc:
        raise HTTPException(400, "X-Device-Id must be a UUID") from exc


def device_id_header(
    device_id: uuid.UUID = Depends(public_device_id),
    authorization: str | None = Header(None),
    session: Session = Depends(get_session),
) -> uuid.UUID:
    if settings.authenticated_accounts_enabled:
        login = resolve_session(session, authorization, "app")
        link = session.get(DeviceLink, device_id)
        if not link or link.account_id != login.principal_id:
            raise HTTPException(403, "This runner does not belong to your account")
    return device_id


def console_member(
    authorization: str | None = Header(None), session: Session = Depends(get_session)
) -> ConsoleUser:
    login = resolve_session(session, authorization, "admin")
    user = session.get(ConsoleUser, login.principal_id)
    if not user or not user.active:
        raise HTTPException(401, "This console account is disabled")
    return user


def require_admin_operations_token(
    request: Request,
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    authorization: str | None = Header(None),
    session: Session = Depends(get_session),
) -> None:
    if authorization:
        user = console_member(authorization, session)
        request.state.admin_user = user
        return
    configured = settings.admin_operations_token
    expected = configured.get_secret_value() if configured else ""
    if not expected or not x_admin_token or not compare_digest(x_admin_token, expected):
        raise HTTPException(403, "Not authorized")
