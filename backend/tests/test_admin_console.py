"""Console regressions inside an outer rollback transaction; never commit fixtures."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from app.api.v1 import admin_dashboard
from app.core.config import settings
from app.core.db import SessionLocal, engine, get_session
from app.main import app
from app.models import Account, AuditEvent, Device, DeviceLink, Run


@pytest.fixture()
def console(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    monkeypatch.setattr(settings, "admin_operations_token", SecretStr("console-test-only"))
    monkeypatch.setattr(settings, "developer_mode_enabled", True)
    app.dependency_overrides[get_session] = lambda: session
    try:
        yield TestClient(app), session, {"X-Admin-Token": "console-test-only"}
    finally:
        app.dependency_overrides.pop(get_session, None)
        session.close()
        transaction.rollback()
        connection.close()


def test_admin_rejects_unauthorized_before_query(console):
    client, _, _ = console
    assert client.get("/v1/admin/dashboard/system").status_code == 403
    assert client.post("/v1/admin/dashboard/simulate", json={}).status_code == 403


def test_pagination_is_bounded(console):
    client, _, headers = console
    for query in ("limit=1000", "offset=-1"):
        assert (
            client.get(f"/v1/admin/dashboard/players?{query}", headers=headers).status_code == 422
        )


def test_multi_device_player_is_one_row_with_combined_distance(console):
    client, session, headers = console
    account = Account(display_name="console-rollback-fixture", role="player")
    session.add(account)
    session.flush()
    for distance in (125, 275):
        device = Device(id=uuid.uuid4())
        session.add(device)
        session.flush()
        session.add(DeviceLink(device_id=device.id, account_id=account.id))
        now = datetime.now(UTC)
        session.add(
            Run(
                id=uuid.uuid4(),
                device_id=device.id,
                started_at=now,
                ended_at=now + timedelta(seconds=60),
                duration_s=60,
                distance_m=distance,
                raw_payload={},
                status="applied",
                pipeline_version=1,
            )
        )
    session.flush()
    response = client.get("/v1/admin/dashboard/players?limit=100", headers=headers)
    assert response.status_code == 200
    rows = [r for r in response.json()["items"] if r["account_id"] == str(account.id)]
    assert len(rows) == 1
    assert rows[0]["total_distance_m"] == 400
    assert len(rows[0]["device_ids"]) == 2


def test_simulation_is_audited_and_idempotent(console, monkeypatch):
    client, session, headers = console
    account = Account(display_name="console-rollback-developer", role="developer")
    device = Device(id=uuid.uuid4())
    session.add_all([account, device])
    session.flush()
    session.add(DeviceLink(device_id=device.id, account_id=account.id))
    session.flush()
    monkeypatch.setattr(
        admin_dashboard, "DEVELOPER_DEVICE_IDS", (device.id, uuid.uuid4(), uuid.uuid4())
    )
    now = datetime.now(UTC)
    payload = {
        "slot": 1,
        "operator_ref": "test",
        "reason": "rollback verification",
        "run": {
            "run_id": str(uuid.uuid4()),
            "started_at": now.isoformat(),
            "ended_at": (now + timedelta(seconds=20)).isoformat(),
            "samples": [
                {"ts": int(now.timestamp() * 1000), "lat": 0, "lon": 0, "accuracy_m": 5},
                {
                    "ts": int(now.timestamp() * 1000) + 20000,
                    "lat": 0,
                    "lon": 0.0004,
                    "accuracy_m": 5,
                },
            ],
        },
    }
    first = client.post("/v1/admin/dashboard/simulate", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "applied"
    second = client.post("/v1/admin/dashboard/simulate", headers=headers, json=payload)
    assert second.json() == first.json()
    events = session.scalars(
        select(AuditEvent).where(
            AuditEvent.target_ref == payload["run"]["run_id"], AuditEvent.action == "run.simulated"
        )
    ).all()
    assert len(events) == 1
    assert events[0].reason == "rollback verification"
    detail = client.get(f"/v1/admin/dashboard/runs/{payload['run']['run_id']}", headers=headers)
    assert detail.json()["simulation"] is True
    assert detail.json()["geometry"]["type"] == "LineString"
    # An existing developer run cannot be replayed under another slot.
    payload["slot"] = 2
    assert (
        client.post("/v1/admin/dashboard/simulate", headers=headers, json=payload).status_code
        == 409
    )


def test_simulation_disabled(console, monkeypatch):
    client, _, headers = console
    monkeypatch.setattr(settings, "developer_mode_enabled", False)
    now = datetime.now(UTC).isoformat()
    response = client.post(
        "/v1/admin/dashboard/simulate",
        headers=headers,
        json={
            "slot": 1,
            "operator_ref": "test",
            "reason": "test",
            "run": {"run_id": str(uuid.uuid4()), "started_at": now, "ended_at": now, "samples": []},
        },
    )
    assert response.status_code == 403
