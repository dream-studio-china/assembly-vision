"""Tests for the frame source factory (design 07.7, ADR-013)."""

from __future__ import annotations

from pathlib import Path

import pytest
from assemblyvision_vision.sources.camera_source import OpenCVCameraSource
from assemblyvision_vision.sources.factory import FrameSourceConfig, build_frame_source
from assemblyvision_vision.sources.folder_source import FolderSource
from assemblyvision_vision.sources.frame_source import FrameStreamError
from assemblyvision_vision.sources.gige_vision_source import GigEVisionFrameSource
from assemblyvision_vision.sources.http_image_source import HttpImageSource
from assemblyvision_vision.sources.rtsp_source import RTSPFrameSource
from assemblyvision_vision.sources.video_source import VideoFrameSource


def test_factory_builds_folder(tmp_path: Path) -> None:
    source = build_frame_source(FrameSourceConfig(source="folder", path=tmp_path))
    assert isinstance(source, FolderSource)


def test_factory_builds_video(tmp_path: Path) -> None:
    video = tmp_path / "sample.avi"
    video.write_bytes(b"placeholder")
    source = build_frame_source(FrameSourceConfig(source="video", path=video, fps=10.0))
    assert isinstance(source, VideoFrameSource)


def test_factory_builds_opencv_device() -> None:
    source = build_frame_source(FrameSourceConfig(source="opencv-device", device=0))
    assert isinstance(source, OpenCVCameraSource)


def test_factory_builds_rtsp() -> None:
    source = build_frame_source(
        FrameSourceConfig(source="rtsp", url="rtsp://host/stream", fps=25.0)
    )
    assert isinstance(source, RTSPFrameSource)


def test_factory_builds_http_image() -> None:
    source = build_frame_source(FrameSourceConfig(source="http-image", url="http://host/frame.jpg"))
    assert isinstance(source, HttpImageSource)


def test_factory_builds_gige_vision(tmp_path: Path) -> None:
    cti = tmp_path / "producer.cti"
    cti.write_bytes(b"fake")
    source = build_frame_source(
        FrameSourceConfig(
            source="gige-vision",
            serial="SN-1",
            gentl_producer=cti,
            trigger_mode="hardware",
            pixel_format="Mono8",
            exposure_us=5000.0,
            gain_db=1.5,
            packet_size=9000,
        )
    )
    assert isinstance(source, GigEVisionFrameSource)


def test_factory_rejects_invalid_gige_trigger_mode(tmp_path: Path) -> None:
    cti = tmp_path / "producer.cti"
    cti.write_bytes(b"fake")
    with pytest.raises(FrameStreamError, match="trigger_mode"):
        build_frame_source(
            FrameSourceConfig(
                source="gige-vision",
                serial="SN-1",
                gentl_producer=cti,
                trigger_mode="floppy",  # type: ignore[arg-type]
            )
        )


def test_factory_requires_required_fields() -> None:
    with pytest.raises(FrameStreamError, match="requires a url"):
        build_frame_source(FrameSourceConfig(source="rtsp"))
    with pytest.raises(FrameStreamError, match="requires a path"):
        build_frame_source(FrameSourceConfig(source="folder"))
    with pytest.raises(FrameStreamError, match="requires a device"):
        build_frame_source(FrameSourceConfig(source="opencv-device"))
    with pytest.raises(FrameStreamError, match="requires a url"):
        build_frame_source(FrameSourceConfig(source="http-image"))
    with pytest.raises(FrameStreamError, match="requires a serial"):
        build_frame_source(FrameSourceConfig(source="gige-vision"))
    with pytest.raises(FrameStreamError, match="requires a gentl_producer"):
        build_frame_source(FrameSourceConfig(source="gige-vision", serial="SN-1"))


def test_factory_rejects_unknown_source_type() -> None:
    with pytest.raises(FrameStreamError, match="unknown frame source type"):
        build_frame_source(FrameSourceConfig(source="gimbal"))  # type: ignore[arg-type]
