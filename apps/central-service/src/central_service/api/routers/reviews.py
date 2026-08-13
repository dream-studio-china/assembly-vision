"""Central append-only human review routes (C4, design 24).

The review queue surfaces NG/uncertain inspections without any review under
the versioned M1 routing policy. Submissions append a revision under an
idempotency key and an optimistic ``If-Match`` revision; a stale revision
returns ``409 REVIEW_CONFLICT`` and no fact is overwritten. The original
machine decision is never mutated.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from assemblyvision_domain.models import (
    ComponentCorrection,
    ComponentCorrectionState,
    ReviewDisposition,
)
from fastapi import APIRouter, Depends, Header, Query, Request, Response

from central_service.api.deps import (
    NOT_FOUND_RESPONSES,
    SECURITY,
    UNAUTHENTICATED_RESPONSES,
    _require_admin,
    get_repository,
)
from central_service.api.problems import ApiProblem
from central_service.api.schemas import (
    ReviewOut,
    ReviewQueueItem,
    ReviewQueuePage,
    ReviewSubmit,
)
from central_service.persistence.repository import (
    AdministratorRow,
    CentralRepository,
    ReviewConflictError,
    ReviewDispositionError,
    ReviewNotFoundError,
    ReviewValidationError,
)

router = APIRouter(tags=["reviews"])

_MAX_PAGE_SIZE = 200
_DEFAULT_PAGE_SIZE = 50
_MAX_IDEMPOTENCY_KEY_LEN = 256


def _review_out(review: Any) -> ReviewOut:
    return ReviewOut(
        inspection_id=review.inspection_id,
        revision=review.revision,
        disposition=review.disposition,
        reason=review.reason,
        note=review.note,
        reviewer=review.reviewer,
        component_corrections=review.component_corrections,
        original_business_result=review.original_business_result,
        original_internal_decision=review.original_internal_decision,
        original_reason_codes=review.original_reason_codes,
        created_at=review.created_at,
    )


@router.get(
    "/reviews/queue",
    response_model=ReviewQueuePage,
    openapi_extra={"security": SECURITY},
    responses=UNAUTHENTICATED_RESPONSES,
)
def list_review_queue(
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE)] = _DEFAULT_PAGE_SIZE,
) -> ReviewQueuePage:
    """NG/uncertain inspections awaiting review (C4 routing policy)."""
    after_completed_at: datetime | None = None
    after_id: int | None = None
    if cursor is not None:
        decoded = _parse_queue_cursor(cursor)
        if decoded is None:
            raise ApiProblem(
                status_code=400,
                code="INVALID_CURSOR",
                detail="the cursor is invalid",
            )
        after_completed_at, after_id = decoded
    items, has_more = repository.list_review_queue(
        administrator.organization_id,
        after_completed_at=after_completed_at,
        after_id=after_id,
        limit=limit,
    )
    next_cursor = _encode_queue_cursor(items[-1].summary) if has_more and items else None
    return ReviewQueuePage(
        items=[
            ReviewQueueItem(
                inspection_id=item.summary.inspection_id,
                device_id=item.summary.device_id,
                completed_at=item.summary.completed_at,
                barcode_value=item.summary.barcode_value,
                product_code=item.summary.product_code,
                business_result=item.summary.business_result,
                internal_decision=item.summary.internal_decision,
                reason_codes=item.reason_codes,
            )
            for item in items
        ],
        next_cursor=next_cursor,
    )


@router.get(
    "/inspections/{inspection_id}/reviews",
    response_model=list[ReviewOut],
    openapi_extra={"security": SECURITY},
    responses={**UNAUTHENTICATED_RESPONSES, **NOT_FOUND_RESPONSES},
)
def list_review_history(
    inspection_id: str,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> list[ReviewOut]:
    """Append-only review history for one inspection, oldest first (C4)."""
    if not _valid_uuid(inspection_id):
        raise ApiProblem(
            status_code=404,
            code="INSPECTION_NOT_FOUND",
            detail="the inspection does not exist in this organization",
        )
    history = repository.list_review_history(administrator.organization_id, inspection_id)
    if (
        not history
        and repository.get_inspection_detail(administrator.organization_id, inspection_id) is None
    ):
        raise ApiProblem(
            status_code=404,
            code="INSPECTION_NOT_FOUND",
            detail="the inspection does not exist in this organization",
        )
    return [_review_out(review) for review in history]


@router.post(
    "/inspections/{inspection_id}/reviews",
    response_model=ReviewOut,
    status_code=201,
    openapi_extra={"security": SECURITY},
    responses={
        **UNAUTHENTICATED_RESPONSES,
        **NOT_FOUND_RESPONSES,
        409: {
            "description": "Stale If-Match revision; a newer review already exists",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
        422: {
            "description": "Disposition not permitted for the machine outcome, or invalid corrections",
            "content": {
                "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
            },
        },
    },
)
def submit_review(
    inspection_id: str,
    body: ReviewSubmit,
    response: Response,
    request: Request,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> ReviewOut:
    """Append one review revision; If-Match guards against concurrent change."""
    if not _valid_uuid(inspection_id):
        raise ApiProblem(
            status_code=404,
            code="INSPECTION_NOT_FOUND",
            detail="the inspection does not exist in this organization",
        )
    if idempotency_key is None or not idempotency_key.strip():
        raise ApiProblem(
            status_code=422,
            code="IDEMPOTENCY_KEY_REQUIRED",
            detail="an Idempotency-Key header is required",
        )
    if len(idempotency_key) > _MAX_IDEMPOTENCY_KEY_LEN:
        raise ApiProblem(
            status_code=422,
            code="IDEMPOTENCY_KEY_INVALID",
            detail="the idempotency key is too long",
        )
    if_match_revision: int | None = None
    if if_match is not None:
        try:
            if_match_revision = int(if_match)
        except ValueError as exc:
            raise ApiProblem(
                status_code=422,
                code="IF_MATCH_INVALID",
                detail="If-Match must be an integer revision",
            ) from exc
    try:
        result = repository.submit_review(
            organization_id=administrator.organization_id,
            inspection_id=inspection_id,
            disposition=ReviewDisposition(body.disposition),
            reason=body.reason,
            note=body.note,
            component_corrections=[
                ComponentCorrection(
                    component_code=correction.component_code,
                    corrected_state=ComponentCorrectionState(correction.corrected_state),
                    note=correction.note,
                )
                for correction in body.component_corrections
            ],
            reviewer=administrator.username,
            idempotency_key=idempotency_key,
            request_hash=_review_request_hash(body),
            if_match_revision=if_match_revision,
            created_at=datetime.now(UTC),
        )
    except ReviewNotFoundError as exc:
        raise ApiProblem(
            status_code=404,
            code="INSPECTION_NOT_FOUND",
            detail="the inspection does not exist in this organization",
        ) from exc
    except ReviewConflictError as exc:
        raise ApiProblem(
            status_code=409,
            code="REVIEW_CONFLICT",
            detail=str(exc),
        ) from exc
    except ReviewDispositionError as exc:
        raise ApiProblem(
            status_code=422,
            code="REVIEW_DISPOSITION_INVALID",
            detail=str(exc),
        ) from exc
    except ReviewValidationError as exc:
        raise ApiProblem(
            status_code=422,
            code="INVALID_CORRECTION",
            detail=str(exc),
        ) from exc
    if result.replayed:
        response.status_code = 200
    return _review_out(result.review)


def _review_request_hash(body: ReviewSubmit) -> str:
    """Canonical SHA-256 of the submitted review content (idempotency binding)."""
    canonical = json.dumps(
        body.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def _parse_queue_cursor(cursor: str) -> tuple[datetime, int] | None:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    completed_at = data.get("c")
    row_id = data.get("i")
    if not isinstance(completed_at, str) or not isinstance(row_id, int):
        return None
    try:
        parsed = datetime.fromisoformat(completed_at)
    except ValueError:
        return None
    return parsed, row_id


def _encode_queue_cursor(last: Any) -> str:
    payload = json.dumps(
        {"c": last.completed_at.isoformat(), "i": last.id},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
