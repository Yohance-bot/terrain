import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core import observability


class CapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []
        self.setFormatter(observability.JsonFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(self.format(record))


def test_request_and_run_correlation_are_logged_and_returned() -> None:
    app = FastAPI()
    metrics = observability.configure_observability(app)

    @app.get("/context")
    def context() -> dict[str, str | None]:
        return observability.current_correlation()

    handler = CapturingHandler()
    observability.logger.addHandler(handler)
    try:
        response = TestClient(app).get(
            "/context",
            headers={"X-Request-ID": "request-123", "X-Run-ID": "run-456"},
        )
    finally:
        observability.logger.removeHandler(handler)

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-123"
    assert response.headers["X-Run-ID"] == "run-456"
    assert response.json() == {"request_id": "request-123", "run_id": "run-456"}
    assert metrics.snapshot() == {
        "requests_total": 1,
        "responses_by_status": {200: 1},
        "failures_total": 0,
    }
    log = json.loads(handler.messages[-1])
    assert log["event"] == "http_request_completed"
    assert log["request_id"] == "request-123"
    assert log["run_id"] == "run-456"
    assert log["status_code"] == 200
    assert log["path"] == "/context"


def test_error_logs_exclude_query_and_exception_message() -> None:
    app = FastAPI()
    metrics = observability.configure_observability(app)

    @app.get("/explode")
    def explode() -> None:
        raise ValueError("password=do-not-log")

    handler = CapturingHandler()
    observability.logger.addHandler(handler)
    try:
        response = TestClient(app, raise_server_exceptions=False).get(
            "/explode?token=do-not-log",
            headers={"X-Request-ID": "request-789"},
        )
    finally:
        observability.logger.removeHandler(handler)

    assert response.status_code == 500
    assert metrics.snapshot()["failures_total"] == 1
    error_log = handler.messages[-1]
    assert "do-not-log" not in error_log
    assert json.loads(error_log)["error_type"] == "ValueError"
    assert json.loads(error_log)["path"] == "/explode"


def test_http_422_response_body_is_logged() -> None:
    app = FastAPI()
    observability.configure_observability(app)

    @app.get("/reject")
    def reject() -> None:
        raise HTTPException(status_code=422, detail="example rejection")

    handler = CapturingHandler()
    observability.logger.addHandler(handler)
    try:
        response = TestClient(app).get("/reject")
    finally:
        observability.logger.removeHandler(handler)

    assert response.status_code == 422
    validation_log = next(
        log for log in map(json.loads, handler.messages) if log["event"] == "http_422_response"
    )
    assert json.loads(validation_log["response_body"]) == {"detail": "example rejection"}
    assert validation_log["status_code"] == 422


def test_request_validation_error_is_logged() -> None:
    app = FastAPI()
    observability.configure_observability(app)

    class Payload(BaseModel):
        required_field: str

    @app.post("/validate")
    def validate(payload: Payload) -> dict[str, str]:
        return {"ok": "yes"}

    handler = CapturingHandler()
    observability.logger.addHandler(handler)
    try:
        response = TestClient(app).post("/validate", json={})
    finally:
        observability.logger.removeHandler(handler)

    assert response.status_code == 422
    validation_log = next(
        log for log in map(json.loads, handler.messages)
        if log["event"] == "request_validation_failed"
    )
    assert validation_log["validation_errors"]
    assert '"detail"' in validation_log["response_body"]
