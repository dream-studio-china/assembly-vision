"""Edge repository: read/query inspection records and upload tasks.

The repository owns all SQLite access for the local API. It stores immutable
inspection snapshots with denormalized filter columns so the dashboard can
query recent results without loading the whole record (design 16.10).
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from assemblyvision_domain.errors import AssemblyVisionError
from assemblyvision_domain.models import (
    AggregatedComponentEvidence,
    InspectionRecord,
    MediaMetadata,
    UploadTask,
)
from sqlalchemy import bindparam, create_engine, event, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from assemblyvision_edge.persistence.schema import (
    component_evidence,
    inspections,
    media,
    rule_identities,
    upload_tasks,
)
from assemblyvision_edge.retention.policy import RetentionPolicy

_PAGE_DEFAULT_LIMIT = 50
_PAGE_MAX_LIMIT = 200


class RepositoryError(AssemblyVisionError):
    """Raised for database-level failures."""


class InvalidCursorError(RepositoryError):
    """Raised when a cursor is malformed or bound to a different filter set."""


@dataclass(frozen=True)
class InspectionSummary:
    """Dashboard summary derived from a stored inspection record."""

    inspection_id: UUID
    completed_at: str
    business_result: str
    internal_decision: str
    barcode: str | None
    product_code: str | None
    sn: str | None
    reason_summary: list[str]
    latency_ms: int
    upload_state: str
    model_rule_versions: dict[str, str | None]


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True)
class ClaimedUploadTask:
    """One leased upload task plus the fencing token for its terminal updates.

    The token is generated per claim and persisted in ``lease_owner``; every
    terminal or retry transition must present the same token so a worker whose
    lease was reclaimed can never overwrite the new holder (PR-017 F3).
    """

    task: UploadTask
    lease_owner: str


@dataclass(frozen=True)
class UploadQueueMetrics:
    """Persistent upload queue observability (design 13.9, E1).

    ``pending_bytes`` covers tasks that are not yet terminal (PENDING,
    RETRY_WAIT, IN_PROGRESS); ``oldest_pending_at`` is the creation time of the
    oldest waiting task, so operators can see a stalled queue without reading
    media files.
    """

    by_state: dict[str, int]
    pending_bytes: int
    oldest_pending_at: str | None


@dataclass(frozen=True)
class RetentionTarget:
    """One media artifact that is receipt-verified and past its hold deadline.

    Eligibility (design 12.7, E2 task E2a): the artifact must be ``AVAILABLE``,
    not purged/deleting/held/faulted, past its ``retention_eligible_at``, and
    its inspection ``SYNCED`` with a verified media receipt that includes the
    central object identifier.
    """

    media_id: UUID
    inspection_id: UUID
    kind: str
    relative_path: str
    size_bytes: int
    retention_eligible_at: str


@dataclass(frozen=True)
class ClaimedRetentionTarget:
    """A retention target leased to one cleanup worker with a fencing token.

    The token is persisted in ``delete_lease_owner``; every terminal or retry
    transition must present the same token so a worker whose lease was
    reclaimed can never overwrite the new holder (E2 task invariant 4/5).
    """

    media_id: UUID
    inspection_id: UUID
    kind: str
    relative_path: str
    size_bytes: int
    retention_eligible_at: str
    lease_owner: str
    lease_expires_at: str


@dataclass(frozen=True)
class RetentionMetrics:
    """Persistent cleanup state for device status and alerts (E2)."""

    eligible_count: int
    eligible_bytes: int
    deleting_count: int
    delete_error_count: int
    purged_count: int
    integrity_fault_count: int = 0


@dataclass(frozen=True)
class MediaIdentity:
    """One projected media row used by the startup integrity scan (E2d)."""

    media_id: UUID
    inspection_id: UUID
    kind: str
    relative_path: str
    size_bytes: int
    checksum_sha256: str


def _verified_media_receipt_exists() -> str:
    """SQL fragment: the media task holds a receipt with a central object ID.

    A receipt is only trusted for retention when the media task is SUCCEEDED
    with a persisted receipt that includes the central object identifier; the
    repository validates receipt content at the ``mark_upload_succeeded``
    boundary (PR-020 F12), so presence here implies verification.
    """
    return f"""
        EXISTS (
            SELECT 1 FROM {upload_tasks.name} t
            WHERE t.kind = 'MEDIA' AND t.object_id = m.media_id
              AND t.status = 'SUCCEEDED'
              AND t.receipt_json IS NOT NULL
              AND t.central_object_id IS NOT NULL
        )
    """


def _retention_eligible_where() -> str:
    """SQL predicate for receipt-gated retention eligibility (design 12.7).

    Protects pending/in-progress/retrying/failed/cancelled uploads (the
    inspection can only be ``SYNCED`` when every task holds a verified
    receipt), held/locked/faulted artifacts, and anything without an elapsed
    hold deadline. Shared by the eligibility query, the claim transaction, and
    the metrics aggregate.
    """
    return f"""
        m.lifecycle = 'AVAILABLE'
        AND m.purged_at IS NULL
        AND m.deleting_at IS NULL
        AND (m.integrity_status IS NULL OR m.integrity_status <> 'FAULT')
        AND m.hold_reason IS NULL
        AND m.retention_eligible_at IS NOT NULL
        AND m.retention_eligible_at <= :now
        AND i.synchronization_status = 'SYNCED'
        AND {_verified_media_receipt_exists()}
    """


def _filter_fingerprint(filters: dict[str, object]) -> str:
    """Canonical SHA-256 of the active filter set.

    A cursor is only valid for the exact filter set that produced it; reusing
    a cursor across different filters would silently walk the wrong result
    set (AUDIT-001 4.5).
    """
    canonical = json.dumps(filters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _encode_cursor(completed_at: str, inspection_id: str, filters: str | None = None) -> str:
    payload: dict[str, str] = {"completed_at": completed_at, "inspection_id": inspection_id}
    if filters is not None:
        payload["filters"] = filters
    raw = json.dumps(payload, sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str | None, filters: str | None = None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw)
        completed_at = str(payload["completed_at"])
        inspection_id = str(payload["inspection_id"])
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise InvalidCursorError("invalid cursor") from exc
    if filters is not None and payload.get("filters") != filters:
        raise InvalidCursorError("cursor does not match the current filters")
    return completed_at, inspection_id


def _json_loads(raw: str | None) -> Any:
    return json.loads(raw) if raw is not None else None


def _to_record(row: Any) -> InspectionRecord:
    payload: dict[str, Any] = {
        "inspection_id": row.inspection_id,
        "device_id": row.device_id,
        "device_sequence": row.device_sequence,
        "lifecycle_status": row.lifecycle_status,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "barcode_result": _json_loads(row.barcode_result),
        "product_resolution": _json_loads(row.product_resolution),
        "product_detection": _json_loads(row.product_detection),
        "roi_result": _json_loads(row.roi_result),
        "frame_quality_summary": _json_loads(row.frame_quality_summary),
        "application_version": row.application_version,
        "product_model_version_id": row.product_model_version_id,
        "product_model_checksum_sha256": row.product_model_checksum_sha256,
        "component_model_version_id": row.component_model_version_id,
        "component_model_checksum_sha256": row.component_model_checksum_sha256,
        "rule_version_id": row.rule_version_id,
        "aggregation_policy_version": row.aggregation_policy_version,
        "decision": _json_loads(row.decision),
        "synchronization_status": row.synchronization_status,
        "processing_ms": row.processing_ms,
        "inference_metadata": _json_loads(row.inference_metadata),
        # Evidence and media are attached from their dedicated tables for full
        # records; summaries only read decision-level fields.
        "evidence": [],
        "media": [],
    }
    return InspectionRecord.model_validate(payload)


def _install_sqlite_pragmas(engine: Engine) -> None:
    """Apply connection-scoped SQLite pragmas required by design 14.5.

    WAL is a persistent database property set once in ``open``; foreign keys and
    the busy timeout are configured on every checked-out connection because they
    are connection-scoped.
    """

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def _verify_database_integrity(engine: Engine) -> None:
    """Fail closed when SQLite reports database corruption (design 12.8, E2d).

    ``quick_check`` is a fast bounded check run at every open. Corruption must
    enter storage-not-ready mode and require a documented restore; the service
    must never silently rebuild over corrupted evidence.
    """
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA quick_check")).scalar()
    if result != "ok":
        raise RuntimeError(
            f"edge database integrity check failed: {result}; restore from a "
            "validated backup (runbook 05) before serving"
        )


def _content_hash(record: InspectionRecord) -> str:
    """Canonical SHA-256 of the immutable inspection projection.

    ``synchronization_status`` is excluded because it is mutable synchronization
    state; every other field is part of the immutable evidence (F10, contract
    05).
    """
    payload = record.model_dump(mode="json")
    payload.pop("synchronization_status", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_record_json(record: InspectionRecord) -> str:
    """Canonical JSON of the full projection, matching the upload payload.

    The scheduler serializes the persisted record the same way when building
    the inspection payload, so the recorded task size matches the bytes that
    will be uploaded (E1).
    """
    return json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _has_verified_receipt(row: Any) -> bool:
    """Return whether a succeeded task has the persisted receipt required for sync.

    Metadata needs a verified receipt; media additionally needs the central
    object identifier that retention and central binding rely on (PR-017 F5
    follow-up).
    """
    return (
        row["status"] == "SUCCEEDED"
        and bool(row["receipt_json"])
        and (row["kind"] != "MEDIA" or bool(row["central_object_id"]))
    )


class EdgeRepository:
    """SQLite-backed query layer for the local edge API."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def open(cls, db_path: Any, *, migrate: bool = True) -> EdgeRepository:
        from pathlib import Path

        engine = create_engine(f"sqlite:///{Path(db_path)}", future=True)
        _install_sqlite_pragmas(engine)
        if migrate:
            from assemblyvision_edge.persistence.migrate import migrate_to_head

            migrate_to_head(str(db_path))
            with engine.begin() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
            _verify_database_integrity(engine)
        return cls(engine)

    def close(self) -> None:
        self._engine.dispose()

    def probe_writability(self) -> bool:
        """Return whether the SQLite/outbox store accepts a write transaction.

        Used by the storage recovery probe (PR-020 F05): ``BEGIN IMMEDIATE``
        acquires the write lock and fails on a read-only volume or locked
        database, so a successful probe proves the outbox can commit.
        """
        import sqlite3

        try:
            raw = self._engine.raw_connection()
        except sqlite3.Error:
            return False
        try:
            cursor = raw.cursor()
            try:
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute("ROLLBACK")
                return True
            except sqlite3.Error:
                return False
            finally:
                cursor.close()
        finally:
            raw.close()

    def upsert_inspection(
        self, record: InspectionRecord, *, retention: RetentionPolicy | None = None
    ) -> str:
        """Insert an inspection idempotently, returning ``inserted`` or ``unchanged``.

        The inspection projection is immutable (F10): re-importing identical
        content is a no-op, while different content for an existing inspection ID
        raises :class:`RepositoryError` without any partial mutation. Duplicate
        child identities (component evidence codes, media paths) are rejected so
        an inspection is never partially imported (C2). Seeding-only entry
        point; production persistence must use
        :meth:`persist_inspection_and_enqueue_uploads` so the projection and its
        upload outbox tasks commit atomically (PR-017 F2).
        """
        content_hash, payload, decision, barcode, product, media_ids = self._prepare_projection(
            record
        )
        try:
            with self._engine.begin() as conn:
                return self._upsert_inspection_inner(
                    conn,
                    record,
                    content_hash,
                    payload,
                    decision,
                    barcode,
                    product,
                    media_ids,
                    retention=retention,
                )
        except IntegrityError as exc:
            raise RepositoryError(
                f"inspection {record.inspection_id} violates immutable projection constraints"
            ) from exc

    def _prepare_projection(
        self, record: InspectionRecord
    ) -> tuple[str, dict[str, Any], dict[str, Any], str | None, str | None, list[str]]:
        """Validate the immutable projection and derive its persisted columns."""
        codes = [evidence.component_code for evidence in record.evidence]
        if len(codes) != len(set(codes)):
            raise RepositoryError(
                f"inspection {record.inspection_id} has duplicate component evidence"
            )
        paths = [item.relative_path for item in record.media]
        if len(paths) != len(set(paths)):
            raise RepositoryError(f"inspection {record.inspection_id} has duplicate media paths")
        media_ids = [str(item.media_id) for item in record.media]
        if len(media_ids) != len(set(media_ids)):
            raise RepositoryError(f"inspection {record.inspection_id} has duplicate media IDs")
        content_hash = _content_hash(record)
        payload = record.model_dump(mode="json")
        decision = payload["decision"]
        barcode = payload["barcode_result"].get("value")
        product = payload["product_resolution"].get("product_code")
        return content_hash, payload, decision, barcode, product, media_ids

    def _upsert_inspection_inner(
        self,
        conn: Any,
        record: InspectionRecord,
        content_hash: str,
        payload: dict[str, Any],
        decision: dict[str, Any],
        barcode: str | None,
        product: str | None,
        media_ids: list[str],
        *,
        retention: RetentionPolicy | None = None,
    ) -> str:
        """Insert the immutable projection inside an open transaction.

        Returns ``inserted`` or ``unchanged``; raises :class:`RepositoryError`
        on a content conflict without partial mutation (PR-017 F2).
        """
        existing = conn.execute(
            text("SELECT content_sha256 FROM inspections WHERE inspection_id = :id"),
            {"id": str(record.inspection_id)},
        ).scalar_one_or_none()
        if existing is not None:
            if existing != content_hash:
                raise RepositoryError(
                    f"inspection {record.inspection_id} content conflict; "
                    "immutable evidence cannot be overwritten"
                )
            return "unchanged"
        conflicting_media_id = conn.execute(
            text(f"SELECT media_id FROM {media.name} WHERE media_id IN :media_ids").bindparams(
                bindparam("media_ids", expanding=True)
            ),
            {"media_ids": media_ids},
        ).scalar_one_or_none()
        if conflicting_media_id is not None:
            raise RepositoryError(
                f"inspection {record.inspection_id} reuses media ID {conflicting_media_id}"
            )
        conn.execute(
            text(
                f"""
                INSERT INTO {inspections.name} (
                    inspection_id, device_id, device_sequence, lifecycle_status,
                    started_at, completed_at, barcode_result, product_resolution,
                    product_detection, roi_result, frame_quality_summary,
                    application_version, product_model_version_id,
                    product_model_checksum_sha256, component_model_version_id,
                    component_model_checksum_sha256, rule_version_id,
                    aggregation_policy_version, decision, synchronization_status,
                    processing_ms, inference_metadata, content_sha256,
                    business_result, internal_decision, barcode_value, product_code
                ) VALUES (
                    :inspection_id, :device_id, :device_sequence, :lifecycle_status,
                    :started_at, :completed_at, :barcode_result, :product_resolution,
                    :product_detection, :roi_result, :frame_quality_summary,
                    :application_version, :product_model_version_id,
                    :product_model_checksum_sha256, :component_model_version_id,
                    :component_model_checksum_sha256, :rule_version_id,
                    :aggregation_policy_version, :decision, :synchronization_status,
                    :processing_ms, :inference_metadata, :content_sha256,
                    :business_result, :internal_decision, :barcode_value, :product_code
                )
                """
            ),
            {
                "inspection_id": str(record.inspection_id),
                "device_id": str(record.device_id),
                "device_sequence": record.device_sequence,
                "lifecycle_status": record.lifecycle_status.value,
                "started_at": record.started_at.isoformat(),
                "completed_at": record.completed_at.isoformat(),
                "barcode_result": json.dumps(payload["barcode_result"]),
                "product_resolution": json.dumps(payload["product_resolution"]),
                "product_detection": json.dumps(payload["product_detection"])
                if payload["product_detection"]
                else None,
                "roi_result": json.dumps(payload["roi_result"]) if payload["roi_result"] else None,
                "frame_quality_summary": json.dumps(payload["frame_quality_summary"]),
                "application_version": record.application_version,
                "product_model_version_id": str(record.product_model_version_id),
                "product_model_checksum_sha256": record.product_model_checksum_sha256,
                "component_model_version_id": str(record.component_model_version_id),
                "component_model_checksum_sha256": record.component_model_checksum_sha256,
                "rule_version_id": str(record.rule_version_id),
                "aggregation_policy_version": record.aggregation_policy_version,
                "decision": json.dumps(decision),
                "synchronization_status": record.synchronization_status,
                "processing_ms": record.processing_ms,
                "inference_metadata": json.dumps(record.inference_metadata)
                if record.inference_metadata
                else None,
                "content_sha256": content_hash,
                "business_result": record.decision.business_result.value,
                "internal_decision": record.decision.internal_decision.value,
                "barcode_value": barcode,
                "product_code": product,
            },
        )
        for evidence in record.evidence:
            conn.execute(
                text(
                    f"""
                    INSERT INTO {component_evidence.name} (
                        inspection_id, component_code, state, best_confidence,
                        usable_frame_count, detection_count, adjacent_detection_run,
                        supporting_frame_ids, policy_reason_codes, box_area_ratios,
                        box_centers
                    ) VALUES (
                        :inspection_id, :component_code, :state, :best_confidence,
                        :usable_frame_count, :detection_count, :adjacent_detection_run,
                        :supporting_frame_ids, :policy_reason_codes, :box_area_ratios,
                        :box_centers
                    )
                    """
                ),
                {
                    "inspection_id": str(record.inspection_id),
                    "component_code": evidence.component_code,
                    "state": evidence.state,
                    "best_confidence": evidence.best_confidence,
                    "usable_frame_count": evidence.usable_frame_count,
                    "detection_count": evidence.detection_count,
                    "adjacent_detection_run": evidence.adjacent_detection_run,
                    "supporting_frame_ids": json.dumps(
                        [str(i) for i in evidence.supporting_frame_ids]
                    ),
                    "policy_reason_codes": json.dumps(evidence.policy_reason_codes),
                    "box_area_ratios": json.dumps(evidence.box_area_ratios),
                    "box_centers": json.dumps([[x, y] for x, y in evidence.box_centers]),
                },
            )
        for item in record.media:
            eligible_at = None
            if retention is not None:
                deadline = retention.eligible_at(item.kind, record.completed_at)
                eligible_at = deadline.isoformat() if deadline is not None else None
            conn.execute(
                text(
                    f"""
                    INSERT INTO {media.name} (
                        media_id, inspection_id, kind, lifecycle, relative_path,
                        mime_type, size_bytes, checksum_sha256, created_at,
                        retention_eligible_at
                    ) VALUES (
                        :media_id, :inspection_id, :kind, :lifecycle, :relative_path,
                        :mime_type, :size_bytes, :checksum_sha256, :created_at,
                        :retention_eligible_at
                    )
                    """
                ),
                {
                    "media_id": str(item.media_id),
                    "inspection_id": str(record.inspection_id),
                    "kind": item.kind,
                    "lifecycle": item.lifecycle.value,
                    "relative_path": item.relative_path,
                    "mime_type": item.mime_type,
                    "size_bytes": item.size_bytes,
                    "checksum_sha256": item.checksum_sha256,
                    "created_at": record.completed_at.isoformat(),
                    "retention_eligible_at": eligible_at,
                },
            )
        return "inserted"

    def persist_inspection_and_enqueue_uploads(
        self, record: InspectionRecord, *, retention: RetentionPolicy | None = None
    ) -> str:
        """Atomically persist the immutable projection and its upload outbox.

        Design 12.4 steps 3+4 and contract 04 section 3: the projection and its
        upload tasks must commit as one recoverable unit so a crash or an
        enqueue failure cannot leave a completed inspection without its required
        tasks (PR-017 F2). Idempotency makes reconciliation a safe repair:
        re-inserting a stranded ``LOCAL_ONLY`` record is ``unchanged``, then the
        still-local status allows the missing tasks to be created; an already
        queued record creates nothing.
        """
        content_hash, payload, decision, barcode, product, media_ids = self._prepare_projection(
            record
        )
        now = datetime.now(UTC).isoformat()
        try:
            with self._engine.begin() as conn:
                status = self._upsert_inspection_inner(
                    conn,
                    record,
                    content_hash,
                    payload,
                    decision,
                    barcode,
                    product,
                    media_ids,
                    retention=retention,
                )
                self._enqueue_inspection_uploads_inner(conn, record, now)
                return status
        except IntegrityError as exc:
            raise RepositoryError(
                f"inspection {record.inspection_id} violates immutable projection "
                "or upload-task constraints"
            ) from exc

    def get_inspection(self, inspection_id: str) -> InspectionRecord | None:
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    text(f"SELECT * FROM {inspections.name} WHERE inspection_id = :id"),
                    {"id": inspection_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return _to_record(row)

    def _attach_media_and_evidence(self, conn: Any, record: InspectionRecord) -> InspectionRecord:
        media_rows = (
            conn.execute(
                text(
                    f"""
                SELECT * FROM {media.name}
                WHERE inspection_id = :id ORDER BY kind
                """
                ),
                {"id": str(record.inspection_id)},
            )
            .mappings()
            .all()
        )
        record.media = [
            MediaMetadata.model_validate(
                {
                    "media_id": m["media_id"],
                    "kind": m["kind"],
                    "lifecycle": m["lifecycle"],
                    "relative_path": m["relative_path"],
                    "mime_type": m["mime_type"],
                    "size_bytes": m["size_bytes"],
                    "checksum_sha256": m["checksum_sha256"],
                }
            )
            for m in media_rows
        ]
        evidence_rows = (
            conn.execute(
                text(
                    f"""
                SELECT * FROM {component_evidence.name}
                WHERE inspection_id = :id ORDER BY component_code
                """
                ),
                {"id": str(record.inspection_id)},
            )
            .mappings()
            .all()
        )
        record.evidence = [
            AggregatedComponentEvidence.model_validate(
                {
                    "component_code": e["component_code"],
                    "state": e["state"],
                    "best_confidence": e["best_confidence"],
                    "usable_frame_count": e["usable_frame_count"],
                    "detection_count": e["detection_count"],
                    "adjacent_detection_run": e["adjacent_detection_run"],
                    "supporting_frame_ids": [
                        UUID(i) for i in json.loads(e["supporting_frame_ids"])
                    ],
                    "policy_reason_codes": json.loads(e["policy_reason_codes"]),
                    "box_area_ratios": json.loads(e["box_area_ratios"]),
                    "box_centers": [(x, y) for x, y in json.loads(e["box_centers"])],
                }
            )
            for e in evidence_rows
        ]
        return record

    def get_inspection_full(self, inspection_id: str) -> InspectionRecord | None:
        record = self.get_inspection(inspection_id)
        if record is None:
            return None
        with self._engine.connect() as conn:
            return self._attach_media_and_evidence(conn, record)

    def list_inspections(
        self,
        *,
        business_result: str | None = None,
        internal_decision: str | None = None,
        barcode: str | None = None,
        product: str | None = None,
        from_iso: str | None = None,
        to_iso: str | None = None,
        cursor: str | None = None,
        limit: int = _PAGE_DEFAULT_LIMIT,
    ) -> Page[InspectionSummary]:
        if limit < 1 or limit > _PAGE_MAX_LIMIT:
            limit = _PAGE_DEFAULT_LIMIT
        clauses: list[str] = ["1 = 1"]
        params: dict[str, Any] = {}
        if business_result:
            clauses.append("business_result = :business_result")
            params["business_result"] = business_result
        if internal_decision:
            clauses.append("internal_decision = :internal_decision")
            params["internal_decision"] = internal_decision
        if barcode:
            clauses.append("barcode_value LIKE :barcode")
            params["barcode"] = f"%{barcode}%"
        if product:
            clauses.append("product_code = :product")
            params["product"] = product
        if from_iso:
            clauses.append("completed_at >= :from_iso")
            params["from_iso"] = from_iso
        if to_iso:
            clauses.append("completed_at <= :to_iso")
            params["to_iso"] = to_iso
        filter_fingerprint = _filter_fingerprint(
            {
                "business_result": business_result,
                "internal_decision": internal_decision,
                "barcode": barcode,
                "product": product,
                "from_iso": from_iso,
                "to_iso": to_iso,
            }
        )
        keys = _decode_cursor(cursor, filter_fingerprint)
        if keys is not None:
            clauses.append(
                "(completed_at < :cursor_at OR (completed_at = :cursor_at AND inspection_id < :cursor_id))"
            )
            params["cursor_at"] = keys[0]
            params["cursor_id"] = keys[1]
        where = " AND ".join(clauses)
        sql = text(
            f"""
            SELECT * FROM {inspections.name}
            WHERE {where}
            ORDER BY completed_at DESC, inspection_id DESC
            LIMIT :limit
            """
        )
        params["limit"] = limit + 1
        with self._engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [self._summary(_to_record(r)) for r in rows]
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = _encode_cursor(
                str(last["completed_at"]), str(last["inspection_id"]), filter_fingerprint
            )
        return Page(items=items, next_cursor=next_cursor)

    @staticmethod
    def _summary(record: InspectionRecord) -> InspectionSummary:
        barcode = record.barcode_result.value
        return InspectionSummary(
            inspection_id=record.inspection_id,
            completed_at=record.completed_at.isoformat(),
            business_result=record.decision.business_result.value,
            internal_decision=record.decision.internal_decision.value,
            barcode=barcode,
            product_code=record.product_resolution.product_code,
            sn=barcode,
            reason_summary=record.decision.reason_codes,
            latency_ms=record.processing_ms,
            upload_state=record.synchronization_status,
            model_rule_versions={
                "product_model": str(record.product_model_version_id),
                "component_model": str(record.component_model_version_id),
                "rule": str(record.rule_version_id),
            },
        )

    def latest_inspection(self) -> InspectionRecord | None:
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        f"""
                    SELECT * FROM {inspections.name}
                    ORDER BY completed_at DESC, inspection_id DESC LIMIT 1
                    """
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return self._attach_media_and_evidence(conn, _to_record(row))

    def list_inspection_media(self, inspection_id: str) -> list[MediaMetadata]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text(f"SELECT * FROM {media.name} WHERE inspection_id = :id ORDER BY kind"),
                    {"id": inspection_id},
                )
                .mappings()
                .all()
            )
        return [
            MediaMetadata.model_validate(
                {
                    "media_id": m["media_id"],
                    "kind": m["kind"],
                    "lifecycle": m["lifecycle"],
                    "relative_path": m["relative_path"],
                    "mime_type": m["mime_type"],
                    "size_bytes": m["size_bytes"],
                    "checksum_sha256": m["checksum_sha256"],
                }
            )
            for m in rows
        ]

    def get_media(self, media_id: str) -> tuple[MediaMetadata, str] | None:
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    text(f"SELECT * FROM {media.name} WHERE media_id = :id"),
                    {"id": media_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            return (
                MediaMetadata.model_validate(
                    {
                        "media_id": row["media_id"],
                        "kind": row["kind"],
                        "lifecycle": row["lifecycle"],
                        "relative_path": row["relative_path"],
                        "mime_type": row["mime_type"],
                        "size_bytes": row["size_bytes"],
                        "checksum_sha256": row["checksum_sha256"],
                    }
                ),
                str(row["inspection_id"]),
            )

    def list_uploads(
        self, cursor: str | None = None, limit: int = _PAGE_DEFAULT_LIMIT
    ) -> Page[UploadTask]:
        if limit < 1 or limit > _PAGE_MAX_LIMIT:
            limit = _PAGE_DEFAULT_LIMIT
        clauses = ["1 = 1"]
        params: dict[str, Any] = {"limit": limit + 1}
        keys = _decode_cursor(cursor)
        if keys is not None:
            clauses.append(
                "(created_at < :cursor_at OR (created_at = :cursor_at AND upload_task_id < :cursor_id))"
            )
            params["cursor_at"] = keys[0]
            params["cursor_id"] = keys[1]
        where = " AND ".join(clauses)
        sql = text(
            f"""
            SELECT * FROM {upload_tasks.name}
            WHERE {where}
            ORDER BY created_at DESC, upload_task_id DESC
            LIMIT :limit
            """
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [self._upload_task(r) for r in rows]
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = _encode_cursor(str(last["created_at"]), str(last["upload_task_id"]))
        return Page(items=items, next_cursor=next_cursor)

    @staticmethod
    def _upload_task(row: Any) -> UploadTask:
        return UploadTask.model_validate(
            {
                "upload_task_id": row["upload_task_id"],
                "device_id": row["device_id"],
                "inspection_id": row["inspection_id"],
                "kind": row["kind"],
                "object_id": row["object_id"],
                "payload_hash": row["payload_hash"],
                "status": row["status"],
                "idempotency_key": row["idempotency_key"],
                "checksum_sha256": row["checksum_sha256"],
                "attempt_count": row["attempt_count"],
                "next_attempt_at": row["next_attempt_at"],
                "last_error_code": row["last_error_code"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "completed_at": row["completed_at"],
            }
        )

    def retry_upload(self, upload_task_id: str, reason: str) -> UploadTask | None:
        with self._engine.begin() as conn:
            row = (
                conn.execute(
                    text(f"SELECT * FROM {upload_tasks.name} WHERE upload_task_id = :id"),
                    {"id": upload_task_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            if row["status"] not in ("RETRY_WAIT", "PERMANENT_FAILURE"):
                return self._upload_task(row)
            conn.execute(
                text(
                    f"""
                    UPDATE {upload_tasks.name}
                    SET status = 'PENDING', attempt_count = attempt_count + 1,
                        last_error_code = NULL
                    WHERE upload_task_id = :id
                    """
                ),
                {"id": upload_task_id},
            )
            updated = (
                conn.execute(
                    text(f"SELECT * FROM {upload_tasks.name} WHERE upload_task_id = :id"),
                    {"id": upload_task_id},
                )
                .mappings()
                .first()
            )
        return self._upload_task(updated)

    def count_pending_uploads(self) -> int:
        with self._engine.connect() as conn:
            result = conn.execute(
                select(func.count())
                .select_from(upload_tasks)
                .where(upload_tasks.c.status.in_(["PENDING", "IN_PROGRESS", "RETRY_WAIT"]))
            ).scalar()
        return int(result or 0)

    def upload_queue_metrics(self) -> UploadQueueMetrics:
        """Aggregate upload task counts, bytes, and oldest pending task (E1)."""
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        f"SELECT status, COUNT(*) AS n, SUM(size_bytes) AS bytes "
                        f"FROM {upload_tasks.name} GROUP BY status"
                    )
                )
                .mappings()
                .all()
            )
            oldest = conn.execute(
                text(
                    f"SELECT MIN(created_at) FROM {upload_tasks.name} "
                    "WHERE status IN ('PENDING', 'RETRY_WAIT', 'IN_PROGRESS')"
                )
            ).scalar()
        by_state = {row["status"]: int(row["n"]) for row in rows}
        pending_bytes = sum(
            int(row["bytes"] or 0)
            for row in rows
            if row["status"] in ("PENDING", "RETRY_WAIT", "IN_PROGRESS")
        )
        return UploadQueueMetrics(
            by_state=by_state,
            pending_bytes=pending_bytes,
            oldest_pending_at=oldest,
        )

    def retention_eligible(self, now_iso: str, limit: int = 200) -> list[RetentionTarget]:
        """Return receipt-gated retention candidates (design 12.7, E2a).

        Read-only view used by the cleanup worker and by observability; the
        claim transaction re-checks the same predicate atomically.
        """
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        f"""
                    SELECT m.media_id, m.inspection_id, m.kind, m.relative_path,
                           m.size_bytes, m.retention_eligible_at
                    FROM {media.name} m
                    JOIN {inspections.name} i ON i.inspection_id = m.inspection_id
                    WHERE {_retention_eligible_where()}
                    ORDER BY m.retention_eligible_at ASC, m.created_at ASC, m.media_id ASC
                    LIMIT :limit
                    """
                    ),
                    {"now": now_iso, "limit": limit},
                )
                .mappings()
                .all()
            )
        return [self._retention_target(r) for r in rows]

    @staticmethod
    def _retention_target(row: Any) -> RetentionTarget:
        return RetentionTarget(
            media_id=UUID(str(row["media_id"])),
            inspection_id=UUID(str(row["inspection_id"])),
            kind=str(row["kind"]),
            relative_path=str(row["relative_path"]),
            size_bytes=int(row["size_bytes"]),
            retention_eligible_at=str(row["retention_eligible_at"]),
        )

    def claim_retention_batch(
        self, limit: int, lease_seconds: int, now_iso: str
    ) -> list[ClaimedRetentionTarget]:
        """Lease up to ``limit`` retention candidates to one cleanup worker.

        Runs in an immediate transaction so one writer claims each artifact
        (E2 task E2a). Abandoned claims whose lease expired are released first,
        then eligible artifacts are claimed with a fresh per-artifact fencing
        token. The update re-checks the eligibility predicate, so an artifact
        already claimed by a concurrent worker is never double-claimed.
        """
        lease_expires = (
            datetime.fromisoformat(now_iso) + timedelta(seconds=lease_seconds)
        ).isoformat()
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                    UPDATE {media.name}
                    SET deleting_at = NULL, delete_lease_owner = NULL,
                        delete_lease_expires_at = NULL
                    WHERE deleting_at IS NOT NULL AND delete_lease_expires_at IS NOT NULL
                      AND delete_lease_expires_at < :now
                    """
                ),
                {"now": now_iso},
            )
            rows = (
                conn.execute(
                    text(
                        f"""
                        SELECT m.media_id, m.inspection_id, m.kind, m.relative_path,
                               m.size_bytes, m.retention_eligible_at
                        FROM {media.name} m
                        JOIN {inspections.name} i ON i.inspection_id = m.inspection_id
                        WHERE {_retention_eligible_where()}
                        ORDER BY m.retention_eligible_at ASC, m.created_at ASC, m.media_id ASC
                        LIMIT :limit
                        """
                    ),
                    {"now": now_iso, "limit": limit},
                )
                .mappings()
                .all()
            )
            ids = [str(r["media_id"]) for r in rows]
            if not ids:
                return []
            owners = {media_id: str(uuid4()) for media_id in ids}
            conn.execute(
                text(
                    f"""
                    UPDATE {media.name}
                    SET deleting_at = :now, delete_lease_owner = :owner,
                        delete_lease_expires_at = :lease
                    WHERE media_id = :media_id
                      AND lifecycle = 'AVAILABLE' AND purged_at IS NULL
                      AND deleting_at IS NULL AND hold_reason IS NULL
                      AND (integrity_status IS NULL OR integrity_status <> 'FAULT')
                      AND retention_eligible_at IS NOT NULL
                      AND retention_eligible_at <= :now
                    """
                ),
                [
                    {
                        "now": now_iso,
                        "owner": owners[media_id],
                        "lease": lease_expires,
                        "media_id": media_id,
                    }
                    for media_id in ids
                ],
            )
            claimed: list[ClaimedRetentionTarget] = []
            for row in rows:
                media_id = str(row["media_id"])
                still_held = conn.execute(
                    text(
                        f"SELECT 1 FROM {media.name} "
                        "WHERE media_id = :id AND delete_lease_owner = :owner "
                        "AND deleting_at IS NOT NULL"
                    ),
                    {"id": media_id, "owner": owners[media_id]},
                ).scalar_one_or_none()
                if still_held is None:
                    # A concurrent worker claimed it after our SELECT; skip.
                    continue
                target = self._retention_target(row)
                claimed.append(
                    ClaimedRetentionTarget(
                        media_id=target.media_id,
                        inspection_id=target.inspection_id,
                        kind=target.kind,
                        relative_path=target.relative_path,
                        size_bytes=target.size_bytes,
                        retention_eligible_at=target.retention_eligible_at,
                        lease_owner=owners[media_id],
                        lease_expires_at=lease_expires,
                    )
                )
        return claimed

    def confirm_retention_claim(
        self, media_id: str, lease_owner: str, now_iso: str, lease_seconds: int
    ) -> ClaimedRetentionTarget | None:
        """Fenced pre-unlink confirmation and lease renewal (PR-020 F02/F03).

        Re-validates the full eligibility predicate atomically: the caller must
        still hold an unexpired lease, the artifact must still be ``AVAILABLE``
        with no hold/fault, the deadline must still be elapsed, and the
        inspection must still be ``SYNCED`` with a verified media receipt. A
        hold or integrity fault applied after the claim therefore invalidates
        it. On success the lease is renewed so the worker can unlink safely;
        returns None when the claim is no longer valid.
        """
        new_lease = (datetime.fromisoformat(now_iso) + timedelta(seconds=lease_seconds)).isoformat()
        with self._engine.begin() as conn:
            row = (
                conn.execute(
                    text(
                        f"""
                        SELECT m.media_id, m.inspection_id, m.kind, m.relative_path,
                               m.size_bytes, m.retention_eligible_at,
                               m.delete_lease_expires_at
                        FROM {media.name} m
                        JOIN {inspections.name} i ON i.inspection_id = m.inspection_id
                        WHERE m.media_id = :media_id
                          AND m.delete_lease_owner = :owner
                          AND m.deleting_at IS NOT NULL
                          AND m.delete_lease_expires_at IS NOT NULL
                          AND m.delete_lease_expires_at >= :now
                          AND m.lifecycle = 'AVAILABLE'
                          AND m.purged_at IS NULL
                          AND (m.integrity_status IS NULL OR m.integrity_status <> 'FAULT')
                          AND m.hold_reason IS NULL
                          AND m.retention_eligible_at IS NOT NULL
                          AND m.retention_eligible_at <= :now
                          AND i.synchronization_status = 'SYNCED'
                          AND {_verified_media_receipt_exists()}
                        """
                    ),
                    {"media_id": media_id, "owner": lease_owner, "now": now_iso},
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            updated = conn.execute(
                text(
                    f"""
                    UPDATE {media.name}
                    SET delete_lease_expires_at = :lease
                    WHERE media_id = :media_id AND delete_lease_owner = :owner
                      AND deleting_at IS NOT NULL
                      AND delete_lease_expires_at >= :now
                    """
                ),
                {"lease": new_lease, "media_id": media_id, "owner": lease_owner, "now": now_iso},
            )
            if updated.rowcount == 0:
                return None
        target = self._retention_target(row)
        return ClaimedRetentionTarget(
            media_id=target.media_id,
            inspection_id=target.inspection_id,
            kind=target.kind,
            relative_path=target.relative_path,
            size_bytes=target.size_bytes,
            retention_eligible_at=target.retention_eligible_at,
            lease_owner=lease_owner,
            lease_expires_at=new_lease,
        )

    def apply_media_hold(self, media_id: str, reason: str) -> int:
        """Apply a hold and atomically invalidate any active deletion claim.

        A hold protects the artifact from retention deletion even if a cleanup
        worker already claimed it (PR-020 F03): the claim is cleared so the
        worker's fenced pre-unlink confirmation fails.
        """
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    f"""
                    UPDATE {media.name}
                    SET hold_reason = :reason, deleting_at = NULL,
                        delete_lease_owner = NULL, delete_lease_expires_at = NULL
                    WHERE media_id = :id
                    """
                ),
                {"reason": reason, "id": media_id},
            )
        return int(result.rowcount or 0)

    def finalize_media_purge(
        self, media_id: str, lease_owner: str, now_iso: str, reason: str
    ) -> int:
        """Mark one media artifact purged when the caller still holds its lease.

        The row becomes an audit tombstone (``PURGED`` + timestamp/reason); the
        file must already be absent on disk. Returns 0 when the lease was
        reclaimed or expired, or when the artifact became held/faulted after
        the claim, so a stale worker can never purge a newer holder's artifact
        (PR-020 F03).
        """
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    f"""
                    UPDATE {media.name}
                    SET lifecycle = 'PURGED', purged_at = :now, purge_reason = :reason,
                        deleting_at = NULL, delete_lease_owner = NULL,
                        delete_lease_expires_at = NULL
                    WHERE media_id = :id AND delete_lease_owner = :owner
                      AND deleting_at IS NOT NULL
                      AND delete_lease_expires_at IS NOT NULL
                      AND delete_lease_expires_at >= :now
                      AND lifecycle = 'AVAILABLE'
                      AND purged_at IS NULL
                      AND hold_reason IS NULL
                      AND (integrity_status IS NULL OR integrity_status <> 'FAULT')
                      AND retention_eligible_at IS NOT NULL
                      AND retention_eligible_at <= :now
                      AND EXISTS (
                          SELECT 1 FROM {inspections.name} i
                          WHERE i.inspection_id = {media.name}.inspection_id
                            AND i.synchronization_status = 'SYNCED'
                      )
                      AND EXISTS (
                          SELECT 1 FROM {upload_tasks.name} t
                          WHERE t.kind = 'MEDIA' AND t.object_id = :media_id
                            AND t.status = 'SUCCEEDED'
                            AND t.receipt_json IS NOT NULL
                            AND t.central_object_id IS NOT NULL
                      )
                    """
                ),
                {
                    "now": now_iso,
                    "reason": reason,
                    "owner": lease_owner,
                    "id": media_id,
                    "media_id": media_id,
                },
            )
        return int(result.rowcount or 0)

    def record_media_delete_failure(
        self, media_id: str, lease_owner: str, error_code: str, now_iso: str
    ) -> int:
        """Record a retryable unlink failure and release the claim (E2b).

        The artifact stays ``AVAILABLE`` with ``last_delete_error`` set so the
        failure is observable and the next cycle can retry it. Returns 0 when
        the lease was reclaimed or expired.
        """
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    f"""
                    UPDATE {media.name}
                    SET last_delete_error = :error, deleting_at = NULL,
                        delete_lease_owner = NULL, delete_lease_expires_at = NULL
                    WHERE media_id = :id AND delete_lease_owner = :owner
                      AND delete_lease_expires_at IS NOT NULL
                      AND delete_lease_expires_at >= :now
                    """
                ),
                {"error": error_code, "owner": lease_owner, "id": media_id, "now": now_iso},
            )
        return int(result.rowcount or 0)

    def mark_media_integrity_fault(
        self, media_id: str, lease_owner: str, error_code: str, now_iso: str
    ) -> int:
        """Mark media as integrity-faulted and release its cleanup claim (E2b).

        A faulted artifact is never eligible for deletion again (E2 invariant
        3/8); the row stays as evidence for operator reconciliation. Returns 0
        when the lease was reclaimed or expired.
        """
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    f"""
                    UPDATE {media.name}
                    SET integrity_status = 'FAULT', last_delete_error = NULL,
                        deleting_at = NULL, delete_lease_owner = NULL,
                        delete_lease_expires_at = NULL
                    WHERE media_id = :id AND delete_lease_owner = :owner
                      AND delete_lease_expires_at IS NOT NULL
                      AND delete_lease_expires_at >= :now
                    """
                ),
                {"error": error_code, "owner": lease_owner, "id": media_id, "now": now_iso},
            )
        return int(result.rowcount or 0)

    def recover_expired_retention_claims(self, now_iso: str) -> int:
        """Release retention claims whose lease expired (crash recovery)."""
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    f"""
                    UPDATE {media.name}
                    SET deleting_at = NULL, delete_lease_owner = NULL,
                        delete_lease_expires_at = NULL
                    WHERE deleting_at IS NOT NULL AND delete_lease_expires_at IS NOT NULL
                      AND delete_lease_expires_at < :now
                    """
                ),
                {"now": now_iso},
            )
        return int(result.rowcount or 0)

    def retention_metrics(self, now_iso: str) -> RetentionMetrics:
        """Aggregate cleanup state for device status and alerts (E2)."""
        with self._engine.connect() as conn:
            eligible = (
                conn.execute(
                    text(
                        f"""
                        SELECT COUNT(*) AS n, COALESCE(SUM(m.size_bytes), 0) AS bytes
                        FROM {media.name} m
                        JOIN {inspections.name} i ON i.inspection_id = m.inspection_id
                        WHERE {_retention_eligible_where()}
                        """
                    ),
                    {"now": now_iso},
                )
                .mappings()
                .one()
            )
            deleting = conn.execute(
                text(f"SELECT COUNT(*) FROM {media.name} WHERE deleting_at IS NOT NULL")
            ).scalar()
            delete_errors = conn.execute(
                text(
                    f"SELECT COUNT(*) FROM {media.name} "
                    "WHERE last_delete_error IS NOT NULL AND lifecycle = 'AVAILABLE' "
                    "AND purged_at IS NULL"
                )
            ).scalar()
            purged = conn.execute(
                text(f"SELECT COUNT(*) FROM {media.name} WHERE lifecycle = 'PURGED'")
            ).scalar()
            integrity_faults = conn.execute(
                text(f"SELECT COUNT(*) FROM {media.name} WHERE integrity_status = 'FAULT'")
            ).scalar()
        return RetentionMetrics(
            eligible_count=int(eligible["n"]),
            eligible_bytes=int(eligible["bytes"]),
            deleting_count=int(deleting or 0),
            delete_error_count=int(delete_errors or 0),
            purged_count=int(purged or 0),
            integrity_fault_count=int(integrity_faults or 0),
        )

    def list_media_for_integrity(self) -> list[MediaIdentity]:
        """Return projected, non-purged media rows for the startup scan (E2d)."""
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        f"SELECT media_id, inspection_id, kind, relative_path, "
                        f"size_bytes, checksum_sha256 FROM {media.name} "
                        "WHERE lifecycle = 'AVAILABLE' "
                        "ORDER BY inspection_id ASC, media_id ASC"
                    )
                )
                .mappings()
                .all()
            )
        return [
            MediaIdentity(
                media_id=UUID(str(row["media_id"])),
                inspection_id=UUID(str(row["inspection_id"])),
                kind=str(row["kind"]),
                relative_path=str(row["relative_path"]),
                size_bytes=int(row["size_bytes"]),
                checksum_sha256=str(row["checksum_sha256"]),
            )
            for row in rows
        ]

    def mark_media_integrity_fault_direct(self, media_id: str, error_code: str) -> int:
        """Mark media as integrity-faulted without a lease (startup scan, E2d).

        The startup scan runs before any worker starts, so no fencing is
        needed; a faulted artifact is protected from deletion forever. Any
        active deletion claim is cleared so the cleanup worker's fenced
        pre-unlink confirmation fails (PR-020 F03).
        """
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    f"""
                    UPDATE {media.name}
                    SET integrity_status = 'FAULT', last_delete_error = NULL,
                        deleting_at = NULL, delete_lease_owner = NULL,
                        delete_lease_expires_at = NULL
                    WHERE media_id = :id
                      AND (integrity_status IS NULL OR integrity_status <> 'FAULT')
                    """
                ),
                {"id": media_id},
            )
        return int(result.rowcount or 0)

    def enqueue_inspection_uploads(self, record: InspectionRecord) -> int:
        """Insert one inspection task plus one media task per artifact.

        Seeding/repair-only entry point; production persistence should call
        :meth:`persist_inspection_and_enqueue_uploads` so the projection and its
        tasks commit atomically (PR-017 F2). See
        :meth:`_enqueue_inspection_uploads_inner` for the idempotency semantics.
        """
        now = datetime.now(UTC).isoformat()
        try:
            with self._engine.begin() as conn:
                return self._enqueue_inspection_uploads_inner(conn, record, now)
        except IntegrityError as exc:
            raise RepositoryError(
                f"cannot enqueue uploads for inspection {record.inspection_id}: "
                "upload tasks violate uniqueness constraints"
            ) from exc

    def _enqueue_inspection_uploads_inner(
        self, conn: Any, record: InspectionRecord, now: str
    ) -> int:
        """Insert idempotent upload tasks inside an open transaction.

        Transactional outbox (design 12.4 step 4, ADR-005): tasks are inserted
        with stable idempotency keys so duplicate calls, restart reconciliation,
        and concurrent writers can never create a duplicate task. Enqueue only
        applies while the inspection is still ``LOCAL_ONLY`` (or not yet
        projected); once any task was created the projection moves to ``QUEUED``
        and re-imports are no-ops. Returns the number of newly inserted tasks.
        """
        inspection_task = {
            "kind": "INSPECTION",
            "object_id": str(record.inspection_id),
            "payload_hash": _content_hash(record),
            "idempotency_key": f"inspection:{record.device_id}:{record.inspection_id}",
            "checksum_sha256": _content_hash(record),
            "size_bytes": len(_canonical_record_json(record).encode("utf-8")),
        }
        media_tasks = [
            {
                "kind": "MEDIA",
                "object_id": str(item.media_id),
                "payload_hash": item.checksum_sha256,
                "idempotency_key": f"media:{record.device_id}:{item.media_id}",
                "checksum_sha256": item.checksum_sha256,
                "size_bytes": item.size_bytes,
            }
            for item in record.media
        ]
        tasks = [inspection_task, *media_tasks]
        inserted = 0
        status_row = conn.execute(
            text(
                f"SELECT synchronization_status FROM {inspections.name} WHERE inspection_id = :id"
            ),
            {"id": str(record.inspection_id)},
        ).scalar_one_or_none()
        if status_row not in (None, "LOCAL_ONLY"):
            return 0
        for task in tasks:
            exists = conn.execute(
                text(f"SELECT 1 FROM {upload_tasks.name} WHERE idempotency_key = :key"),
                {"key": task["idempotency_key"]},
            ).scalar_one_or_none()
            if exists is not None:
                continue
            conn.execute(
                text(
                    f"""
                    INSERT INTO {upload_tasks.name} (
                        upload_task_id, device_id, inspection_id, kind, object_id,
                        payload_hash, status, idempotency_key, checksum_sha256,
                        size_bytes, attempt_count, next_attempt_at, last_error_code,
                        created_at, updated_at, completed_at
                    ) VALUES (
                        :upload_task_id, :device_id, :inspection_id, :kind, :object_id,
                        :payload_hash, 'PENDING', :idempotency_key, :checksum_sha256,
                        :size_bytes, 0, NULL, NULL, :created_at, :created_at, NULL
                    )
                    """
                ),
                {
                    "upload_task_id": str(uuid4()),
                    "device_id": str(record.device_id),
                    "inspection_id": str(record.inspection_id),
                    "kind": task["kind"],
                    "object_id": task["object_id"],
                    "payload_hash": task["payload_hash"],
                    "idempotency_key": task["idempotency_key"],
                    "checksum_sha256": task["checksum_sha256"],
                    "size_bytes": task["size_bytes"],
                    "created_at": now,
                },
            )
            inserted += 1
        if status_row == "LOCAL_ONLY":
            conn.execute(
                text(
                    f"UPDATE {inspections.name} SET synchronization_status = 'QUEUED' "
                    "WHERE inspection_id = :id"
                ),
                {"id": str(record.inspection_id)},
            )
        return inserted

    def claim_upload_tasks(
        self, limit: int, lease_seconds: int, now_iso: str
    ) -> list[ClaimedUploadTask]:
        """Lease up to ``limit`` due upload tasks to this worker.

        Runs in an immediate transaction so one writer claims each task. Tasks
        whose lease already expired return to ``PENDING`` first (clearing the
        old owner), then due ``PENDING``/``RETRY_WAIT`` tasks are claimed and
        marked ``IN_PROGRESS`` with a fresh per-task fencing token and lease
        (design 13.3/13.5 worker-crash recovery, PR-017 F3).
        """
        lease_expires = (
            datetime.fromisoformat(now_iso) + timedelta(seconds=lease_seconds)
        ).isoformat()
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                    UPDATE {upload_tasks.name}
                    SET status = 'PENDING', lease_expires_at = NULL,
                        lease_owner = NULL, updated_at = :now
                    WHERE status = 'IN_PROGRESS' AND lease_expires_at IS NOT NULL
                      AND lease_expires_at < :now
                    """
                ),
                {"now": now_iso},
            )
            rows = (
                conn.execute(
                    text(
                        f"""
                        SELECT * FROM {upload_tasks.name}
                        WHERE status IN ('PENDING', 'RETRY_WAIT')
                          AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
                          AND (
                              kind != 'MEDIA'
                              OR inspection_id IS NULL
                              OR EXISTS (
                                  SELECT 1 FROM {upload_tasks.name} parent
                                  WHERE parent.kind = 'INSPECTION'
                                    AND parent.inspection_id = {upload_tasks.name}.inspection_id
                                    AND parent.status = 'SUCCEEDED'
                              )
                          )
                        ORDER BY CASE kind WHEN 'INSPECTION' THEN 0 ELSE 1 END,
                                 created_at ASC, upload_task_id ASC
                        LIMIT :limit
                        """
                    ),
                    {"now": now_iso, "limit": limit},
                )
                .mappings()
                .all()
            )
            task_ids = [str(row["upload_task_id"]) for row in rows]
            claimed: list[ClaimedUploadTask] = []
            if task_ids:
                owners = {task_id: str(uuid4()) for task_id in task_ids}
                conn.execute(
                    text(
                        f"""
                        UPDATE {upload_tasks.name}
                        SET status = 'IN_PROGRESS', lease_expires_at = :lease,
                            lease_owner = :owner, updated_at = :now
                        WHERE upload_task_id = :task_id
                        """
                    ),
                    [
                        {
                            "lease": lease_expires,
                            "owner": owners[task_id],
                            "now": now_iso,
                            "task_id": task_id,
                        }
                        for task_id in task_ids
                    ],
                )
                rows = (
                    conn.execute(
                        text(
                            f"SELECT * FROM {upload_tasks.name} WHERE upload_task_id IN :task_ids"
                        ).bindparams(bindparam("task_ids", expanding=True)),
                        {"task_ids": task_ids},
                    )
                    .mappings()
                    .all()
                )
                claimed = [
                    ClaimedUploadTask(
                        task=self._upload_task(row), lease_owner=owners[str(row["upload_task_id"])]
                    )
                    for row in rows
                ]
        return claimed

    def mark_upload_succeeded(
        self,
        upload_task_id: str,
        lease_owner: str,
        now_iso: str,
        *,
        central_object_id: str | None = None,
        receipt_json: str | None = None,
    ) -> int:
        """Mark one task succeeded when the caller still holds its lease.

        The verified receipt and central object identifier are persisted so
        retention can later gate on confirmed uploads (contract 04 section 6,
        PR-017 F5). Returns the number of updated rows: zero means the lease
        was reclaimed (stale worker) and nothing is mutated. The inspection's
        synchronization state is recomputed from all of its tasks.
        """
        with self._engine.begin() as conn:
            row = (
                conn.execute(
                    text(
                        f"SELECT kind, inspection_id FROM {upload_tasks.name} "
                        "WHERE upload_task_id = :id"
                    ),
                    {"id": upload_task_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                return 0
            if receipt_json is None or (row["kind"] == "MEDIA" and central_object_id is None):
                return 0
            result = conn.execute(
                text(
                    f"""
                    UPDATE {upload_tasks.name}
                    SET status = 'SUCCEEDED', completed_at = :now, updated_at = :now,
                        lease_expires_at = NULL, lease_owner = NULL, last_error_code = NULL,
                        central_object_id = :object_id, receipt_json = :receipt
                    WHERE upload_task_id = :id AND status = 'IN_PROGRESS'
                      AND lease_owner = :owner
                    """
                ),
                {
                    "now": now_iso,
                    "owner": lease_owner,
                    "object_id": central_object_id,
                    "receipt": receipt_json,
                    "id": upload_task_id,
                },
            )
            if result.rowcount == 0:
                return 0
            if row["inspection_id"] is not None:
                self._refresh_inspection_sync(conn, str(row["inspection_id"]))
        return 1

    @staticmethod
    def _refresh_inspection_sync(conn: Any, inspection_id: str) -> None:
        """Recompute an inspection's synchronization state from all its tasks.

        Design 14: ``QUEUED`` while work is outstanding, ``PARTIAL`` after some
        required task succeeded, ``SYNCED`` only when every required task has a
        verified receipt, and ``FAILED`` when any required task is permanently
        failed (PR-017 F5).
        """
        rows = (
            conn.execute(
                text(
                    f"SELECT kind, status, central_object_id, receipt_json "
                    f"FROM {upload_tasks.name} WHERE inspection_id = :id"
                ),
                {"id": inspection_id},
            )
            .mappings()
            .all()
        )
        if not rows:
            return
        if any(row["status"] == "PERMANENT_FAILURE" for row in rows):
            state = "FAILED"
        elif all(_has_verified_receipt(row) for row in rows):
            state = "SYNCED"
        elif any(_has_verified_receipt(row) for row in rows):
            state = "PARTIAL"
        else:
            state = "QUEUED"
        conn.execute(
            text(
                f"UPDATE {inspections.name} SET synchronization_status = :state "
                "WHERE inspection_id = :id"
            ),
            {"state": state, "id": inspection_id},
        )

    def mark_upload_retry(
        self,
        upload_task_id: str,
        lease_owner: str,
        error_code: str,
        next_attempt_at_iso: str,
        now_iso: str,
    ) -> int:
        """Schedule a retry when the caller still holds the lease; 0 = lost lease."""
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    f"""
                    UPDATE {upload_tasks.name}
                    SET status = 'RETRY_WAIT', attempt_count = attempt_count + 1,
                        next_attempt_at = :next, last_error_code = :error,
                        lease_expires_at = NULL, lease_owner = NULL, updated_at = :now
                    WHERE upload_task_id = :id AND status = 'IN_PROGRESS'
                      AND lease_owner = :owner
                    """
                ),
                {
                    "next": next_attempt_at_iso,
                    "error": error_code,
                    "owner": lease_owner,
                    "now": now_iso,
                    "id": upload_task_id,
                },
            )
        return int(result.rowcount or 0)

    def mark_upload_permanent_failure(
        self, upload_task_id: str, lease_owner: str, error_code: str, now_iso: str
    ) -> int:
        """Mark one task permanently failed when the caller still holds the lease.

        Local evidence is preserved; returns 0 when the lease was reclaimed.
        """
        with self._engine.begin() as conn:
            row = (
                conn.execute(
                    text(
                        f"SELECT inspection_id FROM {upload_tasks.name} WHERE upload_task_id = :id"
                    ),
                    {"id": upload_task_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                return 0
            result = conn.execute(
                text(
                    f"""
                    UPDATE {upload_tasks.name}
                    SET status = 'PERMANENT_FAILURE', attempt_count = attempt_count + 1,
                        completed_at = :now, last_error_code = :error,
                        lease_expires_at = NULL, lease_owner = NULL, updated_at = :now
                    WHERE upload_task_id = :id AND status = 'IN_PROGRESS'
                      AND lease_owner = :owner
                    """
                ),
                {"now": now_iso, "error": error_code, "owner": lease_owner, "id": upload_task_id},
            )
            if result.rowcount == 0:
                return 0
            if row["inspection_id"] is not None:
                self._refresh_inspection_sync(conn, str(row["inspection_id"]))
        return 1

    def get_upload_task(self, upload_task_id: str) -> UploadTask | None:
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    text(f"SELECT * FROM {upload_tasks.name} WHERE upload_task_id = :id"),
                    {"id": upload_task_id},
                )
                .mappings()
                .first()
            )
            return self._upload_task(row) if row is not None else None

    def register_rule_identity(self, rule_id: str, rule_version: int, content_hash: str) -> None:
        """Record a rule identity durably and reject conflicting content.

        The in-process registry in ``config`` only protects one interpreter
        lifetime; this SQLite registry makes rule identity immutable across
        service restarts (PR-008 P2, design 14.5 rule_installations semantics).
        Concurrent registrations of the same identity are resolved by
        re-reading the stored hash: equal content succeeds, differing content
        fails with :class:`RepositoryError` instead of leaking a raw
        SQLAlchemy ``IntegrityError``.
        """
        try:
            with self._engine.begin() as conn:
                existing = conn.execute(
                    text(
                        f"SELECT content_sha256 FROM {rule_identities.name} "
                        "WHERE rule_id = :rule_id AND rule_version = :rule_version"
                    ),
                    {"rule_id": rule_id, "rule_version": rule_version},
                ).scalar_one_or_none()
                if existing is not None:
                    if existing != content_hash:
                        raise RepositoryError(
                            f"rule identity {rule_id} v{rule_version} was previously registered "
                            "with different content; published rules are immutable"
                        )
                    return
                conn.execute(
                    text(
                        f"INSERT INTO {rule_identities.name} "
                        "(rule_id, rule_version, content_sha256, registered_at) "
                        "VALUES (:rule_id, :rule_version, :content_sha256, :registered_at)"
                    ),
                    {
                        "rule_id": rule_id,
                        "rule_version": rule_version,
                        "content_sha256": content_hash,
                        "registered_at": datetime.now(UTC).isoformat(),
                    },
                )
        except IntegrityError as exc:
            # Unique-race: another writer registered this identity between our
            # SELECT and INSERT. The failed transaction is rolled back; re-read
            # the stored hash in a fresh transaction.
            with self._engine.begin() as conn:
                stored = conn.execute(
                    text(
                        f"SELECT content_sha256 FROM {rule_identities.name} "
                        "WHERE rule_id = :rule_id AND rule_version = :rule_version"
                    ),
                    {"rule_id": rule_id, "rule_version": rule_version},
                ).scalar_one_or_none()
            if stored == content_hash:
                return
            raise RepositoryError(
                f"rule identity {rule_id} v{rule_version} was previously registered "
                "with different content; published rules are immutable"
            ) from exc

    def latest_business_result(self) -> str | None:
        with self._engine.connect() as conn:
            result = conn.execute(
                select(inspections.c.business_result)
                .order_by(inspections.c.completed_at.desc(), inspections.c.inspection_id.desc())
                .limit(1)
            ).scalar()
        return result

    def statistics(self, from_iso: str | None = None, to_iso: str | None = None) -> dict[str, int]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if from_iso:
            clauses.append("completed_at >= :from_iso")
            params["from_iso"] = from_iso
        if to_iso:
            clauses.append("completed_at <= :to_iso")
            params["to_iso"] = to_iso
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._engine.connect() as conn:
            total = conn.execute(
                text(f"SELECT COUNT(*) FROM {inspections.name}{where}"), params
            ).scalar_one()
            ng = conn.execute(
                text(
                    f"SELECT COUNT(*) FROM {inspections.name}{where}"
                    + (" AND" if clauses else " WHERE")
                    + " business_result = 'NG'"
                ),
                params,
            ).scalar_one()
        return {"total": int(total), "ng": int(ng)}

    def list_by_barcode(self, barcode: str) -> list[InspectionRecord]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        f"""
                    SELECT * FROM {inspections.name}
                    WHERE barcode_value = :barcode
                    ORDER BY completed_at ASC, inspection_id ASC
                    """
                    ),
                    {"barcode": barcode},
                )
                .mappings()
                .all()
            )
            return [self._attach_media_and_evidence(conn, _to_record(r)) for r in rows]
