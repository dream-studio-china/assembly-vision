"""Strict typed parser for the edge upload envelope (C2a, design 13.3).

The parser accepts the exact envelope the current edge ``HttpUploadSink``
sends (task C1 section 5.2): bounded JSON with typed fields, Base64 payload,
declared byte size, and optional SHA-256. The canonical request hash is the
SHA-256 of the decoded payload bytes - the same value the edge computes via
``_content_hash`` for INSPECTION tasks - so an identical replay carries the
same hash and a content conflict is detectable (task C1 section 5.4).

Validation order matters: body bound, JSON shape, typed fields, Base64
decoding, declared size, declared checksum, then the inspection-payload bound
and semantic identity checks. Unknown fields are rejected at the mutation
boundary (contract 05).
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from assemblyvision_domain.models import APIModel, InspectionRecord
from pydantic import Field, ValidationError, field_validator

from central_service.api.settings import CentralSettings
from central_service.ingest.errors import IngestError
from central_service.persistence.repository import DeviceRow


class UploadEnvelope(APIModel):
    """Bounded edge upload envelope; unknown fields are rejected."""

    idempotency_key: str = Field(min_length=1, max_length=256)
    kind: Literal["INSPECTION", "MEDIA"]
    object_id: str
    inspection_id: str | None = None
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    payload_b64: str = Field(min_length=1)

    @field_validator("object_id", "inspection_id")
    @classmethod
    def _uuid_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        UUID(value)
        return value


@dataclass(frozen=True)
class ParsedEnvelope:
    """A validated upload envelope with its decoded payload and hash."""

    idempotency_key: str
    kind: Literal["INSPECTION", "MEDIA"]
    object_id: str
    inspection_id: str | None
    checksum_sha256: str | None
    size_bytes: int
    payload: bytes
    request_hash: str


def parse_envelope(body: bytes, settings: CentralSettings) -> ParsedEnvelope:
    """Parse and validate one upload envelope against the configured bounds."""
    if len(body) > settings.max_envelope_body_bytes:
        raise IngestError(
            status_code=413,
            code="PAYLOAD_TOO_LARGE",
            detail="the upload envelope exceeds the configured body limit",
        )
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise IngestError(
            status_code=422,
            code="INVALID_ENVELOPE",
            detail="the upload envelope is not valid JSON",
        ) from exc
    if not isinstance(data, dict):
        raise IngestError(
            status_code=422,
            code="INVALID_ENVELOPE",
            detail="the upload envelope must be a JSON object",
        )
    try:
        envelope = UploadEnvelope(**data)
    except ValidationError as exc:
        raise IngestError(
            status_code=422,
            code="INVALID_ENVELOPE",
            detail="the upload envelope failed validation",
            errors=_validation_errors(exc),
        ) from exc
    try:
        payload = base64.b64decode(envelope.payload_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise IngestError(
            status_code=422,
            code="INVALID_PAYLOAD_ENCODING",
            detail="the payload is not valid Base64",
        ) from exc
    if len(payload) != envelope.size_bytes:
        raise IngestError(
            status_code=422,
            code="SIZE_MISMATCH",
            detail="the decoded payload size does not match the declared size",
        )
    request_hash = hashlib.sha256(payload).hexdigest()
    if envelope.checksum_sha256 is not None and envelope.checksum_sha256 != request_hash:
        raise IngestError(
            status_code=422,
            code="CHECKSUM_MISMATCH",
            detail="the declared checksum does not match the decoded payload",
        )
    if envelope.kind == "INSPECTION" and len(payload) > settings.max_inspection_payload_bytes:
        raise IngestError(
            status_code=413,
            code="PAYLOAD_TOO_LARGE",
            detail="the inspection payload exceeds the configured limit",
        )
    return ParsedEnvelope(
        idempotency_key=envelope.idempotency_key,
        kind=envelope.kind,
        object_id=envelope.object_id,
        inspection_id=envelope.inspection_id,
        checksum_sha256=envelope.checksum_sha256 or request_hash,
        size_bytes=envelope.size_bytes,
        payload=payload,
        request_hash=request_hash,
    )


def decode_inspection_payload(envelope: ParsedEnvelope, device: DeviceRow) -> InspectionRecord:
    """Decode and validate the INSPECTION payload against the authenticated device.

    The payload must be a valid current ``InspectionRecord`` whose device
    identity matches the authenticated device and whose inspection identity
    matches the envelope (task C1 section 5.1/5.4).
    """
    try:
        data = json.loads(envelope.payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise IngestError(
            status_code=422,
            code="INVALID_PAYLOAD",
            detail="the inspection payload is not valid JSON",
        ) from exc
    if not isinstance(data, dict):
        raise IngestError(
            status_code=422,
            code="INVALID_PAYLOAD",
            detail="the inspection payload must be a JSON object",
        )
    # The edge excludes the mutable ``synchronization_status`` from the
    # immutable upload payload (edge ``_load_payload`` pops it); the central
    # re-adds the terminal value only so the canonical model validates. The
    # raw accepted bytes stored in ``payload_json`` remain byte-for-byte the
    # uploaded evidence.
    data.setdefault("synchronization_status", "SYNCED")
    try:
        record = InspectionRecord(**data)
    except ValidationError as exc:
        raise IngestError(
            status_code=422,
            code="INVALID_PAYLOAD",
            detail="the inspection payload failed schema validation",
            errors=_validation_errors(exc),
        ) from exc
    if str(record.device_id) != device.device_id:
        raise IngestError(
            status_code=403,
            code="DEVICE_MISMATCH",
            detail="the payload device does not match the authenticated upload credential",
        )
    if (
        str(record.inspection_id) != envelope.inspection_id
        or str(record.inspection_id) != envelope.object_id
    ):
        raise IngestError(
            status_code=422,
            code="IDENTITY_MISMATCH",
            detail="the envelope identity does not match the inspection payload",
        )
    return record


def _validation_errors(exc: ValidationError) -> list[dict[str, str]]:
    """Bounded per-field validation details for the problem response."""
    return [
        {"field": ".".join(str(p) for p in err.get("loc", ())), "message": err.get("msg", "")}
        for err in exc.errors()
    ]
