"""Image and camera frame sources (design 07.3, ADR-013)."""

from assemblyvision_vision.sources.camera_source import OpenCVCameraSource, ReconnectPolicy
from assemblyvision_vision.sources.factory import FrameSourceConfig, build_frame_source
from assemblyvision_vision.sources.folder_source import FolderSource
from assemblyvision_vision.sources.frame_source import (
    AppliedSettings,
    CameraCapabilities,
    CameraSettings,
    CapturedFrame,
    FrameSource,
    FrameStreamError,
)
from assemblyvision_vision.sources.http_image_source import HttpImageSource
from assemblyvision_vision.sources.rtsp_source import RTSPFrameSource
from assemblyvision_vision.sources.video_source import VideoFrameSource

__all__ = [
    "AppliedSettings",
    "CameraCapabilities",
    "CameraSettings",
    "CapturedFrame",
    "FolderSource",
    "FrameSource",
    "FrameSourceConfig",
    "FrameStreamError",
    "HttpImageSource",
    "OpenCVCameraSource",
    "RTSPFrameSource",
    "ReconnectPolicy",
    "VideoFrameSource",
    "build_frame_source",
]
