"""C4 central review repository tests.

Exercises the append-only revision chain, If-Match optimistic concurrency,
idempotent retries, disposition policy, audit events, the NG/uncertain
review queue, and a real threaded concurrent-submission race on SQLite with
BEGIN IMMEDIATE serialization.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from assemblyvision_domain.models import (
    BusinessResult,
    ComponentCorrection,
    ComponentCorrectionState,
    ReviewDisposition,
)
from central_service.persistence.repository import (
    CentralRepository,
    PilotBootstrapResult,
    ReviewConflictError,
    ReviewDispositionError,
    ReviewNotFoundError,
)
from central_service.persistence.schema import audit_logs, metadata, review_records
from ingest_fixtures import build_record, canonical_payload, content_hash
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

# Test fixtures carry their own credential strings; these are never real.
_ADMIN_TOKEN = "test-admin-token-0123456789abcdef"  # noqa: S105
_DEVICE_TOKEN = "test-device-token-0123456789abcdef"  # noqa: S105
_DEVICE_ID = uuid4()


def _sqlite_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", _enable_foreign_keys)
    metadata.create_all(engine)
    return engine


def _enable_foreign_keys(dbapi_connection: Any, connection_record: object) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture
def repository() -> Iterator[CentralRepository]:
    engine = _sqlite_engine()
    try:
        yield CentralRepository(engine)
    finally:
        engine.dispose()


@pytest.fixture
def device(repository: CentralRepository) -> PilotBootstrapResult:
    return repository.bootstrap_pilot(
        organization_name="Org A",
        site_name="Site A",
        line_name="Line A",
        device_id=str(_DEVICE_ID),
        device_name="Edge 1",
        device_upload_token=_DEVICE_TOKEN,
        admin_username="admin",
        admin_token=_ADMIN_TOKEN,
    )


def _seed_inspection(
    repository: CentralRepository,
    device: PilotBootstrapResult,
    *,
    business: BusinessResult = BusinessResult.NG,
    sequence: int = 1,
) -> str:
    record = build_record(device_id=_DEVICE_ID, device_sequence=sequence, business=business)
    device_row = repository.get_device(device.organization_id, device.device_row_id)
    assert device_row is not None
    repository.ingest_inspection(
        device=device_row,
        idempotency_key=f"inspection:{record.device_id}:{record.inspection_id}",
        request_hash=content_hash(record),
        object_id=str(record.inspection_id),
        inspection_id=str(record.inspection_id),
        record=record,
        payload_json=canonical_payload(record).decode("utf-8"),
        received_at=datetime.now(UTC),
    )
    return str(record.inspection_id)


def _submit(
    repository: CentralRepository,
    device: PilotBootstrapResult,
    inspection_id: str,
    *,
    disposition: ReviewDisposition = ReviewDisposition.CONFIRMED_NG,
    if_match_revision: int | None = None,
    idempotency_key: str | None = None,
    reviewer: str = "pilot-admin",
    corrections: list[ComponentCorrection] | None = None,
) -> Any:
    return repository.submit_review(
        organization_id=device.organization_id,
        inspection_id=inspection_id,
        disposition=disposition,
        reason="confirmed by operator",
        note=None,
        component_corrections=corrections or [],
        reviewer=reviewer,
        idempotency_key=idempotency_key or f"review-{uuid4()}",
        if_match_revision=if_match_revision,
        created_at=datetime.now(UTC),
    )


def test_submit_review_appends_revision_and_audit(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    inspection_id = _seed_inspection(repository, device)
    result = _submit(repository, device, inspection_id, if_match_revision=None)
    assert result.replayed is False
    assert result.review.revision == 1
    assert result.review.disposition == "CONFIRMED_NG"
    assert result.review.original_business_result == "NG"
    assert result.review.original_internal_decision == "NG"
    assert result.review.original_reason_codes == ["COMPONENT_MISSING:component_a"]
    second = _submit(
        repository, device, inspection_id, if_match_revision=1, idempotency_key=f"r2-{uuid4()}"
    )
    assert second.review.revision == 2
    with repository._engine.connect() as connection:
        review_count = connection.execute(select(func.count(review_records.c.id))).scalar_one()
        audit_rows = connection.execute(
            select(audit_logs.c.action).where(audit_logs.c.action == "REVIEW_APPENDED")
        ).all()
    assert int(review_count) == 2
    assert len(audit_rows) == 2


def test_submit_review_idempotent_retry_returns_original(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    inspection_id = _seed_inspection(repository, device)
    key = f"review-{uuid4()}"
    first = _submit(repository, device, inspection_id, idempotency_key=key)
    second = _submit(
        repository,
        device,
        inspection_id,
        idempotency_key=key,
        if_match_revision=1,
    )
    assert second.replayed is True
    assert second.review.revision == first.review.revision
    with repository._engine.connect() as connection:
        review_count = connection.execute(select(func.count(review_records.c.id))).scalar_one()
    assert int(review_count) == 1


def test_submit_review_stale_if_match_conflicts(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    inspection_id = _seed_inspection(repository, device)
    _submit(repository, device, inspection_id, if_match_revision=None)
    with pytest.raises(ReviewConflictError):
        _submit(
            repository,
            device,
            inspection_id,
            if_match_revision=0,  # stale: current revision is 1
        )


def test_submit_review_unknown_inspection(repository: CentralRepository, device: Any) -> None:
    with pytest.raises(ReviewNotFoundError):
        _submit(repository, device, str(uuid4()))


def test_submit_review_disposition_policy(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    # NG inspections may not be CORRECTED_NG (that is for sampled OK audits).
    inspection_id = _seed_inspection(repository, device, business=BusinessResult.NG)
    with pytest.raises(ReviewDispositionError):
        _submit(
            repository,
            device,
            inspection_id,
            disposition=ReviewDisposition.CORRECTED_NG,
        )
    ok_id = _seed_inspection(repository, device, business=BusinessResult.OK, sequence=2)
    with pytest.raises(ReviewDispositionError):
        _submit(repository, device, ok_id, disposition=ReviewDisposition.REINSPECT)


def test_submit_review_component_corrections_snapshot(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    inspection_id = _seed_inspection(repository, device)
    result = _submit(
        repository,
        device,
        inspection_id,
        corrections=[
            ComponentCorrection(
                component_code="component_a",
                corrected_state=ComponentCorrectionState.PRESENT,
                note="visible under better lighting",
            )
        ],
    )
    assert result.review.component_corrections == [
        {
            "component_code": "component_a",
            "corrected_state": "PRESENT",
            "note": "visible under better lighting",
        }
    ]


def test_review_queue_lists_unreviewed_ng_only(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    ng_id = _seed_inspection(repository, device, business=BusinessResult.NG, sequence=1)
    _seed_inspection(repository, device, business=BusinessResult.OK, sequence=2)
    queue, has_more = repository.list_review_queue(
        device.organization_id, after_completed_at=None, after_id=None, limit=50
    )
    assert has_more is False
    assert len(queue) == 1
    assert queue[0].summary.inspection_id == ng_id
    assert queue[0].reason_codes == ["COMPONENT_MISSING:component_a"]
    # After review, the inspection leaves the queue.
    _submit(repository, device, ng_id)
    empty, _ = repository.list_review_queue(
        device.organization_id, after_completed_at=None, after_id=None, limit=50
    )
    assert empty == []


def test_review_history_oldest_first(
    repository: CentralRepository, device: PilotBootstrapResult
) -> None:
    inspection_id = _seed_inspection(repository, device)
    _submit(repository, device, inspection_id, if_match_revision=None)
    _submit(repository, device, inspection_id, if_match_revision=1)
    history = repository.list_review_history(device.organization_id, inspection_id)
    assert [r.revision for r in history] == [1, 2]
    latest = repository.get_latest_review(device.organization_id, inspection_id)
    assert latest is not None
    assert latest.revision == 2


def test_concurrent_review_submissions_conflict_explicitly(tmp_path: Any) -> None:
    """Two simultaneous submissions: one append wins, the other gets 409.

    The If-Match optimistic lock is authoritative; BEGIN IMMEDIATE serializes
    the read-then-insert so the loser observes the winner's revision and
    fails with an explicit conflict instead of forking the chain. Two
    independent repositories over one file database give each thread its own
    connection (StaticPool would serialize them on a single connection).
    """
    from central_service.api.settings import CentralSettings
    from central_service.persistence.bootstrap import resolve_plan, run_bootstrap

    db_path = tmp_path / "review-race.sqlite3"
    seed_engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    event.listen(seed_engine, "connect", _enable_foreign_keys)
    metadata.create_all(seed_engine)
    seed = CentralRepository(seed_engine)
    run_bootstrap(
        seed,
        resolve_plan(
            CentralSettings(
                database_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
                secure_cookies=False,
            ),
            admin_token=_ADMIN_TOKEN,
            device_upload_token=_DEVICE_TOKEN,
            device_id=str(_DEVICE_ID),
        ),
    )
    device = seed.bootstrap_pilot(
        organization_name="Org A",
        site_name="Site A",
        line_name="Line A",
        device_id=str(_DEVICE_ID),
        device_name="Edge 1",
        device_upload_token=_DEVICE_TOKEN,
        admin_username="admin",
        admin_token=_ADMIN_TOKEN,
    )
    inspection_id = _seed_inspection(seed, device)
    seed_engine.dispose()

    def _open() -> CentralRepository:
        engine = create_engine(f"sqlite+pysqlite:///{db_path}")
        event.listen(engine, "connect", _enable_foreign_keys)
        return CentralRepository(engine)

    repo_a = _open()
    repo_b = _open()
    barrier = threading.Barrier(2)
    results: list[Any] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker(repo: CentralRepository) -> None:
        barrier.wait()
        try:
            result = _submit(repo, device, inspection_id, if_match_revision=None)
            with lock:
                results.append(result)
        except Exception as exc:  # noqa: BLE001 - collect for assertion
            with lock:
                errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(repo_a,)),
        threading.Thread(target=worker, args=(repo_b,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ReviewConflictError)
    history = repo_a.list_review_history(device.organization_id, inspection_id)
    assert [r.revision for r in history] == [1]


class _FakeReviewDiag:
    constraint_name = "uq_review_records_inspection_revision"


class _FakeReviewOrig(Exception):
    diag = _FakeReviewDiag()


def test_concurrent_unique_race_maps_to_review_conflict(
    repository: CentralRepository,
    device: PilotBootstrapResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost insert race on the review revision constraint is a 409.

    PostgreSQL concurrent submissions both read the latest revision before
    either commits; the loser hits the unique (inspection, revision) constraint
    and must surface as REVIEW_CONFLICT (simulated via the diag path), never
    an internal error.
    """
    inspection_id = _seed_inspection(repository, device)

    def _review_insert_fails(*args: object, **kwargs: object) -> object:
        raise IntegrityError("INSERT", {}, _FakeReviewOrig())

    monkeypatch.setattr(review_records, "insert", _review_insert_fails)
    with pytest.raises(ReviewConflictError):
        _submit(repository, device, inspection_id)
    with repository._engine.connect() as connection:
        review_count = connection.execute(select(func.count(review_records.c.id))).scalar_one()
    assert int(review_count) == 0
