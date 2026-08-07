"""Camera state endpoint (design 15.3.1, M1 static placeholder)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from assemblyvision_edge.api.deps import get_runtime
from assemblyvision_edge.api.schemas import CameraState
from assemblyvision_edge.api.state import EdgeRuntime

router = APIRouter(prefix="/camera", tags=["camera"])


@router.get("/state", response_model=CameraState)
def camera_state(runtime: EdgeRuntime = Depends(get_runtime)) -> CameraState:
    return CameraState.model_validate(runtime.camera_state())
