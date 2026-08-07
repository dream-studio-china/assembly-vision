"""Health endpoints (design 15.3.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from assemblyvision_edge.api.deps import get_repository, get_runtime
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def health_live() -> dict[str, str]:
    """Process liveness only; never blocks on dependencies."""
    return {"status": "ok"}


@router.get("/ready")
def health_ready(
    runtime: EdgeRuntime = Depends(get_runtime),
    repository: EdgeRepository = Depends(get_repository),
) -> dict[str, object]:
    if runtime.pipeline is None:
        raise ApiProblem(
            status_code=503,
            code="NOT_READY",
            detail="inspection engine is not ready",
        )
    return runtime.device_status(repository.count_pending_uploads())
