"""FastAPI application factory for the local edge API.

Composition root: opens the SQLite repository, reconciles existing CLI output,
builds the optional inspection pipeline, installs problem handlers, registers
the design 15.3 API routers, and serves the built frontend as static assets.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from assemblyvision_edge import __version__
from assemblyvision_edge.api.logging_buffer import LogBuffer
from assemblyvision_edge.api.problems import install_problem_handlers
from assemblyvision_edge.api.routers import (
    auth,
    camera,
    configuration,
    derived,
    dev,
    device,
    health,
    inspection,
    inspections,
    logs,
    media,
    uploads,
    ws,
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

# Least-privilege content security policy for the locally served dashboard
# (AUDIT-001 4.5). Element Plus and ECharts use inline style attributes, so
# 'unsafe-inline' is required for styles; media is rendered from blob URLs.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' blob: data:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'self'"
)


def create_app(settings: ServerSettings, *, reconcile: bool = True) -> FastAPI:
    # Validate at the composition root as well as the CLI path: programmatic
    # callers must not bypass the TLS/credential/storage policy (PR-017 F7
    # follow-up, E2c).
    settings.validate()
    runtime = EdgeRuntime(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repository = EdgeRepository.open(str(settings.db_path))
        app.state.repository = repository
        app.state.runtime = runtime
        app.state.settings = settings
        app.state.log_buffer = LogBuffer()
        # E4a: the in-memory runtime event bus drives the WebSocket channel;
        # REST remains authoritative and publishing never blocks the runtime.
        from assemblyvision_edge.api.events import RuntimeEventBus

        event_bus = RuntimeEventBus(source_id=str(runtime.device_id))
        runtime.event_bus = event_bus
        app.state.event_bus = event_bus
        _install_log_handler(app.state.log_buffer)
        if reconcile:
            imported = reconcile_output_root(repository, settings.output_root)
            if imported:
                log.info("reconciled %d inspection records from output root", imported)
            # Startup integrity (design 12.8, E2d): verify projected media
            # against the filesystem and recover abandoned cleanup claims
            # before any worker starts. Faults durably protect the artifact and
            # gate intake/readiness until documented reconciliation (PR-020
            # F08); checksum policy and coverage are exposed for operations
            # (PR-020 F09).
            # Full verification is the safe default. Deployments that cannot
            # afford it must explicitly configure a bounded checksum sample.
            from assemblyvision_edge.api.settings import IntegrityScanSettings
            from assemblyvision_edge.persistence.reconcile import scan_storage_integrity

            scan_settings = settings.integrity_scan or IntegrityScanSettings(verify_checksums=True)
            report = scan_storage_integrity(
                repository,
                settings.output_root,
                verify_checksums=bool(scan_settings and scan_settings.verify_checksums),
                sample_limit=scan_settings.sample_limit if scan_settings else None,
                sample_max_bytes=scan_settings.sample_max_bytes if scan_settings else None,
            )
            runtime.integrity_scan = report
            runtime.integrity_scan_at = datetime.now(UTC).isoformat()
            runtime.integrity_scan_settings = scan_settings
            integrity_fault_count = repository.retention_metrics(
                datetime.now(UTC).isoformat()
            ).integrity_fault_count
            if report.faults or integrity_fault_count:
                log.warning(
                    "storage integrity scan has %d fault(s) of %d media: %s "
                    "(checksummed %d, skipped %d)",
                    integrity_fault_count,
                    report.checked,
                    report.fault_codes,
                    report.checksum_checked,
                    report.skipped,
                )
            if integrity_fault_count:
                runtime.storage_integrity_fault = True
            repository.recover_expired_retention_claims(datetime.now(UTC).isoformat())
        runtime.load_config(repository)
        if runtime.pipeline is None and not runtime.instances:
            log.warning("inspection engine is not ready: %s", runtime.pipeline_error)
        from assemblyvision_edge.upload.scheduler import (
            DirectoryUploadSink,
            HttpUploadSink,
            UploadScheduler,
            UploadSink,
        )

        # The outbox always enqueues tasks, but the worker only drains them to
        # an explicitly configured destination. Without one, tasks accumulate
        # and stay visible in the API; they are never silently written to a
        # guessed local directory (design 13.8 requires site configuration).
        scheduler: UploadScheduler | None = None
        upload = settings.upload
        sink: UploadSink | None = None
        if upload is not None:
            if upload.sink_dir is not None:
                sink = DirectoryUploadSink(upload.sink_dir)
            elif upload.base_url:
                sink = HttpUploadSink(
                    upload.base_url,
                    token=upload.token,
                    connect_timeout_seconds=upload.connect_timeout_seconds,
                    request_timeout_seconds=upload.request_timeout_seconds,
                )
            if sink is not None:
                scheduler = UploadScheduler(
                    repository,
                    sink,
                    output_root=settings.output_root,
                    interval_seconds=upload.interval_seconds,
                    batch_size=upload.batch_size,
                    lease_seconds=upload.lease_seconds,
                    base_retry_seconds=upload.base_retry_seconds,
                    maximum_retry_seconds=upload.maximum_retry_seconds,
                    exponent_cap=upload.exponent_cap,
                    maximum_bandwidth_mbps=upload.maximum_bandwidth_mbps,
                    circuit_failure_threshold=upload.circuit_failure_threshold,
                    circuit_open_seconds=upload.circuit_open_seconds,
                    on_change=_upload_changed_notifier(event_bus),
                )
        if scheduler is None:
            log.warning(
                "upload scheduler is disabled: configure an upload sink directory "
                "or an HTTPS central endpoint (design 13.8)"
            )
        app.state.upload_scheduler = scheduler
        if scheduler is not None:
            scheduler.start()
        # Retention cleanup worker (design 12.7, E2b): only an explicitly
        # enabled, approved retention policy can ever delete local media. With
        # no policy the worker is inert and never touches the filesystem.
        from assemblyvision_edge.retention.worker import RetentionCleanupWorker

        cleanup_worker: RetentionCleanupWorker | None = None
        if settings.retention is not None and settings.retention.enabled:
            cleanup_worker = RetentionCleanupWorker(
                repository,
                settings.output_root,
                settings.retention.to_policy(),
                lease_seconds=300,
                batch_size=16,
            )
            cleanup_worker.start()
        app.state.cleanup_worker = cleanup_worker
        yield
        if cleanup_worker is not None:
            cleanup_worker.stop()
        if scheduler is not None:
            scheduler.stop()
        runtime.shutdown()
        repository.close()
        logging.getLogger().removeHandler(app.state.log_buffer)

    app = FastAPI(
        title="AssemblyVision Edge API",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.viewer_sessions = {}
    app.state.auth_failures = {}

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

    @app.middleware("http")
    async def _security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", _CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

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
    # The dev router declares its own enablement gate ahead of viewer
    # authentication, so a disabled harness returns 404 DEV_TOOLS_DISABLED
    # before any credential check while enabled endpoints keep auth (F8).
    app.include_router(dev.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    # The runtime event channel performs its own credential check before
    # accepting the socket (E4a), consistent with the REST viewer model.
    app.include_router(ws.router, prefix="/api/v1")
    # Health keeps /health/live deliberately unauthenticated (design 15.3.1);
    # /health/ready requires the viewer credential.
    app.include_router(health.router, prefix="/api/v1")

    _install_static_routes(app, settings.static_dir)
    return app


def _upload_changed_notifier(event_bus: Any) -> Callable[[], None]:
    """Return the scheduler change callback that pushes a transient event."""

    def notify() -> None:
        event_bus.publish("upload.changed", {"event": "batch_processed"})

    return notify


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
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (root / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)
