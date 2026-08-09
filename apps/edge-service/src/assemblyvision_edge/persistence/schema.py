"""SQLite schema defined as SQLAlchemy Core tables.

The table set and indexes implement docs/design/04-edge-client-architecture.md
section 6.1 and contract 05 section 4. Nested inspection objects are stored as
immutable JSON snapshots; evidence and media get dedicated rows for querying.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

inspections = Table(
    "inspections",
    metadata,
    Column("inspection_id", String(36), primary_key=True),
    Column("device_id", String(36), nullable=False),
    Column("device_sequence", Integer, nullable=False),
    Column("lifecycle_status", String(32), nullable=False),
    Column("started_at", Text, nullable=False),
    Column("completed_at", Text, nullable=False),
    Column("barcode_result", Text, nullable=False),
    Column("product_resolution", Text, nullable=False),
    Column("product_detection", Text, nullable=True),
    Column("roi_result", Text, nullable=True),
    Column("frame_quality_summary", Text, nullable=False),
    Column("application_version", String(64), nullable=False),
    Column("product_model_version_id", String(36), nullable=False),
    Column("product_model_checksum_sha256", String(64), nullable=False),
    Column("component_model_version_id", String(36), nullable=False),
    Column("component_model_checksum_sha256", String(64), nullable=False),
    Column("rule_version_id", String(36), nullable=False),
    Column("aggregation_policy_version", String(64), nullable=False),
    Column("decision", Text, nullable=False),
    Column("synchronization_status", String(32), nullable=False),
    Column("processing_ms", Integer, nullable=False),
    Column("inference_metadata", Text, nullable=True),
    Column(
        "content_sha256",
        String(64),
        nullable=False,
        comment="SHA-256 of the immutable inspection projection for conflict detection",
    ),
    # Denormalized filter columns (contract 05 section 4 indexes).
    Column("business_result", String(16), nullable=False),
    Column("internal_decision", String(16), nullable=False),
    Column("barcode_value", String(256), nullable=True),
    Column("product_code", String(128), nullable=True),
)

Index("ix_inspections_completed_at", inspections.c.completed_at.desc())
Index("ix_inspections_business_result", inspections.c.business_result)
Index("ix_inspections_internal_decision", inspections.c.internal_decision)
Index("ix_inspections_barcode_value", inspections.c.barcode_value)
Index("ix_inspections_product_code", inspections.c.product_code)
Index("ix_inspections_device_id", inspections.c.device_id)
Index("ix_inspections_model_version", inspections.c.product_model_version_id)
Index("ix_inspections_sync_status", inspections.c.synchronization_status)

component_evidence = Table(
    "component_evidence",
    metadata,
    Column("evidence_id", Integer, primary_key=True, autoincrement=True),
    Column(
        "inspection_id",
        String(36),
        ForeignKey("inspections.inspection_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("component_code", String(128), nullable=False),
    Column("state", String(16), nullable=False),
    Column("best_confidence", Float, nullable=True),
    Column("usable_frame_count", Integer, nullable=False),
    Column("detection_count", Integer, nullable=False),
    Column("adjacent_detection_run", Integer, nullable=False),
    Column("supporting_frame_ids", JSON, nullable=False),
    Column("policy_reason_codes", JSON, nullable=False),
    Column("box_area_ratios", JSON, nullable=False),
    Column("box_centers", JSON, nullable=False),
)

media = Table(
    "media",
    metadata,
    Column("media_id", String(36), primary_key=True),
    Column(
        "inspection_id",
        String(36),
        ForeignKey("inspections.inspection_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("kind", String(32), nullable=False),
    Column("lifecycle", String(16), nullable=False),
    Column("relative_path", String(512), nullable=False),
    Column("mime_type", String(64), nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("checksum_sha256", String(64), nullable=False),
)

upload_tasks = Table(
    "upload_tasks",
    metadata,
    Column("upload_task_id", String(36), primary_key=True),
    Column("device_id", String(36), nullable=False),
    Column("inspection_id", String(36), nullable=True),
    Column("kind", String(32), nullable=False),
    Column("object_id", String(36), nullable=False),
    Column("payload_hash", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("idempotency_key", String(256), nullable=False),
    Column("checksum_sha256", String(64), nullable=True),
    Column("attempt_count", Integer, nullable=False),
    Column("next_attempt_at", Text, nullable=True),
    Column("lease_expires_at", Text, nullable=True),
    Column(
        "lease_owner",
        String(36),
        nullable=True,
        comment="Unique per-claim token fencing terminal updates to the lease holder (PR-017 F3)",
    ),
    Column("last_error_code", String(64), nullable=True),
    Column(
        "central_object_id",
        String(256),
        nullable=True,
        comment="Central object identifier from the verified upload receipt (PR-017 F5)",
    ),
    Column(
        "receipt_json",
        Text,
        nullable=True,
        comment="Verified server receipt stored only after checksum/size validation (PR-017 F5)",
    ),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("completed_at", Text, nullable=True),
)

Index("ix_upload_tasks_status", upload_tasks.c.status)
Index("ix_upload_tasks_inspection", upload_tasks.c.inspection_id)
Index("ix_upload_tasks_due", upload_tasks.c.status, upload_tasks.c.next_attempt_at)

device_events = Table(
    "device_events",
    metadata,
    Column("event_id", String(36), primary_key=True),
    Column("device_id", String(36), nullable=False),
    Column("occurred_at", Text, nullable=False),
    Column("code", String(64), nullable=False),
    Column("severity", String(16), nullable=False),
    Column("message", String(512), nullable=False),
)

active_packages = Table(
    "active_packages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("task", String(32), nullable=False),
    Column("model_version_id", String(36), nullable=False),
    Column("semantic_version", String(64), nullable=True),
    Column("rule_version_id", String(36), nullable=True),
    Column("installed_at", Text, nullable=False),
)

rule_identities = Table(
    "rule_identities",
    metadata,
    Column("rule_id", String(128), primary_key=True),
    Column("rule_version", Integer, primary_key=True),
    Column("content_sha256", String(64), nullable=False),
    Column("registered_at", Text, nullable=False),
    comment="Durable installed-rule registry: a rule identity is immutable once registered",
)
