import json
import re
import urllib.error
import urllib.request
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.v1.accounts import DEVELOPER_DEVICE_IDS, link_device_to_account, summary
from app.core.authentication import (
    issue_session,
    password_hash,
    resolve_session,
    throttle,
    verify_password,
)
from app.core.config import settings
from app.core.db import get_session
from app.models import Account, AccountAuthMethod, AuthSession, ConsoleUser, LoginCredential

router = APIRouter(prefix="/auth", tags=["authentication"])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=128)
    scope: Literal["app", "admin"] = "app"

    @field_validator("username")
    @classmethod
    def normalize(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]{3,32}", value):
            raise ValueError("Use 3–32 letters, numbers, dots, dashes or underscores")
        return value


class SignUp(Credentials):
    @field_validator("display_name")
    @classmethod
    def valid_name(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("Use at least two characters for the display name")
        return value.strip()

    display_name: str = Field(min_length=2, max_length=32)


class ProfileCredentials(BaseModel):
    _normalize = field_validator("username")(Credentials.normalize)
    username: str = Field(min_length=3, max_length=32)
    new_password: str | None = Field(default=None, min_length=12, max_length=128)
    current_password: str | None = Field(default=None, max_length=128)
    display_name: str | None = Field(default=None, min_length=2, max_length=32)
    scope: Literal["app", "admin"] = "app"


def caller_device(value: str | None) -> uuid.UUID:
    try:
        return uuid.UUID(value or "")
    except ValueError as exc:
        raise HTTPException(400, "Device identifier is missing or invalid") from exc


def app_login(session: Session, account: Account, device_header: str | None):
    caller_device(device_header)
    account_summary = summary(session, account)
    # Stable account-owned ledger: switching accounts cannot transfer past runs.
    device_id = (
        DEVELOPER_DEVICE_IDS[account_summary.developer_slot - 1]
        if account_summary.developer_slot
        else uuid.uuid5(account.id, "terrarun-ledger")
    )
    link_device_to_account(session, device_id, account.id)
    session.flush()
    return {
        "token": issue_session(session, "app", account.id),
        "device_id": str(device_id),
        "account": summary(session, account).model_dump(mode="json"),
    }


def member_json(session, user):
    credential = session.scalar(
        select(LoginCredential).where(
            LoginCredential.scope == "admin", LoginCredential.principal_id == user.id
        )
    )
    return {
        "id": str(user.id),
        "display_name": user.display_name,
        "role": user.role,
        "username": credential.username if credential else None,
    }


@router.post("/login")
def login(
    payload: Credentials,
    request: Request,
    x_device_id: str | None = Header(None),
    session: Session = Depends(get_session),
):
    throttle(f"login-ip:{request.client.host}", limit=60)
    throttle(f"login:{request.client.host}:{payload.scope}:{payload.username}")
    credential = session.scalar(
        select(LoginCredential).where(
            LoginCredential.scope == payload.scope, LoginCredential.username == payload.username
        )
    )
    if not credential or not verify_password(payload.password, credential.password_hash):
        raise HTTPException(401, "Username or password is incorrect")
    if payload.scope == "admin":
        user = session.get(ConsoleUser, credential.principal_id)
        if not user or not user.active:
            raise HTTPException(401, "Username or password is incorrect")
        return {
            "token": issue_session(session, "admin", user.id),
            "member": member_json(session, user),
        }
    account = session.get(Account, credential.principal_id)
    if not account:
        raise HTTPException(401, "Account unavailable")
    return app_login(session, account, x_device_id)


@router.post("/register")
def register(
    payload: SignUp,
    request: Request,
    x_device_id: str | None = Header(None),
    session: Session = Depends(get_session),
):
    throttle(f"register:{request.client.host}")
    if payload.scope != "app":
        raise HTTPException(403, "Admin accounts require an invitation from an owner")
    if len(payload.password) < 12:
        raise HTTPException(422, "Use a password with at least 12 characters")
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext("app:" + payload.username))))
    if session.scalar(
        select(LoginCredential.id).where(
            LoginCredential.scope == "app", LoginCredential.username == payload.username
        )
    ):
        raise HTTPException(409, "That username is unavailable")
    account = Account(display_name=payload.display_name.strip(), role="player")
    session.add(account)
    session.flush()
    session.add(
        LoginCredential(
            scope="app",
            principal_id=account.id,
            username=payload.username,
            password_hash=password_hash(payload.password),
        )
    )
    return app_login(session, account, x_device_id)


class GoogleSession(BaseModel):
    access_token: str = Field(min_length=20, max_length=8192)


@router.post("/google")
def google(
    payload: GoogleSession,
    request: Request,
    x_device_id: str | None = Header(None),
    session: Session = Depends(get_session),
):
    throttle(f"google:{request.client.host}")
    req = urllib.request.Request(
        settings.supabase_url.rstrip("/") + "/auth/v1/user",
        headers={
            "apikey": settings.supabase_publishable_key,
            "Authorization": "Bearer " + payload.access_token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            user = json.load(response)
    except urllib.error.HTTPError as exc:
        raise HTTPException(401, "Google session could not be verified") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(503, "Google sign-in is temporarily unavailable") from exc
    if not user.get("email_confirmed_at") or not any(
        i.get("provider") == "google" for i in user.get("identities", [])
    ):
        raise HTTPException(401, "A verified Google identity is required")
    subject = str(uuid.UUID(user["id"]))
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext("google:" + subject))))
    method = session.scalar(
        select(AccountAuthMethod).where(
            AccountAuthMethod.provider == "google", AccountAuthMethod.provider_subject == subject
        )
    )
    if method:
        account = session.get(Account, method.account_id)
    else:
        metadata = user.get("user_metadata", {})
        account = Account(
            display_name=str(metadata.get("full_name") or "Runner")[:32], role="player"
        )
        session.add(account)
        session.flush()
        session.add(
            AccountAuthMethod(account_id=account.id, provider="google", provider_subject=subject)
        )
    return app_login(session, account, x_device_id)


@router.get("/profile")
def profile(
    scope: Literal["app", "admin"] = "app",
    authorization: str | None = Header(None),
    session: Session = Depends(get_session),
):
    login = resolve_session(session, authorization, scope)
    credential = session.scalar(
        select(LoginCredential).where(
            LoginCredential.scope == scope, LoginCredential.principal_id == login.principal_id
        )
    )
    return {
        "username": credential.username if credential else None,
        "has_password": credential is not None,
    }


@router.put("/profile")
def update_credentials(
    payload: ProfileCredentials,
    authorization: str | None = Header(None),
    session: Session = Depends(get_session),
):
    login = resolve_session(session, authorization, payload.scope)
    username = payload.username
    credential = session.scalar(
        select(LoginCredential).where(
            LoginCredential.scope == payload.scope,
            LoginCredential.principal_id == login.principal_id,
        )
    )
    if credential and not verify_password(payload.current_password or "", credential.password_hash):
        raise HTTPException(401, "Current password is incorrect")
    duplicate = session.scalar(
        select(LoginCredential).where(
            LoginCredential.scope == payload.scope, LoginCredential.username == username
        )
    )
    if duplicate and duplicate.principal_id != login.principal_id:
        raise HTTPException(409, "That username is unavailable")
    if not credential:
        if not payload.new_password:
            raise HTTPException(422, "Set a password to enable username sign-in")
        credential = LoginCredential(
            scope=payload.scope,
            principal_id=login.principal_id,
            username=username,
            password_hash=password_hash(payload.new_password),
        )
        session.add(credential)
    else:
        credential.username = username
        if payload.new_password:
            credential.password_hash = password_hash(payload.new_password)
    if payload.display_name:
        person = session.get(
            ConsoleUser if payload.scope == "admin" else Account, login.principal_id
        )
        person.display_name = payload.display_name.strip()
    if payload.new_password:
        session.execute(
            delete(AuthSession).where(
                AuthSession.principal_id == login.principal_id,
                AuthSession.scope == payload.scope,
                AuthSession.token_hash != login.token_hash,
            )
        )
    session.flush()
    return {"username": username, "has_password": True}


@router.post("/logout", status_code=204)
def logout(
    scope: Literal["app", "admin"] = "app",
    authorization: str | None = Header(None),
    session: Session = Depends(get_session),
):
    login = resolve_session(session, authorization, scope)
    session.delete(login)
    session.flush()
