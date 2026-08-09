"""E4a runtime event bus and WebSocket channel tests (design 15.5/15.6).

Covers the event envelope contract, monotonic per-source sequence, bounded
buffering with slow-consumer disconnection without publisher blocking,
WebSocket authentication, and the real runtime transition sources (inspection
completion, pause/resume, upload-scheduler changes).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from assemblyvision_domain.models import BusinessResult
from assemblyvision_edge.api.app import create_app
from assemblyvision_edge.api.events import EventEnvelope, RuntimeEventBus, _Disconnect
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

    def test_cross_thread_publish_disconnects_slow_consumer_without_queuefull(
        self,
    ) -> None:
        """PR23-F02: worker-thread publishes never raise QueueFull on the loop."""

        async def scenario() -> None:
            bus = RuntimeEventBus(source_id="dev-1", max_buffer=2)
            loop = asyncio.get_running_loop()
            queue = bus.subscribe(loop)
            raised: list[BaseException] = []

            def handle_exception(
                _loop: asyncio.AbstractEventLoop, context: dict[str, object]
            ) -> None:
                exc = context.get("exception")
                if exc is not None:
                    raised.append(exc if isinstance(exc, BaseException) else RuntimeError(str(exc)))

            loop.set_exception_handler(handle_exception)

            def worker() -> None:
                for _ in range(8):
                    bus.publish("inspection.started", {"inspection_id": "i-1"})

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
            # Let the scheduled deliveries run on the owning loop.
            await asyncio.sleep(0.05)
            items: list[EventEnvelope | _Disconnect] = []
            while not queue.empty():
                items.append(queue.get_nowait())
            # The buffer filled, so the consumer was disconnected exactly once
            # and no normal envelope followed the sentinel.
            disconnects = [item for item in items if isinstance(item, _Disconnect)]
            normals = [item for item in items if not isinstance(item, _Disconnect)]
            assert len(disconnects) == 1
            assert len(items) == 1
            assert normals == []
            assert raised == []

        asyncio.run(scenario())

    def test_publish_after_loop_close_is_a_noop(self) -> None:
        """PR23-F02: a closing loop drops the subscription without raising."""

        loop = asyncio.new_event_loop()
        bus = RuntimeEventBus(source_id="dev-1")
        bus.subscribe(loop)
        loop.close()
        # Publishing from a worker thread after the loop closed must never
        # raise into the inspection/upload caller.
        bus.publish("upload.changed", {"event": "batch_processed"})
        assert bus.connection_count == 0

    def test_stats_count_events_and_slow_consumers(self) -> None:
        """PR-023 F05: published and disconnect counters change deterministically."""

        async def scenario() -> None:
            bus = RuntimeEventBus(source_id="dev-1", max_buffer=2)
            loop = asyncio.get_running_loop()
            queue = bus.subscribe(loop)
            bus.publish("inspection.started", {"inspection_id": "i-1"})
            bus.publish("inspection.completed", {"inspection_id": "i-1"})
            bus.publish("inspection.started", {"inspection_id": "i-2"})
            # The buffer filled; the consumer is disconnected.
            stats = bus.stats()
            assert stats.active_connections == 1
            assert stats.published_total == 3
            assert stats.published_by_type == {"inspection.started": 2, "inspection.completed": 1}
            assert stats.slow_consumer_disconnects == 1
            assert stats.delivery_failures == 0
            item = queue.get_nowait()
            assert isinstance(item, _Disconnect)

        asyncio.run(scenario())

    def test_delivery_failures_are_counted(self) -> None:
        """PR-023 F05: a closing loop counts one failed delivery, not a crash."""

        loop = asyncio.new_event_loop()
        bus = RuntimeEventBus(source_id="dev-1")
        bus.subscribe(loop)
        loop.close()
        bus.publish("a", {})
        stats = bus.stats()
        assert stats.active_connections == 0
        assert stats.delivery_failures == 1


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
        with (  # noqa: SIM117
            TestClient(app) as client,
            pytest.raises(WebSocketDisconnect) as excinfo,
        ):
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
        with (
            TestClient(app) as client,
            client.websocket_connect(
                "/api/v1/ws/runtime", headers={"Authorization": "Bearer viewer-secret"}
            ) as ws,
        ):
            bus = app.state.event_bus
            bus.publish("alert.raised", {"code": "TEST"})
            envelope = ws.receive_json()
            assert envelope["type"] == "alert.raised"

    def test_runtime_ticket_requires_viewer(self, tmp_path: Path) -> None:
        settings = ServerSettings(
            output_root=tmp_path / "out",
            db_path=tmp_path / "edge.sqlite3",
            api_token="viewer-secret",  # noqa: S106 - test fixture credential
        )
        app = create_app(settings)
        with TestClient(app) as client:
            denied = client.post("/api/v1/ws/runtime/ticket")
            assert denied.status_code == 401
            granted = client.post(
                "/api/v1/ws/runtime/ticket",
                headers={"Authorization": "Bearer viewer-secret"},
            )
            assert granted.status_code == 200
            body = granted.json()
            assert body["ticket"]
            assert body["channel"] == "runtime"
            assert body["expires_at"]

    def test_runtime_ticket_is_single_use(self, tmp_path: Path) -> None:
        settings = ServerSettings(
            output_root=tmp_path / "out",
            db_path=tmp_path / "edge.sqlite3",
            api_token="viewer-secret",  # noqa: S106 - test fixture credential
        )
        app = create_app(settings)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/ws/runtime/ticket",
                headers={"Authorization": "Bearer viewer-secret"},
            )
            ticket = response.json()["ticket"]
            # First connection succeeds and streams events.
            with client.websocket_connect("/api/v1/ws/runtime", subprotocols=[ticket]) as ws:
                bus = app.state.event_bus
                bus.publish("alert.raised", {"code": "TICKET"})
                envelope = ws.receive_json()
                assert envelope["type"] == "alert.raised"
            # The same ticket cannot be replayed on a second connection.
            with (  # noqa: SIM117
                pytest.raises(WebSocketDisconnect) as excinfo,
                client.websocket_connect("/api/v1/ws/runtime", subprotocols=[ticket]),
            ):
                pass
            assert excinfo.value.code == 4401

    def test_expired_runtime_ticket_is_rejected(self, tmp_path: Path) -> None:
        from datetime import timedelta

        settings = ServerSettings(
            output_root=tmp_path / "out",
            db_path=tmp_path / "edge.sqlite3",
            api_token="viewer-secret",  # noqa: S106 - test fixture credential
        )
        app = create_app(settings)
        with TestClient(app) as client:
            stale = "stale-ticket"
            app.state.ws_tickets[stale] = datetime.now(UTC) - timedelta(seconds=1)
            with (  # noqa: SIM117
                pytest.raises(WebSocketDisconnect) as excinfo,
                client.websocket_connect("/api/v1/ws/runtime", subprotocols=[stale]),
            ):
                pass
            assert excinfo.value.code == 4401

    def test_runtime_stats_endpoint_requires_viewer(self, tmp_path: Path) -> None:
        settings = ServerSettings(
            output_root=tmp_path / "out",
            db_path=tmp_path / "edge.sqlite3",
            api_token="viewer-secret",  # noqa: S106 - test fixture credential
        )
        app = create_app(settings)
        with TestClient(app) as client:
            denied = client.get("/api/v1/ws/runtime/stats")
            assert denied.status_code == 401
            granted = client.get(
                "/api/v1/ws/runtime/stats",
                headers={"Authorization": "Bearer viewer-secret"},
            )
            assert granted.status_code == 200
            body = granted.json()
            assert body["active_connections"] == 0
            assert body["published_total"] == 0
            assert body["published_by_type"] == {}
            assert body["slow_consumer_disconnects"] == 0
            assert body["delivery_failures"] == 0


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

    def test_per_frame_inspection_publishes_started_then_completed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PR-023 F03: default per-frame mode emits one matching lifecycle pair."""
        import time as time_module

        from assemblyvision_edge.api import state as state_module

        from tests.test_instances import _make_images, _write_edge_config

        published: list[tuple[str, dict[str, object]]] = []

        class RecordingBus:
            def publish(
                self, event_type: str, data: dict[str, object], *, correlation_id: str | None = None
            ) -> object:
                published.append((event_type, data))
                return None

        class FakePipeline:
            def inspect_frame(
                self,
                frame: object,
                writer: object,
                *,
                suppress_optional_capture: bool = False,
                inspection_id: UUID | None = None,
            ) -> object:
                record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-frame")
                return record.model_copy(update={"inspection_id": inspection_id})

        monkeypatch.setattr(
            state_module,
            "_build_instance_pipeline",
            lambda instance, rule_registry=None, model_registry=None: FakePipeline(),
        )
        (tmp_path / "out").mkdir(parents=True, exist_ok=True)
        settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
        runtime = EdgeRuntime(settings)
        runtime.event_bus = RecordingBus()
        repository = EdgeRepository.open(settings.db_path)
        config_path = _write_edge_config(tmp_path, _make_images(tmp_path))
        runtime.load_instances(config_path, repository)
        try:
            deadline = time_module.monotonic() + 10.0
            while time_module.monotonic() < deadline:
                if any(t == "inspection.started" for t, _ in published) and any(
                    t == "inspection.completed" for t, _ in published
                ):
                    break
                time_module.sleep(0.05)
            started = [e for t, e in published if t == "inspection.started"]
            completed = [e for t, e in published if t == "inspection.completed"]
            assert started and completed
            # Every started/completed pair shares its inspection_id and the
            # instance identity, and a completed never precedes its start.
            started_ids = [e["inspection_id"] for e in started]
            for event in started + completed:
                assert event["instance_id"] == "line-1"
            for event in completed:
                assert event["inspection_id"] in started_ids
        finally:
            runtime.shutdown()
            repository.close()
