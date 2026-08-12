"""C2a/C2b inspection and media ingestion.

The router hands the raw request body here; this module parses the envelope,
validates the payload against the authenticated device, persists accepted
inspection metadata (C2a) or binds media bytes into the object store (C2b),
and returns a receipt the edge scheduler accepts as verified. The receipt
echoes the fields the edge validates (task C1 section 5.3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from central_service.api.settings import CentralSettings
from central_service.ingest.envelope import (
    ParsedEnvelope,
    decode_inspection_payload,
    parse_envelope,
)
from central_service.ingest.errors import IngestError
from central_service.persistence.repository import (
    CentralRepository,
    DeviceRow,
    PayloadConflictError,
    UploadReceiptRow,
)
from central_service.storage.object_store import ObjectStorage

log = logging.getLogger("central_service.ingest")


@dataclass(frozen=True)
class IngestionResult:
    """Outcome of one accepted or replayed upload."""

    receipt: UploadReceiptRow
    replayed: bool


def ingest_upload(
    *,
    repository: CentralRepository,
    storage: ObjectStorage,
    device: DeviceRow,
    body: bytes,
    settings: CentralSettings,
    received_at: datetime | None = None,
) -> IngestionResult:
    """Parse, validate, and persist one edge upload envelope.

    INSPECTION envelopes are validated against the authenticated device and
    persisted idempotently; identical replay returns the original receipt.
    MEDIA envelopes are bound into the object store after cross-checking the
    bytes against the parent inspection manifest (C2b).
    """
    envelope = parse_envelope(body, settings)
    if envelope.kind == "MEDIA":
        return ingest_media(
            repository=repository,
            storage=storage,
            device=device,
            envelope=envelope,
            settings=settings,
            received_at=received_at,
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
    log.info(
        "inspection upload device=%s inspection=%s object=%s kind=INSPECTION replayed=%s",
        device.device_id,
        record.inspection_id,
        envelope.object_id,
        replayed,
    )
    return IngestionResult(receipt=receipt, replayed=replayed)


def ingest_media(
    *,
    repository: CentralRepository,
    storage: ObjectStorage,
    device: DeviceRow,
    envelope: ParsedEnvelope,
    settings: CentralSettings,
    received_at: datetime | None,
) -> IngestionResult:
    """Bind one MEDIA envelope into the object store with a verified receipt.

    The parent inspection must already be accepted (the edge scheduler enforces
    metadata-before-media); the incoming bytes are cross-checked against the
    media metadata recorded in the inspection manifest. The object is staged
    under a central generated tenant-scoped key and the binding row reports
    AVAILABLE only after the write (C1 invariant 8).
    """
    if envelope.inspection_id is None:
        raise IngestError(
            status_code=422,
            code="INVALID_ENVELOPE",
            detail="a MEDIA upload requires a parent inspection id",
        )
    if len(envelope.payload) > settings.max_media_payload_bytes:
        raise IngestError(
            status_code=413,
            code="PAYLOAD_TOO_LARGE",
            detail="the media payload exceeds the configured limit",
        )
    manifest_lookup = repository.get_inspection_media_manifest(device.id, envelope.inspection_id)
    if manifest_lookup is None:
        raise IngestError(
            status_code=422,
            code="INSPECTION_NOT_FOUND",
            detail="the parent inspection is not accepted for this device",
        )
    inspection_row_id, capture_at, manifest = manifest_lookup
    entry = manifest.get(envelope.object_id)
    if entry is None:
        raise IngestError(
            status_code=422,
            code="MEDIA_NOT_IN_MANIFEST",
            detail="the media id is not part of the parent inspection manifest",
        )
    if entry.size_bytes != envelope.size_bytes or entry.checksum_sha256 != envelope.checksum_sha256:
        raise IngestError(
            status_code=422,
            code="MEDIA_MANIFEST_MISMATCH",
            detail="the media bytes do not match the parent inspection manifest",
        )
    if received_at is None:
        received_at = datetime.now(UTC)

    # Idempotent replay: identical bytes return the original receipt without
    # re-writing the object; a reused key with different content is a conflict.
    existing = repository.get_receipt(device, envelope.idempotency_key)
    if existing is not None:
        if existing.request_hash == envelope.request_hash:
            return IngestionResult(receipt=existing, replayed=True)
        repository.record_payload_conflict(
            device=device,
            target_type="media-upload",
            target_id=envelope.object_id,
            detail=f"idempotency_key={envelope.idempotency_key} replay conflict",
        )
        raise PayloadConflictError(
            reason="the media idempotency key was accepted with different content",
            idempotency_key=envelope.idempotency_key,
        )
    # A source media identity already bound (e.g. re-upload under a different
    # key) is a conflict detected before any object write, so the common
    # retry path never stages an orphan; persist_media re-checks under the
    # database lock as the concurrent backstop.
    if repository.get_media_binding(device.id, envelope.object_id) is not None:
        repository.record_payload_conflict(
            device=device,
            target_type="media-upload",
            target_id=envelope.object_id,
            detail=f"idempotency_key={envelope.idempotency_key} source media already bound",
        )
        raise PayloadConflictError(
            reason="the source media id is already bound for this device",
            idempotency_key=envelope.idempotency_key,
        )

    object_key = _object_key(device, envelope.object_id, received_at)
    central_object_id = str(uuid4())
    try:
        storage.put_object(object_key, envelope.payload, entry.mime_type)
    except Exception as exc:  # noqa: BLE001 - any store failure is retryable
        log.error(
            "object store unavailable device=%s object=%s",
            device.device_id,
            envelope.object_id,
            exc_info=exc,
        )
        raise IngestError(
            status_code=503,
            code="OBJECT_STORE_UNAVAILABLE",
            detail="the object store could not accept the media; retry later",
            headers={"Retry-After": "5"},
        ) from exc

    receipt, replayed = repository.persist_media(
        device=device,
        inspection_row_id=inspection_row_id,
        idempotency_key=envelope.idempotency_key,
        request_hash=envelope.request_hash,
        object_id=envelope.object_id,
        inspection_id=envelope.inspection_id,
        central_object_id=central_object_id,
        object_key=object_key,
        media_kind=entry.media_kind,
        mime_type=entry.mime_type,
        size_bytes=envelope.size_bytes,
        checksum_sha256=envelope.checksum_sha256,
        capture_at=capture_at,
        received_at=received_at,
    )
    log.info(
        "media upload device=%s inspection=%s object=%s kind=MEDIA size=%d replayed=%s",
        device.device_id,
        envelope.inspection_id,
        envelope.object_id,
        envelope.size_bytes,
        replayed,
    )
    return IngestionResult(receipt=receipt, replayed=replayed)


def _object_key(device: DeviceRow, source_media_id: str, received_at: datetime) -> str:
    """Opaque tenant-scoped object key (task C1 section 8.3).

    Generated by the central server; the client never supplies storage paths.
    The registered device identity is sanitized so an operator-registered id
    cannot inject path segments into the key structure.
    """
    safe_device_id = "".join(ch for ch in device.device_id if ch.isalnum() or ch in "._-")
    return (
        f"org/{device.organization_id}/device/{safe_device_id}/"
        f"{received_at.year}/{received_at.month:02d}/{source_media_id}"
    )


__all__ = [
    "IngestError",
    "IngestionResult",
    "PayloadConflictError",
    "ingest_upload",
]
