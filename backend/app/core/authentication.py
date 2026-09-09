"""Opaque, revocable sessions; passwords never leave the server hash boundary."""

import hashlib
import hmac
import secrets
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from threading import Lock

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import AuthSession

_ATTEMPTS: OrderedDict[str, tuple[int, float]] = OrderedDict()
_LOCK = Lock()


def throttle(key: str, limit: int = 12) -> None:
    now = time.monotonic()
    with _LOCK:
        count, since = _ATTEMPTS.get(key, (0, now))
        if now - since > 900:
            count, since = 0, now
        if count >= limit:
            raise HTTPException(429, "Too many sign-in attempts. Try again in 15 minutes.")
        _ATTEMPTS[key] = (count + 1, since)
        _ATTEMPTS.move_to_end(key)
        while len(_ATTEMPTS) > 4096:
            _ATTEMPTS.popitem(last=False)


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    value = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=64 * 1024 * 1024
    ).hex()
    return f"scrypt${salt}${value}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt, expected = encoded.split("$")
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=64 * 1024 * 1024
        ).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_session(session: Session, scope: str, principal_id) -> str:
    token = secrets.token_urlsafe(48)
    session.add(
        AuthSession(
            token_hash=token_digest(token),
            scope=scope,
            principal_id=principal_id,
            expires_at=datetime.now(UTC) + timedelta(hours=12 if scope == "admin" else 24 * 30),
        )
    )
    session.flush()
    return token


def resolve_session(session: Session, authorization: str | None, scope: str) -> AuthSession:
    if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 512:
        raise HTTPException(401, "Sign in to continue")
    login = session.get(AuthSession, token_digest(authorization[7:]))
    if not login or login.scope != scope or login.expires_at <= datetime.now(UTC):
        raise HTTPException(401, "Your session has expired. Sign in again.")
    return login
