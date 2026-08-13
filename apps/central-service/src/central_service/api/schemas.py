"""Typed response schemas for the central API (contract 05)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from assemblyvision_domain.models import APIModel
from pydantic import Field, field_validator, model_validator


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

    @field_validator("component_code")
    @classmethod
    def _normalize_component_code(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("component_code must be a non-empty component identifier")
        return value


class ReviewSubmit(APIModel):
    """One review append; the machine outcome is never overwritten (C4)."""

    disposition: Literal[
        "CONFIRMED_NG", "CONFIRMED_OK", "CORRECTED_NG", "INCONCLUSIVE", "REINSPECT"
    ]
    reason: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    component_corrections: list[ComponentCorrectionIn] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def _require_reason_when_inconclusive(self) -> ReviewSubmit:
        if self.disposition == "INCONCLUSIVE" and not (self.reason and self.reason.strip()):
            raise ValueError("an inconclusive review requires a reason")
        return self

    @model_validator(mode="after")
    def _reject_duplicate_component_corrections(self) -> ReviewSubmit:
        codes = [correction.component_code for correction in self.component_corrections]
        if len(codes) != len(set(codes)):
            raise ValueError("each component may be corrected at most once")
        return self


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


# ---------------------------------------------------------------------------
# C5 metadata governance contracts. Published central versions are immutable
# and registered metadata only; they never imply a device downloaded,
# validated, or activated the content. Request bodies inherit ``extra="forbid"``
# from the APIModel base (contract 15.1).
# ---------------------------------------------------------------------------


class ComponentCreate(APIModel):
    """Create a component in the organization vocabulary (C5)."""

    component_code: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)


class ComponentOut(APIModel):
    id: int
    organization_id: int
    component_code: str
    display_name: str
    created_at: datetime


class ComponentPage(APIModel):
    items: list[ComponentOut]
    next_cursor: str | None = None


class ProductCreate(APIModel):
    """Create a stable product identity (C5)."""

    product_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)


class ProductOut(APIModel):
    """A stable product identity (C5)."""

    id: int
    organization_id: int
    product_code: str
    name: str
    created_at: datetime


class ProductSummaryOut(APIModel):
    """A stable product with its latest governed version (C5)."""

    id: int
    organization_id: int
    product_code: str
    name: str
    created_at: datetime
    version_count: int
    latest_version_id: str | None
    latest_version_number: int | None
    latest_version_status: str | None


class ProductPage(APIModel):
    items: list[ProductSummaryOut]
    next_cursor: str | None = None


class ProductVersionComponentIn(APIModel):
    component_code: str = Field(min_length=1, max_length=64)
    expected_count: int = Field(ge=1, le=64)


class ProductVersionCreate(APIModel):
    """Draft a new immutable product version (C5).

    Barcode mappings are exact values only (ADR-015); a version may declare
    none, but every value must be 1..256 characters.
    """

    barcodes: list[str] = Field(default_factory=list, max_length=100)
    components: list[ProductVersionComponentIn] = Field(min_length=1, max_length=64)


class ProductVersionComponentOut(APIModel):
    component_code: str
    expected_count: int


class ProductVersionOut(APIModel):
    id: int
    organization_id: int
    product_id: int
    product_code: str
    version_id: str
    version: int
    status: str
    barcodes: list[str]
    components: list[ProductVersionComponentOut]
    published_at: datetime | None
    published_by: str | None
    publish_reason: str | None
    created_at: datetime


class ProductDetailOut(APIModel):
    """A stable product with all its immutable versions (C5)."""

    id: int
    organization_id: int
    product_code: str
    name: str
    created_at: datetime
    versions: list[ProductVersionOut]


class RuleCreate(APIModel):
    """Create a stable rule identity (C5)."""

    rule_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)


class RuleOut(APIModel):
    """A stable rule identity (C5)."""

    id: int
    organization_id: int
    rule_code: str
    name: str
    created_at: datetime


class RuleSummaryOut(APIModel):
    """A stable rule with its latest governed version (C5)."""

    id: int
    organization_id: int
    rule_code: str
    name: str
    created_at: datetime
    version_count: int
    latest_version_id: str | None
    latest_version_number: int | None
    latest_version_status: str | None


class RulePage(APIModel):
    items: list[RuleSummaryOut]
    next_cursor: str | None = None


class RulePolicyIn(APIModel):
    """Per-component confidence/temporal policy (design 14 ComponentPolicy)."""

    component_code: str = Field(min_length=1, max_length=64)
    high_confidence: float = Field(gt=0, le=1)
    medium_confidence: float = Field(gt=0, le=1)
    minimum_medium_detections: int = Field(ge=1, le=64)
    require_adjacent_frames: bool = False
    expected_count: int = Field(ge=1, le=64)


class RuleVersionCreate(APIModel):
    """Draft a new immutable rule version (C5, design 14 RuleConfiguration)."""

    product_version_id: str
    barcode_required: bool = False
    minimum_usable_frames: int = Field(ge=1, le=1000)
    mandatory_gates: dict[str, bool] = Field(default_factory=dict, max_length=16)
    component_policies: list[RulePolicyIn] = Field(min_length=1, max_length=64)
    compatible_component_model_version_ids: list[str] = Field(default_factory=list, max_length=32)


class RulePolicyOut(APIModel):
    component_code: str
    high_confidence: float
    medium_confidence: float
    minimum_medium_detections: int
    require_adjacent_frames: bool
    expected_count: int


class RuleVersionOut(APIModel):
    id: int
    organization_id: int
    rule_id: int
    rule_code: str
    product_version_id: str
    version_id: str
    version: int
    status: str
    barcode_required: bool
    minimum_usable_frames: int
    uncertain_maps_to_ng: bool
    mandatory_gates: dict[str, bool]
    component_policies: list[RulePolicyOut]
    compatible_model_version_ids: list[str]
    content_sha256: str
    published_at: datetime | None
    published_by: str | None
    publish_reason: str | None
    created_at: datetime


class RuleDetailOut(APIModel):
    """A stable rule with all its immutable versions (C5)."""

    id: int
    organization_id: int
    rule_code: str
    name: str
    created_at: datetime
    versions: list[RuleVersionOut]


class ModelCreate(APIModel):
    """Create a stable model package identity (C5)."""

    model_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    task: Literal["PRODUCT_DETECTION", "COMPONENT_DETECTION"]


class ModelPackageOut(APIModel):
    """A stable model package identity (C5)."""

    id: int
    organization_id: int
    model_code: str
    name: str
    task: str
    created_at: datetime


class ModelSummaryOut(APIModel):
    """A stable model package with its latest governed version (C5)."""

    id: int
    organization_id: int
    model_code: str
    name: str
    task: str
    created_at: datetime
    version_count: int
    latest_version_id: str | None
    latest_version_number: int | None
    latest_version_status: str | None


class ModelPage(APIModel):
    items: list[ModelSummaryOut]
    next_cursor: str | None = None


class ArtifactIn(APIModel):
    name: str = Field(min_length=1, max_length=128)
    uri: str = Field(min_length=1, max_length=512)
    sha256: str
    size_bytes: int = Field(ge=0)


class DatasetIn(APIModel):
    dataset_version: str = Field(min_length=1, max_length=64)
    purpose: Literal["TRAIN", "VALIDATION", "TEST", "ACCEPTANCE"] = "TRAIN"
    manifest_uri: str = Field(min_length=1, max_length=512)


class MetricIn(APIModel):
    name: str = Field(min_length=1, max_length=64)
    value: float
    scope: str = Field(min_length=1, max_length=64)


class ModelManifestIn(APIModel):
    """Declarative model manifest draft (C5, design 14 ModelManifest).

    Artifact checksums are normalized to bare lowercase 64-hex; the central
    server records declarations only and never verifies artifact bytes.
    """

    task: Literal["PRODUCT_DETECTION", "COMPONENT_DETECTION"]
    semantic_version: str = Field(min_length=1, max_length=32)
    edge_version_label: str = Field(min_length=1, max_length=64)
    runtime: str = Field(min_length=1, max_length=64)
    input_width: int = Field(ge=1, le=8192)
    input_height: int = Field(ge=1, le=8192)
    class_names: list[str] = Field(min_length=1, max_length=256)
    artifacts: list[ArtifactIn] = Field(min_length=1, max_length=32)
    datasets: list[DatasetIn] = Field(default_factory=list, max_length=32)
    split_strategy: str = Field(min_length=1, max_length=64)
    source_revision: str = Field(min_length=1, max_length=128)
    training_config_revision: str = Field(min_length=1, max_length=128)
    metrics: list[MetricIn] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class ArtifactOut(APIModel):
    name: str
    uri: str
    sha256: str
    size_bytes: int


class DatasetOut(APIModel):
    dataset_version: str
    purpose: str
    manifest_uri: str


class MetricOut(APIModel):
    name: str
    value: float
    scope: str


class ModelVersionOut(APIModel):
    id: int
    organization_id: int
    model_package_id: int
    model_code: str
    task: str
    version_id: str
    version: int
    status: str
    semantic_version: str
    edge_version_label: str
    runtime: str
    input_width: int
    input_height: int
    class_names: list[str]
    artifacts: list[ArtifactOut]
    datasets: list[DatasetOut]
    split_strategy: str
    source_revision: str
    training_config_revision: str
    metrics: list[MetricOut]
    limitations: list[str]
    manifest_sha256: str
    published_at: datetime | None
    published_by: str | None
    publish_reason: str | None
    created_at: datetime


class ModelDetailOut(APIModel):
    """A stable model package with all its immutable versions (C5)."""

    id: int
    organization_id: int
    model_code: str
    name: str
    task: str
    created_at: datetime
    versions: list[ModelVersionOut]


class PublishRequest(APIModel):
    """Required actor context for an immutable publish (C5)."""

    reason: str = Field(min_length=1, max_length=512)


class DesiredConfigurationIn(APIModel):
    """Desired bundle for one device (M1, C5).

    The record expresses intent only: packages are installed manually in M1
    and assignment is never proof of download, validation, or activation.
    """

    product_version_id: str
    product_model_version_id: str
    component_model_version_id: str
    rule_version_id: str
    reason: str = Field(min_length=1, max_length=512)


class DesiredConfigurationOut(APIModel):
    id: int
    organization_id: int
    device_row_id: int
    device_id: str
    device_name: str
    revision: int
    product_version_id: str
    product_model_version_id: str
    component_model_version_id: str
    rule_version_id: str
    reason: str
    assigned_by: str
    assigned_at: datetime
    created_at: datetime


class DesiredConfigurationPage(APIModel):
    items: list[DesiredConfigurationOut]
    next_cursor: str | None = None
