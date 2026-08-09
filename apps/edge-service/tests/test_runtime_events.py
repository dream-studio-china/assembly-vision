"""E4a runtime event bus and WebSocket channel tests (design 15.5/15.6).

Covers the event envelope contract, monotonic per-source sequence, bounded
buffering with slow-consumer disconnection without publisher blocking,
WebSocket authentication, and the real runtime transition sources (inspection
completion, pause/resume, upload-scheduler changes).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from assemblyvision_domain.models import BusinessResult
from assemblyvision_edge.api.app import create_app
from assemblyvision_edge.api.events import RuntimeEventBus, _Disconnect
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.api.state import EdgeRuntime
from assemblyvision_edge.persistence.repository import EdgeRepository
from assemblyvision_edge.upload.scheduler import DirectoryUploadSink, UploadScheduler
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.test_api import _record


class TestRuntimeEventBus:
    def test_sequence_and_envelope_fields(self) -> None:
        async def scenario() -> None:
            bus = RuntimeEventBus(source_id="dev-1", max_buffer=4)
            queue = bus.subscribe(asyncio.get_running_loop())
            first = bus.publish("inspection.completed", {"inspection_id": "i-1"})
            second = bus.publish("device.status_changed", {"paused": True}, correlation_id="c-1")
            assert first.sequence == 1
            assert second.sequence == 2
            assert first.type == "inspection.completed"
            assert first.source_id == "dev-1"
            assert first.schema_version == 1
            assert first.event_id
            assert first.occurred_at
            assert first.data == {"inspection_id": "i-1"}
            assert second.correlation_id == "c-1"
            got_first = await queue.get()
            got_second = await queue.get()
            assert not isinstance(got_first, _Disconnect)
            assert not isinstance(got_second, _Disconnect)
            assert got_first.sequence == 1
            assert got_second.sequence == 2

        asyncio.run(scenario())

    def test_slow_consumer_is_disconnected_without_blocking_publisher(self) -> None:
        async def scenario() -> None:
            bus = RuntimeEventBus(source_id="dev-1", max_buffer=2)
            queue = bus.subscribe(asyncio.get_running_loop())
            bus.publish("a", {})
            bus.publish("b", {})
            # The queue is full; a third publish must not block and the slow
            # consumer is drained and handed a disconnect sentinel (E4 invariant 2).
            bus.publish("c", {})
            item = await queue.get()
            assert isinstance(item, _Disconnect)
            assert queue.empty()

        asyncio.run(scenario())

    def test_publish_without_consumers_is_a_noop(self) -> None:
        bus = RuntimeEventBus(source_id="dev-1")
        bus.publish("alert.raised", {"code": "TEST"})
        assert bus.last_sequence == 1
        assert bus.connection_count == 0


class TestWebSocketChannel:
    @pytest.fixture
    def dev_client(self, tmp_path: Path) -> Iterator[tuple[TestClient, RuntimeEventBus]]:
        """Unauthenticated M1 development mode (no api_token configured)."""
        settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
        app = create_app(settings)
        with TestClient(app) as client:
            yield client, app.state.event_bus

    def test_streams_envelopes_to_connected_client(
        self, dev_client: tuple[TestClient, RuntimeEventBus]
    ) -> None:
        client, bus = dev_client
        with client.websocket_connect("/api/v1/ws/runtime") as ws:
            bus.publish("inspection.completed", {"inspection_id": "i-9"})
            envelope = ws.receive_json()
            assert envelope["type"] == "inspection.completed"
            assert envelope["data"] == {"inspection_id": "i-9"}
            assert envelope["sequence"] == 1
            assert envelope["source_id"]
            assert envelope["schema_version"] == 1
            assert envelope["event_id"]
            assert envelope["occurred_at"]

    def test_sequence_is_monotonic_across_events(
        self, dev_client: tuple[TestClient, RuntimeEventBus]
    ) -> None:
        client, bus = dev_client
        with client.websocket_connect("/api/v1/ws/runtime") as ws:
            bus.publish("upload.changed", {"event": "x"})
            bus.publish("upload.changed", {"event": "y"})
            assert ws.receive_json()["sequence"] == 1
            assert ws.receive_json()["sequence"] == 2

    def test_unauthenticated_socket_is_rejected(self, tmp_path: Path) -> None:
        settings = ServerSettings(
            output_root=tmp_path / "out",
            db_path=tmp_path / "edge.sqlite3",
            api_token="viewer-secret",  # noqa: S106 - test fixture credential
        )
        app = create_app(settings)
        # pytest.raises must wrap the websocket session context, so the
        # contexts cannot be flattened.
        with TestClient(app) as client, pytest.raises(  # noqa: SIM117
            WebSocketDisconnect
        ) as excinfo:
            with client.websocket_connect("/api/v1/ws/runtime"):
                pass
        assert excinfo.value.code == 4401

    def test_bearer_authenticated_socket_streams(self, tmp_path: Path) -> None:
        settings = ServerSettings(
            output_root=tmp_path / "out",
            db_path=tmp_path / "edge.sqlite3",
            api_token="viewer-secret",  # noqa: S106 - test fixture credential
        )
        app = create_app(settings)
        with TestClient(app) as client, client.websocket_connect(
            "/api/v1/ws/runtime", headers={"Authorization": "Bearer viewer-secret"}
        ) as ws:
            bus = app.state.event_bus
            bus.publish("alert.raised", {"code": "TEST"})
            envelope = ws.receive_json()
            assert envelope["type"] == "alert.raised"


class TestEventSources:
    def test_pause_resume_publishes_device_status(self, tmp_path: Path) -> None:
        runtime = EdgeRuntime(
            ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
        )
        bus = RuntimeEventBus(source_id="dev")
        runtime.event_bus = bus
        assert bus.last_sequence == 0
        runtime.pause("maintenance")
        assert bus.last_sequence == 1
        runtime.resume()
        assert bus.last_sequence == 2

    def test_persist_projection_publishes_inspection_completed(self, tmp_path: Path) -> None:
        repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
        try:
            runtime = EdgeRuntime(
                ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
            )
            runtime.repository = repo
            bus = RuntimeEventBus(source_id="dev")
            runtime.event_bus = bus
            record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-evt")
            assert runtime._persist_projection(record) is True  # noqa: SLF001
            assert bus.last_sequence == 1
            assert bus.publish("probe", {}).sequence == 2
        finally:
            repo.close()

    def test_upload_scheduler_change_callback_fires_after_handled_batch(
        self, tmp_path: Path
    ) -> None:
        repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
        try:
            calls: list[int] = []
            scheduler = UploadScheduler(
                repo,
                DirectoryUploadSink(tmp_path / "sink"),
                output_root=tmp_path / "out",
                interval_seconds=0.0,
                on_change=lambda: calls.append(1),
            )
            record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-upload")
            assert repo.persist_inspection_and_enqueue_uploads(record) == "inserted"
            scheduler.run_once()
            assert calls  # one metadata task handled -> notification fired
        finally:
            repo.close()
