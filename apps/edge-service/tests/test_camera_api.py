"""Tests for per-instance camera state and preview (ADR-013)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.camera_manager import CameraSourceManager
from assemblyvision_vision.sources.folder_source import FolderSource
from PIL import Image


def _make_folder(tmp_path: Path, count: int = 2, *, empty: bool = False) -> Path:
    folder = tmp_path / "images"
    folder.mkdir(exist_ok=True)
    if empty:
        return folder
    for i in range(count):
        Image.new("RGB", (64, 48), (i * 40, 128, 128)).save(folder / f"img_{i}.png")
    return folder


def _runtime_with_source(tmp_path: Path, folder: Path) -> EdgeRuntime:
    settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    runtime = EdgeRuntime(settings)
    manager = CameraSourceManager({"cam": FolderSource(folder, loop=True, fps=100.0)})
    manager.start()
    runtime.camera_manager = manager
    return runtime


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_instance_camera_state_reports_connected(tmp_path: Path) -> None:
    runtime = _runtime_with_source(tmp_path, _make_folder(tmp_path))
    try:
        assert _wait_until(lambda: runtime.camera_manager.latest_frame("cam") is not None)
        state = runtime.instance_camera_state("cam")
        assert state is not None
        assert state["connected"] is True
        assert state["source_width"] == 64
        assert state["source_height"] == 48
        assert state["last_frame_at"] is not None
        assert runtime.instance_camera_state("missing") is None
    finally:
        runtime.shutdown()


def test_preview_jpeg_returns_encoded_frame(tmp_path: Path) -> None:
    runtime = _runtime_with_source(tmp_path, _make_folder(tmp_path))
    try:
        assert _wait_until(lambda: runtime.camera_manager.latest_frame("cam") is not None)
        preview = runtime.preview_jpeg("cam")
        assert preview is not None
        data, frame_at = preview
        assert data.startswith(b"\xff\xd8")  # JPEG SOI marker
        assert frame_at != ""
        assert runtime.preview_jpeg("missing") is None
    finally:
        runtime.shutdown()


def test_preview_is_rate_limited(tmp_path: Path) -> None:
    runtime = _runtime_with_source(tmp_path, _make_folder(tmp_path))
    try:
        assert _wait_until(lambda: runtime.camera_manager.latest_frame("cam") is not None)
        first = runtime.preview_jpeg("cam")
        assert first is not None
        first_data = first[0]
        # A second immediate call must reuse the cached JPEG (rate limited).
        second = runtime.preview_jpeg("cam")
        assert second is not None and second[0] is first_data
    finally:
        runtime.shutdown()


def test_preview_unavailable_when_no_frame(tmp_path: Path) -> None:
    runtime = _runtime_with_source(tmp_path, _make_folder(tmp_path, empty=True))
    try:
        time.sleep(0.1)
        assert runtime.preview_jpeg("cam") is None
        state = runtime.instance_camera_state("cam")
        assert state is not None and state["connected"] is False
    finally:
        runtime.shutdown()


def test_camera_api_preview_and_state(tmp_path: Path) -> None:
    from assemblyvision_edge.api.deps import get_runtime
    from assemblyvision_edge.api.problems import install_problem_handlers
    from assemblyvision_edge.api.routers.camera import router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    runtime = _runtime_with_source(tmp_path, _make_folder(tmp_path))
    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    client = TestClient(app)
    try:
        assert _wait_until(lambda: runtime.camera_manager.latest_frame("cam") is not None)
        state = client.get("/camera/state", params={"instance_id": "cam"})
        assert state.status_code == 200
        assert state.json()["connected"] is True

        preview = client.get("/camera/cam/preview")
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "image/jpeg"
        assert preview.content.startswith(b"\xff\xd8")

        missing_state = client.get("/camera/state", params={"instance_id": "nope"})
        assert missing_state.status_code == 404
        assert missing_state.json()["code"] == "INSTANCE_NOT_FOUND"

        missing_preview = client.get("/camera/nope/preview")
        assert missing_preview.status_code == 404
    finally:
        runtime.shutdown()


def test_camera_api_preview_503_when_no_frame(tmp_path: Path) -> None:
    from assemblyvision_edge.api.deps import get_runtime
    from assemblyvision_edge.api.problems import install_problem_handlers
    from assemblyvision_edge.api.routers.camera import router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    runtime = _runtime_with_source(tmp_path, _make_folder(tmp_path, empty=True))
    app = FastAPI()
    install_problem_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    client = TestClient(app)
    try:
        response = client.get("/camera/cam/preview")
        assert response.status_code == 503
        assert response.json()["code"] == "CAMERA_UNAVAILABLE"
    finally:
        runtime.shutdown()
