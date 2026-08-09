"""E2a retention state and eligibility tests (task E2a exit criteria).

Covers the durable retention schema/migration, receipt-gated eligibility, the
fenced claim transaction, purge finalization, retryable delete failures, lease
recovery, concurrent claims, and retention metrics. No filesystem deletion
happens here; that is the cleanup worker's responsibility (E2b).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from assemblyvision_domain.models import (
    BusinessResult,
    InspectionRecord,
    MediaLifecycle,
    MediaMetadata,
)
from assemblyvision_edge.persistence.repository import EdgeRepository
from assemblyvision_edge.retention.policy import RetentionPolicy
from sqlalchemy import text

from tests.test_api import _record

NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[EdgeRepository]:
    repository = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        yield repository
    finally:
        repository.close()


def _with_media(record: InspectionRecord, kinds: list[str]) -> InspectionRecord:
    """Replace the default KEY_FRAME with media of the given kinds."""
    record.media = [
        MediaMetadata(
            media_id=uuid4(),
            kind=kind,  # type: ignore[arg-type]  # test helper accepts any media kind
            lifecycle=MediaLifecycle.AVAILABLE,
            relative_path=f"{record.inspection_id}/{kind.lower()}.jpg",
            mime_type="image/jpeg",
            size_bytes=100,
            checksum_sha256="0" * 64,
        )
        for kind in kinds
    ]
    return record


def _seed(
    repo: EdgeRepository,
    *,
    completed_at: datetime = NOW - timedelta(days=3),
    kinds: list[str] | None = None,
    retention: RetentionPolicy | None = None,
) -> InspectionRecord:
    """Persist one record with media and mark all uploads verified + SYNCED.

    ``retention`` is passed to the persist call so ``retention_eligible_at``
    is computed at enqueue; pass None to keep media permanently protected.
    """
    record = _record(completed_at, business=BusinessResult.OK, barcode="SN-E2A")
    if kinds is not None:
        _with_media(record, kinds)
    repo.persist_inspection_and_enqueue_uploads(record, retention=retention)
    _mark_synced(repo, record)
    return record


def _mark_synced(repo: EdgeRepository, record: InspectionRecord) -> None:
    """Drive every upload task to SUCCEEDED with a receipt and central object."""
    with repo._engine.begin() as conn:  # noqa: SLF001
        conn.execute(
            text(
                "UPDATE upload_tasks SET status = 'SUCCEEDED', completed_at = :now, "
                "receipt_json = :receipt, central_object_id = :oid "
                "WHERE inspection_id = :id"
            ),
            {
                "now": NOW.isoformat(),
                "receipt": '{"kind":"verified"}',
                "oid": f"central-{record.inspection_id}",
                "id": str(record.inspection_id),
            },
        )
        conn.execute(
            text(
                "UPDATE inspections SET synchronization_status = 'SYNCED' WHERE inspection_id = :id"
            ),
            {"id": str(record.inspection_id)},
        )


def _set_task_status(
    repo: EdgeRepository,
    record: InspectionRecord,
    status: str,
    *,
    receipt: bool = True,
    central_object: bool = True,
) -> None:
    with repo._engine.begin() as conn:  # noqa: SLF001
        conn.execute(
            text(
                "UPDATE upload_tasks SET status = :status, receipt_json = :receipt, "
                "central_object_id = :oid WHERE inspection_id = :id"
            ),
            {
                "status": status,
                "receipt": '{"kind":"verified"}' if receipt else None,
                "oid": f"central-{record.inspection_id}" if central_object else None,
                "id": str(record.inspection_id),
            },
        )


def _media_ids(repo: EdgeRepository, record: InspectionRecord) -> list[str]:
    with repo._engine.connect() as conn:  # noqa: SLF001
        rows = (
            conn.execute(
                text("SELECT media_id FROM media WHERE inspection_id = :id"),
                {"id": str(record.inspection_id)},
            )
            .scalars()
            .all()
        )
    return [str(m) for m in rows]


class TestMigration:
    def test_fresh_and_reopened_database_preserves_data(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        from datetime import timedelta

        record = _seed(
            repo,
            retention=RetentionPolicy({"KEY_FRAME": timedelta(days=1)}),
            kinds=["KEY_FRAME"],
        )
        repo.close()
        reopened = EdgeRepository.open(tmp_path / "edge.sqlite3")
        try:
            eligible = reopened.retention_eligible(NOW.isoformat())
            assert [str(t.media_id) for t in eligible] == _media_ids(reopened, record)
        finally:
            reopened.close()

    def test_upgrade_0006_to_0007_preserves_rows_and_protects_legacy_media(
        self, tmp_path: Path
    ) -> None:
        """A database at 0006 keeps its rows; media has no hold deadline after."""
        from datetime import timedelta

        from alembic import command
        from alembic.config import Config
        from assemblyvision_edge.persistence.migrate import _ALEMBIC_INI, _MIGRATIONS_DIR

        db = tmp_path / "edge.sqlite3"
        repo = EdgeRepository.open(db)
        _seed(
            repo,
            retention=RetentionPolicy({"KEY_FRAME": timedelta(days=1)}),
            kinds=["KEY_FRAME"],
        )
        repo.close()

        cfg = Config(str(_ALEMBIC_INI))
        cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
        # Round-trip through 0006 (which predates the retention columns).
        command.downgrade(cfg, "0006")
        command.upgrade(cfg, "head")

        reopened = EdgeRepository.open(db)
        try:
            with reopened._engine.connect() as conn:  # noqa: SLF001
                count = conn.execute(text("SELECT COUNT(*) FROM media")).scalar()
                deadline = conn.execute(
                    text("SELECT retention_eligible_at FROM media LIMIT 1")
                ).scalar()
            assert count == 1
            assert deadline is None  # legacy rows are protected by default
            assert reopened.retention_eligible(NOW.isoformat()) == []
        finally:
            reopened.close()


class TestEligibility:
    def test_eligible_when_receipt_verified_and_deadline_elapsed(
        self, repo: EdgeRepository
    ) -> None:
        from datetime import timedelta

        record = _seed(
            repo,
            retention=RetentionPolicy({"KEY_FRAME": timedelta(days=1)}),
            kinds=["KEY_FRAME"],
        )
        eligible = repo.retention_eligible(NOW.isoformat())
        assert [str(t.media_id) for t in eligible] == _media_ids(repo, record)

    def test_no_policy_or_unknown_kind_is_never_eligible(self, repo: EdgeRepository) -> None:
        from datetime import timedelta

        # No policy at all: no retention_eligible_at is recorded.
        no_policy = _seed(repo, kinds=["KEY_FRAME"])
        assert repo.retention_eligible(NOW.isoformat()) == []
        # Kind absent from the policy map stays protected.
        other = _seed(
            repo,
            retention=RetentionPolicy({"KEY_FRAME": timedelta(days=1)}),
            kinds=["ANNOTATED_FRAME", "PRODUCT_ROI"],
        )
        assert repo.retention_eligible(NOW.isoformat()) == []
        assert no_policy and other  # keep references alive for the reader

    def test_unexpired_deadline_is_not_eligible(self, repo: EdgeRepository) -> None:
        from datetime import timedelta

        fresh = _seed(
            repo,
            completed_at=NOW - timedelta(hours=2),
            retention=RetentionPolicy({"KEY_FRAME": timedelta(days=1)}),
            kinds=["KEY_FRAME"],
        )
        assert fresh.inspection_id is not None
        assert repo.retention_eligible(NOW.isoformat()) == []

    @pytest.mark.parametrize(
        "status", ["PENDING", "IN_PROGRESS", "RETRY_WAIT", "PERMANENT_FAILURE", "CANCELLED"]
    )
    def test_pending_or_failed_upload_is_never_eligible(
        self, repo: EdgeRepository, status: str
    ) -> None:
        from datetime import timedelta

        record = _seed(
            repo,
            retention=RetentionPolicy({"KEY_FRAME": timedelta(days=1)}),
            kinds=["KEY_FRAME"],
        )
        _set_task_status(repo, record, status)
        assert repo.retention_eligible(NOW.isoformat()) == []

    def test_missing_receipt_or_central_object_is_not_eligible(self, repo: EdgeRepository) -> None:
        from datetime import timedelta

        no_receipt = _seed(
            repo,
            retention=RetentionPolicy({"KEY_FRAME": timedelta(days=1)}),
            kinds=["KEY_FRAME"],
        )
        _set_task_status(repo, no_receipt, "SUCCEEDED", receipt=False)
        assert repo.retention_eligible(NOW.isoformat()) == []

        no_object = _seed(
            repo,
            retention=RetentionPolicy({"KEY_FRAME": timedelta(days=1)}),
            kinds=["KEY_FRAME"],
        )
        _set_task_status(repo, no_object, "SUCCEEDED", central_object=False)
        assert repo.retention_eligible(NOW.isoformat()) == []

    def test_inspection_must_be_synced(self, repo: EdgeRepository) -> None:
        from datetime import timedelta

        record = _seed(
            repo,
            retention=RetentionPolicy({"KEY_FRAME": timedelta(days=1)}),
            kinds=["KEY_FRAME"],
        )
        with repo._engine.begin() as conn:  # noqa: SLF001
            conn.execute(
                text(
                    "UPDATE inspections SET synchronization_status = 'PARTIAL' "
                    "WHERE inspection_id = :id"
                ),
                {"id": str(record.inspection_id)},
            )
        assert repo.retention_eligible(NOW.isoformat()) == []

    def test_held_locked_faulted_or_purged_is_not_eligible(self, repo: EdgeRepository) -> None:
        from datetime import timedelta

        policy = RetentionPolicy({"KEY_FRAME": timedelta(days=1)})
        held = _seed(repo, retention=policy, kinds=["KEY_FRAME"])
        with repo._engine.begin() as conn:  # noqa: SLF001
            conn.execute(
                text("UPDATE media SET hold_reason = 'acceptance' WHERE inspection_id = :id"),
                {"id": str(held.inspection_id)},
            )
        faulted = _seed(repo, retention=policy, kinds=["KEY_FRAME"])
        with repo._engine.begin() as conn:  # noqa: SLF001
            conn.execute(
                text("UPDATE media SET integrity_status = 'FAULT' WHERE inspection_id = :id"),
                {"id": str(faulted.inspection_id)},
            )
        purged = _seed(repo, retention=policy, kinds=["KEY_FRAME"])
        with repo._engine.begin() as conn:  # noqa: SLF001
            conn.execute(
                text(
                    "UPDATE media SET lifecycle = 'PURGED', purged_at = :now WHERE inspection_id = :id"
                ),
                {"now": NOW.isoformat(), "id": str(purged.inspection_id)},
            )
        deleting = _seed(repo, retention=policy, kinds=["KEY_FRAME"])
        with repo._engine.begin() as conn:  # noqa: SLF001
            conn.execute(
                text(
                    "UPDATE media SET deleting_at = :now, delete_lease_owner = :owner "
                    "WHERE inspection_id = :id"
                ),
                {
                    "now": NOW.isoformat(),
                    "owner": str(uuid4()),
                    "id": str(deleting.inspection_id),
                },
            )
        assert repo.retention_eligible(NOW.isoformat()) == []


class TestClaimAndFencing:
    def test_claim_finalize_purge_requires_matching_token(self, repo: EdgeRepository) -> None:
        from datetime import timedelta

        record = _seed(
            repo,
            retention=RetentionPolicy({"KEY_FRAME": timedelta(days=1)}),
            kinds=["KEY_FRAME"],
        )
        claimed = repo.claim_retention_batch(10, 120, NOW.isoformat())
        assert len(claimed) == 1
        target = claimed[0]
        assert str(target.media_id) in _media_ids(repo, record)

        # A stale/foreign token can never finalize or record a failure.
        assert (
            repo.finalize_media_purge(
                str(target.media_id), str(uuid4()), NOW.isoformat(), "retention"
            )
            == 0
        )
        assert (
            repo.record_media_delete_failure(
                str(target.media_id), str(uuid4()), "ENOENT", NOW.isoformat()
            )
            == 0
        )
        # The legitimate holder can finalize exactly once.
        assert (
            repo.finalize_media_purge(
                str(target.media_id), target.lease_owner, NOW.isoformat(), "retention"
            )
            == 1
        )
        assert (
            repo.finalize_media_purge(
                str(target.media_id), target.lease_owner, NOW.isoformat(), "retention"
            )
            == 0
        )
        with repo._engine.connect() as conn:  # noqa: SLF001
            row = conn.execute(
                text("SELECT lifecycle, purged_at, purge_reason FROM media WHERE media_id = :id"),
                {"id": str(target.media_id)},
            ).one()
        assert row.lifecycle == "PURGED"
        assert row.purged_at == NOW.isoformat()
        assert row.purge_reason == "retention"

    def test_delete_failure_releases_claim_for_retry(self, repo: EdgeRepository) -> None:
        from datetime import timedelta

        _seed(
            repo,
            retention=RetentionPolicy({"KEY_FRAME": timedelta(days=1)}),
            kinds=["KEY_FRAME"],
        )
        claimed = repo.claim_retention_batch(10, 120, NOW.isoformat())
        target = claimed[0]
        assert (
            repo.record_media_delete_failure(
                str(target.media_id), target.lease_owner, "EACCES", NOW.isoformat()
            )
            == 1
        )
        with repo._engine.connect() as conn:  # noqa: SLF001
            row = conn.execute(
                text(
                    "SELECT last_delete_error, deleting_at, delete_lease_owner "
                    "FROM media WHERE media_id = :id"
                ),
                {"id": str(target.media_id)},
            ).one()
        assert row.last_delete_error == "EACCES"
        assert row.deleting_at is None
        assert row.delete_lease_owner is None
        # The released artifact is eligible again for a retry.
        again = repo.claim_retention_batch(10, 120, NOW.isoformat())
        assert [str(t.media_id) for t in again] == [str(target.media_id)]

    def test_expired_lease_is_recovered_and_stale_token_rejected(
        self, repo: EdgeRepository
    ) -> None:
        from datetime import timedelta

        _seed(
            repo,
            retention=RetentionPolicy({"KEY_FRAME": timedelta(days=1)}),
            kinds=["KEY_FRAME"],
        )
        first = repo.claim_retention_batch(10, 1, (NOW - timedelta(minutes=2)).isoformat())
        assert len(first) == 1
        # The old holder tries to finalize after its lease lapsed: rejected.
        assert (
            repo.finalize_media_purge(
                str(first[0].media_id), first[0].lease_owner, NOW.isoformat(), "retention"
            )
            == 0
        )
        released = repo.recover_expired_retention_claims(NOW.isoformat())
        assert released == 1
        second = repo.claim_retention_batch(10, 120, NOW.isoformat())
        assert len(second) == 1
        assert second[0].lease_owner != first[0].lease_owner
        assert (
            repo.finalize_media_purge(
                str(second[0].media_id), second[0].lease_owner, NOW.isoformat(), "retention"
            )
            == 1
        )

    def test_integrity_fault_marks_and_protects_artifact(self, repo: EdgeRepository) -> None:
        from datetime import timedelta

        _seed(
            repo,
            retention=RetentionPolicy({"KEY_FRAME": timedelta(days=1)}),
            kinds=["KEY_FRAME"],
        )
        claimed = repo.claim_retention_batch(10, 120, NOW.isoformat())
        target = claimed[0]
        assert (
            repo.mark_media_integrity_fault(
                str(target.media_id), target.lease_owner, "MEDIA_EVIDENCE_MISSING", NOW.isoformat()
            )
            == 1
        )
        with repo._engine.connect() as conn:  # noqa: SLF001
            row = conn.execute(
                text(
                    "SELECT integrity_status, deleting_at, delete_lease_owner "
                    "FROM media WHERE media_id = :id"
                ),
                {"id": str(target.media_id)},
            ).one()
        assert row.integrity_status == "FAULT"
        assert row.deleting_at is None
        assert row.delete_lease_owner is None
        # A faulted artifact is permanently protected from deletion.
        assert repo.retention_eligible(NOW.isoformat()) == []

    def test_concurrent_workers_claim_disjoint_batches(self, tmp_path: Path) -> None:
        from datetime import timedelta

        db = tmp_path / "edge.sqlite3"
        first = EdgeRepository.open(db)
        try:
            policy = RetentionPolicy({"KEY_FRAME": timedelta(days=1)})
            records = [_seed(first, retention=policy, kinds=["KEY_FRAME"]) for _ in range(8)]
            expected = {m for r in records for m in _media_ids(first, r)}
            first.close()

            repo_a = EdgeRepository.open(db)
            repo_b = EdgeRepository.open(db)
            barrier = threading.Barrier(2)
            results: list[list[str]] = [[], []]

            def _claim(repo: EdgeRepository, out: list[str]) -> None:
                barrier.wait()
                claimed = repo.claim_retention_batch(10, 120, NOW.isoformat())
                out.extend(str(t.media_id) for t in claimed)

            threads = [
                threading.Thread(target=_claim, args=(repo_a, results[0])),
                threading.Thread(target=_claim, args=(repo_b, results[1])),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)
            got = set(results[0]) | set(results[1])
            assert got == expected
            assert not (set(results[0]) & set(results[1]))  # disjoint claims
            repo_a.close()
            repo_b.close()
        finally:
            first.close()


class TestMetrics:
    def test_retention_metrics_reflect_state(self, repo: EdgeRepository) -> None:
        from datetime import timedelta

        policy = RetentionPolicy({"KEY_FRAME": timedelta(days=1)})
        eligible_record = _seed(repo, retention=policy, kinds=["KEY_FRAME"])
        held = _seed(repo, retention=policy, kinds=["KEY_FRAME"])
        with repo._engine.begin() as conn:  # noqa: SLF001
            conn.execute(
                text("UPDATE media SET hold_reason = 'review' WHERE inspection_id = :id"),
                {"id": str(held.inspection_id)},
            )
        metrics = repo.retention_metrics(NOW.isoformat())
        assert metrics.eligible_count == 1
        assert metrics.eligible_bytes == 100
        assert metrics.deleting_count == 0
        assert metrics.purged_count == 0

        claimed = repo.claim_retention_batch(10, 120, NOW.isoformat())
        assert len(claimed) == 1
        repo.finalize_media_purge(
            str(claimed[0].media_id), claimed[0].lease_owner, NOW.isoformat(), "retention"
        )
        after = repo.retention_metrics(NOW.isoformat())
        assert after.eligible_count == 0
        assert after.purged_count == 1
        assert eligible_record.inspection_id is not None
