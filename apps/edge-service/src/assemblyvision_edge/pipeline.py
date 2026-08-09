"""Inspection pipeline orchestration.

Sequences folder input through product detection, ROI generation, component
detection, and the deterministic rule engine, then persists JSON, ROI, and
annotated evidence (docs/design/06-ai-detection-pipeline.md). The pipeline is
fail-safe: any detection, ROI, or read failure produces NG, never OK.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from uuid import UUID, uuid4

from assemblyvision_domain import reason_codes as rc
from assemblyvision_domain.errors import (
    DetectionError,
    ImageReadError,
    ROIGenerationError,
    RuleEvaluationError,
)
from assemblyvision_domain.models import (
    AggregatedComponentEvidence,
    BarcodeResult,
    BusinessResult,
    ComponentDetection,
    FrameQualitySummary,
    InferenceMetadata,
    InferenceSettings,
    InferenceStageMetadata,
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
from assemblyvision_vision.manifests import manifest_model_version
from assemblyvision_vision.roi.geometry import Box, apply_transform, inverse_transform
from assemblyvision_vision.roi.roi_engine import ROIEngine
from assemblyvision_vision.sources.folder_source import FolderSource
from assemblyvision_vision.sources.frame_source import CapturedFrame
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
from assemblyvision_edge.temporal.aggregator import (
    TemporalAggregationConfig,
    TemporalAggregator,
    temporal_policy_version,
)
from assemblyvision_edge.temporal.window_manager import FrameObservation, ProductWindow

log = logging.getLogger("assemblyvision.pipeline")


def _artifact_checksum(manifest: ModelManifest) -> str:
    if not manifest.artifacts:
        return "0" * 64
    return manifest.artifacts[0].sha256


def _validate_product_provenance(
    detection: ProductDetection,
    frame_id: UUID,
    manifest: ModelManifest,
    frame: Image.Image,
) -> bool:
    """Reject detections that do not belong to the current frame/model (P1)."""
    if detection.frame_id != frame_id:
        return False
    if detection.model_version_id != manifest.model_version_id:
        return False
    box = detection.bbox
    return box.image_width == frame.width and box.image_height == frame.height


_COORD_TOLERANCE = 1e-6


@dataclass
class _DetectionOutcome:
    """Result of one frame's product/ROI/component detection pass."""

    product_detection: ProductDetection | None = None
    roi_result: ROIResult | None = None
    roi_image: Image.Image | None = None
    observations: list[ComponentDetection] = field(default_factory=list)
    gates: dict[str, bool] = field(
        default_factory=lambda: {
            "product_detected": False,
            "roi_valid": False,
            "component_inference_valid": False,
            "minimum_valid_frames_met": True,
        }
    )
    reasons: list[str] = field(default_factory=list)
    product_latency_ms: float | None = None
    component_latency_ms: float | None = None

    @classmethod
    def empty(cls) -> _DetectionOutcome:
        return cls()


def _reason_counts(reasons: list[str]) -> list[ReasonCount]:
    """Aggregate a flat reason list into stable, count-ordered ReasonCounts."""
    counts: dict[str, int] = {}
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1
    return [ReasonCount(reason_code=code, count=count) for code, count in sorted(counts.items())]


def _representative_frame(frames: list[FrameObservation]) -> FrameObservation | None:
    """Pick the frame that best represents the window for media persistence.

    Prefers the frame with the most component observations, breaking ties by
    the highest observation confidence; the first such frame wins so the choice
    is deterministic for equal evidence.
    """
    if not frames:
        return None
    return max(
        frames,
        key=lambda frame: (
            len(frame.observations),
            max((obs.confidence for obs in frame.observations), default=0.0),
        ),
    )


def _is_translation_transform(transform: tuple[float, float, float, float, float, float]) -> bool:
    """Accept only the invertible translation transform used by the M1 ROI engine."""
    a, b, _c, d, e, _f = transform
    return a == 1.0 and b == 0.0 and d == 0.0 and e == 1.0


def _validate_component_provenance(
    observations: list[ComponentDetection],
    frame_id: UUID,
    manifest: ModelManifest,
    roi: Image.Image,
    frame: Image.Image,
    transform: tuple[float, float, float, float, float, float],
) -> bool:
    """Reject component observations with stale frame/model or inconsistent geometry.

    Each ROI box is mapped to full-frame space with the recorded transform and
    compared to the detector-provided full-frame box within a floating-point
    tolerance, so internally contradictory evidence can never contribute to OK.
    Only the supported invertible translation transform is accepted for M1
    (F12).
    """
    if not _is_translation_transform(transform):
        return False
    inverse = inverse_transform(transform)
    for obs in observations:
        if obs.frame_id != frame_id:
            return False
        if obs.model_version_id != manifest.model_version_id:
            return False
        if obs.roi_bbox.image_width != roi.width or obs.roi_bbox.image_height != roi.height:
            return False
        if (
            obs.full_frame_bbox.image_width != frame.width
            or obs.full_frame_bbox.image_height != frame.height
        ):
            return False
        expected = apply_transform(Box.from_bbox(obs.roi_bbox), inverse)
        actual = obs.full_frame_bbox
        if not (
            math.isclose(expected.x_min, actual.x_min, rel_tol=0.0, abs_tol=_COORD_TOLERANCE)
            and math.isclose(expected.y_min, actual.y_min, rel_tol=0.0, abs_tol=_COORD_TOLERANCE)
            and math.isclose(expected.x_max, actual.x_max, rel_tol=0.0, abs_tol=_COORD_TOLERANCE)
            and math.isclose(expected.y_max, actual.y_max, rel_tol=0.0, abs_tol=_COORD_TOLERANCE)
        ):
            return False
    return True


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
        temporal_config: TemporalAggregationConfig | None = None,
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
        self._temporal = (
            TemporalAggregator(temporal_config) if temporal_config is not None else None
        )
        self._sequence = count(1)

    def inspect_image(
        self, source: FolderSource, path: Path, writer: OutputWriter
    ) -> InspectionRecord:
        """Run one inspection and persist its evidence, returning the record."""
        try:
            image = source.read(path)
        except ImageReadError as exc:
            log.warning("image read failed for %s: %s", path, exc)
            image = None
        return self._inspect_impl(image=image, image_read_error=image is None, writer=writer)

    def inspect_frame(
        self, frame: CapturedFrame, writer: OutputWriter | None = None
    ) -> InspectionRecord:
        """Inspect one captured camera frame; each frame is one inspection (ADR-013).

        ``writer`` is optional: a dev/test call can analyze without persisting
        evidence (ADR-014).
        """
        return self._inspect_impl(image=frame.image, image_read_error=False, writer=writer)

    def frame_observations(self, frame: CapturedFrame) -> FrameObservation:
        """Run one frame's detection pass for temporal window aggregation.

        Returns a frame observation carrying per-component detections, gate
        validity, and the images needed to persist a representative key frame.
        A frame whose product-detection quality gate reports unusable is marked
        unusable and cannot contribute evidence or valid opportunities
        (PR-015 F4); its quality reasons are preserved for diagnostics.
        """
        frame_id = uuid4()
        outcome = self._detect_frame(frame.image, frame_id)
        product_detection = outcome.product_detection
        quality_usable = (
            product_detection.quality.usable if product_detection is not None else False
        )
        if product_detection is not None and not product_detection.quality.usable:
            outcome.reasons.extend(product_detection.quality.reason_codes)
        return FrameObservation(
            frame_id=frame_id,
            sequence=frame.sequence,
            captured_at=frame.wall_clock_utc,
            quality_usable=quality_usable,
            product_detected=outcome.gates["product_detected"],
            roi_valid=outcome.gates["roi_valid"],
            inference_valid=outcome.gates["component_inference_valid"],
            product_detection=outcome.product_detection,
            roi_result=outcome.roi_result,
            observations=outcome.observations,
            reasons=outcome.reasons,
            product_latency_ms=outcome.product_latency_ms,
            component_latency_ms=outcome.component_latency_ms,
            image=frame.image,
            roi_image=outcome.roi_image,
            product_identity=frame.product_identity,
            # ProductDetector reports this as a failed selection with no
            # ProductDetection, so preserve the detector's explicit ambiguity
            # signal for ProductWindowManager instead of treating it as a
            # diagnostic-only rejected frame (PR-015 F1).
            multi_product=frame.multi_product or rc.MULTIPLE_PRODUCTS in outcome.reasons,
        )

    def inspect_window(
        self, window: ProductWindow, writer: OutputWriter | None = None
    ) -> InspectionRecord:
        """Finalize one product window into a single inspection record.

        The per-component temporal aggregator resolves frame evidence, the rule
        engine evaluates the aggregated evidence exactly once, and the record
        stores a canonical SHA-256 identity for the exact temporal policy
        (design 10, ADR-010).
        """
        if self._temporal is None:
            raise AssertionError("temporal aggregation is not configured for this pipeline")
        evidence_map = self._temporal.aggregate(
            window.frame_evidence_list(), tuple(self._rule.required_components)
        )
        # Window-integrity violations (interruption, identity mixing, missing
        # identity) are the only frame-independent reasons that force NG.
        # Per-frame rejection reasons stay diagnostic and cannot veto a window
        # whose aggregated evidence satisfies every rule (PR-015 F5).
        integrity_reasons = list(window.integrity_reason_codes)
        total_frames = len(window.frames)
        usable_frames = sum(
            1 for frame in window.frames if frame.quality_usable and frame.inference_valid
        )
        frame_reasons: list[str] = []
        for frame in window.frames:
            frame_reasons.extend(frame.reasons)
        reason_counts = _reason_counts(frame_reasons)
        gates = {
            "product_detected": any(frame.product_detected for frame in window.frames),
            "roi_valid": any(frame.roi_valid for frame in window.frames),
            "component_inference_valid": any(frame.inference_valid for frame in window.frames),
            "minimum_valid_frames_met": usable_frames >= self._temporal.config.minimum_valid_frames,
        }
        context = RuleContext(
            product_identity_verified=not self._rule.barcode_required,
            component_model_version=manifest_model_version(self._component_manifest),
            gates=gates,
            components=evidence_map,
        )
        decided = None
        try:
            decided = self._rule_engine.evaluate(context, self._rule)
        except RuleEvaluationError as exc:
            integrity_reasons.append(rc.RULE_EVALUATION_ERROR)
            log.error("rule evaluation failed for window %s: %s", window.inspection_id, exc)

        if decided is None:
            missing = sorted(set(self._rule.required_components))
            low: list[str] = []
            final_reasons = sorted(set(integrity_reasons))
            internal = InternalDecision.NG
        else:
            missing = decided.missing_components
            low = decided.low_confidence_components
            final_reasons = sorted(set(decided.reason_codes) | set(integrity_reasons))
            internal = InternalDecision.NG if final_reasons else InternalDecision.OK
        decision = InspectionDecision(
            internal_decision=internal,
            business_result=BusinessResult.NG
            if internal is not InternalDecision.OK
            else BusinessResult.OK,
            missing_components=missing,
            low_confidence_components=low,
            reason_codes=final_reasons,
            decided_at=datetime.now(UTC),
        )

        representative = _representative_frame(window.frames)
        product_detection = representative.product_detection if representative else None
        roi_result = representative.roi_result if representative else None
        completed_at = datetime.now(UTC)
        record = InspectionRecord(
            inspection_id=window.inspection_id,
            device_id=self._device_id,
            device_sequence=next(self._sequence),
            lifecycle_status=InspectionLifecycle.COMPLETED,
            started_at=window.started_at,
            completed_at=completed_at,
            barcode_result=BarcodeResult(status="NOT_REQUIRED"),
            product_resolution=ProductResolution(
                status="RESOLVED", source="CONFIGURED_DEFAULT", product_code=self._rule.product_type
            ),
            product_detection=product_detection,
            roi_result=roi_result,
            frame_quality_summary=FrameQualitySummary(
                total_frame_count=total_frames,
                usable_frame_count=usable_frames,
                rejected_frame_count=total_frames - usable_frames,
                reasons=reason_counts,
            ),
            application_version=self._config.application_version,
            product_model_version_id=self._product_manifest.model_version_id,
            product_model_checksum_sha256=_artifact_checksum(self._product_manifest),
            component_model_version_id=self._component_manifest.model_version_id,
            component_model_checksum_sha256=_artifact_checksum(self._component_manifest),
            rule_version_id=rule_version_id(self._rule),
            aggregation_policy_version=temporal_policy_version(self._temporal.config),
            evidence=[evidence_map[key] for key in self._rule.required_components],
            decision=decision,
            synchronization_status="LOCAL_ONLY",
            processing_ms=max(0, int((completed_at - window.started_at).total_seconds() * 1000)),
            inference_metadata=self._window_inference_metadata(window.frames),
        )

        annotated = None
        if representative is not None and representative.image is not None:
            product_box = product_detection.bbox if product_detection is not None else None
            annotated = annotate_full_frame(
                representative.image,
                product_box,
                [(obs.component_code, obs.full_frame_bbox) for obs in representative.observations],
            )
        if writer is None:
            return record
        return writer.save(
            record,
            full_frame=representative.image if representative else None,
            roi_image=representative.roi_image if representative else None,
            annotated=annotated,
        )

    def _detect_frame(self, frame: Image.Image, frame_id: UUID) -> _DetectionOutcome:
        """Run product/ROI/component detection for one frame with provenance checks."""
        outcome = _DetectionOutcome()
        product_started = time.monotonic()
        try:
            result = self._product_detector.detect(frame, frame_id)
        except DetectionError as exc:
            outcome.reasons.append(exc.reason_code)
            log.warning("product detection failed: %s", exc)
            return outcome
        outcome.product_latency_ms = (time.monotonic() - product_started) * 1000
        if result.selected is None:
            outcome.reasons.append(result.reason_code or rc.NO_PRODUCT)
            return outcome
        if not _validate_product_provenance(
            result.selected, frame_id, self._product_manifest, frame
        ):
            outcome.reasons.append(rc.INFERENCE_ERROR)
            log.warning("product detection provenance mismatch for frame %s", frame_id)
            return outcome
        outcome.product_detection = result.selected
        outcome.gates["product_detected"] = True
        try:
            generated = self._roi_engine.generate(frame, frame_id, result.selected.bbox)
        except ROIGenerationError as exc:
            outcome.reasons.append(rc.ROI_INVALID)
            log.warning("ROI generation failed: %s", exc)
            return outcome
        outcome.roi_image = generated.roi_image
        outcome.roi_result = generated.result
        outcome.gates["roi_valid"] = True
        component_started = time.monotonic()
        try:
            observations = self._component_detector.detect(
                generated.roi_image,
                frame_id,
                tuple(self._rule.required_components),
                generated.result.transform_full_to_roi,
                (frame.width, frame.height),
            )
            outcome.component_latency_ms = (time.monotonic() - component_started) * 1000
            if not _validate_component_provenance(
                observations,
                frame_id,
                self._component_manifest,
                generated.roi_image,
                frame,
                generated.result.transform_full_to_roi,
            ):
                observations = []
                outcome.reasons.append(rc.INFERENCE_ERROR)
                log.warning("component detection provenance mismatch for frame %s", frame_id)
            else:
                outcome.observations = observations
                outcome.gates["component_inference_valid"] = True
        except DetectionError as exc:
            outcome.reasons.append(exc.reason_code)
            log.warning("component detection failed: %s", exc)
        return outcome

    def _window_inference_metadata(
        self, frames: list[FrameObservation]
    ) -> InferenceMetadata | None:
        """Snapshot inference traceability from the window's last valid frame."""
        for frame in reversed(frames):
            if frame.component_latency_ms is not None or frame.product_latency_ms is not None:
                return self._collect_inference_metadata(
                    frame.product_latency_ms, frame.component_latency_ms, frame.captured_at
                )
        return None

    def _inspect_impl(
        self,
        *,
        image: Image.Image | None,
        image_read_error: bool,
        writer: OutputWriter | None,
    ) -> InspectionRecord:
        inspection_id = uuid4()
        frame_id = uuid4()
        started_at = datetime.now(UTC)
        started = time.monotonic()

        extra_reasons: list[str] = []
        frame = image
        if image_read_error:
            extra_reasons.append(rc.IMAGE_READ_ERROR)
        outcome = (
            self._detect_frame(frame, frame_id) if frame is not None else _DetectionOutcome.empty()
        )
        product_detection = outcome.product_detection
        roi_result = outcome.roi_result
        roi_image = outcome.roi_image
        observations = outcome.observations
        gates = outcome.gates
        product_latency_ms = outcome.product_latency_ms
        component_latency_ms = outcome.component_latency_ms
        extra_reasons.extend(outcome.reasons)

        evidence_map = self._build_evidence(observations, gates, frame is not None, frame_id)
        context = RuleContext(
            product_identity_verified=not self._rule.barcode_required,
            component_model_version=manifest_model_version(self._component_manifest),
            gates=gates,
            components=evidence_map,
        )
        decided = None
        try:
            decided = self._rule_engine.evaluate(context, self._rule)
        except RuleEvaluationError as exc:
            extra_reasons.append(rc.RULE_EVALUATION_ERROR)
            log.error("rule evaluation failed for inspection %s: %s", inspection_id, exc)

        if decided is None:
            missing = sorted(set(self._rule.required_components))
            low: list[str] = []
            final_reasons = sorted(set(extra_reasons))
            internal = InternalDecision.NG
        else:
            missing = decided.missing_components
            low = decided.low_confidence_components
            final_reasons = sorted(set(decided.reason_codes) | set(extra_reasons))
            internal = InternalDecision.NG if final_reasons else InternalDecision.OK
        decision = InspectionDecision(
            internal_decision=internal,
            business_result=BusinessResult.NG
            if internal is not InternalDecision.OK
            else BusinessResult.OK,
            missing_components=missing,
            low_confidence_components=low,
            reason_codes=final_reasons,
            decided_at=datetime.now(UTC),
        )

        inference_metadata = self._collect_inference_metadata(
            product_latency_ms if frame is not None else None,
            component_latency_ms if gates["roi_valid"] else None,
            started_at,
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
                    [ReasonCount(reason_code=rc.IMAGE_READ_ERROR, count=1)] if frame is None else []
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
            inference_metadata=inference_metadata,
        )

        annotated = None
        if frame is not None:
            product_box = product_detection.bbox if product_detection is not None else None
            annotated = annotate_full_frame(
                frame,
                product_box,
                [(obs.component_code, obs.full_frame_bbox) for obs in observations],
            )
        if writer is None:
            return record
        return writer.save(record, full_frame=frame, roi_image=roi_image, annotated=annotated)

    def _collect_inference_metadata(
        self,
        product_latency_ms: float | None,
        component_latency_ms: float | None,
        inspected_at: datetime,
    ) -> InferenceMetadata | None:
        """Snapshot typed per-stage inference traceability (contract 03, P2).

        Records the model name/version, input size, latency, timestamp, and
        effective parameters for each detection stage that ran.
        """
        stages: dict[str, object] = {}
        if product_latency_ms is not None:
            product = getattr(self._product_detector, "effective_settings", None)
            if product is not None:
                stages["product_detection"] = InferenceStageMetadata(
                    model_name=str(self._product_manifest.model_id),
                    model_version=manifest_model_version(self._product_manifest),
                    input_size=list(product["imgsz"]),
                    latency_ms=product_latency_ms,
                    timestamp=inspected_at,
                    settings=InferenceSettings(**dict(product)),
                )
        if component_latency_ms is not None:
            component = getattr(self._component_detector, "effective_settings", None)
            if component is not None:
                stages["component_detection"] = InferenceStageMetadata(
                    model_name=str(self._component_manifest.model_id),
                    model_version=manifest_model_version(self._component_manifest),
                    input_size=list(component["imgsz"]),
                    latency_ms=component_latency_ms,
                    timestamp=inspected_at,
                    settings=InferenceSettings(**dict(component)),
                )
        if not stages:
            return None
        return InferenceMetadata.model_validate(stages)

    def _build_evidence(
        self,
        observations: list[ComponentDetection],
        gates: dict[str, bool],
        frame_readable: bool,
        frame_id: UUID,
    ) -> dict[str, AggregatedComponentEvidence]:
        evidence_map: dict[str, AggregatedComponentEvidence] = {}
        roi_valid = gates.get("roi_valid", False)
        inference_valid = gates.get("component_inference_valid", False)
        for key in self._rule.required_components:
            hits = [obs for obs in observations if obs.component_code == key]
            if roi_valid and inference_valid and hits:
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
            elif roi_valid and inference_valid:
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
