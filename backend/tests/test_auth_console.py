"""Real database checks with rollback: no fixture accounts escape the transaction."""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.core.config import settings
from app.core.db import SessionLocal, engine, get_session
from app.core.authentication import password_hash, issue_session
from app.main import app
from app.models import Account, ConsoleUser, LoginCredential, DeviceLink


@pytest.fixture()
def auth(monkeypatch):
    conn = engine.connect()
    tx = conn.begin()
    session = SessionLocal(bind=conn, join_transaction_mode="create_savepoint")
    app.dependency_overrides[get_session] = lambda: session
    monkeypatch.setattr(settings, "authenticated_accounts_enabled", True)
    try:
        yield TestClient(app), session
    finally:
        app.dependency_overrides.pop(get_session, None)
        session.close()
        tx.rollback()
        conn.close()


def admin(session, role="owner"):
    user = ConsoleUser(display_name="Rollback Owl", role=role)
    session.add(user)
    session.flush()
    return user, {"Authorization": "Bearer " + issue_session(session, "admin", user.id)}


def test_password_login_scope_and_device_isolation(auth):
    client, session = auth
    account = Account(display_name="Rollback Runner", role="player")
    session.add(account)
    session.flush()
    session.add(
        LoginCredential(
            scope="app",
            principal_id=account.id,
            username="rollback.runner",
            password_hash=password_hash("correct horse river canyon"),
        )
    )
    session.flush()
    device = str(uuid.uuid4())
    payload = {"username": "rollback.runner", "password": "correct horse river canyon"}
    first = client.post("/v1/auth/login", headers={"X-Device-Id": device}, json=payload)
    assert first.status_code == 200, first.text
    token = first.json()["token"]
    ledger = first.json()["device_id"]
    headers = {"Authorization": "Bearer " + token, "X-Device-Id": ledger}
    assert client.get("/v1/account", headers=headers).json()["id"] == str(account.id)
    assert client.get("/v1/account", headers={**headers, "X-Device-Id": device}).status_code == 403
    assert client.get("/v1/admin/console/me", headers=headers).status_code == 401
    assert (
        client.post(
            "/v1/auth/login", headers={"X-Device-Id": device}, json={**payload, "scope": "admin"}
        ).status_code
        == 401
    )
    assert client.post("/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/v1/account", headers=headers).status_code == 401
    assert session.get(DeviceLink, uuid.UUID(ledger)).account_id == account.id
    assert (
        client.post(
            "/v1/account/developer-login", headers=headers, json={"pin": "2468"}
        ).status_code
        == 401
    )


def test_profile_change_revokes_other_sessions_and_validates_username(auth):
    client, session = auth
    user, headers = admin(session)
    other = issue_session(session, "admin", user.id)
    response = client.put(
        "/v1/auth/profile", headers=headers, json={"scope": "admin", "username": "bad name"}
    )
    assert response.status_code == 422
    assert (
        client.put(
            "/v1/auth/profile",
            headers=headers,
            json={
                "scope": "admin",
                "username": "rollback.owl",
                "new_password": "forest canopy sunrise",
            },
        ).status_code
        == 200
    )
    assert (
        client.get("/v1/admin/console/me", headers={"Authorization": "Bearer " + other}).status_code
        == 401
    )
    assert (
        client.put(
            "/v1/auth/profile",
            headers=headers,
            json={"scope": "admin", "username": "rollback.owl2", "current_password": "wrong"},
        ).status_code
        == 401
    )


def test_shared_notes_conflict_and_member_roles(auth):
    client, session = auth
    owner, headers = admin(session)
    member, member_headers = admin(session, "admin")
    note = client.post(
        "/v1/admin/console/notes",
        headers=headers,
        json={"title": "Route bug", "body": "Reproduce at turn two"},
    )
    assert note.status_code == 201, note.text
    note = note.json()
    payload = {
        "title": "Route bug",
        "body": "Verified by the second user",
        "status": "done",
        "version": note["updated_at"],
    }
    updated = client.put(
        "/v1/admin/console/notes/" + note["id"], headers=member_headers, json=payload
    )
    assert updated.status_code == 200, updated.text
    assert (
        client.put(
            "/v1/admin/console/notes/" + note["id"], headers=headers, json=payload
        ).status_code
        == 409
    )
    create = {
        "username": "new.rollback",
        "password": "forest canopy sunshine",
        "display_name": "New Owl",
    }
    assert (
        client.post("/v1/admin/console/members", headers=member_headers, json=create).status_code
        == 403
    )
    created = client.post("/v1/admin/console/members", headers=headers, json=create)
    assert created.status_code == 201, created.text
    assert (
        client.patch(
            "/v1/admin/console/members/" + str(owner.id), headers=headers, json={"active": False}
        ).status_code
        == 409
    )
    assert (
        client.patch(
            "/v1/admin/console/members/" + str(member.id), headers=headers, json={"active": False}
        ).status_code
        == 200
    )
    assert client.get("/v1/admin/console/notes", headers=member_headers).status_code == 401


def test_assistant_source_boundary():
    from app.services.assistant import tool_result, files

    assert files()
    assert not any(".env" in path or path.endswith("/config.py") for path in files())
    assert tool_result("read_file", {"path": "../../backend/.env"}, None).startswith(
        "File unavailable"
    )
    assert tool_result("shell", {"command": "anything"}, None) == "Unknown tool."
