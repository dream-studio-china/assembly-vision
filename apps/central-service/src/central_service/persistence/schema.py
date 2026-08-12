"""Central pilot schema defined as SQLAlchemy Core tables (C1b).

The table set implements docs/tasks/C1-central-server-m1.md section 8.1 for
the tenant/device/credential domain: organizations, sites, production_lines,
devices (with hashed upload credentials), pilot administrators, their browser
sessions, and a minimum audit log. The Alembic migrations under
``apps/central-service/migrations/`` mirror these definitions for PostgreSQL;
tests create the same schema through ``metadata.create_all`` on SQLite.

Tenant-hierarchy integrity is enforced in the database: production lines and
devices carry composite foreign keys that bind their ``organization_id`` to
the organization of their referenced site/line, so a row can never reference
another tenant's hierarchy node.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)

metadata = MetaData()

# Audit logs can grow far beyond pilot scale on PostgreSQL, while SQLite test
# databases need the exact INTEGER type for a rowid-alias primary key.
_BigIntId = BigInteger().with_variant(Integer, "sqlite")

_UTC_NOW = func.now()

organizations = Table(
    "organizations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(128), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
)

sites = Table(
    "sites",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("organization_id", "name", name="uq_sites_organization_name"),
    # Referenced by the composite site foreign keys on production_lines and
    # devices, which bind organization_id to the referenced site's tenant.
    UniqueConstraint("id", "organization_id", name="uq_sites_id_organization"),
)

production_lines = Table(
    "production_lines",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("site_id", Integer, nullable=False),
    Column("name", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("site_id", "name", name="uq_production_lines_site_name"),
    UniqueConstraint("id", "organization_id", name="uq_production_lines_id_organization"),
    ForeignKeyConstraint(
        ["organization_id", "site_id"],
        ["sites.id", "sites.organization_id"],
        name="fk_production_lines_site_organization",
        ondelete="CASCADE",
    ),
)

devices = Table(
    "devices",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("site_id", Integer, nullable=False),
    Column("production_line_id", Integer, nullable=False),
    # Edge device identity (``device_id`` in the edge upload envelope); the
    # integer primary key stays internal. The edge identity is unique per
    # organization so a registration cannot collide across tenants.
    Column("device_id", String(128), nullable=False),
    Column("name", String(128), nullable=False),
    Column("status", String(16), nullable=False, server_default="ACTIVE"),
    Column("upload_token_hash", String(128), nullable=False),
    Column("upload_token_salt", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("organization_id", "device_id", name="uq_devices_organization_device"),
    ForeignKeyConstraint(
        ["organization_id", "site_id"],
        ["sites.id", "sites.organization_id"],
        name="fk_devices_site_organization",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["organization_id", "production_line_id"],
        ["production_lines.id", "production_lines.organization_id"],
        name="fk_devices_line_organization",
        ondelete="CASCADE",
    ),
)

administrators = Table(
    "administrators",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("username", String(128), nullable=False),
    Column("token_hash", String(128), nullable=False),
    Column("token_salt", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("organization_id", "username", name="uq_administrators_organization_username"),
)

admin_sessions = Table(
    "admin_sessions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "administrator_id",
        ForeignKey("administrators.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # Every tenant-owned row carries organization scope (C1 invariant 6); the
    # session is validated against the administrator's organization on use.
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # Public random lookup half of the session token; the secret half is only
    # ever stored hashed, so a leaked session table cannot forge a session.
    Column("session_lookup", String(32), nullable=False, unique=True),
    Column("session_token_hash", String(128), nullable=False),
    Column("session_token_salt", String(64), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
)

audit_logs = Table(
    "audit_logs",
    metadata,
    Column("id", _BigIntId, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    ),
    Column("actor_type", String(16), nullable=False),
    Column("actor_id", Integer, nullable=True),
    Column("action", String(64), nullable=False),
    Column("target_type", String(64), nullable=True),
    Column("target_id", String(64), nullable=True),
    Column("detail", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
)

Index("ix_devices_organization", devices.c.organization_id)
Index("ix_admin_sessions_expires_at", admin_sessions.c.expires_at)
Index("ix_admin_sessions_organization", admin_sessions.c.organization_id)
Index("ix_audit_organization_created", audit_logs.c.organization_id, audit_logs.c.created_at)

# ---------------------------------------------------------------------------
# Ingestion domain (C2a, design 14 and task C1 section 8.1): idempotent
# inspection uploads. Edge identifiers are preserved exactly (UUID strings);
# edge-observed timestamps and the central receive time are stored separately.
# Every tenant-owned row carries organization_id (C1 invariant 6).
# ---------------------------------------------------------------------------

upload_receipts = Table(
    "upload_receipts",
    metadata,
    Column("id", _BigIntId, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "device_row_id",
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("idempotency_key", String(256), nullable=False),
    # Canonical SHA-256 of the accepted payload; an identical replay must carry
    # the same hash, a reuse with a different hash is a payload conflict.
    Column("request_hash", String(64), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("object_id", String(36), nullable=False),
    Column("inspection_id", String(36), nullable=True),
    # Central object identifier for MEDIA receipts (C2b); null for INSPECTION.
    Column("central_object_id", String(128), nullable=True),
    # Echoed receipt fields: byte size of the accepted decoded payload and its
    # canonical SHA-256 (the edge validates both on every verified receipt).
    Column("size_bytes", Integer, nullable=False),
    Column("status", String(16), nullable=False, server_default="ACCEPTED"),
    Column("response_code", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("device_row_id", "idempotency_key", name="uq_upload_receipts_device_key"),
)

inspections = Table(
    "inspections",
    metadata,
    Column("id", _BigIntId, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "device_row_id",
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # Edge business identity: the edge-generated inspection UUID and its
    # per-device sequence. Both are write-once after accepted ingestion.
    Column("inspection_id", String(36), nullable=False),
    Column("device_sequence", Integer, nullable=False),
    Column("lifecycle_status", String(16), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("barcode_status", String(16), nullable=False),
    Column("barcode_value", String(256), nullable=True),
    Column("product_resolution_status", String(16), nullable=False),
    Column("product_code", String(128), nullable=True),
    Column("product_version_id", String(36), nullable=True),
    Column("internal_decision", String(16), nullable=False),
    Column("business_result", String(8), nullable=False),
    Column("missing_components", JSON, nullable=False),
    Column("low_confidence_components", JSON, nullable=False),
    Column("decision_reason_codes", JSON, nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    Column("application_version", String(64), nullable=False),
    Column("product_model_version_id", String(36), nullable=False),
    Column("product_model_checksum_sha256", String(64), nullable=False),
    Column("component_model_version_id", String(36), nullable=False),
    Column("component_model_checksum_sha256", String(64), nullable=False),
    Column("rule_version_id", String(36), nullable=False),
    Column("aggregation_policy_version", String(64), nullable=False),
    Column("processing_ms", Integer, nullable=False),
    # Bounded immutable snapshots (design 05 section 4): inference traceability
    # and the exact accepted payload for byte-level audit comparison.
    Column("inference_metadata", JSON, nullable=True),
    Column("payload_json", Text, nullable=False),
    Column("request_hash", String(64), nullable=False),
    UniqueConstraint("device_row_id", "inspection_id", name="uq_inspections_device_inspection"),
    UniqueConstraint("device_row_id", "device_sequence", name="uq_inspections_device_sequence"),
)

inspection_components = Table(
    "inspection_components",
    metadata,
    Column("id", _BigIntId, primary_key=True, autoincrement=True),
    Column(
        "inspection_id",
        ForeignKey("inspections.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("component_code", String(64), nullable=False),
    Column("state", String(16), nullable=False),
    Column("best_confidence", Float, nullable=True),
    Column("usable_frame_count", Integer, nullable=False),
    Column("detection_count", Integer, nullable=False),
    Column("policy_reason_codes", JSON, nullable=False),
    UniqueConstraint(
        "inspection_id", "component_code", name="uq_inspection_components_inspection_code"
    ),
)

# Keyset history pagination (design 14 section 8.2) and the partial barcode
# index; barcode is never globally unique.
Index(
    "ix_inspections_org_completed",
    inspections.c.organization_id,
    inspections.c.completed_at.desc(),
    inspections.c.id.desc(),
)
Index(
    "ix_inspections_device_completed",
    inspections.c.device_row_id,
    inspections.c.completed_at.desc(),
    inspections.c.id.desc(),
)
Index(
    "ix_inspections_barcode",
    inspections.c.organization_id,
    inspections.c.barcode_value,
    sqlite_where=text("barcode_value IS NOT NULL"),
    postgresql_where=text("barcode_value IS NOT NULL"),
)
Index("ix_upload_receipts_device", upload_receipts.c.device_row_id)
Index("ix_inspection_components_inspection", inspection_components.c.inspection_id)
