"""Inspection pipeline orchestration.

Sequences folder input through product detection, ROI generation, component
detection, and the deterministic rule engine, then persists JSON, ROI, and
annotated evidence (docs/design/06-ai-detection-pipeline.md). The pipeline is
fail-safe: any detection, ROI, or read failure produces NG, never OK.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from uuid import UUID, uuid4

from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.errors import (
    DetectionError,
    ImageReadError,
    ROIGenerationError,
)
from assemblyvision_domain.models import (
    AggregatedComponentEvidence,
    BarcodeResult,
    BusinessResult,
    ComponentDetection,
    FrameQualitySummary,
    InspectionDecision,
    InspectionLifecycle,
    InspectionRecord,
    InternalDecision,
    ModelManifest,
    ProductDetection,
    ProductResolution,
    ReasonCount,
    ROIResult,
)
from assemblyvision_vision.roi.roi_engine import ROIEngine
from assemblyvision_vision.sources.folder_source import FolderSource
from PIL import Image

from assemblyvision_edge.config import PipelineConfig
from assemblyvision_edge.detection.component_detector import ComponentDetector
from assemblyvision_edge.detection.product_detector import ProductDetector
from assemblyvision_edge.output.writer import OutputWriter, annotate_full_frame
from assemblyvision_edge.rules.rule_engine import (
    RuleContext,
    RuleDefinition,
    RuleEngine,
    rule_version_id,
)

log = logging.getLogger("assemblyvision.pipeline")


def _artifact_checksum(manifest: ModelManifest) -> str:
    if not manifest.artifacts:
        return "0" * 64
    return manifest.artifacts[0].sha256


class InspectionPipeline:
    """Coordinates a single static-image inspection end to end."""

    def __init__(
        self,
        *,
        product_detector: ProductDetector,
        component_detector: ComponentDetector,
        roi_engine: ROIEngine,
        rule_engine: RuleEngine,
        rule: RuleDefinition,
        product_manifest: ModelManifest,
        component_manifest: ModelManifest,
        config: PipelineConfig,
        device_id: UUID,
    ) -> None:
        self._product_detector = product_detector
        self._component_detector = component_detector
        self._roi_engine = roi_engine
        self._rule_engine = rule_engine
        self._rule = rule
        self._product_manifest = product_manifest
        self._component_manifest = component_manifest
        self._config = config
        self._device_id = device_id
        self._sequence = count(1)

    def inspect_image(self, source: FolderSource, path: Path, writer: OutputWriter) -> InspectionRecord:
        """Run one inspection and persist its evidence, returning the record."""
        inspection_id = uuid4()
        frame_id = uuid4()
        started_at = datetime.now(UTC)
        started = time.monotonic()

        extra_reasons: list[str] = []
        frame: Image.Image | None = None
        try:
            frame = source.read(path)
        except ImageReadError as exc:
            extra_reasons.append(rc.IMAGE_READ_ERROR)
            log.warning("image read failed for %s: %s", path, exc)

        product_detection: ProductDetection | None = None
        roi_result: ROIResult | None = None
        roi_image: Image.Image | None = None
        observations: list[ComponentDetection] = []
        gates = {
            "product_detected": False,
            "roi_valid": False,
            "minimum_valid_frames_met": True,
        }

        if frame is not None:
            try:
                outcome = self._product_detector.detect(frame, frame_id)
            except DetectionError as exc:
                extra_reasons.append(exc.reason_code)
                log.warning("product detection failed: %s", exc)
            else:
                if outcome.selected is None:
                    extra_reasons.append(outcome.reason_code or rc.NO_PRODUCT)
                else:
                    product_detection = outcome.selected
                    gates["product_detected"] = True
                    try:
                        generated = self._roi_engine.generate(frame, frame_id, product_detection.bbox)
                    except ROIGenerationError as exc:
                        extra_reasons.append(rc.ROI_INVALID)
                        log.warning("ROI generation failed: %s", exc)
                    else:
                        roi_image = generated.roi_image
                        roi_result = generated.result
                        gates["roi_valid"] = True
                        try:
                            observations = self._component_detector.detect(
                                generated.roi_image,
                                frame_id,
                                tuple(self._rule.required_components),
                                generated.result.transform_full_to_roi,
                                (frame.width, frame.height),
                            )
                        except DetectionError as exc:
                            extra_reasons.append(exc.reason_code)
                            log.warning("component detection failed: %s", exc)

        evidence_map = self._build_evidence(observations, gates, frame is not None, frame_id)
        context = RuleContext(
            product_identity_verified=not self._rule.barcode_required,
            component_model_version=self._config.component_detection.model_version,
            gates=gates,
            components=evidence_map,
        )
        decided = self._rule_engine.evaluate(context, self._rule)
        final_reasons = sorted(set(decided.reason_codes) | set(extra_reasons))
        internal = InternalDecision.NG if final_reasons else InternalDecision.OK
        decision = InspectionDecision(
            internal_decision=internal,
            business_result=BusinessResult.NG if internal is not InternalDecision.OK else BusinessResult.OK,
            missing_components=decided.missing_components,
            low_confidence_components=decided.low_confidence_components,
            reason_codes=final_reasons,
            decided_at=datetime.now(UTC),
        )

        record = InspectionRecord(
            inspection_id=inspection_id,
            device_id=self._device_id,
            device_sequence=next(self._sequence),
            lifecycle_status=InspectionLifecycle.COMPLETED,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            barcode_result=BarcodeResult(status="NOT_REQUIRED"),
            product_resolution=ProductResolution(
                status="RESOLVED", source="CONFIGURED_DEFAULT", product_code=self._rule.product_type
            ),
            product_detection=product_detection,
            roi_result=roi_result,
            frame_quality_summary=FrameQualitySummary(
                total_frame_count=1,
                usable_frame_count=1 if frame is not None else 0,
                rejected_frame_count=0 if frame is not None else 1,
                reasons=(
                    [ReasonCount(reason_code=rc.IMAGE_READ_ERROR, count=1)]
                    if frame is None
                    else []
                ),
            ),
            application_version=self._config.application_version,
            product_model_version_id=self._product_manifest.model_version_id,
            product_model_checksum_sha256=_artifact_checksum(self._product_manifest),
            component_model_version_id=self._component_manifest.model_version_id,
            component_model_checksum_sha256=_artifact_checksum(self._component_manifest),
            rule_version_id=rule_version_id(self._rule),
            aggregation_policy_version="single-frame-mvp-1",
            evidence=[evidence_map[key] for key in self._rule.required_components],
            decision=decision,
            synchronization_status="LOCAL_ONLY",
            processing_ms=int((time.monotonic() - started) * 1000),
        )

        annotated = None
        if frame is not None:
            annotated = annotate_full_frame(
                frame,
                product_detection.bbox if product_detection is not None else None,
                [(obs.component_code, obs.full_frame_bbox) for obs in observations],
            )
        return writer.save(record, full_frame=frame, roi_image=roi_image, annotated=annotated)

    def _build_evidence(
        self,
        observations: list[ComponentDetection],
        gates: dict[str, bool],
        frame_readable: bool,
        frame_id: UUID,
    ) -> dict[str, AggregatedComponentEvidence]:
        evidence_map: dict[str, AggregatedComponentEvidence] = {}
        roi_valid = gates.get("roi_valid", False)
        for key in self._rule.required_components:
            hits = [obs for obs in observations if obs.component_code == key]
            if roi_valid and hits:
                ratios = [
                    obs.roi_bbox.area / (obs.roi_bbox.image_width * obs.roi_bbox.image_height)
                    for obs in hits
                ]
                centers = [
                    (
                        (obs.roi_bbox.x_min + obs.roi_bbox.x_max) / 2 / obs.roi_bbox.image_width,
                        (obs.roi_bbox.y_min + obs.roi_bbox.y_max) / 2 / obs.roi_bbox.image_height,
                    )
                    for obs in hits
                ]
                evidence_map[key] = AggregatedComponentEvidence(
                    component_code=key,
                    state="PRESENT",
                    best_confidence=max(obs.confidence for obs in hits),
                    usable_frame_count=1,
                    detection_count=len(hits),
                    adjacent_detection_run=1,
                    supporting_frame_ids=[frame_id],
                    box_area_ratios=ratios,
                    box_centers=centers,
                )
            elif roi_valid:
                evidence_map[key] = AggregatedComponentEvidence(
                    component_code=key,
                    state="MISSING",
                    best_confidence=None,
                    usable_frame_count=1,
                    detection_count=0,
                    supporting_frame_ids=[frame_id],
                    policy_reason_codes=[rc.COMPONENT_MISSING],
                )
            else:
                evidence_map[key] = AggregatedComponentEvidence(
                    component_code=key,
                    state="UNCERTAIN",
                    best_confidence=None,
                    usable_frame_count=1 if frame_readable else 0,
                    detection_count=0,
                    supporting_frame_ids=[frame_id] if frame_readable else [],
                    policy_reason_codes=[rc.COMPONENT_UNVERIFIABLE],
                )
        return evidence_map
