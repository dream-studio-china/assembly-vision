"""Sad-path and boundary tests for the edge repository."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from assemblyvision_domain.models import BusinessResult
from assemblyvision_edge.persistence.repository import EdgeRepository, RepositoryError
from assemblyvision_edge.persistence.schema import upload_tasks
from sqlalchemy import text

from tests.test_api import _record


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[EdgeRepository]:
    repository = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        yield repository
    finally:
        repository.close()


def _seed(repo: EdgeRepository, count: int, *, offset: int = 0) -> list[str]:
    ids = []
    for i in range(count):
        completed = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=i + offset)
        business = BusinessResult.OK if i % 2 == 0 else BusinessResult.NG
        record = _record(completed, business=business, barcode=f"SN-{i + offset:04d}")
        repo.upsert_inspection(record)
        ids.append(str(record.inspection_id))
    return ids


def test_limit_clamped_to_default(repo: EdgeRepository) -> None:
    _seed(repo, 3)
    for bad in (0, -1, 9999):
        page = repo.list_inspections(limit=bad)
        assert len(page.items) == 3


def test_cursor_pagination_walks_all_rows(repo: EdgeRepository) -> None:
    ids = _seed(repo, 5)
    seen: list[str] = []
    cursor: str | None = None
    iterations = 0
    while iterations < 10:
        page = repo.list_inspections(limit=2, cursor=cursor)
        seen.extend(str(item.inspection_id) for item in page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
        iterations += 1
    assert set(seen) == set(ids)
    assert len(seen) == 5


def test_invalid_cursor_raises(repo: EdgeRepository) -> None:
    _seed(repo, 2)
    with pytest.raises(RepositoryError):
        repo.list_inspections(cursor="not-a-cursor")


def test_filters_apply(repo: EdgeRepository) -> None:
    _seed(repo, 4)
    ng = repo.list_inspections(business_result="NG")
    assert all(item.business_result == "NG" for item in ng.items)
    ok = repo.list_inspections(internal_decision="OK")
    assert all(item.internal_decision == "OK" for item in ok.items)
    by_barcode = repo.list_inspections(barcode="SN-0002")
    assert all(item.sn == "SN-0002" for item in by_barcode.items)
    by_product = repo.list_inspections(product="model_a")
    assert all(item.product_code == "model_a" for item in by_product.items)
    window = repo.list_inspections(
        from_iso="2026-01-01T00:00:00+00:00",
        to_iso="2026-01-01T00:02:59+00:00",
    )
    assert len(window.items) <= 3


def test_latest_inspection_empty_and_present(repo: EdgeRepository) -> None:
    assert repo.latest_inspection() is None
    assert repo.latest_business_result() is None
    _seed(repo, 2)
    latest = repo.latest_inspection()
    assert latest is not None
    assert repo.latest_business_result() == latest.decision.business_result.value


def test_statistics_filters(repo: EdgeRepository) -> None:
    _seed(repo, 4)
    all_stats = repo.statistics()
    assert all_stats["total"] == 4
    assert all_stats["ng"] == 2
    filtered = repo.statistics(
        from_iso="2026-01-01T00:00:00+00:00", to_iso="2026-01-01T00:00:59+00:00"
    )
    assert filtered["total"] == 1


def _insert_upload(
    repo: EdgeRepository, *, status: str, created_offset_min: int, task_id: str | None = None
) -> str:
    task_id = task_id or str(uuid4())
    created = (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=created_offset_min)).isoformat()
    with repo._engine.begin() as conn:  # noqa: SLF001
        conn.execute(
            text(
                f"""
                INSERT INTO {upload_tasks.name} (
                    upload_task_id, device_id, inspection_id, kind, object_id,
                    payload_hash, status, idempotency_key, checksum_sha256,
                    attempt_count, next_attempt_at, last_error_code, created_at,
                    updated_at, completed_at
                ) VALUES (
                    :id, :device, NULL, 'INSPECTION', :object, :hash, :status,
                    :idem, :checksum, 0, NULL, NULL, :created, :created, NULL
                )
                """
            ),
            {
                "id": task_id,
                "device": str(uuid4()),
                "object": str(uuid4()),
                "hash": "abc",
                "status": status,
                "idem": f"inspection:device:{task_id}",
                "checksum": "0" * 64,
                "created": created,
            },
        )
    return task_id


def test_list_uploads_and_pagination(repo: EdgeRepository) -> None:
    for i in range(3):
        _insert_upload(repo, status="PENDING", created_offset_min=i)
    page = repo.list_uploads(limit=1)
    assert len(page.items) == 1
    assert page.next_cursor is not None
    page2 = repo.list_uploads(cursor=page.next_cursor, limit=1)
    assert len(page2.items) == 1
    clamped = repo.list_uploads(limit=0)
    assert len(clamped.items) == 3
    with pytest.raises(RepositoryError):
        repo.list_uploads(cursor="garbage")


def test_retry_upload_not_found(repo: EdgeRepository) -> None:
    assert repo.retry_upload(str(uuid4()), "why") is None


def test_retry_upload_ignores_succeeded(repo: EdgeRepository) -> None:
    task_id = _insert_upload(repo, status="SUCCEEDED", created_offset_min=1)
    task = repo.retry_upload(task_id, "why")
    assert task is not None
    assert task.status == "SUCCEEDED"
    assert task.attempt_count == 0


def test_retry_upload_requeues_retry_wait(repo: EdgeRepository) -> None:
    task_id = _insert_upload(repo, status="RETRY_WAIT", created_offset_min=1)
    task = repo.retry_upload(task_id, "operator action")
    assert task is not None
    assert task.status == "PENDING"
    assert task.attempt_count == 1
    assert task.last_error_code is None


def test_retry_upload_requeues_permanent_failure(repo: EdgeRepository) -> None:
    task_id = _insert_upload(repo, status="PERMANENT_FAILURE", created_offset_min=1)
    task = repo.retry_upload(task_id, "operator action")
    assert task is not None
    assert task.status == "PENDING"
    assert task.attempt_count == 1


def test_count_pending_uploads(repo: EdgeRepository) -> None:
    _insert_upload(repo, status="PENDING", created_offset_min=1)
    _insert_upload(repo, status="IN_PROGRESS", created_offset_min=2)
    _insert_upload(repo, status="RETRY_WAIT", created_offset_min=3)
    _insert_upload(repo, status="SUCCEEDED", created_offset_min=4)
    assert repo.count_pending_uploads() == 3


def test_get_media_and_inspection_media_unknown(repo: EdgeRepository) -> None:
    assert repo.get_media(str(uuid4())) is None
    assert repo.list_inspection_media("nope") == []
    assert repo.get_inspection("nope") is None
    assert repo.get_inspection_full("nope") is None


def test_list_by_barcode(repo: EdgeRepository) -> None:
    _seed(repo, 3)
    records = repo.list_by_barcode("SN-0002")
    assert len(records) == 1
    assert records[0].barcode_result.value == "SN-0002"
    assert repo.list_by_barcode("UNKNOWN") == []


def test_upsert_idempotent(repo: EdgeRepository) -> None:
    record = _record(datetime(2026, 1, 1, tzinfo=UTC), business=BusinessResult.OK, barcode="SN-X")
    assert repo.upsert_inspection(record) == "inserted"
    assert repo.upsert_inspection(record) == "unchanged"
    page = repo.list_inspections(limit=100)
    assert len(page.items) == 1
    assert page.items[0].inspection_id == record.inspection_id


def test_upsert_conflicting_content_raises_without_mutation(repo: EdgeRepository) -> None:
    completed = datetime(2026, 1, 1, tzinfo=UTC)
    record = _record(completed, business=BusinessResult.OK, barcode="SN-X")
    assert repo.upsert_inspection(record) == "inserted"

    conflicting = _record(completed, business=BusinessResult.NG, barcode="SN-X")
    conflicting.inspection_id = record.inspection_id
    with pytest.raises(RepositoryError, match="content conflict"):
        repo.upsert_inspection(conflicting)

    fetched = repo.get_inspection_full(str(record.inspection_id))
    assert fetched is not None
    assert fetched.decision.business_result is BusinessResult.OK
    assert fetched.barcode_result.value == "SN-X"


def test_reopened_database_uses_wal_and_connection_pragmas(tmp_path: Path) -> None:
    db_path = tmp_path / "edge.sqlite3"
    repo = EdgeRepository.open(db_path)
    repo.upsert_inspection(
        _record(datetime(2026, 1, 1, tzinfo=UTC), business=BusinessResult.OK, barcode="SN-WAL")
    )
    repo.close()

    reopened = EdgeRepository.open(db_path)
    try:
        with reopened._engine.connect() as conn:  # noqa: SLF001
            assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000
    finally:
        reopened.close()


def test_migration_reaches_head(repo: EdgeRepository) -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from assemblyvision_edge.persistence.migrate import _ALEMBIC_INI, _MIGRATIONS_DIR

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with repo._engine.connect() as conn:  # noqa: SLF001
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == head


def test_verify_revision_rejects_wrong_head(tmp_path: Path) -> None:
    import sqlite3

    from assemblyvision_edge.persistence.migrate import _verify_revision

    db = tmp_path / "edge.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    conn.execute("INSERT INTO alembic_version VALUES ('9999')")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="expected"):
        _verify_revision(str(db), "0001")


def test_upsert_rejects_duplicate_component_evidence(repo: EdgeRepository) -> None:
    from assemblyvision_domain.models import AggregatedComponentEvidence

    record = _record(datetime(2026, 1, 1, tzinfo=UTC), business=BusinessResult.OK, barcode="SN-DUP")
    record.evidence = [
        AggregatedComponentEvidence(
            component_code="component_a",
            state="PRESENT",
            best_confidence=0.9,
            usable_frame_count=1,
            detection_count=1,
            adjacent_detection_run=1,
            supporting_frame_ids=[uuid4()],
            policy_reason_codes=[],
            box_area_ratios=[0.5],
            box_centers=[(0.5, 0.5)],
        ),
        AggregatedComponentEvidence(
            component_code="component_a",
            state="PRESENT",
            best_confidence=0.9,
            usable_frame_count=1,
            detection_count=1,
            adjacent_detection_run=1,
            supporting_frame_ids=[uuid4()],
            policy_reason_codes=[],
            box_area_ratios=[0.5],
            box_centers=[(0.5, 0.5)],
        ),
    ]
    with pytest.raises(RepositoryError, match="duplicate component evidence"):
        repo.upsert_inspection(record)


def test_upsert_rejects_duplicate_media_paths(repo: EdgeRepository) -> None:
    from assemblyvision_domain.models import MediaLifecycle, MediaMetadata

    record = _record(
        datetime(2026, 1, 1, tzinfo=UTC), business=BusinessResult.OK, barcode="SN-DUPM"
    )
    record.media = [
        MediaMetadata(
            media_id=uuid4(),
            kind="KEY_FRAME",
            lifecycle=MediaLifecycle.AVAILABLE,
            relative_path="key.jpg",
            mime_type="image/jpeg",
            size_bytes=1,
            checksum_sha256="0" * 64,
        ),
        MediaMetadata(
            media_id=uuid4(),
            kind="PRODUCT_ROI",
            lifecycle=MediaLifecycle.AVAILABLE,
            relative_path="key.jpg",
            mime_type="image/jpeg",
            size_bytes=1,
            checksum_sha256="0" * 64,
        ),
    ]
    with pytest.raises(RepositoryError, match="duplicate media paths"):
        repo.upsert_inspection(record)


def test_verify_revision_rejects_missing_head(tmp_path: Path) -> None:
    from assemblyvision_edge.persistence.migrate import _verify_revision

    with pytest.raises(RuntimeError, match="no alembic head"):
        _verify_revision(str(tmp_path / "edge.sqlite3"), None)


def test_verify_revision_surfaces_sqlite_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    from assemblyvision_edge.persistence import migrate

    def broken_connect(path: object) -> object:
        raise sqlite3.Error("cannot open")

    monkeypatch.setattr("assemblyvision_edge.persistence.migrate.sqlite3.connect", broken_connect)
    with pytest.raises(RuntimeError, match="cannot read edge database migration state"):
        migrate._verify_revision(str(tmp_path / "edge.sqlite3"), "0001")
