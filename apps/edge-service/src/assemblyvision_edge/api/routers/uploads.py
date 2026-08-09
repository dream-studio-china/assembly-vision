"""Upload queue visibility and manual retry endpoints (design 15.3.3)."""

from __future__ import annotations

from assemblyvision_domain.models import UploadTask
from fastapi import APIRouter, Depends

from assemblyvision_edge.api.deps import get_repository
from assemblyvision_edge.api.problems import ApiProblem
from assemblyvision_edge.api.schemas import Page
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(prefix="/uploads", tags=["uploads"])

_RETRYABLE_STATES = ("RETRY_WAIT", "PERMANENT_FAILURE")


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
    transition preserves attempt history by incrementing ``attempt_count``.
    Unknown tasks return 404 and non-eligible tasks return 409 with their
    current state, so an operator action can never reset a task that is
    succeeded, leased by the worker, or cancelled (E3 task invariant 3).
    """
    task = repository.get_upload_task(upload_task_id)
    if task is None:
        raise ApiProblem(
            status_code=404,
            code="NOT_FOUND",
            detail="upload task not found",
        )
    if task.status not in _RETRYABLE_STATES:
        raise ApiProblem(
            status_code=409,
            code="TASK_NOT_RETRYABLE",
            detail=f"upload task is {task.status} and cannot be manually retried",
        )
    updated = repository.retry_upload(upload_task_id, "manual")
    if updated is None:  # pragma: no cover - guarded by the lookup above
        raise ApiProblem(status_code=404, code="NOT_FOUND", detail="upload task not found")
    return updated
