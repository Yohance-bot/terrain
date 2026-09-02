"""Privacy retention tests that do not require a PostGIS instance."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Device, DeviceProfile, Run
from app.services import privacy


class ScalarRows:
    def __init__(self, rows: list[Run]):
        self.rows = rows

    def all(self) -> list[Run]:
        return self.rows


class DeviceDeletionSession:
    def __init__(self, device: Device, profile: DeviceProfile | None, runs: list[Run]):
        self.device = device
        self.profile = profile
        self.runs = runs
        self.deleted: list[object] = []
        self.flush_count = 0

    def get(self, model: type[object], key: object) -> object | None:
        if model is Device:
            return self.device if key == self.device.id else None
        if model is DeviceProfile:
            return self.profile
        raise AssertionError(f"unexpected lookup: {model}")

    def scalars(self, statement: object) -> ScalarRows:
        return ScalarRows(self.runs)

    def delete(self, value: object) -> None:
        self.deleted.append(value)

    def flush(self) -> None:
        self.flush_count += 1


class RetentionSession:
    def __init__(self, runs: list[Run]):
        self.runs = runs
        self.executed_statement: object | None = None
        self.executed_params: object | None = None

    def scalars(self, statement: object) -> ScalarRows:
        return ScalarRows(self.runs)

    def execute(self, statement: object, params: object) -> object:
        self.executed_statement = statement
        self.executed_params = params
        return type("Result", (), {"rowcount": 2})()


def _run() -> Run:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    return Run(
        id=uuid.uuid4(),
        device_id=uuid.uuid4(),
        started_at=now - timedelta(minutes=10),
        ended_at=now,
        duration_s=600,
        raw_payload={"samples": [{"lat": 12.9, "lon": 77.6}]},
        sample_ts=[1],
        sample_accuracy_m=[3.0],
        pipeline_version=1,
    )


def test_retention_erases_only_raw_trace_fields() -> None:
    run = _run()
    run.distance_m = 1_234
    now = datetime(2026, 10, 12, tzinfo=UTC)
    session = RetentionSession([run])

    result = privacy.enforce_retention(session, now=now)

    assert result.raw_traces_deleted == 1
    assert result.route_polylines_reduced == 2
    assert run.raw_payload == {}
    assert run.sample_ts is None
    assert run.sample_accuracy_m is None
    assert run.raw_trace_deleted_at == now
    assert run.distance_m == 1_234
    assert session.executed_params == {"simplification_m": 25.0}


def test_retention_policy_is_available_without_device_identity() -> None:
    response = TestClient(app).get("/v1/privacy/retention")

    assert response.status_code == 200
    assert response.json() == {
        "raw_trace_retention_days": 30,
        "route_polyline_full_precision_days": 90,
    }


def test_device_deletion_removes_personal_data_but_not_derived_history() -> None:
    device = Device(id=uuid.uuid4(), label="personal label")
    profile = DeviceProfile(device_id=device.id, home_selection_note="near home")
    run = _run()
    run.device_id = device.id
    derived_distance = 777
    run.distance_m = derived_distance
    session = DeviceDeletionSession(device, profile, [run])
    now = datetime(2026, 8, 12, tzinfo=UTC)

    result = privacy.anonymize_device(session, device_id=device.id, now=now)

    assert result.raw_traces_deleted == 1
    assert device.label is None
    assert device.privacy_deleted_at == now
    assert profile in session.deleted
    assert run.raw_payload == {}
    assert run.geom is None
    assert run.distance_m == derived_distance
    assert session.flush_count == 1


def test_device_deletion_rejects_unknown_device() -> None:
    device = Device(id=uuid.uuid4())
    session = DeviceDeletionSession(device, None, [])

    with pytest.raises(Exception) as exc_info:
        privacy.anonymize_device(session, device_id=uuid.uuid4())

    assert getattr(exc_info.value, "status_code", None) == 404
