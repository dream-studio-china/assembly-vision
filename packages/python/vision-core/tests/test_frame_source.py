"""Tests for the FrameSource protocol types (design 07.3, ADR-013)."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Event

from assemblyvision_vision.sources.frame_source import (
    AppliedSettings,
    CameraCapabilities,
    CameraSettings,
    CapturedFrame,
    FrameSource,
    FrameStreamError,
)
from PIL import Image


def test_captured_frame_dimensions_derive_from_image() -> None:
    image = Image.new("RGB", (320, 240), "red")
    frame = CapturedFrame(
        monotonic_ts_ns=1_000_000,
        wall_clock_utc=datetime(2026, 1, 1, tzinfo=UTC),
        sequence=7,
        pixel_format="RGB",
        status="OK",
        image=image,
    )
    assert frame.width == 320
    assert frame.height == 240
    assert frame.sequence == 7
    assert frame.status == "OK"


def test_camera_settings_defaults_are_none() -> None:
    settings = CameraSettings()
    assert settings.fps is None
    assert settings.width is None
    assert settings.height is None


def test_camera_capabilities_and_applied_settings() -> None:
    caps = CameraCapabilities(source_width=800, source_height=600, fps=25.0, pixel_format="RGB")
    assert caps.source_width == 800
    applied = AppliedSettings(fps=25.0, width=800, height=600)
    assert applied.width == 800


def test_frame_stream_error_is_assemblyvision_error() -> None:
    assert issubclass(FrameStreamError, Exception)
    error = FrameStreamError("cannot decode frame")
    assert "cannot decode frame" in str(error)


def test_frame_source_is_runtime_checkable_protocol() -> None:
    """A minimal structural implementation satisfies the protocol."""

    class FakeSource:
        def open(self) -> CameraCapabilities:
            return CameraCapabilities(640, 480, None, "RGB")

        def configure(self, settings: CameraSettings) -> AppliedSettings:
            return AppliedSettings(settings.fps, 640, 480)

        def frames(self, stop: Event):  # type: ignore[no-untyped-def]
            if stop.is_set():
                return
            yield None  # pragma: no cover - protocol shape only

        def close(self) -> None:
            return

    assert isinstance(FakeSource(), FrameSource)
