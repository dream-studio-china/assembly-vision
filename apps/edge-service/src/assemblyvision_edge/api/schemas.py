"""Typed Pydantic response schemas for the edge API (design 14.4.1).

These models give every edge endpoint a named OpenAPI schema instead of an
arbitrary ``dict[str, object]`` response (F9, contract 02). Canonical domain
records (``InspectionRecord``, ``MediaMetadata``, ``UploadTask``) live in the
shared domain package and are reused directly.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from assemblyvision_domain.models import (
    BusinessResult,
    ComponentCorrectionState,
    InternalDecision,
    ReviewDisposition,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Problem(BaseModel):
    """RFC 7807 problem response (contract 05 section 6)."""

    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int
    detail: str
    code: str
    request_id: str | None = None
    errors: list[dict[str, str]] = Field(default_factory=list)


class RetryUploadRequest(BaseModel):
    """Operator confirmation for a manual upload retry (design 15.3.3).

    ``reason`` is optional so legacy callers that retry without a body keep
    working; the dashboard always sends a non-empty operator reason, which is
    stripped of surrounding whitespace before it reaches the repository audit
    log.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=200)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class ComponentCorrectionRequest(BaseModel):
    """Per-component ground truth submitted with a review (design 24.7)."""

    model_config = ConfigDict(extra="forbid")

    component_code: str = Field(min_length=1, max_length=64)
    corrected_state: ComponentCorrectionState
    note: str | None = Field(default=None, max_length=500)


class SubmitReviewRequest(BaseModel):
    """Human disposition for one inspection (design 24.3/24.6).

    ``reviewer`` identifies the reviewer; ``reason`` is mandatory for
    ``INCONCLUSIVE`` and stripped of surrounding whitespace otherwise. A review
    never rewrites the machine decision: the record is appended and references
    any superseded review.
    """

    model_config = ConfigDict(extra="forbid")

    disposition: ReviewDisposition
    reason: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    reviewer: str = Field(min_length=1, max_length=128)
    supersedes_review_id: UUID | None = None
    component_corrections: list[ComponentCorrectionRequest] = Field(default_factory=list)

    @field_validator("reason", "note", "reviewer")
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("reviewer")
    @classmethod
    def _reviewer_required(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            raise ValueError("reviewer must be a non-empty name")
        return value

    @model_validator(mode="after")
    def _require_reason_when_inconclusive(self) -> SubmitReviewRequest:
        if self.disposition is ReviewDisposition.INCONCLUSIVE and not self.reason:
            raise ValueError("an inconclusive review requires a reason")
        return self


class ReviewQueueItem(BaseModel):
    """One inspection row of the review queue with its review state (24.4)."""

    model_config = ConfigDict(extra="forbid")

    inspection_id: UUID
    completed_at: str
    business_result: BusinessResult
    internal_decision: InternalDecision
    barcode: str | None = None
    reason_summary: list[str] = Field(default_factory=list)
    has_review: bool
    latest_disposition: ReviewDisposition | None = None


class HealthLive(BaseModel):
    status: str


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


class DeviceStatus(BaseModel):
    device_id: str
    observed_at: str
    operational_state: str
    inspection_ready: bool
    inspection_error_code: str | None = None
    sync_ready: bool
    camera_connected: bool
    model_loaded: bool
    central_connected: bool
    disk_free_bytes: int
    upload_pending_count: int
    # Upload queue observability (design 13.9, E1): persistent queue facts come
    # from the repository, attempt/success/failure liveness from the worker.
    upload_pending_bytes: int = 0
    upload_oldest_pending_at: str | None = None
    upload_attempts: int = 0
    upload_successes: int = 0
    upload_failures: int = 0
    upload_failure_rate: float = 0.0
    upload_last_attempt_at: str | None = None
    upload_last_success_at: str | None = None
    upload_last_error_code: str | None = None
    # Upload throughput observability (design 13.9, E3a): bytes actually sent
    # to the sink and the configured bandwidth ceiling (None = unthrottled).
    upload_bytes_sent: int = 0
    upload_bandwidth_mbps: float | None = None
    # Circuit-breaker liveness (design 13.5, E3b): CLOSED / OPEN / HALF_OPEN.
    upload_circuit_state: str = "CLOSED"
    upload_circuit_last_change_at: str | None = None
    # Storage pressure and cleanup observability (design 12.7, E2c): the
    # server is the single authority for thresholds and mode; the dashboard
    # renders these instead of duplicating a fixed warning threshold.
    storage_mode: str = "NORMAL"
    storage_free_bytes: int = 0
    storage_free_percent: float = 0.0
    storage_free_inodes: int = 0
    storage_inode_percent: float = 0.0
    storage_warning_free_percent: float = 0.0
    storage_critical_free_percent: float = 0.0
    storage_stop_free_percent: float = 0.0
    storage_observed_at: str | None = None
    storage_write_fault: bool = False
    cleanup_enabled: bool = False
    cleanup_eligible_count: int = 0
    cleanup_eligible_bytes: int = 0
    cleanup_deleting_count: int = 0
    cleanup_delete_error_count: int = 0
    cleanup_purged_count: int = 0
    cleanup_integrity_fault_count: int = 0
    cleanup_last_run_at: str | None = None
    cleanup_last_error_code: str | None = None
    integrity_scan_last_run_at: str | None = None
    integrity_scan_checked: int = 0
    integrity_scan_faults: int = 0
    integrity_scan_checksummed: int = 0
    integrity_scan_skipped: int = 0
    integrity_scan_skipped_reason: str | None = None
    integrity_verify_checksums: bool = False
    current_product_model_version_id: str | None = None
    current_component_model_version_id: str | None = None
    current_rule_version_id: str | None = None
    alerts: list[str] = Field(default_factory=list)


class CameraState(BaseModel):
    connected: bool
    source_width: int
    source_height: int
    fps: int | None = None
    last_frame_at: str | None = None
    error_code: str | None = None
    camera_serial: str | None = None
    camera_model: str | None = None
    firmware_version: str | None = None
    gentl_producer: str | None = None
    transport_parent: str | None = None
    pixel_format: str | None = None
    trigger_mode: str | None = None
    exposure_us: float | None = None
    gain_db: float | None = None
    packet_size: int | None = None


class InspectionRuntimeState(BaseModel):
    window_active: bool
    paused: bool
    faulted: bool
    current_inspection_id: str | None = None
    last_result: str | None = None
    paused_reason: str | None = None
    paused_by: str | None = None
    paused_at: str | None = None


class VideoFrameInspectResult(BaseModel):
    """One analyzed frame's decision summary (web dev test harness, ADR-014)."""

    index: int
    business_result: BusinessResult
    internal_decision: InternalDecision
    reason_codes: list[str] = Field(default_factory=list)


class VideoInspectResult(BaseModel):
    """Per-frame summary for an uploaded test video (ADR-014).

    ``truncated`` is true when a decode resource budget (frame count or wall
    clock) ended iteration early, so consumers do not mistake the summary for a
    complete analysis of the source video (F6).
    """

    instance_id: str
    analyzed_frames: int
    ok_count: int
    ng_count: int
    frames: list[VideoFrameInspectResult] = Field(default_factory=list)
    truncated: bool = False


class InspectionSummary(BaseModel):
    inspection_id: str
    completed_at: str
    business_result: str
    internal_decision: str
    barcode: str | None = None
    product_code: str | None = None
    sn: str | None = None
    reason_summary: list[str] = Field(default_factory=list)
    latency_ms: int
    upload_state: str
    model_rule_versions: dict[str, str | None] = Field(default_factory=dict)


class LogEvent(BaseModel):
    logged_at: str
    level: str
    component: str
    message: str
    trace_id: str | None = None


class ProductDetectionSnapshot(BaseModel):
    model_version: str
    confidence_threshold: float
    iou_threshold: float


class ComponentDetectionSnapshot(BaseModel):
    model_version: str
    iou_threshold: float
    components: dict[str, float] = Field(default_factory=dict)


class ROISnapshot(BaseModel):
    margin_x_ratio: float
    margin_y_ratio: float
    min_area_pixels: int
    min_expanded_area_retained: float
    normalize_perspective: bool


class RuleSnapshot(BaseModel):
    rule_id: str
    rule_version: int
    product_type: str
    required_components: list[str] = Field(default_factory=list)


class ManagedConfiguration(BaseModel):
    application_version: str | None = None
    product_detection: ProductDetectionSnapshot | None = None
    component_detection: ComponentDetectionSnapshot | None = None
    roi: ROISnapshot | None = None
    rule: RuleSnapshot | None = None


class EffectiveConfiguration(BaseModel):
    revision: str
    checksum_sha256: str
    managed: ManagedConfiguration = Field(default_factory=ManagedConfiguration)
    local_overrides: dict[str, object] = Field(default_factory=dict)


class TraceabilityAttempt(BaseModel):
    attempt: int
    inspection_id: str
    timestamp: str
    result: str
    reason: str
    operator: str


class TraceabilityView(BaseModel):
    sn: str
    final_status: str
    attempts: list[TraceabilityAttempt] = Field(default_factory=list)


class StatisticsSummary(BaseModel):
    total_inspections: int
    pass_count: int
    ng_count: int
    pass_rate: float


class InspectionImages(BaseModel):
    """Image slot URLs plus per-slot lifecycle state (F14).

    A PURGED slot carries no content URL so the UI renders an explicit purged
    state instead of a broken image; UNAVAILABLE covers missing or failed media.
    """

    inspection_id: str
    original: str
    detection: str
    annotated: str
    original_status: Literal["AVAILABLE", "PURGED", "UNAVAILABLE"] = "UNAVAILABLE"
    detection_status: Literal["AVAILABLE", "PURGED", "UNAVAILABLE"] = "UNAVAILABLE"
    annotated_status: Literal["AVAILABLE", "PURGED", "UNAVAILABLE"] = "UNAVAILABLE"
