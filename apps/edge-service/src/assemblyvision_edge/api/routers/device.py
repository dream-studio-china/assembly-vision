"""Device status endpoint (design 15.3.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from assemblyvision_edge.api.deps import get_repository, get_runtime
from assemblyvision_edge.api.schemas import DeviceStatus
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(prefix="/device", tags=["device"])


@router.get("/status", response_model=DeviceStatus)
def device_status(
    runtime: EdgeRuntime = Depends(get_runtime),
    repository: EdgeRepository = Depends(get_repository),
) -> DeviceStatus:
    return DeviceStatus.model_validate(runtime.device_status(repository.count_pending_uploads()))
