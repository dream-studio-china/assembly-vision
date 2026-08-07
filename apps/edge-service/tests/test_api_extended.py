"""Extended API tests: health-ready with pipeline, M1 mutation removal, SPA
api-prefix branch, HTTP-problem handler, and __main__ module."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from assemblyvision_edge.api.app import create_app
from assemblyvision_edge.api.settings import ServerSettings
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from tests.test_state import _fake_pipeline


def _app_state(c: TestClient) -> FastAPI:
    return cast(FastAPI, c.app)


def _app(tmp_path: Path, *, static: bool = False) -> FastAPI:
    root = tmp_path / "out"
    root.mkdir(exist_ok=True)
    static_dir = None
    if static:
        static_dir = tmp_path / "dist"
        static_dir.mkdir(exist_ok=True)
        static_dir.joinpath("index.html").write_text("<html>index</html>")
    return create_app(
        ServerSettings(output_root=root, db_path=tmp_path / "edge.sqlite3", static_dir=static_dir)
    )


def test_health_ready_ok_with_pipeline(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        app_state = _app_state(c)
        app_state.state.runtime.pipeline = _fake_pipeline()
        response = c.get("/api/v1/health/ready")
        assert response.status_code == 200
        assert response.json()["inspection_ready"] is True


def test_m1_removed_mutations_return_404_with_pipeline(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        app_state = _app_state(c)
        app_state.state.runtime.pipeline = _fake_pipeline()
        for endpoint, payload in (
            ("/api/v1/inspection/pause", {"reason": "break"}),
            ("/api/v1/inspection/resume", {"reason": "back"}),
        ):
            response = c.post(endpoint, json=payload)
            assert response.status_code == 404, endpoint


def test_spa_returns_index_for_unknown_api_path(tmp_path: Path) -> None:
    app = _app(tmp_path, static=True)
    with TestClient(app) as c:
        response = c.get("/api/v1/no-such-route")
        assert response.status_code == 200
        assert response.text == "<html>index</html>"


def test_http_problem_handler_with_header(tmp_path: Path) -> None:
    app = _app(tmp_path)

    @app.get("/api/v1/_http", include_in_schema=False)
    def http_boom() -> None:
        raise HTTPException(
            status_code=409, detail="conflict", headers={"X-Problem-Code": "CUSTOM_CODE"}
        )

    with TestClient(app) as c:
        response = c.get("/api/v1/_http")
        assert response.status_code == 409
        assert response.json()["code"] == "CUSTOM_CODE"
        assert response.headers["content-type"].startswith("application/problem+json")


def test_http_problem_handler_falls_back_to_http_code(tmp_path: Path) -> None:
    app = _app(tmp_path)

    @app.get("/api/v1/_http2", include_in_schema=False)
    def http_boom2() -> None:
        raise HTTPException(status_code=418, detail="teapot")

    with TestClient(app) as c:
        response = c.get("/api/v1/_http2")
        assert response.status_code == 418
        assert response.json()["code"] == "HTTP_418"


def test_request_id_preserved_from_header(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as c:
        response = c.get("/api/v1/inspections/nope", headers={"X-Request-ID": "rid-123"})
        assert response.status_code == 404
        assert response.json()["request_id"] == "rid-123"


def test_main_module_entrypoint(tmp_path: Path) -> None:
    import runpy

    import pytest

    with pytest.raises(SystemExit):
        runpy.run_module("assemblyvision_edge", run_name="__main__")
