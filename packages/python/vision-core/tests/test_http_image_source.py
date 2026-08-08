"""Tests for the HTTP-image frame source (design 07.3, ADR-013).

A local HTTP server serves the test image so no external endpoint is needed.
"""

from __future__ import annotations

import http.server
import io
import threading
from collections.abc import Iterator
from threading import Event

import pytest
from assemblyvision_vision.sources.frame_source import CameraSettings, FrameStreamError
from assemblyvision_vision.sources.http_image_source import (
    HttpImageReconnectPolicy,
    HttpImageSource,
)
from PIL import Image

_PNG = io.BytesIO()
Image.new("RGB", (64, 48), "blue").save(_PNG, format="PNG")
_PNG_BYTES = _PNG.getvalue()


class _ImageHandler(http.server.BaseHTTPRequestHandler):
    """Serves the test PNG; optionally returns 500 the first N requests."""

    failures = 0

    def do_GET(self) -> None:  # noqa: N802
        if type(self).failures > 0:
            type(self).failures -= 1
            self.send_response(500)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.end_headers()
        self.wfile.write(_PNG_BYTES)

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture
def image_url() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ImageHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/frame.png"
    server.shutdown()
    server.server_close()


def test_http_image_invalid_url_raises() -> None:
    with pytest.raises(FrameStreamError, match="invalid http-image url"):
        HttpImageSource("rtsp://host/stream")


def test_http_image_open_reports_capabilities(image_url: str) -> None:
    source = HttpImageSource(image_url)
    capabilities = source.open()
    assert capabilities.source_width == 64
    assert capabilities.source_height == 48


def test_http_image_configure_applies_fps(image_url: str) -> None:
    source = HttpImageSource(image_url)
    applied = source.configure(CameraSettings(fps=4.0))
    assert applied.fps == 4.0
    assert applied.width == 64


def test_http_image_frames_poll_until_stop(image_url: str) -> None:
    source = HttpImageSource(image_url)
    stop = Event()
    iterator = source.frames(stop)
    first = next(iterator)
    second = next(iterator)
    assert first.sequence == 1 and second.sequence == 2
    assert first.width == 64
    stop.set()
    with pytest.raises(StopIteration):
        next(iterator)


def test_http_image_transient_failure_retries(
    image_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_ImageHandler, "failures", 1)
    source = HttpImageSource(
        image_url, reconnect=HttpImageReconnectPolicy(initial_delay_ms=1, maximum_delay_ms=2)
    )
    stop = Event()
    iterator = source.frames(stop)
    first = next(iterator)
    assert first.sequence == 1
    assert first.width == 64
    stop.set()


def test_http_image_undecodable_body_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BadHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(b"not an image")

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _BadHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/frame.png"
    try:
        with pytest.raises(FrameStreamError, match="cannot decode image from url"):
            HttpImageSource(url)._fetch()
    finally:
        server.shutdown()
        server.server_close()


def test_http_image_corrupt_body_faults_source_not_skipped() -> None:
    """A corrupt response faults the stream instead of being skipped (F4).

    The server returns valid bytes, then corrupt bytes, then valid bytes. The
    corrupt acquisition must raise :class:`FrameStreamError` and must NOT emit
    the later valid frame as if no failure happened.
    """

    class _CorruptThenGoodHandler(http.server.BaseHTTPRequestHandler):
        request_count = 0

        def do_GET(self) -> None:  # noqa: N802
            request_count = type(self).request_count
            type(self).request_count += 1
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            if request_count == 1:
                self.wfile.write(b"not an image")
            else:
                self.wfile.write(_PNG_BYTES)

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CorruptThenGoodHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/frame.png"
    try:
        source = HttpImageSource(
            url, reconnect=HttpImageReconnectPolicy(initial_delay_ms=1, maximum_delay_ms=2)
        )
        stop = Event()
        iterator = source.frames(stop)
        first = next(iterator)
        assert first.sequence == 1
        with pytest.raises(FrameStreamError, match="cannot decode image from url"):
            next(iterator)
        stop.set()
    finally:
        server.shutdown()
        server.server_close()
