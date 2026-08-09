"""Device status endpoint (design 15.3.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from assemblyvision_edge.api.deps import get_repository, get_runtime
from assemblyvision_edge.api.schemas import DeviceStatus
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(prefix="/device", tags=["device"])


@router.get("/status", response_model=DeviceStatus)
def device_status(
    request: Request,
    runtime: EdgeRuntime = Depends(get_runtime),
    repository: EdgeRepository = Depends(get_repository),
) -> DeviceStatus:
    queue = repository.upload_queue_metrics()
    scheduler = request.app.state.upload_scheduler
    health = scheduler.health() if scheduler is not None else None
    return DeviceStatus.model_validate(
        runtime.device_status(
            repository.count_pending_uploads(), queue, health, scheduler is not None
        )
    )
