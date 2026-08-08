"""Edge API viewer authentication and CORS boundary tests (F3, ADR-012)."""

from __future__ import annotations

from pathlib import Path

import pytest
from assemblyvision_edge.api.app import create_app
from assemblyvision_edge.api.settings import ServerSettings
from fastapi.testclient import TestClient


@pytest.fixture
def token_settings(tmp_path: Path) -> ServerSettings:
    return ServerSettings(
        output_root=tmp_path / "out",
        db_path=tmp_path / "edge.sqlite3",
        api_token="test-edge-token",  # noqa: S106 - test fixture credential
    )


def test_health_live_is_open_without_token(token_settings: ServerSettings) -> None:
    app = create_app(token_settings)
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_read_routes_require_token_when_configured(token_settings: ServerSettings) -> None:
    app = create_app(token_settings)
    with TestClient(app) as client:
        for path in ("/api/v1/inspections", "/api/v1/health/ready", "/api/v1/device/status"):
            denied = client.get(path)
            assert denied.status_code == 401, path
            assert denied.json()["code"] == "UNAUTHENTICATED"
            wrong = client.get(path, headers={"Authorization": "Bearer wrong"})
            assert wrong.status_code == 401
            allowed = client.get(path, headers={"Authorization": "Bearer test-edge-token"})
            assert allowed.status_code in (200, 503), path


def test_viewer_session_authenticates_api_and_media(token_settings: ServerSettings) -> None:
    app = create_app(token_settings)
    with TestClient(app) as client:
        denied = client.post("/api/v1/auth/session")
        assert denied.status_code == 401

        created = client.post(
            "/api/v1/auth/session",
            headers={"Authorization": "Bearer test-edge-token"},
        )
        assert created.status_code == 204
        assert "av_edge_viewer_session" in created.headers["set-cookie"]
        assert "HttpOnly" in created.headers["set-cookie"]
        assert "SameSite=strict" in created.headers["set-cookie"]
        assert client.get("/api/v1/inspections").status_code == 200
        assert client.get("/api/v1/media/missing/content").status_code == 404


def test_removed_mutations_are_404_even_with_token(token_settings: ServerSettings) -> None:
    app = create_app(token_settings)
    with TestClient(app) as client:
        for endpoint, payload in (
            ("/api/v1/inspection/pause", {"reason": "shift change"}),
            ("/api/v1/inspection/resume", {"reason": "shift start"}),
            ("/api/v1/camera/reconnect", {"reason": "fault"}),
        ):
            response = client.post(
                endpoint, json=payload, headers={"Authorization": "Bearer test-edge-token"}
            )
            assert response.status_code == 404, endpoint


def test_unauthenticated_dev_mode_when_token_unset(tmp_path: Path) -> None:
    settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/v1/inspections").status_code == 200


def test_cors_rejects_unapproved_origin(token_settings: ServerSettings) -> None:
    app = create_app(token_settings)
    with TestClient(app) as client:
        preflight = client.options(
            "/api/v1/inspections",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert "access-control-allow-origin" not in preflight.headers
        actual = client.get(
            "/api/v1/inspections",
            headers={
                "Origin": "http://evil.example",
                "Authorization": "Bearer test-edge-token",
            },
        )
        assert "access-control-allow-origin" not in actual.headers


def test_cors_allows_loopback_dev_origin(token_settings: ServerSettings) -> None:
    app = create_app(token_settings)
    with TestClient(app) as client:
        preflight = client.options(
            "/api/v1/inspections",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_allows_token_protected_dev_preflight(token_settings: ServerSettings) -> None:
    """Cross-origin Vite dev against a token-protected host must pass preflight.

    The viewer-session exchange is a POST carrying only the Authorization
    header, and every client request also sends ``Content-Type: application/json``,
    so both headers and the POST method must be allowed for loopback origins
    (gap 1).
    """
    app = create_app(token_settings)
    with TestClient(app) as client:
        for method in ("GET", "POST"):
            preflight = client.options(
                "/api/v1/auth/session",
                headers={
                    "Origin": "http://127.0.0.1:5173",
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "Authorization, Content-Type",
                },
            )
            assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
            assert method in preflight.headers["access-control-allow-methods"]
            allowed_headers = preflight.headers["access-control-allow-headers"].lower()
            assert "content-type" in allowed_headers
            assert "authorization" in allowed_headers

        session = client.post(
            "/api/v1/auth/session",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Authorization": "Bearer test-edge-token",
            },
        )
        assert session.status_code == 204
        assert session.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_cors_disabled_when_loopback_off(tmp_path: Path) -> None:
    settings = ServerSettings(
        output_root=tmp_path / "out",
        db_path=tmp_path / "edge.sqlite3",
        cors_allow_loopback=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        preflight = client.options(
            "/api/v1/inspections",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert "access-control-allow-origin" not in preflight.headers
