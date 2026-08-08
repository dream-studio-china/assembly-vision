"""Gated web developer test endpoints (ADR-014).

These file-based request/response tools let a browser take a photo, upload an
image, or upload a short video and get an inspection result. They are a test
harness, not a production acquisition path: they are disabled by default
(``serve --enable-web-test``) and never stream video. Production real-time
acquisition uses the native app / RTSP / camera sources.
"""

from __future__ import annotations

import io
import time
from datetime import UTC, datetime
from typing import Any, cast

from assemblyvision_domain.models import InspectionRecord
from assemblyvision_vision.sources.frame_source import CapturedFrame
from fastapi import APIRouter, Depends, Request
from PIL import Image

from assemblyvision_edge.api.deps import get_runtime, get_settings
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.output.writer import OutputWriter

_MAX_IMAGE_BYTES = 20 * 1024 * 1024


def _require_dev_tools(request: Request) -> None:
    """Dev tools 404 unless the server was started with ``--enable-web-test``."""
    settings: ServerSettings = get_settings(request)
    if not settings.enable_web_test:
        raise ApiProblem(
            status_code=404,
            code="DEV_TOOLS_DISABLED",
            detail="web dev test tools are disabled; start serve with --enable-web-test",
        )


router = APIRouter(prefix="/dev", tags=["dev"], dependencies=[Depends(_require_dev_tools)])


@router.post("/inspect-frame", response_model=InspectionRecord)
async def dev_inspect_frame(
    request: Request,
    instance_id: str | None = None,
    persist: bool = True,
    runtime: EdgeRuntime = Depends(get_runtime),
) -> InspectionRecord:
    """Inspect one uploaded image; writes an evidence bundle unless persist=false."""
    body = await request.body()
    if not body:
        raise ApiProblem(status_code=400, code="EMPTY_BODY", detail="request body is empty")
    if len(body) > _MAX_IMAGE_BYTES:
        raise ApiProblem(
            status_code=413,
            code="PAYLOAD_TOO_LARGE",
            detail=f"image exceeds the {_MAX_IMAGE_BYTES} byte limit",
        )
    try:
        with Image.open(io.BytesIO(body)) as handle:
            image: Image.Image = handle.convert("RGB")
    except Exception as exc:
        raise ApiProblem(
            status_code=400, code="INVALID_IMAGE", detail="body is not a decodable image"
        ) from exc
    pipeline = _resolve_pipeline(runtime, instance_id)
    frame = CapturedFrame(
        monotonic_ts_ns=time.monotonic_ns(),
        wall_clock_utc=datetime.now(UTC),
        sequence=1,
        pixel_format="RGB",
        status="OK",
        image=image,
    )
    writer = OutputWriter(runtime._settings.output_root) if persist else None  # noqa: SLF001
    return cast(InspectionRecord, pipeline.inspect_frame(frame, writer))


def _resolve_pipeline(runtime: EdgeRuntime, instance_id: str | None) -> Any:
    """Resolve the pipeline for the requested (or default) instance."""
    if runtime.instances:
        selected = instance_id if instance_id is not None else next(iter(runtime.instances))
        instance = runtime.instances.get(selected)
        if instance is None:
            raise ApiProblem(
                status_code=404,
                code="INSTANCE_NOT_FOUND",
                detail=f"no inspection instance {selected}",
            )
        if instance.pipeline is None:
            raise ApiProblem(
                status_code=503,
                code="PIPELINE_UNAVAILABLE",
                detail=f"instance {selected} has no loaded inspection pipeline",
            )
        return instance.pipeline
    if runtime.pipeline is None:
        raise ApiProblem(
            status_code=503,
            code="PIPELINE_UNAVAILABLE",
            detail="inspection pipeline is not loaded",
        )
    return runtime.pipeline
