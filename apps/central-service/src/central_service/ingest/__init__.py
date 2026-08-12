"""C2a inspection ingestion: envelope parsing, device checks, and persistence.

The router hands the raw request body here; this module parses the envelope,
rejects unsupported task kinds, validates the decoded inspection payload
against the authenticated device, and persists the inspection, receipt, and
audit event through the repository's single transaction. The returned receipt
echoes the fields the edge validates (task C1 section 5.3) and is safe for
the edge scheduler to accept as verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from central_service.api.settings import CentralSettings
from central_service.ingest.envelope import decode_inspection_payload, parse_envelope
from central_service.ingest.errors import IngestError
from central_service.persistence.repository import (
    CentralRepository,
    DeviceRow,
    PayloadConflictError,
    UploadReceiptRow,
)


@dataclass(frozen=True)
class IngestionResult:
    """Outcome of one accepted or replayed inspection upload."""

    receipt: UploadReceiptRow
    replayed: bool


def ingest_upload(
    *,
    repository: CentralRepository,
    device: DeviceRow,
    body: bytes,
    settings: CentralSettings,
    received_at: datetime | None = None,
) -> IngestionResult:
    """Parse, validate, and persist one edge inspection upload.

    MEDIA envelopes are rejected with a retryable 503 in this delivery: media
    staging and object binding is the C2b milestone, and a permanent failure
    here would strand the edge's pending media tasks. INSPECTION envelopes are
    parsed, validated against the authenticated device, and persisted
    idempotently; identical replay returns the original receipt.
    """
    envelope = parse_envelope(body, settings)
    if envelope.kind == "MEDIA":
        raise IngestError(
            status_code=503,
            code="MEDIA_INGESTION_UNAVAILABLE",
            detail="media ingestion is not available in this pilot step; retry later",
            headers={"Retry-After": "5"},
        )
    record = decode_inspection_payload(envelope, device)
    if received_at is None:
        received_at = datetime.now(UTC)
    # The edge uploads canonical sorted-compact JSON, so the decoded bytes are
    # the canonical form already; the accepted text is preserved verbatim so
    # the persisted payload always matches what was hashed and replayed.
    payload_json = envelope.payload.decode("utf-8")
    receipt, replayed = repository.ingest_inspection(
        device=device,
        idempotency_key=envelope.idempotency_key,
        request_hash=envelope.request_hash,
        object_id=envelope.object_id,
        inspection_id=str(record.inspection_id),
        record=record,
        payload_json=payload_json,
        received_at=received_at,
    )
    return IngestionResult(receipt=receipt, replayed=replayed)


__all__ = [
    "IngestError",
    "IngestionResult",
    "PayloadConflictError",
    "ingest_upload",
]
