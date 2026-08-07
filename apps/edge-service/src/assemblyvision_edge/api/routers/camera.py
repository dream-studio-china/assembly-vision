"""Camera state endpoints (design 15.3.1, M1 static placeholder)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from assemblyvision_edge.api.deps import get_runtime
from assemblyvision_edge.api.state import EdgeRuntime

router = APIRouter(prefix="/camera", tags=["camera"])


class CameraReconnectRequest(BaseModel):
    reason: str = "operator requested"


@router.get("/state")
def camera_state(runtime: EdgeRuntime = Depends(get_runtime)) -> dict[str, object]:
    return runtime.camera_state()


@router.post("/reconnect")
def camera_reconnect(
    _body: CameraReconnectRequest,
    runtime: EdgeRuntime = Depends(get_runtime),
) -> dict[str, object]:
    # Static placeholder adapter has nothing to reconnect (M1).
    return {"accepted": True, "operation_id": None, "detail": None}
