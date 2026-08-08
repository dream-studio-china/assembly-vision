"""Camera state and preview endpoints (design 15.3.1, ADR-013)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from assemblyvision_edge.api.deps import get_runtime
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.schemas import CameraState
from assemblyvision_edge.api.state import EdgeRuntime

router = APIRouter(prefix="/camera", tags=["camera"])


@router.get("/state", response_model=CameraState)
def camera_state(
    instance_id: str | None = None, runtime: EdgeRuntime = Depends(get_runtime)
) -> CameraState:
    """Camera connection and capture settings; per-instance when requested."""
    if instance_id is not None:
        state = runtime.instance_camera_state(instance_id)
        if state is None:
            raise ApiProblem(
                status_code=404,
                code="INSTANCE_NOT_FOUND",
                detail=f"no camera instance {instance_id}",
            )
        return CameraState.model_validate(state)
    return CameraState.model_validate(runtime.camera_state())


@router.get("/{instance_id}/preview")
def camera_preview(instance_id: str, runtime: EdgeRuntime = Depends(get_runtime)) -> Response:
    """Return the latest captured frame as a rate-limited JPEG (ADR-013)."""
    preview = runtime.preview_jpeg(instance_id)
    if preview is not None:
        data, _ = preview
        return Response(content=data, media_type="image/jpeg")
    if runtime.camera_manager is None or runtime.camera_manager.state(instance_id) is None:
        raise ApiProblem(
            status_code=404,
            code="INSTANCE_NOT_FOUND",
            detail=f"no camera instance {instance_id}",
        )
    raise ApiProblem(
        status_code=503,
        code="CAMERA_UNAVAILABLE",
        detail=f"no frame available for camera instance {instance_id}",
    )
