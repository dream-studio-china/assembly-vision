"""metadata governance tables and audit correlation columns.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-12

C5 initial metadata and manual configuration governance: organization-scoped
components, products, rules, and model packages with immutable
draft/publish versioning, exact barcode mappings, explicit rule/model
compatibility, single-device desired configuration recording, and bounded
request/reason/before/after audit correlation on the existing audit_logs
table. Published versions are never updated or deleted; changes always
create a higher version. A published central version is registered metadata
only and never implies device download, validation, or activation.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("request_id", sa.String(length=64), nullable=True))
    op.add_column("audit_logs", sa.Column("reason", sa.String(length=512), nullable=True))
    op.add_column("audit_logs", sa.Column("before_state", sa.JSON(), nullable=True))
    op.add_column("audit_logs", sa.Column("after_state", sa.JSON(), nullable=True))

    op.create_table(
        "components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("component_code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("organization_id", "component_code", name="uq_components_org_code"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_components_org_key"),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("organization_id", "product_code", name="uq_products_org_code"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_products_org_key"),
    )

    op.create_table(
        "product_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.String(length=128), nullable=True),
        sa.Column("publish_reason", sa.String(length=512), nullable=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("product_id", "version", name="uq_product_versions_product_version"),
        sa.UniqueConstraint(
            "organization_id", "version_id", name="uq_product_versions_org_version_id"
        ),
        sa.UniqueConstraint(
            "product_id", "idempotency_key", name="uq_product_versions_product_key"
        ),
    )
    op.create_index("ix_product_versions_product", "product_versions", ["product_id", "version"])
    op.create_index(
        "ix_product_versions_org_created",
        "product_versions",
        ["organization_id", "created_at"],
    )

    op.create_table(
        "product_version_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_version_id",
            sa.Integer(),
            sa.ForeignKey("product_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "component_id",
            sa.Integer(),
            sa.ForeignKey("components.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("expected_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "product_version_id",
            "component_id",
            name="uq_product_version_components_version_component",
        ),
    )

    op.create_table(
        "product_version_barcodes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_version_id",
            sa.Integer(),
            sa.ForeignKey("product_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("barcode_value", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.UniqueConstraint(
            "product_version_id",
            "barcode_value",
            name="uq_product_version_barcodes_version_barcode",
        ),
    )
    op.create_index(
        "uq_product_version_barcodes_published",
        "product_version_barcodes",
        ["organization_id", "barcode_value"],
        unique=True,
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )

    op.create_table(
        "rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("organization_id", "rule_code", name="uq_rules_org_code"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_rules_org_key"),
    )

    op.create_table(
        "rule_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_version_id",
            sa.Integer(),
            sa.ForeignKey("product_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("barcode_required", sa.Boolean(), nullable=False),
        sa.Column("minimum_usable_frames", sa.Integer(), nullable=False),
        sa.Column("uncertain_maps_to_ng", sa.Boolean(), nullable=False),
        sa.Column("mandatory_gates", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.String(length=128), nullable=True),
        sa.Column("publish_reason", sa.String(length=512), nullable=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("rule_id", "version", name="uq_rule_versions_rule_version"),
        sa.UniqueConstraint(
            "organization_id", "version_id", name="uq_rule_versions_org_version_id"
        ),
        sa.UniqueConstraint("rule_id", "idempotency_key", name="uq_rule_versions_rule_key"),
    )
    op.create_index("ix_rule_versions_rule", "rule_versions", ["rule_id", "version"])
    op.create_index(
        "ix_rule_versions_org_created",
        "rule_versions",
        ["organization_id", "created_at"],
    )

    op.create_table(
        "rule_component_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "rule_version_id",
            sa.Integer(),
            sa.ForeignKey("rule_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "component_id",
            sa.Integer(),
            sa.ForeignKey("components.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("high_confidence", sa.Float(), nullable=False),
        sa.Column("medium_confidence", sa.Float(), nullable=False),
        sa.Column("minimum_medium_detections", sa.Integer(), nullable=False),
        sa.Column("require_adjacent_frames", sa.Boolean(), nullable=False),
        sa.Column("expected_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "rule_version_id",
            "component_id",
            name="uq_rule_component_policies_version_component",
        ),
    )

    op.create_table(
        "model_packages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("task", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("organization_id", "model_code", name="uq_model_packages_org_code"),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_model_packages_org_key"),
    )

    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_package_id",
            sa.Integer(),
            sa.ForeignKey("model_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="DRAFT", nullable=False),
        sa.Column("semantic_version", sa.String(length=32), nullable=False),
        sa.Column("edge_version_label", sa.String(length=64), nullable=False),
        sa.Column("runtime", sa.String(length=64), nullable=False),
        sa.Column("input_width", sa.Integer(), nullable=False),
        sa.Column("input_height", sa.Integer(), nullable=False),
        sa.Column("class_names", sa.JSON(), nullable=False),
        sa.Column("artifacts", sa.JSON(), nullable=False),
        sa.Column("datasets", sa.JSON(), nullable=False),
        sa.Column("split_strategy", sa.String(length=64), nullable=False),
        sa.Column("source_revision", sa.String(length=128), nullable=False),
        sa.Column("training_config_revision", sa.String(length=128), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.String(length=128), nullable=True),
        sa.Column("publish_reason", sa.String(length=512), nullable=True),
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "model_package_id", "version", name="uq_model_versions_package_version"
        ),
        sa.UniqueConstraint(
            "organization_id", "version_id", name="uq_model_versions_org_version_id"
        ),
        sa.UniqueConstraint(
            "model_package_id", "idempotency_key", name="uq_model_versions_package_key"
        ),
    )
    op.create_index("ix_model_versions_package", "model_versions", ["model_package_id", "version"])
    op.create_index(
        "ix_model_versions_org_created",
        "model_versions",
        ["organization_id", "created_at"],
    )

    op.create_table(
        "rule_model_compatibilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "rule_version_id",
            sa.Integer(),
            sa.ForeignKey("rule_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_version_id",
            sa.Integer(),
            sa.ForeignKey("model_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "rule_version_id",
            "model_version_id",
            name="uq_rule_model_compatibilities_version_model",
        ),
    )

    op.create_table(
        "desired_configurations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Integer(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "device_row_id",
            sa.Integer(),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "product_version_id",
            sa.Integer(),
            sa.ForeignKey("product_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "product_model_version_id",
            sa.Integer(),
            sa.ForeignKey("model_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "component_model_version_id",
            sa.Integer(),
            sa.ForeignKey("model_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "rule_version_id",
            sa.Integer(),
            sa.ForeignKey("rule_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=512), nullable=False),
        sa.Column("assigned_by", sa.String(length=128), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("device_row_id", name="uq_desired_configurations_device"),
    )


def downgrade() -> None:
    op.drop_table("desired_configurations")
    op.drop_table("rule_model_compatibilities")
    op.drop_table("model_versions")
    op.drop_table("model_packages")
    op.drop_table("rule_component_policies")
    op.drop_table("rule_versions")
    op.drop_table("rules")
    op.drop_index("uq_product_version_barcodes_published", table_name="product_version_barcodes")
    op.drop_table("product_version_barcodes")
    op.drop_table("product_version_components")
    op.drop_index("ix_product_versions_org_created", table_name="product_versions")
    op.drop_index("ix_product_versions_product", table_name="product_versions")
    op.drop_table("product_versions")
    op.drop_table("products")
    op.drop_table("components")
    op.drop_column("audit_logs", "after_state")
    op.drop_column("audit_logs", "before_state")
    op.drop_column("audit_logs", "reason")
    op.drop_column("audit_logs", "request_id")
