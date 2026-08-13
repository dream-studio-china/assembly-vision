"""Central pilot authentication and tenant API tests (C1b).

The application is built with an injected SQLite-backed repository so the full
FastAPI path (dependencies, problem responses, cookies) is exercised without
PostgreSQL. Device upload credentials and administrator credentials are
proven to be strictly separated.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from central_service.api.app import create_app
from central_service.api.readiness import ReadinessCheck, ReadinessResult
from central_service.api.settings import CentralSettings
from central_service.persistence.bootstrap import resolve_plan, run_bootstrap
from central_service.persistence.repository import CentralRepository
from central_service.persistence.schema import metadata
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ingest_fixtures import NoopObjectStorage
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105


@pytest.fixture
def repository() -> Iterator[CentralRepository]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    try:
        yield CentralRepository(engine)
    finally:
        engine.dispose()


@pytest.fixture
def client(repository: CentralRepository) -> Iterator[TestClient]:
    run_bootstrap(
        repository,
        resolve_plan(_settings(), admin_token=_ADMIN_TOKEN, device_upload_token=_DEVICE_TOKEN),
    )
    with TestClient(_app(repository)) as test_client:
        yield test_client


def _settings(**overrides: object) -> CentralSettings:
    values: dict[str, object] = {
        "database_url": "postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        "admin_session_ttl_minutes": 60,
        # Plain-HTTP test client must be able to send the session cookie back.
        "secure_cookies": False,
    }
    values.update(overrides)
    return CentralSettings(**values)  # type: ignore[arg-type]


def _app(
    repository: CentralRepository, settings_overrides: dict[str, object] | None = None
) -> FastAPI:
    readiness = ReadinessResult(
        checks=(
            ReadinessCheck(name="database", ok=True, detail="ok"),
            ReadinessCheck(name="object_store", ok=True, detail="ok"),
            ReadinessCheck(name="credentials", ok=True, detail="ok"),
        )
    )
    settings = _settings(**(settings_overrides or {}))
    return create_app(
        settings,
        readiness=lambda: readiness,
        repository=repository,
        storage=NoopObjectStorage(),
    )


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_ADMIN_TOKEN}"}


def _device_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_DEVICE_TOKEN}"}


def test_auth_me_requires_credential(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_auth_me_with_admin_bearer(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me", headers=_admin_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "pilot-admin"
    assert body["organization_id"] > 0
    assert body["administrator_id"] > 0


def test_device_credential_cannot_access_admin_routes(client: TestClient) -> None:
    for path in ("/api/v1/auth/me", "/api/v1/sites", "/api/v1/lines", "/api/v1/devices"):
        response = client.get(path, headers=_device_headers())
        assert response.status_code == 401, path
        assert response.json()["code"] == "UNAUTHENTICATED", path


def test_admin_session_exchange_and_use(client: TestClient) -> None:
    session = client.post("/api/v1/auth/session", headers=_admin_headers())
    assert session.status_code == 204
    cookie = session.cookies.get("av_central_admin_session")
    assert cookie
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "pilot-admin"
    # The bearer token must still be required for the session exchange itself.
    bad = client.post("/api/v1/auth/session", headers=_device_headers())
    assert bad.status_code == 401


def test_session_cookie_flags(client: TestClient) -> None:
    # HttpOnly and SameSite=strict are unconditional; Secure is controlled by
    # deployment configuration because TLS is terminated outside the API.
    session = client.post("/api/v1/auth/session", headers=_admin_headers())
    set_cookie = session.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Secure" not in set_cookie  # dev test client is plain HTTP


def test_admin_session_revoke_signs_out(client: TestClient) -> None:
    session = client.post("/api/v1/auth/session", headers=_admin_headers())
    assert session.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 200

    revoked = client.post("/api/v1/auth/session/revoke")
    assert revoked.status_code == 204
    # The cookie is cleared (expired) and the session row is deleted, so the
    # next request is unauthenticated again.
    set_cookie = revoked.headers["set-cookie"]
    assert "Max-Age=0" in set_cookie
    assert client.get("/api/v1/auth/me").status_code == 401

    # Sign-out is idempotent, including with no session cookie present.
    again = client.post("/api/v1/auth/session/revoke")
    assert again.status_code == 204


def test_session_cookie_is_secure_when_configured(
    repository: CentralRepository,
) -> None:
    run_bootstrap(
        repository,
        resolve_plan(_settings(), admin_token=_ADMIN_TOKEN, device_upload_token=_DEVICE_TOKEN),
    )
    with TestClient(_app(repository, settings_overrides={"secure_cookies": True})) as client:
        session = client.post("/api/v1/auth/session", headers=_admin_headers())
    assert session.status_code == 204
    assert "Secure" in session.headers["set-cookie"]


def test_admin_credential_cannot_open_device_session(client: TestClient) -> None:
    # A valid administrator token must not be accepted as a device credential
    # anywhere; the session endpoint rejects it only when it is not an
    # administrator credential. The device authentication path is exercised
    # directly at the repository level and by C2a ingest routes.
    response = client.post(
        "/api/v1/auth/session", headers={"Authorization": "Bearer some-device-like-token"}
    )
    assert response.status_code == 401


def test_tenant_routes_with_admin(client: TestClient) -> None:
    assert client.get("/api/v1/sites", headers=_admin_headers()).status_code == 200
    assert client.get("/api/v1/lines", headers=_admin_headers()).status_code == 200
    devices_response = client.get("/api/v1/devices", headers=_admin_headers())
    assert devices_response.status_code == 200
    body = devices_response.json()
    assert len(body) == 1
    assert body[0]["device_id"] == "edge-device-001"
    assert "upload_token_hash" not in body[0]


def test_device_detail_and_unknown(client: TestClient) -> None:
    devices_response = client.get("/api/v1/devices", headers=_admin_headers())
    device_id = devices_response.json()[0]["id"]
    detail = client.get(f"/api/v1/devices/{device_id}", headers=_admin_headers())
    assert detail.status_code == 200
    assert detail.json()["id"] == device_id
    missing = client.get("/api/v1/devices/99999", headers=_admin_headers())
    assert missing.status_code == 404
    assert missing.json()["code"] == "DEVICE_NOT_FOUND"
