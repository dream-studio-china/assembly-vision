"""Canonical domain and transport models.

This module ports the canonical Pydantic 2 models from the architecture
design (docs/design/14-data-model-and-database.md) down to the subset
required by the static-image MVP. Unknown fields are rejected so that a
schema change surfaces loudly instead of being ignored.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegativeInt = Annotated[int, Field(ge=0)]


class APIModel(BaseModel):
    """Base model for canonical domain objects."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class InternalDecision(StrEnum):
    """Internal inspection decision state."""

    OK = "OK"
    NG = "NG"
    UNCERTAIN = "UNCERTAIN"


class BusinessResult(StrEnum):
    """External business result. UNCERTAIN always maps to NG."""

    OK = "OK"
    NG = "NG"


class InspectionLifecycle(StrEnum):
    """Inspection window lifecycle state."""

    OPEN = "OPEN"
    EVALUATING = "EVALUATING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class MediaLifecycle(StrEnum):
    """Media object lifecycle state."""

    PENDING = "PENDING"
    AVAILABLE = "AVAILABLE"
    FAILED = "FAILED"
    PURGED = "PURGED"


class BoundingBox(APIModel):
    """Pixel-space bounding box with explicit image dimensions."""

    x_min: Annotated[float, Field(ge=0)]
    y_min: Annotated[float, Field(ge=0)]
    x_max: Annotated[float, Field(gt=0)]
    y_max: Annotated[float, Field(gt=0)]
    image_width: Annotated[int, Field(gt=0)]
    image_height: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def validate_bounds(self) -> BoundingBox:
        if not (self.x_min < self.x_max <= self.image_width):
            raise ValueError("x bounds must be ordered and inside the image")
        if not (self.y_min < self.y_max <= self.image_height):
            raise ValueError("y bounds must be ordered and inside the image")
        return self

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def area(self) -> float:
        return self.width * self.height


class FrameQuality(APIModel):
    """Deterministic frame quality assessment."""

    usable: bool
    blur_score: Annotated[float, Field(ge=0)]
    brightness_mean: Annotated[float, Field(ge=0, le=255)]
    saturation_fraction: Confidence
    occlusion_fraction: Confidence | None = None
    reason_codes: list[str] = Field(default_factory=list)


class ReasonCount(APIModel):
    """A single reason code with its occurrence count."""

    reason_code: str
    count: NonNegativeInt


class FrameQualitySummary(APIModel):
    """Frame quality summary for an inspection."""

    total_frame_count: NonNegativeInt
    usable_frame_count: NonNegativeInt
    rejected_frame_count: NonNegativeInt
    reasons: list[ReasonCount] = Field(default_factory=list)


class BarcodeResult(APIModel):
    """Barcode read result."""

    status: Literal["READ", "NOT_READ", "CONFLICT", "NOT_REQUIRED"]
    value: str | None = Field(default=None, max_length=256)
    symbology: str | None = Field(default=None, max_length=64)


class ProductResolution(APIModel):
    """Product type resolution result."""

    status: Literal["RESOLVED", "UNKNOWN", "CONFLICT"]
    source: Literal["BARCODE", "MANUAL", "CONFIGURED_DEFAULT", "NONE"]
    product_code: str | None = None
    product_version_id: UUID | None = None


class MediaMetadata(APIModel):
    """Media object metadata; bytes are never stored in the database."""

    media_id: UUID
    kind: Literal["KEY_FRAME", "ANNOTATED_FRAME", "PRODUCT_ROI", "NG_CLIP", "ROLLING_VIDEO"]
    lifecycle: MediaLifecycle
    relative_path: str
    mime_type: str
    size_bytes: NonNegativeInt
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProductDetection(APIModel):
    """Stage-one product detection on the full frame."""

    frame_id: UUID
    product_class: str
    confidence: Confidence
    bbox: BoundingBox
    model_version_id: UUID
    quality: FrameQuality


class ROIResult(APIModel):
    """Generated product ROI and full-frame/ROI coordinate transform."""

    frame_id: UUID
    product_bbox: BoundingBox
    roi_bbox: BoundingBox
    roi_width: Annotated[int, Field(gt=0)]
    roi_height: Annotated[int, Field(gt=0)]
    orientation_degrees: float | None = None
    transform_full_to_roi: tuple[float, float, float, float, float, float]
    media_id: UUID | None = None


class ComponentDetection(APIModel):
    """Stage-two component observation inside the product ROI."""

    frame_id: UUID
    component_code: str
    confidence: Confidence
    roi_bbox: BoundingBox
    full_frame_bbox: BoundingBox
    model_version_id: UUID


class AggregatedComponentEvidence(APIModel):
    """Per-component aggregated evidence. State is limited to the MVP subset.

    ``box_area_ratios`` and ``box_centers`` are per-detection spatial
    summaries in normalized ROI coordinates; each entry corresponds to one
    detection in ``detection_count`` order. They let the rule engine validate
    declared spatial constraints without depending on any detector package.
    """

    component_code: str
    state: Literal["PRESENT", "MISSING", "UNCERTAIN"]
    best_confidence: Confidence | None = None
    usable_frame_count: NonNegativeInt
    detection_count: NonNegativeInt
    adjacent_detection_run: NonNegativeInt = 0
    supporting_frame_ids: list[UUID] = Field(default_factory=list)
    policy_reason_codes: list[str] = Field(default_factory=list)
    box_area_ratios: list[float] = Field(default_factory=list)
    box_centers: list[tuple[float, float]] = Field(default_factory=list)


class InspectionDecision(APIModel):
    """Deterministic inspection decision produced by the rule engine."""

    internal_decision: InternalDecision
    business_result: BusinessResult
    missing_components: list[str] = Field(default_factory=list)
    low_confidence_components: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    decided_at: datetime


class InspectionRecord(APIModel):
    """Persisted product-level inspection result."""

    inspection_id: UUID
    device_id: UUID
    device_sequence: Annotated[int, Field(gt=0)]
    lifecycle_status: InspectionLifecycle
    started_at: datetime
    completed_at: datetime
    barcode_result: BarcodeResult
    product_resolution: ProductResolution
    product_detection: ProductDetection | None = None
    roi_result: ROIResult | None = None
    frame_quality_summary: FrameQualitySummary
    application_version: str
    product_model_version_id: UUID
    product_model_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_model_version_id: UUID
    component_model_checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_version_id: UUID
    aggregation_policy_version: str
    evidence: list[AggregatedComponentEvidence]
    media: list[MediaMetadata] = Field(default_factory=list)
    decision: InspectionDecision
    synchronization_status: Literal["LOCAL_ONLY", "QUEUED", "PARTIAL", "SYNCED", "FAILED"]
    processing_ms: NonNegativeInt


class Artifact(APIModel):
    """Model artifact reference."""

    name: str
    uri: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: NonNegativeInt


class DatasetReference(APIModel):
    """Dataset reference with purpose."""

    dataset_version: str
    purpose: Literal["TRAIN", "VALIDATION", "TEST", "ACCEPTANCE"]
    manifest_uri: str


class ModelMetric(APIModel):
    """Named model metric."""

    name: str
    value: float
    scope: str


class ModelManifest(APIModel):
    """Immutable model manifest."""

    model_version_id: UUID
    model_id: UUID
    semantic_version: str
    task: Literal["PRODUCT_DETECTION", "COMPONENT_DETECTION"]
    runtime: str
    input_width: Annotated[int, Field(gt=0)]
    input_height: Annotated[int, Field(gt=0)]
    class_names: list[str]
    artifacts: list[Artifact] = Field(default_factory=list)
    datasets: list[DatasetReference] = Field(default_factory=list)
    split_strategy: str
    source_revision: str
    training_config_revision: str
    metrics: list[ModelMetric] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    approved_by: str | None = None
    approved_at: datetime | None = None
    supersedes_model_version_id: UUID | None = None
    created_at: datetime
