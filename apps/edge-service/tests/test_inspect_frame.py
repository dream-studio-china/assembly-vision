"""Parity tests: inspect_frame (camera) equals inspect_image (folder, ADR-013)."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from uuid import uuid4

from assemblyvision_domain.models import InspectionRecord
from assemblyvision_edge.output.writer import OutputWriter
from assemblyvision_edge.pipeline import InspectionPipeline
from assemblyvision_vision.sources.folder_source import FolderSource
from PIL import Image

from tests.test_pipeline import (
    FakeComponentDetector,
    FakeProductDetector,
    _build_pipeline,
    _component_obs,
    _Outcome,
    _product_detection,
)


def _pipeline() -> InspectionPipeline:
    frame_id = uuid4()
    component_detector = FakeComponentDetector([_component_obs(frame_id, "component_a")])
    return _build_pipeline(
        FakeProductDetector(_Outcome(selected=_product_detection(frame_id))),
        component_detector,
    )


def _write_image(path: Path) -> Image.Image:
    image = Image.new("RGB", (800, 600), (200, 200, 200))
    image.save(path)
    return image


def test_inspect_frame_matches_inspect_image(tmp_path: Path) -> None:
    folder = tmp_path / "images"
    folder.mkdir()
    image_path = folder / "frame.png"
    _write_image(image_path)

    writer = OutputWriter(tmp_path / "out")
    pipeline = _pipeline()

    record_from_image = pipeline.inspect_image(FolderSource(folder), image_path, writer)

    source = FolderSource(folder)
    stop = Event()
    frame = next(source.frames(stop))
    record_from_frame = pipeline.inspect_frame(frame, writer)

    assert record_from_image.decision.business_result == record_from_frame.decision.business_result
    assert (
        record_from_image.decision.internal_decision == record_from_frame.decision.internal_decision
    )
    assert record_from_image.decision.reason_codes == record_from_frame.decision.reason_codes

    # Supporting frame IDs are per-inspection identifiers, so compare the
    # decision-relevant evidence fields.
    def _evidence(record: InspectionRecord) -> list[dict[str, object]]:
        return [
            evidence.model_dump(exclude={"supporting_frame_ids"}) for evidence in record.evidence
        ]

    assert _evidence(record_from_image) == _evidence(record_from_frame)
    assert record_from_image.product_detection is not None
    assert record_from_frame.product_detection is not None
