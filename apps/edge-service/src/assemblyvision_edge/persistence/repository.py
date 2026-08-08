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
from typing import Any
from uuid import UUID

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
    upload_tasks,
)

_PAGE_DEFAULT_LIMIT = 50
_PAGE_MAX_LIMIT = 200


class RepositoryError(AssemblyVisionError):
    """Raised for database-level failures."""


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


def _encode_cursor(completed_at: str, inspection_id: str) -> str:
    raw = json.dumps({"completed_at": completed_at, "inspection_id": inspection_id}, sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw)
        return str(payload["completed_at"]), str(payload["inspection_id"])
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise RepositoryError("invalid cursor") from exc


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
        an inspection is never partially imported (C2).
        """
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
        try:
            with self._engine.begin() as conn:
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
                    text(
                        f"SELECT media_id FROM {media.name} WHERE media_id IN :media_ids"
                    ).bindparams(bindparam("media_ids", expanding=True)),
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
                        "roi_result": json.dumps(payload["roi_result"])
                        if payload["roi_result"]
                        else None,
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
        except IntegrityError as exc:
            raise RepositoryError(
                f"inspection {record.inspection_id} violates immutable projection constraints"
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
        keys = _decode_cursor(cursor)
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
            next_cursor = _encode_cursor(str(last["completed_at"]), str(last["inspection_id"]))
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
