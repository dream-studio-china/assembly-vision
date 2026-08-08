"""FastAPI application factory for the local edge API.

Composition root: opens the SQLite repository, reconciles existing CLI output,
builds the optional inspection pipeline, installs problem handlers, registers
the design 15.3 API routers, and serves the built frontend as static assets.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from assemblyvision_edge import __version__
from assemblyvision_edge.api.logging_buffer import LogBuffer
from assemblyvision_edge.api.problems import install_problem_handlers
from assemblyvision_edge.api.routers import (
    auth,
    camera,
    configuration,
    derived,
    device,
    health,
    inspection,
    inspections,
    logs,
    media,
    uploads,
)
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.persistence.reconcile import reconcile_output_root
from assemblyvision_edge.persistence.repository import EdgeRepository

log = logging.getLogger("assemblyvision.api")

_PROBLEM = {
    "type": "https://assemblyvision.example/problems/internal-error",
    "title": "Internal server error",
    "status": 500,
    "detail": "An unexpected error occurred; see the service log for details",
    "code": "INTERNAL_ERROR",
    "request_id": None,
    "errors": [],
}


def create_app(settings: ServerSettings, *, reconcile: bool = True) -> FastAPI:
    runtime = EdgeRuntime(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repository = EdgeRepository.open(str(settings.db_path))
        app.state.repository = repository
        app.state.runtime = runtime
        app.state.settings = settings
        app.state.log_buffer = LogBuffer()
        _install_log_handler(app.state.log_buffer)
        if reconcile:
            imported = reconcile_output_root(repository, settings.output_root)
            if imported:
                log.info("reconciled %d inspection records from output root", imported)
        runtime.load_pipeline(repository)
        if runtime.pipeline is None:
            log.warning("inspection engine is not ready: %s", runtime.pipeline_error)
        yield
        repository.close()
        logging.getLogger().removeHandler(app.state.log_buffer)

    app = FastAPI(
        title="AssemblyVision Edge API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.viewer_sessions = {}

    # The Vite dev server calls the API cross-origin during development; the
    # served dashboard is same-origin and needs no CORS. Allow only anchored
    # loopback origins (any dev port) instead of "*"; production binds the
    # service locally and authenticates via the edge API token (ADR-012). The
    # viewer-session exchange is a POST with a JSON-free Authorization header,
    # and every client request sends Content-Type, so both must pass the
    # preflight for the token-protected dev flow to work across origins.
    if settings.cors_allow_loopback:
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
        )

    install_problem_handlers(app)
    _install_exception_handler(app)

    from fastapi import Depends

    from assemblyvision_edge.api.deps import require_viewer

    for router in (
        device.router,
        camera.router,
        inspection.router,
        inspections.router,
        media.router,
        uploads.router,
        configuration.router,
        logs.router,
        derived.router,
    ):
        app.include_router(router, prefix="/api/v1", dependencies=[Depends(require_viewer)])
    app.include_router(auth.router, prefix="/api/v1")
    # Health keeps /health/live deliberately unauthenticated (design 15.3.1);
    # /health/ready requires the viewer credential.
    app.include_router(health.router, prefix="/api/v1")

    _install_static_routes(app, settings.static_dir)
    return app


def _install_log_handler(buffer: LogBuffer) -> None:
    buffer.setLevel(logging.INFO)
    root = logging.getLogger()
    root.addHandler(buffer)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)


def _install_exception_handler(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error for %s %s", request.method, request.url.path)
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        return JSONResponse(
            status_code=500,
            content={**_PROBLEM, "request_id": request_id},
            media_type="application/problem+json",
            headers={"X-Request-ID": request_id},
        )


def _install_static_routes(app: FastAPI, static_dir: Path | None) -> None:
    if static_dir is None or not static_dir.is_dir():
        return
    index = static_dir / "index.html"
    root = static_dir.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        # API routes never fall back to the SPA; unknown API paths must produce
        # a normal API 404 instead of returning the dashboard HTML (P2).
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (root / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)
