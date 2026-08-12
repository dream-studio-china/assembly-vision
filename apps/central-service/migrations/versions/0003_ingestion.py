"""ingestion tables: upload_receipts, inspections, inspection_components.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-12

C2a inspection ingestion: idempotent upload receipts, the immutable edge
inspection projection, and per-component evidence. Edge identifiers and
timestamps are preserved exactly; the central receive time is stored
separately. Every tenant-owned row carries ``organization_id`` (C1 invariant
6), and ``UNIQUE(device_row_id, idempotency_key)`` plus the inspection
identity uniqueness constraints make replay duplicate-free while a reused
identity with a different payload hash is a 409 conflict.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upload_receipts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
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
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("object_id", sa.String(length=36), nullable=False),
        sa.Column("inspection_id", sa.String(length=36), nullable=True),
        sa.Column("central_object_id", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ACCEPTED"),
        sa.Column("response_code", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "device_row_id", "idempotency_key", name="uq_upload_receipts_device_key"
        ),
    )

    op.create_table(
        "inspections",
        sa.Column("id", sa.BigInteger(), primary_key=True),
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
        sa.Column("inspection_id", sa.String(length=36), nullable=False),
        sa.Column("device_sequence", sa.Integer(), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("barcode_status", sa.String(length=16), nullable=False),
        sa.Column("barcode_value", sa.String(length=256), nullable=True),
        sa.Column("product_resolution_status", sa.String(length=16), nullable=False),
        sa.Column("product_code", sa.String(length=128), nullable=True),
        sa.Column("product_version_id", sa.String(length=36), nullable=True),
        sa.Column("internal_decision", sa.String(length=16), nullable=False),
        sa.Column("business_result", sa.String(length=8), nullable=False),
        sa.Column("missing_components", sa.JSON(), nullable=False),
        sa.Column("low_confidence_components", sa.JSON(), nullable=False),
        sa.Column("decision_reason_codes", sa.JSON(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("application_version", sa.String(length=64), nullable=False),
        sa.Column("product_model_version_id", sa.String(length=36), nullable=False),
        sa.Column("product_model_checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("component_model_version_id", sa.String(length=36), nullable=False),
        sa.Column("component_model_checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("rule_version_id", sa.String(length=36), nullable=False),
        sa.Column("aggregation_policy_version", sa.String(length=64), nullable=False),
        sa.Column("processing_ms", sa.Integer(), nullable=False),
        sa.Column("inference_metadata", sa.JSON(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "device_row_id", "inspection_id", name="uq_inspections_device_inspection"
        ),
        sa.UniqueConstraint(
            "device_row_id", "device_sequence", name="uq_inspections_device_sequence"
        ),
    )

    op.create_table(
        "inspection_components",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "inspection_id",
            sa.BigInteger(),
            sa.ForeignKey("inspections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("component_code", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("best_confidence", sa.Float(), nullable=True),
        sa.Column("usable_frame_count", sa.Integer(), nullable=False),
        sa.Column("detection_count", sa.Integer(), nullable=False),
        sa.Column("policy_reason_codes", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "inspection_id", "component_code", name="uq_inspection_components_inspection_code"
        ),
    )

    op.create_index(
        "ix_inspections_org_completed",
        "inspections",
        ["organization_id", sa.text("completed_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_inspections_device_completed",
        "inspections",
        ["device_row_id", sa.text("completed_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_inspections_barcode",
        "inspections",
        ["organization_id", "barcode_value"],
        postgresql_where=sa.text("barcode_value IS NOT NULL"),
    )
    op.create_index("ix_upload_receipts_device", "upload_receipts", ["device_row_id"])
    op.create_index(
        "ix_inspection_components_inspection", "inspection_components", ["inspection_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_inspection_components_inspection", table_name="inspection_components")
    op.drop_index("ix_upload_receipts_device", table_name="upload_receipts")
    op.drop_index("ix_inspections_barcode", table_name="inspections")
    op.drop_index("ix_inspections_device_completed", table_name="inspections")
    op.drop_index("ix_inspections_org_completed", table_name="inspections")
    op.drop_table("inspection_components")
    op.drop_table("inspections")
    op.drop_table("upload_receipts")
