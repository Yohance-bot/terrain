"""Small, dependency-free request observability primitives.

Logs deliberately omit request bodies, query strings, headers, and exception
messages because those fields can carry device identifiers or other sensitive
client data.
"""

import json
import logging
import re
import sys
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError

from app.core.config import settings

REQUEST_ID_HEADER = "X-Request-ID"
RUN_ID_HEADER = "X-Run-ID"
MAX_CORRELATION_ID_LENGTH = 128
_SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)


class JsonFormatter(logging.Formatter):
    """Emit a stable, machine-readable log schema without arbitrary extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for field_name in (
            "request_id",
            "run_id",
            "method",
            "path",
            "status_code",
            "duration_ms",
            "error_type",
            "response_body",
            "validation_errors",
        ):
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _validation_log_extra(request: Request) -> dict[str, Any]:
    return {
        "request_id": request_correlation_id(request.headers.get(REQUEST_ID_HEADER)),
        "method": request.method,
        "path": request.url.path,
        "status_code": 422,
    }


def register_validation_error_logging(app: FastAPI) -> None:
    """Log complete 422 payloads locally without changing validation behavior."""

    @app.exception_handler(RequestValidationError)
    async def log_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> Response:
        if settings.log_http_422_response_bodies:
            logger.warning(
                "request_validation_failed",
                extra={
                    **_validation_log_extra(request),
                    "validation_errors": exc.errors(),
                    "response_body": json.dumps({"detail": exc.errors()}),
                },
            )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(HTTPException)
    async def log_http_exception(request: Request, exc: HTTPException) -> Response:
        if exc.status_code == 422 and settings.log_http_422_response_bodies:
            logger.warning(
                "http_422_response",
                extra={
                    **_validation_log_extra(request),
                    "response_body": json.dumps({"detail": exc.detail}),
                },
            )
        return await http_exception_handler(request, exc)


logger = logging.getLogger("run.observability")


def configure_logging() -> None:
    """Configure the dedicated logger once, without changing root logging."""
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def safe_correlation_id(value: str | None) -> str | None:
    """Return a bounded client-supplied ID, or ``None`` when it is unsafe."""
    if value and _SAFE_CORRELATION_ID.fullmatch(value):
        return value
    return None


def request_correlation_id(value: str | None) -> str:
    """Return a safe supplied request ID, generating one when absent or unsafe."""
    return safe_correlation_id(value) or uuid.uuid4().hex


def current_correlation() -> dict[str, str | None]:
    """Expose correlation context for future route/service instrumentation."""
    return {"request_id": _request_id.get(), "run_id": _run_id.get()}


@contextmanager
def run_correlation(run_id: str | None) -> Iterator[None]:
    """Bind a validated run ID to logs produced by the current context."""
    token = _run_id.set(safe_correlation_id(run_id))
    try:
        yield
    finally:
        _run_id.reset(token)


@dataclass
class RequestMetrics:
    """In-process counters suitable for an eventual metrics exporter."""

    requests_total: int = 0
    responses_by_status: Counter[int] = field(default_factory=Counter)
    failures_total: int = 0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record(self, status_code: int) -> None:
        with self._lock:
            self.requests_total += 1
            self.responses_by_status[status_code] += 1
            if status_code >= 500:
                self.failures_total += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "requests_total": self.requests_total,
                "responses_by_status": dict(self.responses_by_status),
                "failures_total": self.failures_total,
            }


def configure_observability(app: FastAPI) -> RequestMetrics:
    """Attach request correlation, safe logs, and in-process request metrics."""
    configure_logging()
    metrics = RequestMetrics()
    app.state.request_metrics = metrics
    register_validation_error_logging(app)

    @app.middleware("http")
    async def observe_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request_correlation_id(request.headers.get(REQUEST_ID_HEADER))
        run_id = safe_correlation_id(request.headers.get(RUN_ID_HEADER))
        request_token = _request_id.set(request_id)
        run_token = _run_id.set(run_id)
        started_at = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as error:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            metrics.record(500)
            logger.error(
                "http_request_failed",
                extra={
                    "request_id": request_id,
                    "run_id": run_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "error_type": type(error).__name__,
                },
            )
            raise
        else:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            metrics.record(response.status_code)
            logger.log(
                logging.ERROR if response.status_code >= 500 else logging.INFO,
                "http_request_completed",
                extra={
                    "request_id": request_id,
                    "run_id": run_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            response.headers[REQUEST_ID_HEADER] = request_id
            if run_id:
                response.headers[RUN_ID_HEADER] = run_id
            return response
        finally:
            _request_id.reset(request_token)
            _run_id.reset(run_token)

    return metrics
