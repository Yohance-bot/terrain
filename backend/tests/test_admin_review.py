import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.deps import require_admin_operations_token
from app.core.config import settings
from app.main import app
from app.models import AuditEvent, Run, RunLifecycleEvent
from app.services import review


def test_internal_operations_are_denied_without_an_explicit_token() -> None:
    response = TestClient(app).get(f"/v1/admin/review/devices/{uuid.uuid4()}/runs")

    assert response.status_code == 403
    assert response.json() == {"detail": "Not authorized"}


def test_admin_token_is_disabled_until_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_operations_token", None)

    with pytest.raises(HTTPException) as exc_info:
        require_admin_operations_token("any-value")

    assert exc_info.value.status_code == 403


def test_admin_token_requires_an_exact_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_operations_token", SecretStr("internal-secret"))
    require_admin_operations_token("internal-secret")

    with pytest.raises(HTTPException) as exc_info:
        require_admin_operations_token("wrong-secret")

    assert exc_info.value.status_code == 403


class _ScalarResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> "_ScalarResult":
        return self

    def __iter__(self):
        return iter(self._values)


class _ReversalSession:
    def __init__(self, run: Run, territory_ids: list[uuid.UUID]) -> None:
        self.run = run
        self.territory_ids = territory_ids
        self.added: list[object] = []
        self.flush_count = 0

    def get(self, model: type[object], key: object) -> object | None:
        assert model is Run
        return self.run if key == self.run.id else None

    def execute(self, _statement: object) -> _ScalarResult:
        return _ScalarResult(self.territory_ids)

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        self.flush_count += 1


def test_manual_reversal_retains_evidence_audits_and_rebuilds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = Run(
        id=uuid.uuid4(),
        device_id=uuid.uuid4(),
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
        duration_s=1,
        distance_m=10,
        raw_payload={},
        status="applied",
        source="tracked",
        pipeline_version=1,
        ruleset_version=1,
        lifecycle_version=2,
    )
    territory_ids = [uuid.uuid4(), uuid.uuid4()]
    session = _ReversalSession(run, territory_ids)
    rebuilt: list[uuid.UUID] = []
    monkeypatch.setattr(
        review,
        "recompute_ownership",
        lambda _session, territory_id: rebuilt.append(territory_id),
    )

    outcome = review.reverse_run(
        session,
        run_id=run.id,
        operator_ref="ops@example.test",
        reason="Verified duplicate route submission",
    )

    assert run.status == "reversed"
    assert run.lifecycle_version == 3
    assert outcome.rebuilt_territory_ids == sorted(territory_ids, key=str)
    assert rebuilt == sorted(territory_ids, key=str)
    lifecycle = next(item for item in session.added if isinstance(item, RunLifecycleEvent))
    audit = next(item for item in session.added if isinstance(item, AuditEvent))
    assert lifecycle.sequence == 3
    assert lifecycle.reason == "Verified duplicate route submission"
    assert audit.before_state == {"status": "applied", "lifecycle_version": 2}
    assert audit.after_state == {"status": "reversed", "lifecycle_version": 3}
    assert session.flush_count == 2


def test_reversal_rejects_terminal_runs() -> None:
    run = Run(
        id=uuid.uuid4(),
        device_id=uuid.uuid4(),
        started_at=datetime.now(UTC),
        ended_at=datetime.now(UTC),
        duration_s=1,
        distance_m=0,
        raw_payload={},
        status="reversed",
        source="tracked",
        pipeline_version=1,
        ruleset_version=1,
        lifecycle_version=2,
    )
    session = _ReversalSession(run, [])

    with pytest.raises(HTTPException) as exc_info:
        review.reverse_run(
            session,
            run_id=run.id,
            operator_ref="ops@example.test",
            reason="Already processed",
        )

    assert exc_info.value.status_code == 409
