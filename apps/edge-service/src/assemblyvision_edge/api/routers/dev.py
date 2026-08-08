"""Gated web developer test endpoints (ADR-014).

These file-based request/response tools let a browser take a photo, upload an
image, or upload a short video and get an inspection result. They are a test
harness, not a production acquisition path: they are disabled by default
(``serve --enable-web-test``) and never stream video. Production real-time
acquisition uses the native app / RTSP / camera sources.
"""

from __future__ import annotations

import io
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any, cast

from assemblyvision_domain.models import InspectionRecord
from assemblyvision_vision.sources.frame_source import CapturedFrame, FrameStreamError
from assemblyvision_vision.sources.video_source import VideoFrameSource
from fastapi import APIRouter, Depends, Query, Request
from PIL import Image

from assemblyvision_edge.api.deps import get_runtime, get_settings
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.schemas import VideoFrameInspectResult, VideoInspectResult
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.output.writer import OutputWriter

_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_VIDEO_BYTES = 100 * 1024 * 1024
_MAX_VIDEO_FRAMES = 30


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
    _selected, pipeline = _resolve_pipeline(runtime, instance_id)
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


@router.post("/inspect-video", response_model=VideoInspectResult)
async def dev_inspect_video(
    request: Request,
    instance_id: str | None = None,
    step: int = Query(default=1, ge=1),
    runtime: EdgeRuntime = Depends(get_runtime),
) -> VideoInspectResult:
    """Analyze an uploaded video frame by frame; returns a summary only.

    The video is streamed to a temporary file (never held fully in memory),
    decoded with the shared :class:`VideoFrameSource`, and at most
    ``_MAX_VIDEO_FRAMES`` sampled frames are inspected without persisting
    evidence (ADR-014).
    """
    selected, pipeline = _resolve_pipeline(runtime, instance_id)
    size_limit = _MAX_VIDEO_BYTES
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > size_limit:
                raise ApiProblem(
                    status_code=413,
                    code="PAYLOAD_TOO_LARGE",
                    detail=f"video exceeds the {size_limit} byte limit",
                )
        except ValueError:
            pass
    fd, raw = tempfile.mkstemp(suffix=".video")
    os.close(fd)
    path = Path(raw)
    try:
        size = 0
        with path.open("wb") as handle:
            async for chunk in request.stream():
                size += len(chunk)
                if size > size_limit:
                    raise ApiProblem(
                        status_code=413,
                        code="PAYLOAD_TOO_LARGE",
                        detail=f"video exceeds the {size_limit} byte limit",
                    )
                handle.write(chunk)
        return _analyze_video(path, selected, pipeline, step)
    except FrameStreamError as exc:
        raise ApiProblem(
            status_code=400, code="INVALID_VIDEO", detail="body is not a decodable video"
        ) from exc
    finally:
        path.unlink(missing_ok=True)


def _analyze_video(path: Path, instance_id: str, pipeline: Any, step: int) -> VideoInspectResult:
    source = VideoFrameSource(path)
    stop = Event()
    frames_out: list[VideoFrameInspectResult] = []
    ok_count = 0
    ng_count = 0
    for frame in source.frames(stop):
        if (frame.sequence - 1) % step != 0:
            continue
        if len(frames_out) >= _MAX_VIDEO_FRAMES:
            break
        record = cast(InspectionRecord, pipeline.inspect_frame(frame, None))
        result = str(record.decision.business_result)
        if result == "OK":
            ok_count += 1
        else:
            ng_count += 1
        frames_out.append(
            VideoFrameInspectResult(
                index=frame.sequence,
                business_result=result,
                internal_decision=str(record.decision.internal_decision),
                reason_codes=list(record.decision.reason_codes),
            )
        )
    return VideoInspectResult(
        instance_id=instance_id,
        analyzed_frames=len(frames_out),
        ok_count=ok_count,
        ng_count=ng_count,
        frames=frames_out,
    )


def _resolve_pipeline(runtime: EdgeRuntime, instance_id: str | None) -> tuple[str, Any]:
    """Resolve the pipeline for the requested (or default) instance.

    Returns ``(instance_id, pipeline)``; the id is ``"default"`` for the
    legacy single-pipeline mode.
    """
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
        return selected, instance.pipeline
    if runtime.pipeline is None:
        raise ApiProblem(
            status_code=503,
            code="PIPELINE_UNAVAILABLE",
            detail="inspection pipeline is not loaded",
        )
    return "default", runtime.pipeline
