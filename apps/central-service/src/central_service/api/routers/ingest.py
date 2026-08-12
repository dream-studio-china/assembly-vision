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

from central_service.api.deps import _require_device, get_repository, get_settings
from central_service.api.problems import ApiProblem
from central_service.api.schemas import UploadReceiptOut
from central_service.api.settings import CentralSettings
from central_service.ingest import IngestError, PayloadConflictError, ingest_upload
from central_service.persistence.repository import CentralRepository, DeviceRow

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
        "description": "Media ingestion is not available in this pilot step; retryable",
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
    """Ingest one edge inspection upload and return a verified receipt."""
    body = await request.body()
    try:
        result = ingest_upload(
            repository=repository,
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
        # Only INSPECTION envelopes reach persistence; MEDIA is rejected
        # before this point, so the persisted kind is always INSPECTION.
        kind=cast("Literal['INSPECTION', 'MEDIA']", result.receipt.kind),
        checksum_sha256=result.receipt.request_hash,
        size_bytes=result.receipt.size_bytes,
        central_object_id=result.receipt.central_object_id,
    )
