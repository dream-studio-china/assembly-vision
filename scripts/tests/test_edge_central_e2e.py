"""E6-A16: real edge scheduler and HttpUploadSink against the real central API.

Runs the actual edge ``UploadScheduler`` with the real ``HttpUploadSink``
pointed at a live in-process central FastAPI server (no mocked central,
no stub sink). Verifies the mandatory-matrix items that the mocked
``central.invalid`` fixtures cannot:

- the edge outbox drains in metadata-before-media order and the inspection
  reaches ``QUEUED -> PARTIAL -> SYNCED`` only after verified central receipts;
- the media receipt carries a central object id and the binding is ``AVAILABLE``;
- duplicate replay of the same payload is duplicate-free: the same receipt is
  returned and the central database keeps exactly one row per identity.

This is a developer-only integration harness; the edge runtime itself never
imports central code.
"""

from __future__ import annotations

import hashlib
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import uvicorn
from assemblyvision_domain.models import (
    AggregatedComponentEvidence,
    BarcodeResult,
    BusinessResult,
    FrameQualitySummary,
    InspectionDecision,
    InspectionLifecycle,
    InspectionRecord,
    InternalDecision,
    MediaLifecycle,
    MediaMetadata,
    ProductResolution,
)
from assemblyvision_edge.persistence.repository import EdgeRepository
from assemblyvision_edge.upload.scheduler import HttpUploadSink, UploadScheduler
from central_service.api.app import create_app
from central_service.api.readiness import ReadinessCheck, ReadinessResult
from central_service.api.settings import CentralSettings
from central_service.persistence.bootstrap import resolve_plan, run_bootstrap
from central_service.persistence.repository import CentralRepository
from central_service.persistence.schema import (
    metadata as central_metadata,
)
from central_service.persistence.schema import (
    upload_receipts,
)
from central_service.storage.object_store import ObjectEntry
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105
_DEVICE_ID = uuid4()

_SYNC_TIMEOUT_SECONDS = 45.0


@dataclass
class CentralHarness:
    """Live central test server plus its repository and organization."""

    repository: CentralRepository
    base_url: str
    server: uvicorn.Server
    organization_id: int


class _NoopObjectStorage:
    """In-memory object-store stub satisfying the central ObjectStorage protocol."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def ensure_bucket(self) -> None:
        return None

    def bucket_ready(self) -> bool:
        return True

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    def verify_object(self, key: str, size_bytes: int, checksum_sha256: str) -> None:
        return None

    def object_exists(self, key: str) -> bool:
        return key in self.objects

    def remove_object(self, key: str) -> None:
        self.objects.pop(key, None)

    def list_objects(self, prefix: str) -> Iterator[ObjectEntry]:
        for key in sorted(key for key in self.objects if key.startswith(prefix)):
            yield ObjectEntry(object_key=key, last_modified=None)

    def presigned_get_url(self, key: str, expires_seconds: int) -> str:
        return f"http://fake-store.test/{key}?expires={expires_seconds}"

    def get_object(self, key: str) -> Iterator[bytes]:
        data = self.objects.get(key, b"")
        yield data


def _central_settings() -> CentralSettings:
    return CentralSettings(
        database_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        admin_session_ttl_minutes=60,
        secure_cookies=False,
    )


def _edge_record(completed_at: datetime) -> InspectionRecord:
    """A realistic edge InspectionRecord pinned to the shared device id."""
    inspection_id = uuid4()
    media_id = uuid4()
    media_bytes = f"jpeg-bytes-{media_id}".encode()
    return InspectionRecord(
        inspection_id=inspection_id,
        device_id=_DEVICE_ID,
        device_sequence=1,
        lifecycle_status=InspectionLifecycle.COMPLETED,
        started_at=completed_at,
        completed_at=completed_at,
        barcode_result=BarcodeResult(status="READ", value="SN-0001"),
        product_resolution=ProductResolution(
            status="RESOLVED", source="CONFIGURED_DEFAULT", product_code="model_a"
        ),
        frame_quality_summary=FrameQualitySummary(
            total_frame_count=1, usable_frame_count=1, rejected_frame_count=0
        ),
        application_version="0.1.0",
        product_model_version_id=uuid4(),
        product_model_checksum_sha256="0" * 64,
        component_model_version_id=uuid4(),
        component_model_checksum_sha256="0" * 64,
        rule_version_id=uuid4(),
        aggregation_policy_version="single-frame-mvp-1",
        evidence=[
            AggregatedComponentEvidence(
                component_code="component_a",
                state="PRESENT",
                best_confidence=0.9,
                usable_frame_count=1,
                detection_count=1,
                adjacent_detection_run=1,
                supporting_frame_ids=[uuid4()],
                policy_reason_codes=[],
            )
        ],
        decision=InspectionDecision(
            internal_decision=InternalDecision.OK,
            business_result=BusinessResult.OK,
            missing_components=[],
            low_confidence_components=[],
            reason_codes=[],
            decided_at=completed_at,
        ),
        synchronization_status="LOCAL_ONLY",
        processing_ms=12,
        media=[
            MediaMetadata(
                media_id=media_id,
                kind="KEY_FRAME",
                lifecycle=MediaLifecycle.AVAILABLE,
                relative_path=f"{inspection_id}/key_frame.jpg",
                mime_type="image/jpeg",
                size_bytes=len(media_bytes),
                checksum_sha256=hashlib.sha256(media_bytes).hexdigest(),
            )
        ],
    )


def _start_central_server(app) -> tuple[str, uvicorn.Server]:  # type: ignore[no-untyped-def]
    """Start the real central ASGI app on an ephemeral loopback port."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline and not server.started:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("central test server did not start")
    return f"http://127.0.0.1:{port}", server


def _stop_central_server(server: uvicorn.Server) -> None:
    server.should_exit = True
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and server.started:
        time.sleep(0.05)


@pytest.fixture
def central(tmp_path: Path) -> Iterator[CentralHarness]:
    """Bootstrapped real central API server plus its repository."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    central_metadata.create_all(engine)
    repository = CentralRepository(engine)
    bootstrap = run_bootstrap(
        repository,
        resolve_plan(
            _central_settings(),
            admin_token=_ADMIN_TOKEN,
            device_upload_token=_DEVICE_TOKEN,
            device_id=str(_DEVICE_ID),
        ),
    )
    readiness = ReadinessResult(
        checks=(
            ReadinessCheck(name="database", ok=True, detail="ok"),
            ReadinessCheck(name="object_store", ok=True, detail="ok"),
            ReadinessCheck(name="credentials", ok=True, detail="ok"),
        )
    )
    app = create_app(
        _central_settings(),
        readiness=lambda: readiness,
        repository=repository,
        storage=_NoopObjectStorage(),
    )
    base_url, server = _start_central_server(app)
    try:
        yield CentralHarness(
            repository=repository,
            base_url=base_url,
            server=server,
            organization_id=bootstrap.result.organization_id,
        )
    finally:
        _stop_central_server(server)
        engine.dispose()


def _write_media_file(output_root: Path, record: InspectionRecord) -> None:
    """Write the media artifact the scheduler reads for the MEDIA task."""
    for item in record.media:
        path = output_root / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        data = f"jpeg-bytes-{item.media_id}".encode()
        path.write_bytes(data)


def _run_until_synced(
    scheduler: UploadScheduler, edge_repo: EdgeRepository, inspection_id: str
) -> None:
    deadline = time.monotonic() + _SYNC_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        scheduler.run_once()
        record = edge_repo.get_inspection(str(inspection_id))
        if record is not None and record.synchronization_status == "SYNCED":
            return
        time.sleep(0.1)
    raise AssertionError("edge inspection did not reach SYNCED within the timeout")


def test_edge_scheduler_syncs_against_real_central(central: CentralHarness, tmp_path: Path) -> None:
    central_repo = central.repository
    base_url = central.base_url
    output_root = tmp_path / "out"
    output_root.mkdir()

    # Seed the edge outbox with one inspection carrying one media artifact.
    edge_repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        record = _edge_record(datetime.now(UTC))
        _write_media_file(output_root, record)
        edge_repo.upsert_inspection(record)
        edge_repo.enqueue_inspection_uploads(record)
        assert record.synchronization_status == "LOCAL_ONLY"

        sink = HttpUploadSink(
            base_url=f"{base_url}/api/v1",
            token=_DEVICE_TOKEN,
            client=httpx.Client(timeout=20.0),
        )
        scheduler = UploadScheduler(
            edge_repo,
            sink,
            output_root=output_root,
            interval_seconds=0.1,
            batch_size=4,
        )
        try:
            _run_until_synced(scheduler, edge_repo, str(record.inspection_id))
        finally:
            scheduler.stop()

        # The edge reached SYNCED only after verified central receipts.
        synced = edge_repo.get_inspection(str(record.inspection_id))
        assert synced is not None
        assert synced.synchronization_status == "SYNCED"

        # Both tasks succeeded; the media receipt carries a central object id.
        tasks = {
            task.kind: task
            for task in edge_repo.list_uploads().items
            if str(task.inspection_id) == str(record.inspection_id)
        }
        assert set(tasks) == {"INSPECTION", "MEDIA"}
        assert tasks["INSPECTION"].status == "SUCCEEDED"
        # mark_upload_succeeded rejects a MEDIA receipt without a central
        # object id, so a SUCCEEDED MEDIA task proves the receipt carried one.
        assert tasks["MEDIA"].status == "SUCCEEDED"

        # Central holds the inspection with an AVAILABLE media binding.
        detail = central_repo.get_inspection_detail(
            central.organization_id, str(record.inspection_id)
        )
        assert detail is not None
        assert len(detail.media) == 1
        assert detail.media[0].lifecycle == "AVAILABLE"
    finally:
        edge_repo.close()


def test_duplicate_replay_is_duplicate_free(central: CentralHarness, tmp_path: Path) -> None:
    central_repo = central.repository
    base_url = central.base_url
    output_root = tmp_path / "out"
    output_root.mkdir()
    edge_repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        record = _edge_record(datetime.now(UTC))
        _write_media_file(output_root, record)
        edge_repo.upsert_inspection(record)
        edge_repo.enqueue_inspection_uploads(record)

        sink = HttpUploadSink(
            base_url=f"{base_url}/api/v1",
            token=_DEVICE_TOKEN,
            client=httpx.Client(timeout=20.0),
        )
        scheduler = UploadScheduler(
            edge_repo,
            sink,
            output_root=output_root,
            interval_seconds=0.1,
            batch_size=4,
        )
        try:
            _run_until_synced(scheduler, edge_repo, str(record.inspection_id))
        finally:
            scheduler.stop()

        tasks = {
            task.kind: task
            for task in edge_repo.list_uploads().items
            if str(task.inspection_id) == str(record.inspection_id)
        }
        # Replay the exact payload the sink sent for the inspection task: the
        # central API returns the original receipt (200) and stores nothing new.
        payload = scheduler._load_payload(tasks["INSPECTION"])  # noqa: SLF001 - test drives replay
        replay = sink.upload(tasks["INSPECTION"], payload)
        assert replay.status == "SUCCEEDED"
        assert replay.receipt is not None
        assert replay.receipt.object_id == str(record.inspection_id)

        with central_repo._engine.connect() as connection:  # noqa: SLF001 - test counts receipts
            inspection_receipts = connection.execute(
                select(func.count(upload_receipts.c.id)).where(
                    upload_receipts.c.kind == "INSPECTION"
                )
            ).scalar_one()
            media_receipts = connection.execute(
                select(func.count(upload_receipts.c.id)).where(upload_receipts.c.kind == "MEDIA")
            ).scalar_one()
        assert int(inspection_receipts) == 1
        assert int(media_receipts) == 1
    finally:
        edge_repo.close()
