"""Append-only human review repository and API tests (design 24).

Covers the optional review boundary: any inspection can be reviewed with a
disposition permitted for its machine outcome; records append and supersede by
reference without rewriting evidence; the queue lists every inspection with its
review state; the API maps repository outcomes to 404/409/422 problems.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from assemblyvision_domain.models import (
    BusinessResult,
    ComponentCorrection,
    ComponentCorrectionState,
    InternalDecision,
    ReviewDisposition,
    ReviewRecord,
)
from assemblyvision_edge.api.app import create_app
from assemblyvision_edge.api.settings import ServerSettings
from assemblyvision_edge.persistence.repository import (
    EdgeRepository,
    ReviewConflictError,
    ReviewDispositionError,
    ReviewSubmissionResult,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.test_api import _record


@pytest.fixture
def repo(tmp_path: Path) -> Iterator[EdgeRepository]:
    repository = EdgeRepository.open(tmp_path / "edge.sqlite3")
    try:
        yield repository
    finally:
        repository.close()


def _client(tmp_path: Path, repo: EdgeRepository) -> TestClient:
    app = create_app(
        ServerSettings(output_root=tmp_path / "out", db_path=tmp_path / "edge.sqlite3")
    )
    client = TestClient(app)
    app.state.repository = repo
    return client


class TestReviewRepository:
    def test_submit_review_appends_and_snapshots_machine_outcome(
        self, repo: EdgeRepository
    ) -> None:
        record = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-1")
        repo.persist_inspection_and_enqueue_uploads(record)
        review = ReviewRecord(
            review_id=uuid4(),
            inspection_id=record.inspection_id,
            disposition=ReviewDisposition.CONFIRMED_NG,
            reason="defect visible in frame",
            reviewer="operator-1",
            created_at=datetime.now(UTC),
            original_business_result=record.decision.business_result,
            original_internal_decision=record.decision.internal_decision,
            original_reason_codes=record.decision.reason_codes,
        )

        result = repo.submit_review(review)

        assert result.superseded_review_id is None
        stored = repo.get_review(str(review.review_id))
        assert stored is not None
        assert stored.disposition is ReviewDisposition.CONFIRMED_NG
        assert stored.original_business_result is BusinessResult.NG
        assert stored.original_reason_codes == ["COMPONENT_MISSING:component_a"]

    def test_second_review_supersedes_previous(self, repo: EdgeRepository) -> None:
        record = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-2")
        repo.persist_inspection_and_enqueue_uploads(record)
        first = ReviewRecord(
            review_id=uuid4(),
            inspection_id=record.inspection_id,
            disposition=ReviewDisposition.CONFIRMED_NG,
            reviewer="operator-1",
            created_at=datetime(2026, 8, 10, 8, 0, tzinfo=UTC),
            original_business_result=record.decision.business_result,
            original_internal_decision=record.decision.internal_decision,
            original_reason_codes=record.decision.reason_codes,
        )
        repo.submit_review(first)
        second = ReviewRecord(
            review_id=uuid4(),
            inspection_id=record.inspection_id,
            disposition=ReviewDisposition.CONFIRMED_OK,
            reason="corrected after rework review",
            reviewer="operator-2",
            created_at=datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
            original_business_result=record.decision.business_result,
            original_internal_decision=record.decision.internal_decision,
            original_reason_codes=record.decision.reason_codes,
        )

        result = repo.submit_review(second)

        assert result.superseded_review_id == first.review_id
        history = repo.list_reviews(str(record.inspection_id))
        assert [r.review_id for r in history] == [first.review_id, second.review_id]
        assert history[1].supersedes_review_id == first.review_id

    def test_incompatible_disposition_is_rejected(self, repo: EdgeRepository) -> None:
        record = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-3")
        repo.persist_inspection_and_enqueue_uploads(record)
        review = ReviewRecord(
            review_id=uuid4(),
            inspection_id=record.inspection_id,
            disposition=ReviewDisposition.REINSPECT,
            reviewer="operator-1",
            created_at=datetime.now(UTC),
            original_business_result=record.decision.business_result,
            original_internal_decision=record.decision.internal_decision,
        )

        with pytest.raises(ReviewDispositionError, match="not permitted"):
            repo.submit_review(review)
        assert repo.list_reviews(str(record.inspection_id)) == []

    def test_review_may_only_supersede_same_inspection(self, repo: EdgeRepository) -> None:
        a = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-A")
        b = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-B")
        repo.persist_inspection_and_enqueue_uploads(a)
        repo.persist_inspection_and_enqueue_uploads(b)
        other = ReviewRecord(
            review_id=uuid4(),
            inspection_id=b.inspection_id,
            disposition=ReviewDisposition.CONFIRMED_NG,
            reviewer="operator-1",
            created_at=datetime.now(UTC),
            original_business_result=b.decision.business_result,
            original_internal_decision=b.decision.internal_decision,
        )
        repo.submit_review(other)
        review = ReviewRecord(
            review_id=uuid4(),
            inspection_id=a.inspection_id,
            disposition=ReviewDisposition.CONFIRMED_NG,
            reviewer="operator-1",
            created_at=datetime.now(UTC),
            original_business_result=a.decision.business_result,
            original_internal_decision=a.decision.internal_decision,
            supersedes_review_id=other.review_id,
        )

        with pytest.raises(ReviewConflictError, match="does not belong"):
            repo.submit_review(review)

    def test_review_queue_reports_review_state(self, repo: EdgeRepository) -> None:
        ng = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-Q")
        ok = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-Q2")
        repo.persist_inspection_and_enqueue_uploads(ng)
        repo.persist_inspection_and_enqueue_uploads(ok)
        review = ReviewRecord(
            review_id=uuid4(),
            inspection_id=ng.inspection_id,
            disposition=ReviewDisposition.CONFIRMED_NG,
            reviewer="operator-1",
            created_at=datetime.now(UTC),
            original_business_result=ng.decision.business_result,
            original_internal_decision=ng.decision.internal_decision,
            original_reason_codes=ng.decision.reason_codes,
        )
        repo.submit_review(review)

        page = repo.list_review_queue()
        by_id = {str(item.inspection_id): item for item in page.items}
        assert by_id[str(ng.inspection_id)].has_review is True
        assert by_id[str(ng.inspection_id)].latest_disposition == "CONFIRMED_NG"
        assert by_id[str(ok.inspection_id)].has_review is False
        assert by_id[str(ok.inspection_id)].latest_disposition is None

        open_page = repo.list_review_queue(reviewed=False)
        assert [str(i.inspection_id) for i in open_page.items] == [str(ok.inspection_id)]
        done_page = repo.list_review_queue(reviewed=True)
        assert [str(i.inspection_id) for i in done_page.items] == [str(ng.inspection_id)]

    def test_reviewing_missing_inspection_fails(self, repo: EdgeRepository) -> None:
        review = ReviewRecord(
            review_id=uuid4(),
            inspection_id=uuid4(),
            disposition=ReviewDisposition.CONFIRMED_NG,
            reviewer="operator-1",
            created_at=datetime.now(UTC),
            original_business_result=BusinessResult.NG,
            original_internal_decision=InternalDecision.NG,
        )
        with pytest.raises(Exception, match="no inspection"):
            repo.submit_review(review)

    def test_concurrent_review_submissions_chain_linearly(self, tmp_path: Path) -> None:
        """Two simultaneous submissions of one inspection form one linear chain.

        Supersede resolution is read-then-insert, so it must hold the SQLite
        write lock before reading; without it both submissions could reference
        the same (or no) previous review and fork the chain (PR-031 finding).
        """
        import threading

        db = tmp_path / "edge.sqlite3"
        seed = EdgeRepository.open(db)
        try:
            record = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-RACE")
            seed.persist_inspection_and_enqueue_uploads(record)
        finally:
            seed.close()

        repo_a = EdgeRepository.open(db)
        repo_b = EdgeRepository.open(db)
        barrier = threading.Barrier(2)
        results: list[ReviewSubmissionResult] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(repo: EdgeRepository) -> None:
            barrier.wait()
            try:
                review = ReviewRecord(
                    review_id=uuid4(),
                    inspection_id=record.inspection_id,
                    disposition=ReviewDisposition.CONFIRMED_NG,
                    reviewer="operator-race",
                    created_at=datetime.now(UTC),
                    original_business_result=record.decision.business_result,
                    original_internal_decision=record.decision.internal_decision,
                    original_reason_codes=record.decision.reason_codes,
                )
                result = repo.submit_review(review)
                with lock:
                    results.append(result)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(repo_a,)),
            threading.Thread(target=worker, args=(repo_b,)),
        ]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            assert errors == []
            assert len(results) == 2
            history = repo_a.list_reviews(str(record.inspection_id))
            assert len(history) == 2
            assert {review.review_id for review in history} == {
                result.review.review_id for result in results
            }
            roots = [review for review in history if review.supersedes_review_id is None]
            links = [review for review in history if review.supersedes_review_id is not None]
            assert len(roots) == 1
            assert len(links) == 1
            assert links[0].supersedes_review_id == roots[0].review_id
        finally:
            repo_a.close()
            repo_b.close()

    def test_duplicate_component_corrections_are_rejected(self, repo: EdgeRepository) -> None:
        record = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-DUP")
        repo.persist_inspection_and_enqueue_uploads(record)
        with pytest.raises(ValidationError, match="at most once"):
            ReviewRecord(
                review_id=uuid4(),
                inspection_id=record.inspection_id,
                disposition=ReviewDisposition.CONFIRMED_NG,
                reviewer="operator-1",
                created_at=datetime.now(UTC),
                original_business_result=record.decision.business_result,
                original_internal_decision=record.decision.internal_decision,
                component_corrections=[
                    ComponentCorrection(
                        component_code="component_a",
                        corrected_state=ComponentCorrectionState.PRESENT,
                    ),
                    ComponentCorrection(
                        component_code="component_a",
                        corrected_state=ComponentCorrectionState.MISSING,
                    ),
                ],
            )

    def test_component_corrections_are_normalized(self, repo: EdgeRepository) -> None:
        record = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-NORM")
        repo.persist_inspection_and_enqueue_uploads(record)
        review = ReviewRecord(
            review_id=uuid4(),
            inspection_id=record.inspection_id,
            disposition=ReviewDisposition.CONFIRMED_NG,
            reviewer="operator-1",
            created_at=datetime.now(UTC),
            original_business_result=record.decision.business_result,
            original_internal_decision=record.decision.internal_decision,
            component_corrections=[
                ComponentCorrection(
                    component_code="  component_a  ",
                    corrected_state=ComponentCorrectionState.PRESENT,
                )
            ],
        )
        repo.submit_review(review)
        stored = repo.get_review(str(review.review_id))
        assert stored is not None
        assert stored.component_corrections[0].component_code == "component_a"


class TestReviewApi:
    def test_submit_and_list_review_via_api(self, repo: EdgeRepository, tmp_path: Path) -> None:
        record = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-API")
        repo.persist_inspection_and_enqueue_uploads(record)
        client = _client(tmp_path, repo)
        try:
            response = client.post(
                f"/api/v1/inspections/{record.inspection_id}/reviews",
                json={
                    "disposition": "CONFIRMED_NG",
                    "reason": "defect visible",
                    "reviewer": "operator-1",
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["disposition"] == "CONFIRMED_NG"
            assert body["reviewer"] == "operator-1"
            assert body["original_business_result"] == "NG"

            history = client.get(f"/api/v1/inspections/{record.inspection_id}/reviews")
            assert history.status_code == 200
            assert len(history.json()) == 1
            assert history.json()[0]["review_id"] == body["review_id"]
        finally:
            client.close()

    def test_queue_endpoint_filters_and_marks_reviewed(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        ng = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-QA")
        repo.persist_inspection_and_enqueue_uploads(ng)
        client = _client(tmp_path, repo)
        try:
            queue = client.get(
                "/api/v1/reviews", params={"business_result": "NG", "reviewed": "false"}
            )
            assert queue.status_code == 200
            assert [item["inspection_id"] for item in queue.json()["items"]] == [
                str(ng.inspection_id)
            ]
            assert queue.json()["items"][0]["has_review"] is False
        finally:
            client.close()

    def test_submit_incompatible_disposition_is_422(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        ok = _record(datetime.now(UTC), business=BusinessResult.OK, barcode="SN-422")
        repo.persist_inspection_and_enqueue_uploads(ok)
        client = _client(tmp_path, repo)
        try:
            response = client.post(
                f"/api/v1/inspections/{ok.inspection_id}/reviews",
                json={
                    "disposition": "REINSPECT",
                    "reviewer": "operator-1",
                },
            )
            assert response.status_code == 422
            assert response.json()["code"] == "REVIEW_DISPOSITION_INVALID"
        finally:
            client.close()

    def test_submit_inconclusive_without_reason_is_422(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        ng = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-INC")
        repo.persist_inspection_and_enqueue_uploads(ng)
        client = _client(tmp_path, repo)
        try:
            response = client.post(
                f"/api/v1/inspections/{ng.inspection_id}/reviews",
                json={"disposition": "INCONCLUSIVE", "reviewer": "operator-1"},
            )
            assert response.status_code == 422
        finally:
            client.close()

    def test_submit_duplicate_component_corrections_is_422(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        ng = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-DUP-API")
        repo.persist_inspection_and_enqueue_uploads(ng)
        client = _client(tmp_path, repo)
        try:
            response = client.post(
                f"/api/v1/inspections/{ng.inspection_id}/reviews",
                json={
                    "disposition": "CONFIRMED_NG",
                    "reviewer": "operator-1",
                    "component_corrections": [
                        {"component_code": "component_a", "corrected_state": "PRESENT"},
                        {"component_code": "component_a", "corrected_state": "MISSING"},
                    ],
                },
            )
            assert response.status_code == 422
            assert response.json()["code"] == "VALIDATION_FAILED"
        finally:
            client.close()

    def test_submit_padded_duplicate_component_corrections_is_422(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        """Whitespace-padded codes normalize before the uniqueness check."""
        ng = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-DUP-PAD")
        repo.persist_inspection_and_enqueue_uploads(ng)
        client = _client(tmp_path, repo)
        try:
            response = client.post(
                f"/api/v1/inspections/{ng.inspection_id}/reviews",
                json={
                    "disposition": "CONFIRMED_NG",
                    "reviewer": "operator-1",
                    "component_corrections": [
                        {"component_code": " component_a ", "corrected_state": "PRESENT"},
                        {"component_code": "component_a", "corrected_state": "MISSING"},
                    ],
                },
            )
            assert response.status_code == 422
            assert response.json()["code"] == "VALIDATION_FAILED"
        finally:
            client.close()

    def test_review_unknown_inspection_is_404(self, repo: EdgeRepository, tmp_path: Path) -> None:
        client = _client(tmp_path, repo)
        try:
            response = client.post(
                f"/api/v1/inspections/{uuid4()}/reviews",
                json={"disposition": "CONFIRMED_NG", "reviewer": "operator-1"},
            )
            assert response.status_code == 404
            assert response.json()["code"] == "INSPECTION_NOT_FOUND"
        finally:
            client.close()

    def test_review_requires_viewer_credential(self, tmp_path: Path) -> None:
        repository = EdgeRepository.open(tmp_path / "edge.sqlite3")
        try:
            app = create_app(
                ServerSettings(
                    output_root=tmp_path / "out",
                    db_path=tmp_path / "edge.sqlite3",
                    api_token="test-edge-token",  # noqa: S106 - test fixture credential
                )
            )
            app.state.repository = repository
            client = TestClient(app)
            try:
                response = client.post(
                    f"/api/v1/inspections/{uuid4()}/reviews",
                    json={"disposition": "CONFIRMED_NG", "reviewer": "operator-1"},
                )
                assert response.status_code == 401
                queue = client.get("/api/v1/reviews")
                assert queue.status_code == 401
            finally:
                client.close()
        finally:
            repository.close()

    def test_supersede_via_api_references_prior_review(
        self, repo: EdgeRepository, tmp_path: Path
    ) -> None:
        record = _record(datetime.now(UTC), business=BusinessResult.NG, barcode="SN-SUP")
        repo.persist_inspection_and_enqueue_uploads(record)
        client = _client(tmp_path, repo)
        try:
            first = client.post(
                f"/api/v1/inspections/{record.inspection_id}/reviews",
                json={"disposition": "CONFIRMED_NG", "reviewer": "op-1"},
            ).json()
            second = client.post(
                f"/api/v1/inspections/{record.inspection_id}/reviews",
                json={"disposition": "CONFIRMED_OK", "reason": "corrected", "reviewer": "op-2"},
            ).json()
            assert second["supersedes_review_id"] == first["review_id"]
            history = client.get(f"/api/v1/inspections/{record.inspection_id}/reviews").json()
            assert [h["review_id"] for h in history] == [first["review_id"], second["review_id"]]
        finally:
            client.close()
