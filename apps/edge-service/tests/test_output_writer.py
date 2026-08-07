"""Tests for the evidence and media output writer."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from assemblyvision_domain.errors import OutputError
from assemblyvision_domain.models import (
    BarcodeResult,
    BusinessResult,
    FrameQualitySummary,
    InspectionDecision,
    InspectionLifecycle,
    InspectionRecord,
    InternalDecision,
    ProductResolution,
)
from assemblyvision_edge.output.writer import OutputWriter
from PIL import Image


def _make_record(device_id: UUID) -> InspectionRecord:
    return InspectionRecord(
        inspection_id=uuid4(),
        device_id=device_id,
        device_sequence=1,
        lifecycle_status=InspectionLifecycle.COMPLETED,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        barcode_result=BarcodeResult(status="NOT_REQUIRED"),
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
        evidence=[],
        decision=InspectionDecision(
            internal_decision=InternalDecision.OK,
            business_result=BusinessResult.OK,
            decided_at=datetime.now(UTC),
        ),
        synchronization_status="LOCAL_ONLY",
        processing_ms=12,
    )


def test_writer_persists_inspection_json_and_media(tmp_path: Path) -> None:
    writer = OutputWriter(tmp_path / "out")
    record = _make_record(uuid4())
    frame = Image.new("RGB", (32, 32), (10, 10, 10))

    saved = writer.save(record, full_frame=frame, roi_image=None, annotated=None)

    inspection_dir = tmp_path / "out" / str(saved.inspection_id)
    assert (inspection_dir / "inspection.json").is_file()
    assert (inspection_dir / "key_frame.jpg").is_file()
    payload = json.loads((inspection_dir / "inspection.json").read_text(encoding="utf-8"))
    assert payload["inspection_id"] == str(saved.inspection_id)
    assert len(payload["media"]) == 1
    media = payload["media"][0]
    assert media["kind"] == "KEY_FRAME"
    assert media["mime_type"] == "image/jpeg"
    assert media["size_bytes"] > 0
    raw = (inspection_dir / "key_frame.jpg").read_bytes()
    assert media["checksum_sha256"] == hashlib.sha256(raw).hexdigest()


def test_writer_no_media_writes_json_only(tmp_path: Path) -> None:
    writer = OutputWriter(tmp_path / "out")
    saved = writer.save(_make_record(uuid4()), full_frame=None, roi_image=None, annotated=None)

    inspection_dir = tmp_path / "out" / str(saved.inspection_id)
    assert (inspection_dir / "inspection.json").is_file()
    assert not list(inspection_dir.glob("*.jpg"))


def test_writer_leaves_no_temp_files(tmp_path: Path) -> None:
    writer = OutputWriter(tmp_path / "out")
    saved = writer.save(_make_record(uuid4()), full_frame=None, roi_image=None, annotated=None)

    leftover = [
        p
        for p in (tmp_path / "out" / str(saved.inspection_id)).iterdir()
        if p.name.endswith(".tmp")
    ]
    assert leftover == []


def test_writer_rejects_republishing_same_inspection(tmp_path: Path) -> None:
    writer = OutputWriter(tmp_path / "out")
    record = _make_record(uuid4())
    writer.save(record, full_frame=None, roi_image=None, annotated=None)

    with pytest.raises(OutputError):
        writer.save(record, full_frame=None, roi_image=None, annotated=None)


def test_writer_publishes_bundle_atomically_without_partial_output(tmp_path: Path) -> None:
    writer = OutputWriter(tmp_path / "out")
    record = _make_record(uuid4())
    saved = writer.save(
        record,
        full_frame=Image.new("RGB", (32, 32), (10, 10, 10)),
        roi_image=None,
        annotated=None,
    )

    inspection_dir = tmp_path / "out" / str(saved.inspection_id)
    assert (inspection_dir / "inspection.json").is_file()
    assert (inspection_dir / "key_frame.jpg").is_file()
    staging = [p for p in (tmp_path / "out").iterdir() if p.name.startswith(".staging-")]
    assert staging == []
