"""Frame source factory (design 07.7, ADR-013).

Builds a :class:`FrameSource` from a neutral configuration so callers never
touch vendor or library details. Required fields are validated per source
type before construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from assemblyvision_vision.sources.camera_source import (
    OpenCVCameraSource,
    ReconnectPolicy,
)
from assemblyvision_vision.sources.folder_source import FolderSource
from assemblyvision_vision.sources.frame_source import FrameSource, FrameStreamError
from assemblyvision_vision.sources.gige_vision_source import (
    GigeReconnectPolicy,
    GigEVisionFrameSource,
)
from assemblyvision_vision.sources.http_image_source import (
    HttpImageReconnectPolicy,
    HttpImageSource,
)
from assemblyvision_vision.sources.rtsp_source import RTSPFrameSource, RTSPReconnectPolicy
from assemblyvision_vision.sources.video_source import VideoFrameSource

SourceType = Literal["folder", "video", "opencv-device", "rtsp", "http-image", "gige-vision"]

TriggerMode = Literal["continuous", "software", "hardware"]


@dataclass(frozen=True)
class FrameSourceConfig:
    """Neutral frame source configuration (design 07.7)."""

    source: SourceType
    path: Path | None = None
    url: str | None = None
    device: int | str | None = None
    fps: float | None = None
    loop: bool = False
    reconnect_initial_delay_ms: int = 250
    reconnect_maximum_delay_ms: int = 10000
    serial: str | None = None
    gentl_producer: Path | None = None
    trigger_mode: TriggerMode | None = None
    pixel_format: str | None = None
    exposure_us: float | None = None
    gain_db: float | None = None
    packet_size: int | None = None


def build_frame_source(config: FrameSourceConfig) -> FrameSource:
    """Construct the frame source for a validated configuration."""
    kind = config.source
    if kind == "folder":
        if config.path is None:
            raise FrameStreamError("folder source requires a path")
        return FolderSource(config.path, loop=config.loop, fps=config.fps)
    if kind == "video":
        if config.path is None:
            raise FrameStreamError("video source requires a path")
        return VideoFrameSource(config.path, fps=config.fps, loop=config.loop)
    if kind == "opencv-device":
        if config.device is None:
            raise FrameStreamError("opencv-device source requires a device")
        return OpenCVCameraSource(
            config.device,
            fps=config.fps,
            reconnect=ReconnectPolicy(
                initial_delay_ms=config.reconnect_initial_delay_ms,
                maximum_delay_ms=config.reconnect_maximum_delay_ms,
            ),
        )
    if kind == "rtsp":
        if config.url is None:
            raise FrameStreamError("rtsp source requires a url")
        return RTSPFrameSource(
            config.url,
            fps=config.fps,
            reconnect=RTSPReconnectPolicy(
                initial_delay_ms=config.reconnect_initial_delay_ms,
                maximum_delay_ms=config.reconnect_maximum_delay_ms,
            ),
        )
    if kind == "http-image":
        if config.url is None:
            raise FrameStreamError("http-image source requires a url")
        return HttpImageSource(
            config.url,
            fps=config.fps,
            reconnect=HttpImageReconnectPolicy(
                initial_delay_ms=config.reconnect_initial_delay_ms,
                maximum_delay_ms=config.reconnect_maximum_delay_ms,
            ),
        )
    if kind == "gige-vision":
        if config.serial is None:
            raise FrameStreamError("gige-vision source requires a serial")
        if config.gentl_producer is None:
            raise FrameStreamError("gige-vision source requires a gentl_producer")
        return GigEVisionFrameSource(
            config.serial,
            config.gentl_producer,
            trigger_mode=config.trigger_mode or "continuous",
            pixel_format=config.pixel_format,
            exposure_us=config.exposure_us,
            gain_db=config.gain_db,
            packet_size=config.packet_size,
            fps=config.fps,
            reconnect=GigeReconnectPolicy(
                initial_delay_ms=config.reconnect_initial_delay_ms,
                maximum_delay_ms=config.reconnect_maximum_delay_ms,
            ),
        )
    raise FrameStreamError(f"unknown frame source type: {kind!r}")
