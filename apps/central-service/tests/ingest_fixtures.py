"""Shared fixtures for central C2a ingestion tests.

These helpers mirror the current edge serialization exactly (design 13 and
``HttpUploadSink._build_body`` / ``_content_hash`` in the edge scheduler) so
the tests exercise the true wire contract, not a central-side copy.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

from assemblyvision_domain.models import (
    AggregatedComponentEvidence,
    BarcodeResult,
    BusinessResult,
    FrameQualitySummary,
    InspectionDecision,
    InspectionLifecycle,
    InspectionRecord,
    InternalDecision,
    MediaLifecycle,
    MediaMetadata,
    ProductResolution,
)


def canonical_payload(record: InspectionRecord) -> bytes:
    """The exact bytes the edge scheduler uploads for an INSPECTION task.

    ``synchronization_status`` is mutable synchronization state and is
    excluded from the immutable evidence (matching the edge repository).
    """
    payload = record.model_dump(mode="json")
    payload.pop("synchronization_status", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def content_hash(record: InspectionRecord) -> str:
    """Canonical SHA-256 of the immutable inspection projection."""
    return hashlib.sha256(canonical_payload(record)).hexdigest()


def build_record(
    *,
    device_id: UUID,
    inspection_id: UUID | None = None,
    device_sequence: int = 1,
    business: BusinessResult = BusinessResult.NG,
    media_content: bytes | None = None,
) -> InspectionRecord:
    """A realistic edge InspectionRecord matching the edge test fixtures.

    With ``media_content`` set, the manifest entry describes exactly those
    bytes (real SHA-256 and size), which is what C2b media ingestion
    cross-checks against.
    """
    completed_at = datetime.now(UTC)
    inspection_uuid = inspection_id or uuid4()
    media_id = uuid4()
    if media_content is not None:
        media_entries = [
            MediaMetadata(
                media_id=media_id,
                kind="KEY_FRAME",
                lifecycle=MediaLifecycle.AVAILABLE,
                relative_path=f"{inspection_uuid}/key_frame.jpg",
                mime_type="image/jpeg",
                size_bytes=len(media_content),
                checksum_sha256=hashlib.sha256(media_content).hexdigest(),
            )
        ]
    else:
        media_entries = [
            MediaMetadata(
                media_id=media_id,
                kind="KEY_FRAME",
                lifecycle=MediaLifecycle.AVAILABLE,
                relative_path=f"{inspection_uuid}/key_frame.jpg",
                mime_type="image/jpeg",
                size_bytes=10,
                checksum_sha256="0" * 64,
            )
        ]
    return InspectionRecord(
        inspection_id=inspection_uuid,
        device_id=device_id,
        device_sequence=device_sequence,
        lifecycle_status=InspectionLifecycle.COMPLETED,
        started_at=completed_at,
        completed_at=completed_at,
        barcode_result=BarcodeResult(status="NOT_REQUIRED", value=None),
        product_resolution=ProductResolution(
            status="RESOLVED", source="CONFIGURED_DEFAULT", product_code="model_a"
        ),
        frame_quality_summary=FrameQualitySummary(
            total_frame_count=1, usable_frame_count=1, rejected_frame_count=0
        ),
        application_version="0.1.0",
        product_model_version_id=uuid4(),
        product_model_checksum_sha256="0" * 64,
        component_model_version_id=uuid4(),
        component_model_checksum_sha256="0" * 64,
        rule_version_id=uuid4(),
        aggregation_policy_version="single-frame-mvp-1",
        evidence=[
            AggregatedComponentEvidence(
                component_code="component_a",
                state="PRESENT" if business is BusinessResult.OK else "MISSING",
                best_confidence=0.9 if business is BusinessResult.OK else None,
                usable_frame_count=1,
                detection_count=1 if business is BusinessResult.OK else 0,
                policy_reason_codes=(
                    [] if business is BusinessResult.OK else ["COMPONENT_MISSING:component_a"]
                ),
            )
        ],
        decision=InspectionDecision(
            internal_decision=(
                InternalDecision.OK if business is BusinessResult.OK else InternalDecision.NG
            ),
            business_result=business,
            missing_components=[] if business is BusinessResult.OK else ["component_a"],
            reason_codes=[] if business is BusinessResult.OK else ["COMPONENT_MISSING:component_a"],
            decided_at=completed_at,
        ),
        synchronization_status="LOCAL_ONLY",
        processing_ms=12,
        media=media_entries,
    )


def build_envelope(
    record: InspectionRecord,
    *,
    idempotency_key: str | None = None,
    checksum_sha256: str | None = None,
    size_bytes: int | None = None,
    payload_b64: str | None = None,
) -> bytes:
    """Serialize the edge INSPECTION envelope exactly like ``HttpUploadSink``."""
    payload = canonical_payload(record)
    body = {
        "idempotency_key": idempotency_key
        or f"inspection:{record.device_id}:{record.inspection_id}",
        "kind": "INSPECTION",
        "object_id": str(record.inspection_id),
        "inspection_id": str(record.inspection_id),
        "checksum_sha256": checksum_sha256 or content_hash(record),
        "size_bytes": size_bytes if size_bytes is not None else len(payload),
        "payload_b64": payload_b64 or base64.b64encode(payload).decode("ascii"),
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_media_envelope(
    record: InspectionRecord,
    *,
    source_media_id: UUID,
    bytes_content: bytes,
    idempotency_key: str | None = None,
) -> bytes:
    """A MEDIA envelope carrying raw bytes matching one manifest entry."""
    body = {
        "idempotency_key": idempotency_key or f"media:{record.device_id}:{source_media_id}",
        "kind": "MEDIA",
        "object_id": str(source_media_id),
        "inspection_id": str(record.inspection_id),
        "checksum_sha256": hashlib.sha256(bytes_content).hexdigest(),
        "size_bytes": len(bytes_content),
        "payload_b64": base64.b64encode(bytes_content).decode("ascii"),
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


class NoopObjectStorage:
    """In-memory object-store stub for tests (no MinIO dependency).

    Satisfies the ``ObjectStorage`` protocol so the application lifespan and
    media ingestion can run without a MinIO service. Objects are kept in a
    dict keyed by object key so binding/replay assertions can inspect them.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def ensure_bucket(self) -> None:
        return None

    def bucket_ready(self) -> bool:
        return True

    def put_object(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data

    def object_exists(self, key: str) -> bool:
        return key in self.objects

    def remove_object(self, key: str) -> None:
        self.objects.pop(key, None)

    def list_objects(self, prefix: str) -> Iterator[str]:
        yield from sorted(key for key in self.objects if key.startswith(prefix))
