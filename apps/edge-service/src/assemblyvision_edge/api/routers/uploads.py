"""Upload queue visibility endpoint (design 15.3.3, M1 read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from assemblyvision_edge.api.deps import get_repository
from assemblyvision_edge.persistence.repository import EdgeRepository

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.get("")
def list_uploads(
    cursor: str | None = None,
    limit: int = 50,
    repository: EdgeRepository = Depends(get_repository),
) -> dict[str, object]:
    page = repository.list_uploads(cursor, limit)
    return {
        "items": [
            {
                "upload_task_id": str(t.upload_task_id),
                "device_id": str(t.device_id),
                "inspection_id": str(t.inspection_id) if t.inspection_id else None,
                "kind": t.kind,
                "object_id": str(t.object_id),
                "payload_hash": t.payload_hash,
                "status": t.status,
                "idempotency_key": t.idempotency_key,
                "checksum_sha256": t.checksum_sha256,
                "attempt_count": t.attempt_count,
                "next_attempt_at": t.next_attempt_at.isoformat() if t.next_attempt_at else None,
                "last_error_code": t.last_error_code,
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat(),
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            for t in page.items
        ],
        "next_cursor": page.next_cursor,
    }
