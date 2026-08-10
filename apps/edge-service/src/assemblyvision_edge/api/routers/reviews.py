"""Human review queue and submission endpoints (design 24).

Reviews are append-only dispositions over immutable inspection evidence. A
submission never rewrites the machine decision; the record snapshots the
original outcome and references any superseded review (24.7). The queue lists
every inspection with its review state so the initial all-NG rollout policy can
filter ``business_result=NG`` (including ``UNCERTAIN``) and separate open from
completed items (24.2.1/24.4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from assemblyvision_domain.models import (
    BusinessResult,
    ComponentCorrection,
    InternalDecision,
    ReviewDisposition,
    ReviewRecord,
)
from fastapi import APIRouter, Depends
from pydantic import ValidationError

from assemblyvision_edge.api.deps import get_repository
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.schemas import (
    Page,
    ReviewQueueItem,
    SubmitReviewRequest,
)
from assemblyvision_edge.persistence.repository import (
    EdgeRepository,
    InvalidCursorError,
    RepositoryError,
    ReviewConflictError,
    ReviewDispositionError,
)

router = APIRouter(tags=["reviews"])


def _problem_response(description: str) -> dict[str, object]:
    """Describe the RFC 7807 media type emitted by the shared handlers."""
    return {
        "description": description,
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
        },
    }


@router.get(
    "/reviews",
    response_model=Page[ReviewQueueItem],
    responses={400: _problem_response("Malformed or filter-mismatched cursor")},
)
def list_review_queue(
    business_result: str | None = None,
    internal_decision: str | None = None,
    reviewed: bool | None = None,
    cursor: str | None = None,
    limit: int = 50,
    repository: EdgeRepository = Depends(get_repository),
) -> Page[ReviewQueueItem]:
    """List the review queue with each inspection's review state (24.4)."""
    try:
        page = repository.list_review_queue(
            business_result=business_result,
            internal_decision=internal_decision,
            reviewed=reviewed,
            cursor=cursor,
            limit=limit,
        )
    except InvalidCursorError as exc:
        raise ApiProblem(
            status_code=400,
            code="INVALID_CURSOR",
            detail="the cursor is malformed or does not match the current filters",
        ) from exc
    return Page(
        items=[
            ReviewQueueItem(
                inspection_id=item.inspection_id,
                completed_at=item.completed_at,
                business_result=BusinessResult(item.business_result),
                internal_decision=InternalDecision(item.internal_decision),
                barcode=item.barcode,
                reason_summary=item.reason_summary,
                has_review=item.has_review,
                latest_disposition=(
                    ReviewDisposition(item.latest_disposition)
                    if item.latest_disposition is not None
                    else None
                ),
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/inspections/{inspection_id}/reviews",
    response_model=list[ReviewRecord],
    responses={404: _problem_response("Inspection not found")},
)
def list_inspection_reviews(
    inspection_id: str,
    repository: EdgeRepository = Depends(get_repository),
) -> list[ReviewRecord]:
    """Return the append-only review history of one inspection (24.7)."""
    if repository.get_inspection(inspection_id) is None:
        raise ApiProblem(
            status_code=404, code="INSPECTION_NOT_FOUND", detail=f"no inspection {inspection_id}"
        )
    return repository.list_reviews(inspection_id)


@router.post(
    "/inspections/{inspection_id}/reviews",
    response_model=ReviewRecord,
    responses={
        404: _problem_response("Inspection not found"),
        409: _problem_response("Review conflict (supersede targets another inspection)"),
        422: _problem_response("Invalid disposition or review"),
    },
)
def submit_review(
    inspection_id: str,
    request: SubmitReviewRequest,
    repository: EdgeRepository = Depends(get_repository),
) -> ReviewRecord:
    """Append one human disposition for an inspection (24.3/24.6).

    The disposition must be permitted for the machine outcome: an incompatible
    correction is rejected (422) instead of recorded, and a review may only
    supersede another review of the same inspection (409). The submitted
    reviewer name and reason are required as documented; ``INCONCLUSIVE``
    always requires a reason.
    """
    record = repository.get_inspection(inspection_id)
    if record is None:
        raise ApiProblem(
            status_code=404, code="INSPECTION_NOT_FOUND", detail=f"no inspection {inspection_id}"
        )
    try:
        review = ReviewRecord(
            review_id=uuid4(),
            inspection_id=record.inspection_id,
            disposition=request.disposition,
            reason=request.reason,
            note=request.note,
            reviewer=request.reviewer,
            created_at=datetime.now(UTC),
            original_business_result=record.decision.business_result,
            original_internal_decision=record.decision.internal_decision,
            original_reason_codes=record.decision.reason_codes,
            component_corrections=[
                ComponentCorrection(**correction.model_dump())
                for correction in request.component_corrections
            ],
            supersedes_review_id=request.supersedes_review_id,
        )
        result = repository.submit_review(review)
    except ValidationError as exc:
        raise ApiProblem(
            status_code=422,
            code="REVIEW_VALIDATION_FAILED",
            detail="review record is invalid",
        ) from exc
    except ReviewDispositionError as exc:
        raise ApiProblem(
            status_code=422,
            code="REVIEW_DISPOSITION_INVALID",
            detail=str(exc),
        ) from exc
    except ReviewConflictError as exc:
        raise ApiProblem(
            status_code=409,
            code="REVIEW_CONFLICT",
            detail=str(exc),
        ) from exc
    except RepositoryError as exc:
        raise ApiProblem(
            status_code=500,
            code="INTERNAL_ERROR",
            detail="review could not be stored",
        ) from exc
    # The repository resolves the chained supersede reference when the caller
    # does not supply one; echo it back so the stored record is faithful.
    if result.superseded_review_id is not None and review.supersedes_review_id is None:
        return review.model_copy(update={"supersedes_review_id": result.superseded_review_id})
    return review
