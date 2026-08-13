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
    Boolean,
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
    # C5 governance correlation (design 05 section 8): the request ID ties the
    # event to the correlated request log; the bounded before/after snapshots
    # capture the governed resource state without storing secrets or object
    # storage paths. Existing events keep NULL in all four columns.
    Column("request_id", String(64), nullable=True),
    Column("reason", String(512), nullable=True),
    Column("before_state", JSON, nullable=True),
    Column("after_state", JSON, nullable=True),
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

# Media evidence bytes are stored only in the object store under a central
# generated opaque key; PostgreSQL holds the binding metadata (design 05 3.2).
# The object is finalized and verified before a row may report AVAILABLE
# (C1 invariant 8); central_object_id is the stable identifier echoed in the
# edge MEDIA receipt and is separate from the object key.
inspection_media = Table(
    "inspection_media",
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
    Column(
        "inspection_row_id",
        ForeignKey("inspections.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # Edge media identity (``MediaMetadata.media_id`` in the inspection
    # manifest); unique per device so a replay cannot create a second binding.
    Column("source_media_id", String(36), nullable=False),
    Column("media_kind", String(16), nullable=False),
    Column("mime_type", String(64), nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("checksum_sha256", String(64), nullable=False),
    Column("object_key", String(256), nullable=False),
    Column("central_object_id", String(36), nullable=False),
    Column("lifecycle", String(16), nullable=False, server_default="PENDING"),
    # Edge-observed capture time (inherited from the parent inspection, which
    # carries the edge capture clock) and the central receive time (design 14).
    Column("capture_at", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("device_row_id", "source_media_id", name="uq_inspection_media_device_media"),
    UniqueConstraint("object_key", name="uq_inspection_media_object_key"),
    UniqueConstraint("central_object_id", name="uq_inspection_media_central_object"),
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
Index("ix_inspection_media_inspection", inspection_media.c.inspection_row_id)
Index("ix_inspection_media_device", inspection_media.c.device_row_id)
Index("ix_inspection_media_lifecycle", inspection_media.c.lifecycle)

# Append-only central human review (C4, design 24). Revisions chain per
# inspection; the original machine decision is snapshotted and never
# overwritten. Idempotency keys make client retries duplicate-free.
review_records = Table(
    "review_records",
    metadata,
    Column("id", _BigIntId, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "inspection_row_id",
        ForeignKey("inspections.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("revision", Integer, nullable=False),
    Column("disposition", String(16), nullable=False),
    Column("reason", String(200), nullable=True),
    Column("note", String(2000), nullable=True),
    Column("reviewer", String(128), nullable=False),
    # Bounded immutable snapshot of per-component corrections.
    Column("component_corrections", JSON, nullable=True),
    Column("original_business_result", String(8), nullable=False),
    Column("original_internal_decision", String(16), nullable=False),
    Column("original_reason_codes", JSON, nullable=False),
    Column("idempotency_key", String(256), nullable=False),
    Column("request_hash", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("inspection_row_id", "revision", name="uq_review_records_inspection_revision"),
    UniqueConstraint(
        "inspection_row_id", "idempotency_key", name="uq_review_records_inspection_key"
    ),
)

Index("ix_review_records_inspection", review_records.c.inspection_row_id, review_records.c.revision)
Index("ix_review_records_created", review_records.c.organization_id, review_records.c.created_at)

# ---------------------------------------------------------------------------
# Metadata governance (C5, design 05 sections 4/5): stable product/component,
# rule, and model identities with immutable draft/publish versioning plus
# single-device desired configuration recording. Published versions are never
# updated or deleted; changes always create a higher version. A published
# central version is registered metadata only and never implies that a device
# installed, validated, or activated it. Every tenant-owned row carries
# organization_id (C1 invariant 6).
# ---------------------------------------------------------------------------

# Organization-scoped controlled component vocabulary: product versions and
# rule policies reference components by row so code spellings cannot drift.
components = Table(
    "components",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("component_code", String(64), nullable=False),
    Column("display_name", String(128), nullable=False),
    # Idempotent creation: one request key per organization; the stored
    # request hash distinguishes an identical replay from a conflicting reuse.
    Column("idempotency_key", String(256), nullable=True),
    Column("request_hash", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("organization_id", "component_code", name="uq_components_org_code"),
    UniqueConstraint("organization_id", "idempotency_key", name="uq_components_org_key"),
)

products = Table(
    "products",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("product_code", String(128), nullable=False),
    Column("name", String(128), nullable=False),
    Column("idempotency_key", String(256), nullable=True),
    Column("request_hash", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("organization_id", "product_code", name="uq_products_org_code"),
    UniqueConstraint("organization_id", "idempotency_key", name="uq_products_org_key"),
)

# Immutable product versions. version_id is the public UUID used for edge and
# configuration traceability; version increments from 1 within a product.
product_versions = Table(
    "product_versions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("product_id", ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
    Column("version_id", String(36), nullable=False),
    Column("version", Integer, nullable=False),
    Column("status", String(16), nullable=False, server_default="DRAFT"),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("published_by", String(128), nullable=True),
    Column("publish_reason", String(512), nullable=True),
    Column("idempotency_key", String(256), nullable=True),
    Column("request_hash", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("product_id", "version", name="uq_product_versions_product_version"),
    UniqueConstraint("organization_id", "version_id", name="uq_product_versions_org_version_id"),
    UniqueConstraint("product_id", "idempotency_key", name="uq_product_versions_product_key"),
)

# Frozen membership snapshot of a product version; counts are the required
# quantities the rule engine enforces for that product configuration.
product_version_components = Table(
    "product_version_components",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "product_version_id",
        ForeignKey("product_versions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("component_id", ForeignKey("components.id", ondelete="RESTRICT"), nullable=False),
    Column("expected_count", Integer, nullable=False),
    UniqueConstraint(
        "product_version_id",
        "component_id",
        name="uq_product_version_components_version_component",
    ),
)

# Exact barcode mappings only (ADR-015): prefix/pattern inference is
# prohibited. A barcode row is DRAFT until its version publishes, when it is
# flipped to PUBLISHED; the partial unique index then forbids the same
# barcode value from mapping to a second product version in the organization.
product_version_barcodes = Table(
    "product_version_barcodes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "product_version_id",
        ForeignKey("product_versions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("barcode_value", String(256), nullable=False),
    Column("status", String(16), nullable=False, server_default="DRAFT"),
    UniqueConstraint(
        "product_version_id",
        "barcode_value",
        name="uq_product_version_barcodes_version_barcode",
    ),
)

rules = Table(
    "rules",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("rule_code", String(128), nullable=False),
    Column("name", String(128), nullable=False),
    Column("idempotency_key", String(256), nullable=True),
    Column("request_hash", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("organization_id", "rule_code", name="uq_rules_org_code"),
    UniqueConstraint("organization_id", "idempotency_key", name="uq_rules_org_key"),
)

# Immutable rule versions. content_sha256 pins the canonicalized rule content
# so a rule UUID/version can never be reused with different semantics.
rule_versions = Table(
    "rule_versions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("rule_id", ForeignKey("rules.id", ondelete="CASCADE"), nullable=False),
    Column(
        "product_version_id",
        ForeignKey("product_versions.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("version_id", String(36), nullable=False),
    Column("version", Integer, nullable=False),
    Column("status", String(16), nullable=False, server_default="DRAFT"),
    Column("barcode_required", Boolean, nullable=False),
    Column("minimum_usable_frames", Integer, nullable=False),
    # M1 rules always map uncertain evidence to NG (contract 03 section 5); the
    # column pins the invariant so a later version cannot relax it silently.
    Column("uncertain_maps_to_ng", Boolean, nullable=False),
    Column("mandatory_gates", JSON, nullable=False),
    Column("content_sha256", String(64), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("published_by", String(128), nullable=True),
    Column("publish_reason", String(512), nullable=True),
    Column("idempotency_key", String(256), nullable=True),
    Column("request_hash", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("rule_id", "version", name="uq_rule_versions_rule_version"),
    UniqueConstraint("organization_id", "version_id", name="uq_rule_versions_org_version_id"),
    UniqueConstraint("rule_id", "idempotency_key", name="uq_rule_versions_rule_key"),
)

# Per-component confidence/temporal policy of one rule version (design 14
# ComponentPolicy). Threshold ordering (medium <= high) is validated on write.
rule_component_policies = Table(
    "rule_component_policies",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "rule_version_id",
        ForeignKey("rule_versions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("component_id", ForeignKey("components.id", ondelete="RESTRICT"), nullable=False),
    Column("high_confidence", Float, nullable=False),
    Column("medium_confidence", Float, nullable=False),
    Column("minimum_medium_detections", Integer, nullable=False),
    Column("require_adjacent_frames", Boolean, nullable=False),
    Column("expected_count", Integer, nullable=False),
    UniqueConstraint(
        "rule_version_id",
        "component_id",
        name="uq_rule_component_policies_version_component",
    ),
)

# Explicit component-detector compatibility per rule version: only the listed
# model versions may satisfy this rule, mirroring the edge rule document's
# ``compatible_component_model_versions`` (design 11, edge config.py).
rule_model_compatibilities = Table(
    "rule_model_compatibilities",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "rule_version_id",
        ForeignKey("rule_versions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "model_version_id", ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=False
    ),
    UniqueConstraint(
        "rule_version_id",
        "model_version_id",
        name="uq_rule_model_compatibilities_version_model",
    ),
)

model_packages = Table(
    "model_packages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("model_code", String(128), nullable=False),
    Column("name", String(128), nullable=False),
    # PRODUCT_DETECTION or COMPONENT_DETECTION (design 14 ModelManifest.task).
    Column("task", String(32), nullable=False),
    Column("idempotency_key", String(256), nullable=True),
    Column("request_hash", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("organization_id", "model_code", name="uq_model_packages_org_code"),
    UniqueConstraint("organization_id", "idempotency_key", name="uq_model_packages_org_key"),
)

# Immutable model versions: declarative manifest registration (C5 locks the
# M1 boundary: artifact bytes are never fetched or verified server-side, so
# publication never claims the artifact was validated). manifest_sha256 pins
# the canonical manifest content.
model_versions = Table(
    "model_versions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "model_package_id",
        ForeignKey("model_packages.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("version_id", String(36), nullable=False),
    Column("version", Integer, nullable=False),
    Column("status", String(16), nullable=False, server_default="DRAFT"),
    Column("semantic_version", String(32), nullable=False),
    Column("edge_version_label", String(64), nullable=False),
    Column("runtime", String(64), nullable=False),
    Column("input_width", Integer, nullable=False),
    Column("input_height", Integer, nullable=False),
    Column("class_names", JSON, nullable=False),
    Column("artifacts", JSON, nullable=False),
    Column("datasets", JSON, nullable=False),
    Column("split_strategy", String(64), nullable=False),
    Column("source_revision", String(128), nullable=False),
    Column("training_config_revision", String(128), nullable=False),
    Column("metrics", JSON, nullable=False),
    Column("limitations", JSON, nullable=False),
    Column("manifest_sha256", String(64), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("published_by", String(128), nullable=True),
    Column("publish_reason", String(512), nullable=True),
    Column("idempotency_key", String(256), nullable=True),
    Column("request_hash", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("model_package_id", "version", name="uq_model_versions_package_version"),
    UniqueConstraint("organization_id", "version_id", name="uq_model_versions_org_version_id"),
    UniqueConstraint("model_package_id", "idempotency_key", name="uq_model_versions_package_key"),
)

# Single-device desired configuration (M1, design 05 section 5.2): the central
# records what the operator wants on one device; there is no remote download,
# validation, or activation endpoint, and the record never changes edge
# behavior. A new assignment replaces the previous desired state under an
# If-Match revision guard.
desired_configurations = Table(
    "desired_configurations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "organization_id",
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("device_row_id", ForeignKey("devices.id", ondelete="CASCADE"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column(
        "product_version_id",
        ForeignKey("product_versions.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "product_model_version_id",
        ForeignKey("model_versions.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "component_model_version_id",
        ForeignKey("model_versions.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("rule_version_id", ForeignKey("rule_versions.id", ondelete="RESTRICT"), nullable=False),
    Column("reason", String(512), nullable=False),
    Column("assigned_by", String(128), nullable=False),
    Column("assigned_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=_UTC_NOW, nullable=False),
    UniqueConstraint("device_row_id", name="uq_desired_configurations_device"),
)

Index("ix_product_versions_product", product_versions.c.product_id, product_versions.c.version)
Index(
    "ix_product_versions_org_created",
    product_versions.c.organization_id,
    product_versions.c.created_at,
)
Index("ix_rule_versions_rule", rule_versions.c.rule_id, rule_versions.c.version)
Index("ix_rule_versions_org_created", rule_versions.c.organization_id, rule_versions.c.created_at)
Index("ix_model_versions_package", model_versions.c.model_package_id, model_versions.c.version)
Index(
    "ix_model_versions_org_created", model_versions.c.organization_id, model_versions.c.created_at
)

# Concurrency backstop for exact barcode mapping ambiguity: once a version
# publishes, its barcode value is unique per organization. SQLite and
# PostgreSQL both support partial indexes; the friendly conflict check happens
# in the repository transaction, this index protects concurrent publishes.
Index(
    "uq_product_version_barcodes_published",
    product_version_barcodes.c.organization_id,
    product_version_barcodes.c.barcode_value,
    unique=True,
    sqlite_where=text("status = 'PUBLISHED'"),
    postgresql_where=text("status = 'PUBLISHED'"),
)
