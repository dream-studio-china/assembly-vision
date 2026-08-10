"""FastAPI application factory for the central server.

Composition root: validates settings, opens the PostgreSQL engine, bootstraps
the object-store bucket (idempotent), installs problem handlers and security
headers, and registers the design 05 API routers. Migrations are never
applied automatically; readiness reports schema state instead.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from central_service import __version__
from central_service.api.problems import install_problem_handlers
from central_service.api.readiness import (
    ReadinessResult,
    compute_readiness,
)
from central_service.api.routers import health
from central_service.api.settings import CentralSettings
from central_service.observability.logging import configure_logging
from central_service.persistence.engine import create_database_engine
from central_service.persistence.migrate import applied_revision, current_head
from central_service.storage.object_store import MinioObjectStorage, ObjectStorageSettings

log = logging.getLogger("central_service.api")

_PROBLEM = {
    "type": "https://assemblyvision.example/problems/internal-error",
    "title": "Internal server error",
    "status": 500,
    "detail": "An unexpected error occurred; see the service log for details",
    "code": "INTERNAL_ERROR",
    "request_id": None,
    "errors": [],
}

# Least-privilege content security policy for the pilot administration UI
# (admin-web assets are served separately behind the API in Compose).
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' blob: data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'self'"
)

ReadinessProvider = Callable[[], ReadinessResult]


def create_app(settings: CentralSettings, *, readiness: ReadinessProvider | None = None) -> FastAPI:
    """Build the central FastAPI application.

    ``readiness`` may be injected in tests; the default probes the live
    engine, object store, and credential configuration on every call.
    """
    configure_logging()
    settings.validate_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database_engine(settings.database_url)
        storage = MinioObjectStorage(
            ObjectStorageSettings(
                endpoint=settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                bucket=settings.minio_bucket,
                secure=settings.minio_secure,
            )
        )
        # The API must not auto-migrate (controlled release step); verify
        # schema state and object-store access without failing startup so
        # readiness can report dependency outages to the orchestrator.
        try:
            applied = applied_revision(engine)
        except Exception:  # noqa: BLE001 - startup must tolerate dependency outages
            log.warning("cannot read central schema state at startup", exc_info=True)
            applied = None
        if applied != current_head():
            log.warning(
                "central schema is at revision %s; expected %s - run "
                "`python -m central_service migrate`",
                applied,
                current_head(),
            )
        try:
            storage.ensure_bucket()
        except Exception:  # noqa: BLE001 - startup must tolerate dependency outages
            log.warning("cannot ensure central object-store bucket at startup", exc_info=True)
        app.state.engine = engine
        app.state.storage = storage
        app.state.settings = settings
        app.state.readiness = readiness or (lambda: compute_readiness(engine, storage, settings))
        yield
        engine.dispose()

    app = FastAPI(
        title="AssemblyVision Central API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings

    if settings.cors_allow_loopback:
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "If-Match"],
            allow_credentials=False,
        )

    install_problem_handlers(app)
    _install_exception_handler(app)

    @app.middleware("http")
    async def _correlate_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers.setdefault("X-Request-ID", request_id)
        response.headers.setdefault("Content-Security-Policy", _CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    app.include_router(health.router, prefix="/api/v1")
    return app


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


def app_factory() -> FastAPI:
    """Build the application from environment settings (uvicorn factory)."""
    settings = CentralSettings()
    return create_app(settings)
