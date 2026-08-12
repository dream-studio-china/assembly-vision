"""Typed response schemas for the central API (contract 05)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from assemblyvision_domain.models import APIModel
from pydantic import Field


class HealthLive(APIModel):
    """Liveness response; never blocks on dependencies."""

    status: Literal["ok"]


class Problem(APIModel):
    """RFC 7807 error body (contract 05 section 6).

    ``request_id`` correlates the response with the request log; ``errors``
    carries bounded per-field validation details. Credentials, object keys,
    internal paths, SQL, and stack traces are never included.
    """

    type: str
    title: str
    status: int
    detail: str
    code: str
    request_id: str
    errors: list[dict[str, str]]


class ReadinessReport(APIModel):
    """Readiness response naming each checked dependency.

    ``checks`` maps dependency names to ``"ok"`` only; failure details are
    returned through the RFC 7807 problem body of the 503 response.
    """

    status: Literal["ok"]
    checks: dict[str, str]


class AdminMe(APIModel):
    """The authenticated pilot administrator (``GET /api/v1/auth/me``)."""

    administrator_id: int
    organization_id: int
    username: str


class SiteOut(APIModel):
    """A production site within the administrator's organization."""

    id: int
    organization_id: int
    name: str
    created_at: datetime


class LineOut(APIModel):
    """A production line within the administrator's organization."""

    id: int
    site_id: int
    organization_id: int
    name: str
    created_at: datetime


class DeviceOut(APIModel):
    """A registered edge device; credentials are never exposed."""

    id: int
    organization_id: int
    site_id: int
    production_line_id: int
    device_id: str
    name: str
    status: str
    created_at: datetime


class UploadReceiptOut(APIModel):
    """Verified central receipt for one accepted edge upload (task C1 5.3).

    Every field is echoed from the request so the edge scheduler can validate
    the receipt against the payload it actually sent; a MEDIA receipt always
    carries a non-empty ``central_object_id`` (C2b), which is null for
    INSPECTION receipts.
    """

    idempotency_key: str
    object_id: str
    kind: Literal["INSPECTION", "MEDIA"]
    checksum_sha256: str | None
    size_bytes: int
    central_object_id: str | None = None


class InspectionSummaryOut(APIModel):
    """One inspection row for the history list (C3)."""

    inspection_id: str
    device_id: str
    site_id: int
    line_id: int
    device_sequence: int
    started_at: datetime
    completed_at: datetime
    received_at: datetime
    upload_delay_ms: int
    barcode_value: str | None
    product_code: str | None
    internal_decision: str
    business_result: str
    rule_version_id: str


class ComponentEvidenceOut(APIModel):
    """Per-component aggregated evidence (C3 detail)."""

    component_code: str
    state: str
    best_confidence: float | None
    detection_count: int
    usable_frame_count: int
    policy_reason_codes: list[str]


class MediaItemOut(APIModel):
    """One media binding with a short-lived authorized URL (C3)."""

    source_media_id: str
    kind: str
    mime_type: str
    size_bytes: int
    lifecycle: str
    url: str | None = None


class InspectionDetailOut(APIModel):
    """Full inspection detail with evidence and media (C3)."""

    inspection_id: str
    device_id: str
    site_id: int
    line_id: int
    device_sequence: int
    lifecycle_status: str
    started_at: datetime
    completed_at: datetime
    received_at: datetime
    upload_delay_ms: int
    barcode_status: str
    barcode_value: str | None
    product_resolution_status: str
    product_code: str | None
    internal_decision: str
    business_result: str
    reason_codes: list[str]
    missing_components: list[str]
    low_confidence_components: list[str]
    application_version: str
    product_model_version_id: str
    product_model_checksum_sha256: str
    component_model_version_id: str
    component_model_checksum_sha256: str
    rule_version_id: str
    aggregation_policy_version: str
    processing_ms: int
    inference_metadata: dict[str, object] | None = None
    components: list[ComponentEvidenceOut]
    media: list[MediaItemOut]
    # Verified central receipt for the INSPECTION upload (task C1 5.3).
    receipt_status: str | None = None
    receipt_created_at: datetime | None = None
    # Latest appended review, if any (C4); the machine outcome is never changed.
    latest_review: ReviewOut | None = None


class InspectionPage(APIModel):
    """Keyset-paginated inspection history (C3)."""

    items: list[InspectionSummaryOut]
    next_cursor: str | None = None


class DashboardSummaryOut(APIModel):
    """Overview counts for a scope/period; empty data stays empty (C3)."""

    inspection_count: int
    ok_count: int
    ng_count: int
    uncertain_count: int
    avg_upload_delay_ms: float | None = None


class TimeseriesPointOut(APIModel):
    """One daily bucket of outcome counts (C3 dashboard)."""

    bucket: str
    ok_count: int
    ng_count: int
    uncertain_count: int


class DashboardTimeseriesOut(APIModel):
    """Daily outcome counts for a scope/period (C3 dashboard)."""

    points: list[TimeseriesPointOut]


class DeviceStatusOut(APIModel):
    """One device's central last-seen and inspection volume (C3 overview)."""

    device_id: str
    name: str
    last_seen_at: datetime | None
    inspection_count: int


class ComponentCorrectionIn(APIModel):
    """Per-component ground truth recorded by a reviewer (C4, design 24)."""

    component_code: str = Field(min_length=1, max_length=64)
    corrected_state: Literal["PRESENT", "MISSING", "UNCERTAIN"]
    note: str | None = Field(default=None, max_length=500)


class ReviewSubmit(APIModel):
    """One review append; the machine outcome is never overwritten (C4)."""

    disposition: Literal[
        "CONFIRMED_NG", "CONFIRMED_OK", "CORRECTED_NG", "INCONCLUSIVE", "REINSPECT"
    ]
    reason: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    component_corrections: list[ComponentCorrectionIn] = Field(default_factory=list, max_length=64)


class ReviewOut(APIModel):
    """One appended central review record (C4)."""

    inspection_id: str
    revision: int
    disposition: str
    reason: str | None
    note: str | None
    reviewer: str
    component_corrections: list[dict[str, object]]
    original_business_result: str
    original_internal_decision: str
    original_reason_codes: list[str]
    created_at: datetime


class ReviewQueueItem(APIModel):
    """One NG/uncertain inspection awaiting review (C4 routing policy)."""

    inspection_id: str
    device_id: str
    completed_at: datetime
    barcode_value: str | None
    product_code: str | None
    business_result: str
    internal_decision: str
    reason_codes: list[str]


class ReviewQueuePage(APIModel):
    """Keyset-paginated review queue (C4)."""

    items: list[ReviewQueueItem]
    next_cursor: str | None = None
