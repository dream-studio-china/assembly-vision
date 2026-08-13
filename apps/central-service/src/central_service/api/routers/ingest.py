"""Device upload ingestion routes (C2a).

``POST /api/v1/inspection-uploads`` accepts the current edge upload envelope
over the device upload credential (strictly separated from administrator
credentials, C1b). Accepted inspections, receipts, and audit events commit in
one transaction; identical replay returns the original receipt and a content
conflict returns ``409 PAYLOAD_CONFLICT`` without altering the accepted
resource.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from starlette.concurrency import run_in_threadpool

from central_service.api.deps import _require_device, get_repository, get_settings
from central_service.api.problems import ApiProblem
from central_service.api.schemas import UploadReceiptOut
from central_service.api.settings import CentralSettings
from central_service.ingest import IngestError, PayloadConflictError, ingest_upload
from central_service.persistence.repository import CentralRepository, DeviceRow
from central_service.storage.object_store import ObjectStorage

router = APIRouter(tags=["ingest"])

# RFC 7807 problem responses the ingest route can actually return (task C1
# section 5.4); the Problem schema is declared so it lands in the OpenAPI.
INGEST_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"description": "Identical replay; the original verified receipt is returned"},
    201: {"description": "New valid inspection persisted with a verified receipt"},
    401: {
        "description": "A valid device upload credential is required",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
        },
    },
    403: {
        "description": "The payload device does not match the authenticated device",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
        },
    },
    409: {
        "description": "Payload conflict: a reused identity carried different content",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
        },
    },
    413: {
        "description": "The envelope or payload exceeds the configured limit",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
        },
    },
    422: {
        "description": "Malformed, invalid, or identity-mismatched envelope or payload",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
        },
    },
    503: {
        "description": "The object store could not accept the media; retryable",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
        },
    },
}


@router.post(
    "/inspection-uploads",
    response_model=UploadReceiptOut,
    status_code=201,
    responses=INGEST_RESPONSES,
)
async def inspection_uploads(
    request: Request,
    response: Response,
    device: DeviceRow = Depends(_require_device),
    repository: CentralRepository = Depends(get_repository),
    settings: CentralSettings = Depends(get_settings),
) -> UploadReceiptOut:
    """Ingest one edge inspection or media upload and return a receipt."""
    body = await _read_body_bounded(request, settings.max_envelope_body_bytes)
    try:
        # Synchronous database/object-store work runs in the thread pool so a
        # slow dependency cannot block the event loop or health probes.
        result = await run_in_threadpool(
            ingest_upload,
            repository=repository,
            storage=cast("ObjectStorage", request.app.state.storage),
            device=device,
            body=body,
            settings=settings,
            received_at=datetime.now(UTC),
        )
    except IngestError as exc:
        raise ApiProblem(
            status_code=exc.status_code,
            code=exc.code,
            detail=exc.detail,
            errors=exc.errors,
            headers=exc.headers,
        ) from exc
    except PayloadConflictError as exc:
        raise ApiProblem(
            status_code=409,
            code="PAYLOAD_CONFLICT",
            detail=exc.reason,
        ) from exc
    if result.replayed:
        response.status_code = 200
    return UploadReceiptOut(
        idempotency_key=result.receipt.idempotency_key,
        object_id=result.receipt.object_id,
        kind=cast("Literal['INSPECTION', 'MEDIA']", result.receipt.kind),
        checksum_sha256=result.receipt.request_hash,
        size_bytes=result.receipt.size_bytes,
        central_object_id=result.receipt.central_object_id,
    )


async def _read_body_bounded(request: Request, limit: int) -> bytes:
    """Read the request body with a hard byte cap enforced before buffering.

    ``Content-Length`` is rejected up front when present; a chunked or lying
    client is bounded by counting streamed chunks so a hostile request can
    never allocate beyond the configured envelope limit.
    """
    content_length = request.headers.get("Content-Length")
    if content_length is not None:
        try:
            if int(content_length) > limit:
                raise _payload_too_large()
        except ValueError:
            pass
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise _payload_too_large()
        chunks.append(chunk)
    return b"".join(chunks)


def _payload_too_large() -> ApiProblem:
    return ApiProblem(
        status_code=413,
        code="PAYLOAD_TOO_LARGE",
        detail="the upload envelope exceeds the configured body limit",
    )
