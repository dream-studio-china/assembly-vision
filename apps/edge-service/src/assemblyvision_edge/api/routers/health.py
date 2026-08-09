"""Health endpoints (design 15.3.1)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from assemblyvision_edge.api.deps import get_repository, get_runtime, require_viewer
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.schemas import DeviceStatus, HealthLive
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthLive)
def health_live() -> HealthLive:
    """Process liveness only; never blocks on dependencies."""
    return HealthLive(status="ok")


@router.get("/ready", response_model=DeviceStatus)
def health_ready(
    request: Request,
    runtime: EdgeRuntime = Depends(get_runtime),
    repository: EdgeRepository = Depends(get_repository),
    _: None = Depends(require_viewer),
) -> DeviceStatus:
    if runtime.pipeline is None:
        raise ApiProblem(
            status_code=503,
            code="NOT_READY",
            detail="inspection engine is not ready",
        )
    queue = repository.upload_queue_metrics()
    scheduler = request.app.state.upload_scheduler
    health = scheduler.health() if scheduler is not None else None
    cleanup = request.app.state.cleanup_worker
    now_iso = datetime.now(UTC).isoformat()
    cleanup_health = cleanup.health() if cleanup is not None else None
    cleanup_metrics = repository.retention_metrics(now_iso)
    return DeviceStatus.model_validate(
        runtime.device_status(
            repository.count_pending_uploads(),
            queue,
            health,
            scheduler is not None,
            cleanup=cleanup_health,
            cleanup_metrics=cleanup_metrics,
            cleanup_enabled=cleanup is not None and cleanup.enabled,
        )
    )
