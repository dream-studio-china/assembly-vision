"""Upload queue visibility endpoint (design 15.3.3, M1 read-only)."""

from __future__ import annotations

from assemblyvision_domain.models import UploadTask
from fastapi import APIRouter, Depends

from assemblyvision_edge.api.deps import get_repository
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
