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
        return cls(engine)

    def close(self) -> None:
        self._engine.dispose()

    def upsert_inspection(self, record: InspectionRecord) -> str:
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
                    conn, record, content_hash, payload, decision, barcode, product, media_ids
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
            conn.execute(
                text(
                    f"""
                    INSERT INTO {media.name} (
                        media_id, inspection_id, kind, lifecycle, relative_path,
                        mime_type, size_bytes, checksum_sha256
                    ) VALUES (
                        :media_id, :inspection_id, :kind, :lifecycle, :relative_path,
                        :mime_type, :size_bytes, :checksum_sha256
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
                },
            )
        return "inserted"

    def persist_inspection_and_enqueue_uploads(self, record: InspectionRecord) -> str:
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
                    conn, record, content_hash, payload, decision, barcode, product, media_ids
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
        }
        media_tasks = [
            {
                "kind": "MEDIA",
                "object_id": str(item.media_id),
                "payload_hash": item.checksum_sha256,
                "idempotency_key": f"media:{record.device_id}:{item.media_id}",
                "checksum_sha256": item.checksum_sha256,
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
                        attempt_count, next_attempt_at, last_error_code,
                        created_at, updated_at, completed_at
                    ) VALUES (
                        :upload_task_id, :device_id, :inspection_id, :kind, :object_id,
                        :payload_hash, 'PENDING', :idempotency_key, :checksum_sha256,
                        0, NULL, NULL, :created_at, :created_at, NULL
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
                text(f"SELECT status FROM {upload_tasks.name} WHERE inspection_id = :id"),
                {"id": inspection_id},
            )
            .scalars()
            .all()
        )
        if not rows:
            return
        if any(status == "PERMANENT_FAILURE" for status in rows):
            state = "FAILED"
        elif all(status == "SUCCEEDED" for status in rows):
            state = "SYNCED"
        elif any(status == "SUCCEEDED" for status in rows):
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
