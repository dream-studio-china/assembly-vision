"""Authorized media streaming route (C3, design 05 section 3.2).

Media bytes are served through the API after administrator authentication,
so the browser never touches MinIO directly and no bucket credentials or
object keys are exposed. The binding is resolved organization-scoped; only
AVAILABLE objects are streamed.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from central_service.api.deps import (
    UNAUTHENTICATED_RESPONSES,
    _require_admin,
    get_repository,
)
from central_service.api.problems import ApiProblem
from central_service.persistence.repository import AdministratorRow, CentralRepository
from central_service.storage.object_store import ObjectStorage

router = APIRouter(prefix="/media", tags=["media"])


@router.get(
    "/{central_object_id}",
    responses=UNAUTHENTICATED_RESPONSES,
)
def stream_media(
    central_object_id: str,
    request: Request,
    repository: CentralRepository = Depends(get_repository),
    administrator: AdministratorRow = Depends(_require_admin),
) -> StreamingResponse:
    """Stream one bound media object through the authenticated API."""
    try:
        UUID(central_object_id)
    except ValueError as exc:
        raise ApiProblem(
            status_code=404,
            code="MEDIA_NOT_FOUND",
            detail="the media object does not exist in this organization",
        ) from exc
    binding = repository.get_media_by_central_object_id(
        administrator.organization_id, central_object_id
    )
    if binding is None:
        raise ApiProblem(
            status_code=404,
            code="MEDIA_NOT_FOUND",
            detail="the media object does not exist in this organization",
        )
    if binding.lifecycle != "AVAILABLE":
        raise ApiProblem(
            status_code=410,
            code="MEDIA_UNAVAILABLE",
            detail="the media object is not available for streaming",
        )
    storage: ObjectStorage = request.app.state.storage

    def chunks() -> Iterator[bytes]:
        yield from storage.get_object(binding.object_key)

    return StreamingResponse(
        chunks(),
        media_type=binding.mime_type or "application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff"},
    )
