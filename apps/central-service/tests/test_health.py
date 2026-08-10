"""Health endpoint behavior (C1a)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from central_service.api.app import create_app
from central_service.api.readiness import ReadinessCheck, ReadinessResult
from central_service.api.settings import CentralSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient

_PILOT_TOKEN = "pilot-admin-token-0123456789abcdef"  # noqa: S105 - test fixture credential


def _settings() -> CentralSettings:
    """Build settings that never touch real dependencies in unit tests."""
    return CentralSettings(
        database_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        admin_token=_PILOT_TOKEN,
    )


def _app(readiness: ReadinessResult | None = None) -> FastAPI:
    if readiness is None:
        return create_app(_settings())
    return create_app(_settings(), readiness=lambda: readiness)


@pytest.fixture
def ok_readiness() -> ReadinessResult:
    """A fully healthy readiness result for unit tests."""
    return ReadinessResult(
        checks=(
            ReadinessCheck(name="database", ok=True, detail="ok"),
            ReadinessCheck(name="object_store", ok=True, detail="ok"),
            ReadinessCheck(name="credentials", ok=True, detail="ok"),
        )
    )


@pytest.fixture
def app_client() -> Callable[[ReadinessResult | None], TestClient]:
    """Return a TestClient bound to the app built with the given readiness."""

    def _client(readiness: ReadinessResult | None = None) -> TestClient:
        return TestClient(_app(readiness))

    return _client


def test_health_live_never_blocks(app_client: Callable[..., Any]) -> None:
    with app_client() as client:
        response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready_reports_ok(
    app_client: Callable[..., Any], ok_readiness: ReadinessResult
) -> None:
    with app_client(ok_readiness) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": "ok", "object_store": "ok", "credentials": "ok"}


@pytest.mark.parametrize("failing_check", ["database", "object_store", "credentials"])
def test_health_ready_fails_closed(app_client: Callable[..., Any], failing_check: str) -> None:
    result = ReadinessResult(
        checks=(
            ReadinessCheck(name="database", ok=failing_check != "database", detail="ok"),
            ReadinessCheck(name="object_store", ok=failing_check != "object_store", detail="ok"),
            ReadinessCheck(name="credentials", ok=failing_check != "credentials", detail="ok"),
        )
    )
    with app_client(result) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "NOT_READY"
    assert body["status"] == 503
    assert failing_check in body["detail"]
    assert body["request_id"]


def test_unknown_route_returns_problem(
    app_client: Callable[..., Any], ok_readiness: ReadinessResult
) -> None:
    with app_client(ok_readiness) as client:
        response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "HTTP_404"


def test_request_id_and_security_headers(
    app_client: Callable[..., Any], ok_readiness: ReadinessResult
) -> None:
    with app_client(ok_readiness) as client:
        response = client.get("/api/v1/health/live", headers={"X-Request-ID": "test-request-123"})
    assert response.headers["X-Request-ID"] == "test-request-123"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "same-origin"
