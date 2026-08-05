"""Tests for the domain models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from assemblyvision_edge.domain.models import BoundingBox, InspectionRecord
from assemblyvision_edge.rules.rule_engine import rule_version_id
from pydantic import ValidationError

from tests.conftest import make_rule


def test_bounding_box_valid() -> None:
    box = BoundingBox(
        x_min=1.0, y_min=2.0, x_max=10.0, y_max=20.0, image_width=100, image_height=100
    )
    assert box.width == 9.0
    assert box.height == 18.0
    assert box.area == pytest.approx(162.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"x_min": 10.0, "y_min": 2.0, "x_max": 1.0, "y_max": 20.0},
        {"x_min": 1.0, "y_min": 20.0, "x_max": 10.0, "y_max": 2.0},
        {"x_min": 1.0, "y_min": 2.0, "x_max": 120.0, "y_max": 20.0},
        {"x_min": -1.0, "y_min": 2.0, "x_max": 10.0, "y_max": 20.0},
    ],
)
def test_bounding_box_rejects_invalid(kwargs: dict[str, float]) -> None:
    base = {"x_min": 1.0, "y_min": 2.0, "x_max": 10.0, "y_max": 20.0, "image_width": 100, "image_height": 100}
    base.update(kwargs)
    with pytest.raises(ValidationError):
        BoundingBox.model_validate(base)


def test_bounding_box_rejects_extra_fields() -> None:
    base = {"x_min": 1.0, "y_min": 2.0, "x_max": 10.0, "y_max": 20.0, "image_width": 100, "image_height": 100, "unexpected": 1}
    with pytest.raises(ValidationError):
        BoundingBox.model_validate(base)


def test_rule_version_id_is_deterministic() -> None:
    rule = make_rule()
    assert rule_version_id(rule) == rule_version_id(rule)


def test_inspection_record_json_round_trip() -> None:
    record = InspectionRecord.model_validate(
        {
            "inspection_id": "00000000-0000-4000-8000-0000000000aa",
            "device_id": "00000000-0000-4000-8000-0000000000bb",
            "device_sequence": 1,
            "lifecycle_status": "COMPLETED",
            "started_at": datetime(2026, 1, 1, tzinfo=UTC),
            "completed_at": datetime(2026, 1, 1, tzinfo=UTC),
            "barcode_result": {"status": "NOT_REQUIRED"},
            "product_resolution": {"status": "RESOLVED", "source": "CONFIGURED_DEFAULT", "product_code": "model_a"},
            "frame_quality_summary": {
                "total_frame_count": 1,
                "usable_frame_count": 1,
                "rejected_frame_count": 0,
                "reasons": [],
            },
            "application_version": "0.1.0",
            "product_model_version_id": "00000000-0000-4000-8000-000000000001",
            "product_model_checksum_sha256": "0" * 64,
            "component_model_version_id": "00000000-0000-4000-8000-000000000002",
            "component_model_checksum_sha256": "0" * 64,
            "rule_version_id": "00000000-0000-4000-8000-0000000000cc",
            "aggregation_policy_version": "single-frame-mvp-1",
            "evidence": [],
            "decision": {
                "internal_decision": "OK",
                "business_result": "OK",
                "missing_components": [],
                "low_confidence_components": [],
                "reason_codes": [],
                "decided_at": datetime(2026, 1, 1, tzinfo=UTC),
            },
            "synchronization_status": "LOCAL_ONLY",
            "processing_ms": 12,
        }
    )
    restored = InspectionRecord.model_validate_json(record.model_dump_json())
    assert restored.inspection_id == record.inspection_id
    assert restored.decision.business_result.value == "OK"
