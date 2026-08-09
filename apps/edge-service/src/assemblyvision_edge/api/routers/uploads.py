"""Upload queue visibility and manual retry endpoints (design 15.3.3)."""

from __future__ import annotations

from datetime import UTC, datetime

from assemblyvision_domain.models import UploadTask
from fastapi import APIRouter, Depends

from assemblyvision_edge.api.deps import get_repository
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.schemas import Page
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.get("", response_model=Page[UploadTask])
def list_uploads(
    cursor: str | None = None,
    limit: int = 50,
    repository: EdgeRepository = Depends(get_repository),
) -> Page[UploadTask]:
    page = repository.list_uploads(cursor, limit)
    return Page(items=page.items, next_cursor=page.next_cursor)


@router.post("/{upload_task_id}/retry", response_model=UploadTask)
def retry_upload(
    upload_task_id: str,
    repository: EdgeRepository = Depends(get_repository),
) -> UploadTask:
    """Reset one eligible upload task to ``PENDING`` for a manual retry (E3c).

    Only ``RETRY_WAIT`` and ``PERMANENT_FAILURE`` tasks are eligible; the
    transition is compare-and-set in the repository so a concurrent worker
    claim or a second retry cannot report a false success (PR-022 F03). It
    preserves attempt history by incrementing ``attempt_count`` and clears
    terminal/retry fields. Unknown tasks return 404 and non-eligible tasks
    return 409 with their current state, so an operator action can never reset
    a task that is succeeded, leased by the worker, or cancelled (E3 task
    invariant 3).
    """
    result = repository.retry_upload(upload_task_id, "manual", datetime.now(UTC).isoformat())
    if result.outcome == "NOT_FOUND":
        raise ApiProblem(
            status_code=404,
            code="NOT_FOUND",
            detail="upload task not found",
        )
    if result.outcome == "NOT_RETRYABLE":
        state = result.task.status if result.task is not None else "UNKNOWN"
        raise ApiProblem(
            status_code=409,
            code="TASK_NOT_RETRYABLE",
            detail=f"upload task is {state} and cannot be manually retried",
        )
    if result.task is None:  # pragma: no cover - RETRIED always carries the task
        raise ApiProblem(
            status_code=500,
            code="INTERNAL_ERROR",
            detail="retry succeeded but the task could not be loaded",
        )
    return result.task
