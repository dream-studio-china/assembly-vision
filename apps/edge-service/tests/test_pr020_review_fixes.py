"""Regression tests for PR-020 review findings (F01-F12).

Each test maps to an acceptance criterion in docs/reviews/PR-020-review.md.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from assemblyvision_domain.models import (
    BusinessResult,
    InspectionRecord,
    MediaLifecycle,
    MediaMetadata,
)
from assemblyvision_edge.persistence.reconcile import (
    reconcile_output_root,
    scan_storage_integrity,
)
from assemblyvision_edge.persistence.repository import EdgeRepository
from assemblyvision_edge.retention.policy import RetentionPolicy
from assemblyvision_edge.retention.worker import RetentionCleanupWorker, unlink_media_safely
from PIL import Image
from sqlalchemy import text

from tests.test_api import _record
from tests.test_retention_persistence import NOW, _mark_synced

POLICY = RetentionPolicy({"KEY_FRAME": timedelta(days=1)})


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[EdgeRepository]:
    repository = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        yield repository
    finally:
        repository.close()


def _write_media_file(output_root: Path, record: InspectionRecord) -> None:
    for item in record.media:
        path = output_root / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        data = f"bytes-{item.media_id}".encode()
        path.write_bytes(data)
        item.size_bytes = len(data)
        item.checksum_sha256 = hashlib.sha256(data).hexdigest()


def _seed_eligible(
    repo: EdgeRepository, output_root: Path, *, kinds: list[str] | None = None
) -> InspectionRecord:
    record = _record(NOW - timedelta(days=3), business=BusinessResult.OK, barcode="SN-PR20")
    if kinds is not None:
        record.media = [
            MediaMetadata(
                media_id=uuid4(),
                kind=kind,  # type: ignore[arg-type]  # any media kind for tests
                lifecycle=MediaLifecycle.AVAILABLE,
                relative_path=f"{record.inspection_id}/{kind.lower()}.jpg",
                mime_type="image/jpeg",
                size_bytes=0,
                checksum_sha256="0" * 64,
            )
            for kind in kinds
        ]
    _write_media_file(output_root, record)
    repo.persist_inspection_and_enqueue_uploads(record, retention=POLICY)
    _mark_synced(repo, record)
    return record


def _worker(repo: EdgeRepository, output_root: Path) -> RetentionCleanupWorker:
    return RetentionCleanupWorker(repo, output_root, POLICY, lease_seconds=120)


# --- F01: projection failure must not publish OK and latches a fault ----------


def test_persist_failure_latches_fault_and_does_not_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from assemblyvision_edge.api.settings import ServerSettings
    from assemblyvision_edge.api.state import EdgeRuntime

    (tmp_path / "out").mkdir(parents=True, exist_ok=True)
    settings = ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    runtime = EdgeRuntime(settings)
    repository = EdgeRepository.open(settings.db_path)
    runtime.repository = repository

    record = _record(NOW, business=BusinessResult.OK, barcode="SN-F01")

    def boom(*_args: object, **_kwargs: object) -> object:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(repository, "persist_inspection_and_enqueue_uploads", boom)
    try:
        assert runtime._persist_projection(record) is False
        assert runtime.storage_write_fault is True
        assert runtime.device_status(upload_pending=0)["inspection_ready"] is False
        # A later successful volume observation alone cannot clear the latch.
        runtime.refresh_storage()
        assert runtime.storage_write_fault is True
    finally:
        runtime.shutdown()
        repository.close()


def test_persistence_probe_cannot_clear_fault_without_repository(tmp_path: Path) -> None:
    from assemblyvision_edge.api.settings import ServerSettings
    from assemblyvision_edge.api.state import EdgeRuntime

    output_root = tmp_path / "out"
    output_root.mkdir()
    runtime = EdgeRuntime(
        ServerSettings(output_root=output_root, db_path=tmp_path / "edge.sqlite3")
    )
    runtime.storage_write_fault = True

    assert runtime.probe_persistence() is False
    assert runtime.storage_write_fault is True


# --- F02/F03: fenced claim confirmation and post-claim protection ------------


def test_expired_or_superseded_claim_cannot_unlink(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        record = _seed_eligible(repo, output_root)
        media_id = str(record.media[0].media_id)
        past = (NOW - timedelta(minutes=5)).isoformat()
        first = repo.claim_retention_batch(10, 1, past)
        assert len(first) == 1
        # A second worker reclaims after the first lease lapsed.
        second = repo.claim_retention_batch(10, 120, NOW.isoformat())
        assert len(second) == 1
        assert second[0].lease_owner != first[0].lease_owner
        path = output_root / record.media[0].relative_path

        # The stale holder's worker cannot confirm the claim or unlink.
        worker = _worker(repo, output_root)
        assert worker._process(first[0], NOW.isoformat()) is False  # noqa: SLF001
        assert path.is_file()
        row = _media_row(repo, media_id)
        assert row["lifecycle"] != "PURGED"

        # The current holder alone finalizes.
        assert worker._process(second[0], NOW.isoformat()) is True
        assert not path.exists()
    finally:
        repo.close()


def test_hold_or_fault_after_claim_cancels_deletion(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        held = _seed_eligible(repo, output_root)
        held_id = str(held.media[0].media_id)
        claim = repo.claim_retention_batch(10, 120, NOW.isoformat())
        assert len(claim) == 1
        repo.apply_media_hold(held_id, "review")
        worker = _worker(repo, output_root)
        assert worker._process(claim[0], NOW.isoformat()) is False  # noqa: SLF001
        assert (output_root / held.media[0].relative_path).is_file()
        assert _media_row(repo, held_id)["lifecycle"] != "PURGED"

        faulted = _seed_eligible(repo, output_root)
        faulted_id = str(faulted.media[0].media_id)
        claim2 = repo.claim_retention_batch(10, 120, NOW.isoformat())
        assert len(claim2) == 1
        repo.mark_media_integrity_fault_direct(faulted_id, "MEDIA_PATH_UNSAFE")
        assert worker._process(claim2[0], NOW.isoformat()) is False  # noqa: SLF001
        assert (output_root / faulted.media[0].relative_path).is_file()
        assert _media_row(repo, faulted_id)["lifecycle"] != "PURGED"
        assert repo.retention_eligible(NOW.isoformat()) == []
    finally:
        repo.close()


def test_finalize_purge_rechecks_sync_and_receipt(repo: EdgeRepository, tmp_path: Path) -> None:
    record = _seed_eligible(repo, tmp_path / "out")
    claim = repo.claim_retention_batch(10, 120, NOW.isoformat())
    assert len(claim) == 1
    with repo._engine.begin() as conn:  # noqa: SLF001
        conn.execute(
            text(
                "UPDATE inspections SET synchronization_status = 'PARTIAL' "
                "WHERE inspection_id = :id"
            ),
            {"id": str(record.inspection_id)},
        )

    assert (
        repo.finalize_media_purge(
            str(claim[0].media_id), claim[0].lease_owner, NOW.isoformat(), "retention"
        )
        == 0
    )


# --- F04: symlink swap cannot delete outside the bundle ----------------------


def test_symlink_swapped_bundle_dir_cannot_delete_external_file(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    output_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.txt"
    victim.write_text("keep me")
    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        record = _seed_eligible(repo, output_root)
        media_id = str(record.media[0].media_id)
        claim = repo.claim_retention_batch(10, 120, NOW.isoformat())
        assert len(claim) == 1
        bundle = output_root / str(record.inspection_id)
        bundle.rename(tmp_path / "original-bundle")
        bundle.symlink_to(outside, target_is_directory=True)
        try:
            code, is_fault = unlink_media_safely(output_root, claim[0])
            assert code is not None
            assert is_fault is True
        finally:
            bundle.unlink()  # remove the symlink itself
        assert victim.is_file()  # external file untouched
        assert _media_row(repo, media_id)["lifecycle"] != "PURGED"
    finally:
        repo.close()


# --- F06: exact threshold boundaries are at-or-below -------------------------


def test_exact_threshold_boundaries_are_stop_critical_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from assemblyvision_edge.api.settings import StorageSettings
    from assemblyvision_edge.retention.storage import observe_storage

    calls: dict[str, float] = {"free": 0.0}
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _p: SimpleNamespace(total=100, free=calls["free"], used=100 - calls["free"]),
    )
    monkeypatch.setattr(
        "assemblyvision_edge.retention.storage.os.statvfs",
        lambda _p: SimpleNamespace(f_files=100, f_ffree=100),
    )
    settings = StorageSettings(20.0, 10.0, 5.0)
    # Free-byte values are integers (disk_usage returns whole bytes); exact
    # boundary values enter the more severe mode (at-or-below semantics).
    for free, expected in [(5, "STOP"), (10, "CRITICAL"), (20, "WARNING"), (25, "NORMAL")]:
        calls["free"] = free
        assert observe_storage(tmp_path, settings).mode == expected


# --- F07: critical mode suppresses optional OK capture -----------------------


def test_writer_suppresses_optional_ok_media_but_preserves_ng(tmp_path: Path) -> None:
    from assemblyvision_edge.output.writer import OutputWriter

    root = tmp_path / "out"
    root.mkdir()
    frame = Image.new("RGB", (32, 32), (10, 10, 10))
    ok_record = _record(NOW, business=BusinessResult.OK, barcode="SN-OPT")
    saved = OutputWriter(root).save(
        ok_record, full_frame=frame, roi_image=frame, annotated=frame, suppress_optional=True
    )
    assert saved.media == []
    assert not (root / str(ok_record.inspection_id) / "key_frame.jpg").exists()

    ng_record = _record(NOW, business=BusinessResult.NG, barcode="SN-NG")
    saved_ng = OutputWriter(root).save(
        ng_record, full_frame=frame, roi_image=frame, annotated=frame, suppress_optional=True
    )
    assert len(saved_ng.media) == 3  # mandatory NG evidence preserved
    assert (root / str(ng_record.inspection_id) / "key_frame.jpg").is_file()


# --- F08/F09: startup integrity faults gate readiness and alert ---------------


def test_startup_integrity_fault_gates_ready_and_alerts(tmp_path: Path) -> None:
    from assemblyvision_edge.api.app import create_app
    from assemblyvision_edge.api.settings import IntegrityScanSettings, ServerSettings
    from fastapi.testclient import TestClient

    root = tmp_path / "out"
    record = _record(NOW, business=BusinessResult.OK, barcode="SN-INT")
    directory = root / str(record.inspection_id)
    directory.mkdir(parents=True)
    directory.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))
    # Media referenced by the record but missing from disk.
    directory.joinpath(record.media[0].relative_path.split("/")[-1]).write_bytes(b"x")
    settings = ServerSettings(
        output_root=root,
        db_path=tmp_path / "edge.sqlite3",
        integrity_scan=IntegrityScanSettings(verify_checksums=False),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        status = client.get("/api/v1/device/status").json()
        assert status["cleanup_integrity_fault_count"] >= 1
        assert "STORAGE_INTEGRITY_FAULT" in status["alerts"]
        assert status["inspection_ready"] is False
        # F13: the server exposes its authoritative storage policy and scan
        # coverage; the dashboard renders these instead of client thresholds.
        assert status["storage_warning_free_percent"] > 0
        assert status["storage_observed_at"] is not None
        assert status["integrity_scan_last_run_at"] is not None
        assert status["integrity_scan_checked"] >= 1
        assert status["integrity_verify_checksums"] is False
        ready = client.get("/api/v1/health/ready")
        assert ready.status_code == 503


def test_existing_integrity_fault_remains_latched_after_restart(tmp_path: Path) -> None:
    from assemblyvision_edge.api.app import create_app
    from assemblyvision_edge.api.settings import ServerSettings
    from fastapi.testclient import TestClient

    root = tmp_path / "out"
    database = tmp_path / "edge.sqlite3"
    repository = EdgeRepository.open(database)
    try:
        record = _seed_eligible(repository, root)
        bundle = root / str(record.inspection_id)
        bundle.joinpath("inspection.json").write_text(record.model_dump_json(indent=2))
        repository.mark_media_integrity_fault_direct(
            str(record.media[0].media_id), "MEDIA_EVIDENCE_MISSING"
        )
    finally:
        repository.close()

    app = create_app(ServerSettings(output_root=root, db_path=database))
    with TestClient(app):
        runtime = app.state.runtime
        assert runtime.integrity_scan is not None
        assert runtime.integrity_scan.faults == 0
        assert runtime.storage_integrity_fault is True


def test_default_startup_integrity_policy_verifies_checksums(tmp_path: Path) -> None:
    from assemblyvision_edge.api.app import create_app
    from assemblyvision_edge.api.settings import ServerSettings
    from fastapi.testclient import TestClient

    root = tmp_path / "out"
    root.mkdir()
    app = create_app(ServerSettings(output_root=root, db_path=tmp_path / "edge.sqlite3"))
    with TestClient(app) as client:
        assert client.get("/api/v1/device/status").json()["integrity_verify_checksums"] is True


def test_checksum_policy_detects_same_size_tampering(tmp_path: Path) -> None:
    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        root = tmp_path / "out"
        record = _seed_eligible(repo, root)
        path = root / record.media[0].relative_path
        data = path.read_bytes()
        tampered = bytes([b ^ 0xFF for b in data])  # same size, different bytes
        path.write_bytes(tampered)

        report = scan_storage_integrity(repo, root, verify_checksums=True)
        assert report.checksum_checked == 1
        assert report.fault_codes.get("MEDIA_CHECKSUM_MISMATCH", 0) == 1

        bounded = scan_storage_integrity(repo, root, verify_checksums=True, sample_limit=0)
        assert bounded.checksum_checked == 0
        assert bounded.skipped >= 1
        assert bounded.skipped_reason == "sample_limit"
    finally:
        repo.close()


# --- F10: orphan final bundles are quarantined --------------------------------


def test_orphan_media_bundle_is_quarantined(tmp_path: Path) -> None:
    repo = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        root = tmp_path / "out"
        root.mkdir()
        orphan = root / "orphan-id"
        orphan.mkdir()
        orphan.joinpath("key.jpg").write_bytes(b"no manifest")
        empty = root / "empty-id"
        empty.mkdir()

        assert reconcile_output_root(repo, root) == 0
        assert not orphan.exists()
        assert not empty.exists()
        assert len(list((root / "quarantine").iterdir())) == 2
        # Repeated startup does not rediscover or re-quarantine.
        assert reconcile_output_root(repo, root) == 0
        assert len(list((root / "quarantine").iterdir())) == 2
    finally:
        repo.close()


# --- F11: /health/ready is 503 when admission is closed -----------------------


def test_health_ready_503_on_write_fault_and_stop(tmp_path: Path) -> None:
    from assemblyvision_edge.api.app import create_app
    from assemblyvision_edge.api.settings import ServerSettings
    from assemblyvision_edge.retention.storage import StorageState
    from fastapi.testclient import TestClient

    root = tmp_path / "out"
    root.mkdir()
    settings = ServerSettings(output_root=root, db_path=tmp_path / "edge.sqlite3")
    app = create_app(settings)
    with TestClient(app) as client:
        runtime = app.state.runtime
        runtime.storage_write_fault = True
        assert client.get("/api/v1/health/ready").status_code == 503
        runtime.storage_write_fault = False
        runtime.storage_state = StorageState(
            mode="STOP",
            free_bytes=0,
            total_bytes=100,
            free_percent=0.0,
            free_inodes=0,
            total_inodes=100,
            inode_free_percent=0.0,
            warning_free_percent=20.0,
            critical_free_percent=10.0,
            stop_free_percent=5.0,
            observed_at=NOW.isoformat(),
        )
        assert client.get("/api/v1/health/ready").status_code == 503
        runtime.storage_state = None
        assert client.get("/api/v1/device/status").status_code == 200


# --- F12: repository rejects malformed/mismatched receipts --------------------


def test_mark_upload_succeeded_rejects_mismatched_receipt(repo: EdgeRepository) -> None:
    record = _record(NOW, business=BusinessResult.OK, barcode="SN-REC")
    repo.persist_inspection_and_enqueue_uploads(record)
    claimed = repo.claim_upload_tasks(10, 120, NOW.isoformat())
    tasks = {str(t.task.kind): t for t in claimed}
    assert "INSPECTION" in tasks
    inspection = tasks["INSPECTION"]
    # Media tasks only become due after the inspection holds a verified receipt.
    with repo._engine.connect() as conn:  # noqa: SLF001
        row = (
            conn.execute(
                text(
                    "SELECT idempotency_key, object_id, kind, checksum_sha256, size_bytes "
                    "FROM upload_tasks WHERE upload_task_id = :id"
                ),
                {"id": str(inspection.task.upload_task_id)},
            )
            .mappings()
            .one()
        )
    ok_receipt = json.dumps(
        {
            "idempotency_key": row["idempotency_key"],
            "object_id": row["object_id"],
            "kind": row["kind"],
            "checksum_sha256": row["checksum_sha256"],
            "size_bytes": row["size_bytes"],
        }
    )
    assert (
        repo.mark_upload_succeeded(
            str(inspection.task.upload_task_id),
            inspection.lease_owner,
            NOW.isoformat(),
            receipt_json=ok_receipt,
        )
        == 1
    )
    media_claimed = repo.claim_upload_tasks(10, 120, NOW.isoformat())
    tasks = {str(t.task.kind): t for t in media_claimed}
    assert "MEDIA" in tasks
    media = tasks["MEDIA"]
    media_id = str(media.task.upload_task_id)

    # Malformed JSON, opaque receipt, and mismatched immutable fields are all
    # rejected by the repository (PR-020 F12).
    assert (
        repo.mark_upload_succeeded(
            media_id, media.lease_owner, NOW.isoformat(), receipt_json="{not json"
        )
        == 0
    )
    assert (
        repo.mark_upload_succeeded(
            media_id, media.lease_owner, NOW.isoformat(), receipt_json='{"verified":true}'
        )
        == 0
    )
    bad = json.dumps(
        {
            "idempotency_key": media.task.idempotency_key,
            "object_id": str(media.task.object_id),
            "kind": media.task.kind,
            "checksum_sha256": "f" * 64,
            "size_bytes": 1,
            "central_object_id": "obj",
        }
    )
    assert (
        repo.mark_upload_succeeded(media_id, media.lease_owner, NOW.isoformat(), receipt_json=bad)
        == 0
    )
    with repo._engine.connect() as conn:  # noqa: SLF001
        media_row = (
            conn.execute(
                text(
                    "SELECT idempotency_key, object_id, kind, checksum_sha256, size_bytes "
                    "FROM upload_tasks WHERE upload_task_id = :id"
                ),
                {"id": media_id},
            )
            .mappings()
            .one()
        )
    matching_fields_wrong_central_object = json.dumps(
        {
            "idempotency_key": media_row["idempotency_key"],
            "object_id": media_row["object_id"],
            "kind": media_row["kind"],
            "checksum_sha256": media_row["checksum_sha256"],
            "size_bytes": media_row["size_bytes"],
            "central_object_id": "receipt-object",
        }
    )
    assert (
        repo.mark_upload_succeeded(
            media_id,
            media.lease_owner,
            NOW.isoformat(),
            central_object_id="stored-object",
            receipt_json=matching_fields_wrong_central_object,
        )
        == 0
    )
    with repo._engine.connect() as conn:  # noqa: SLF001
        status = conn.execute(
            text("SELECT status FROM upload_tasks WHERE upload_task_id = :id"), {"id": media_id}
        ).scalar()
    assert status == "IN_PROGRESS"
    # Without a verified media receipt the inspection cannot be SYNCED and the
    # media can never be eligible for retention.
    with repo._engine.connect() as conn:  # noqa: SLF001
        sync = conn.execute(
            text("SELECT synchronization_status FROM inspections WHERE inspection_id = :id"),
            {"id": str(record.inspection_id)},
        ).scalar()
    assert sync != "SYNCED"
    assert repo.retention_eligible(NOW.isoformat()) == []


def _media_row(repo: EdgeRepository, media_id: str) -> dict[str, object]:
    with repo._engine.connect() as conn:  # noqa: SLF001
        row = (
            conn.execute(
                text(
                    "SELECT lifecycle, purge_reason, integrity_status, hold_reason "
                    "FROM media WHERE media_id = :id"
                ),
                {"id": media_id},
            )
            .mappings()
            .one()
        )
    return dict(row)
