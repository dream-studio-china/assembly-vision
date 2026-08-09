"""Gated web developer test endpoints (ADR-014).

These file-based request/response tools let a browser take a photo, upload an
image, or upload a short video and get an inspection result. They are a test
harness, not a production acquisition path: they are disabled by default
(``serve --enable-web-test``) and never stream video. Production real-time
acquisition uses the native app / RTSP / camera sources.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any, cast

from assemblyvision_domain.models import BusinessResult, InspectionRecord
from assemblyvision_vision.sources.frame_source import CapturedFrame, FrameStreamError
from assemblyvision_vision.sources.video_source import VideoFrameSource
from fastapi import APIRouter, Depends, Query, Request
from PIL import Image

from assemblyvision_edge.api.deps import get_runtime, get_settings, require_viewer
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.schemas import VideoFrameInspectResult, VideoInspectResult
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.output.writer import OutputWriter
from assemblyvision_edge.persistence.repository import RepositoryError

log = logging.getLogger("assemblyvision.api")

_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_IMAGE_PIXELS = 50_000_000
_MAX_IMAGE_DIMENSION = 12_000
_MAX_VIDEO_BYTES = 100 * 1024 * 1024
_MAX_VIDEO_FRAMES = 30
_MAX_DECODED_FRAMES = 1000
_MAX_VIDEO_DECODE_SECONDS = 60


def _require_dev_tools(request: Request) -> None:
    """Dev tools 404 unless the server was started with ``--enable-web-test``."""
    settings: ServerSettings = get_settings(request)
    if not settings.enable_web_test:
        raise ApiProblem(
            status_code=404,
            code="DEV_TOOLS_DISABLED",
            detail="web dev test tools are disabled; start serve with --enable-web-test",
        )


# The enablement gate must run before viewer authentication so a disabled
# harness returns 404 DEV_TOOLS_DISABLED instead of leaking a 401 (F8,
# ADR-014). Dependencies run in declaration order; authentication stays for
# enabled endpoints.
router = APIRouter(
    prefix="/dev",
    tags=["dev"],
    dependencies=[Depends(_require_dev_tools), Depends(require_viewer)],
)


async def _read_image_body(request: Request) -> bytes:
    """Stream the image body into a bounded buffer (F5).

    Mirrors the video route: reject an over-limit declared payload up front and
    stop accumulating as soon as the byte limit is crossed, so a chunked request
    without ``Content-Length`` cannot buffer unbounded memory.
    """
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > _MAX_IMAGE_BYTES:
                raise ApiProblem(
                    status_code=413,
                    code="PAYLOAD_TOO_LARGE",
                    detail=f"image exceeds the {_MAX_IMAGE_BYTES} byte limit",
                )
        except ValueError:
            pass
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_IMAGE_BYTES:
            raise ApiProblem(
                status_code=413,
                code="PAYLOAD_TOO_LARGE",
                detail=f"image exceeds the {_MAX_IMAGE_BYTES} byte limit",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_image_size(handle: Image.Image) -> None:
    """Reject images whose decoded buffer would exceed resource limits (F5).

    ``Image.open`` only reads the header, so width/height are known before any
    pixel buffer is allocated by ``convert``.
    """
    width, height = handle.size
    if width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION:
        raise ApiProblem(
            status_code=400,
            code="INVALID_IMAGE",
            detail=f"image dimension exceeds the {_MAX_IMAGE_DIMENSION} pixel limit",
        )
    if width * height > _MAX_IMAGE_PIXELS:
        raise ApiProblem(
            status_code=400,
            code="INVALID_IMAGE",
            detail=f"image exceeds the {_MAX_IMAGE_PIXELS} pixel limit",
        )


@router.post("/inspect-frame", response_model=InspectionRecord)
async def dev_inspect_frame(
    request: Request,
    instance_id: str | None = None,
    persist: bool = True,
    runtime: EdgeRuntime = Depends(get_runtime),
) -> InspectionRecord:
    """Inspect one uploaded image; writes an evidence bundle unless persist=false."""
    body = await _read_image_body(request)
    if not body:
        raise ApiProblem(status_code=400, code="EMPTY_BODY", detail="request body is empty")
    try:
        with Image.open(io.BytesIO(body)) as handle:
            _validate_image_size(handle)
            image: Image.Image = handle.convert("RGB")
    except Image.DecompressionBombError as exc:
        raise ApiProblem(
            status_code=400,
            code="INVALID_IMAGE",
            detail="image dimensions exceed the decoded size limit",
        ) from exc
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
    record = cast(InspectionRecord, pipeline.inspect_frame(frame, writer))
    if writer is not None:
        _import_projection(request, record)
    return record


def _import_projection(request: Request, record: InspectionRecord) -> None:
    """Import a just-published bundle into the SQLite read projection (F7).

    Startup reconciliation imports bundles only once, so a persisted dev
    inspection would otherwise be invisible to history/detail until restart.
    The published bundle remains the source of truth; this upsert mirrors the
    per-bundle import path reconciliation uses (``upsert_inspection``) and is
    content-hash idempotent, so restart reconciliation does not duplicate it.
    The import is best-effort: publishing already succeeded, so a projection
    failure is logged and the successful inspection is still returned rather
    than falsely reporting a failed inspection.
    """
    repository = getattr(request.app.state, "repository", None)
    if repository is None:
        return
    try:
        repository.upsert_inspection(record)
        repository.enqueue_inspection_uploads(record)
    except RepositoryError as exc:
        log.warning(
            "inspection %s was published but the read projection could not be updated: %s",
            record.inspection_id,
            exc,
        )


@router.post("/inspect-video", response_model=VideoInspectResult)
async def dev_inspect_video(
    request: Request,
    instance_id: str | None = None,
    step: int = Query(default=1, ge=1, le=100),
    runtime: EdgeRuntime = Depends(get_runtime),
) -> VideoInspectResult:
    """Analyze an uploaded video frame by frame; returns a summary only.

    The video is streamed to a temporary file (never held fully in memory),
    decoded with the shared :class:`VideoFrameSource`, and at most
    ``_MAX_VIDEO_FRAMES`` sampled frames are inspected without persisting
    evidence (ADR-014). ``step`` is bounded and the total decode work is
    bounded by ``_MAX_DECODED_FRAMES`` and ``_MAX_VIDEO_DECODE_SECONDS``;
    ``truncated`` is set when a decode budget ends iteration early.
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
    truncated = False
    decoded_frames = 0
    started = time.monotonic()
    for frame in source.frames(stop):
        decoded_frames += 1
        if decoded_frames > _MAX_DECODED_FRAMES:
            truncated = True
            break
        if time.monotonic() - started > _MAX_VIDEO_DECODE_SECONDS:
            truncated = True
            break
        if (frame.sequence - 1) % step != 0:
            continue
        if len(frames_out) >= _MAX_VIDEO_FRAMES:
            break
        record = cast(InspectionRecord, pipeline.inspect_frame(frame, None))
        business_result = record.decision.business_result
        if business_result is BusinessResult.OK:
            ok_count += 1
        else:
            ng_count += 1
        frames_out.append(
            VideoFrameInspectResult(
                index=frame.sequence,
                business_result=business_result,
                internal_decision=record.decision.internal_decision,
                reason_codes=list(record.decision.reason_codes),
            )
        )
    return VideoInspectResult(
        instance_id=instance_id,
        analyzed_frames=len(frames_out),
        ok_count=ok_count,
        ng_count=ng_count,
        frames=frames_out,
        truncated=truncated,
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
