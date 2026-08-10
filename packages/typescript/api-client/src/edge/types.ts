// Edge API contract types.
//
// Synchronized by hand from the canonical Pydantic domain models in
// packages/python/domain/src/assemblyvision_domain/models.py and the TS
// interfaces in docs/design/14-data-model-and-database.md (section 14.4).
// Replace with generated types once FastAPI + OpenAPI generation is in place.
//
// Conventions (contract 05): snake_case fields, ISO 8601 UTC timestamps,
// UUID strings, `application/problem+json` errors.

export type UUID = string;
export type ISODateTime = string;

export const INTERNAL_DECISIONS = ["OK", "NG", "UNCERTAIN"] as const;
export type InternalDecision = (typeof INTERNAL_DECISIONS)[number];

export const BUSINESS_RESULTS = ["OK", "NG"] as const;
export type BusinessResult = (typeof BUSINESS_RESULTS)[number];

export const INSPECTION_LIFECYCLES = ["OPEN", "EVALUATING", "COMPLETED", "ABORTED"] as const;
export type InspectionLifecycle = (typeof INSPECTION_LIFECYCLES)[number];

export const MEDIA_LIFECYCLES = ["PENDING", "AVAILABLE", "FAILED", "PURGED"] as const;
export type MediaLifecycle = (typeof MEDIA_LIFECYCLES)[number];

export const DEVICE_OPERATIONAL_STATES = [
  "INITIALIZING",
  "READY",
  "PAUSED",
  "FAULTED",
  "INSPECTING",
] as const;
export type DeviceOperationalState = (typeof DEVICE_OPERATIONAL_STATES)[number];

export const UPLOAD_TASK_STATES = [
  "PENDING",
  "IN_PROGRESS",
  "RETRY_WAIT",
  "SUCCEEDED",
  "PERMANENT_FAILURE",
  "CANCELLED",
] as const;
export type UploadTaskState = (typeof UPLOAD_TASK_STATES)[number];

export const SYNC_STATUSES = ["LOCAL_ONLY", "QUEUED", "PARTIAL", "SYNCED", "FAILED"] as const;
export type SynchronizationStatus = (typeof SYNC_STATUSES)[number];

export const MEDIA_KINDS = [
  "KEY_FRAME",
  "ANNOTATED_FRAME",
  "PRODUCT_ROI",
  "NG_CLIP",
  "ROLLING_VIDEO",
] as const;
export type MediaKind = (typeof MEDIA_KINDS)[number];

export type BoundingBox = {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  image_width: number;
  image_height: number;
};

export type FrameQuality = {
  usable: boolean;
  blur_score: number;
  brightness_mean: number;
  saturation_fraction: number;
  occlusion_fraction: number | null;
  reason_codes: string[];
};

export type ReasonCount = { reason_code: string; count: number };

export type FrameQualitySummary = {
  total_frame_count: number;
  usable_frame_count: number;
  rejected_frame_count: number;
  reasons: ReasonCount[];
};

export type BarcodeResult = {
  status: "READ" | "NOT_READ" | "CONFLICT" | "NOT_REQUIRED";
  value: string | null;
  symbology: string | null;
};

export type ProductResolution = {
  status: "RESOLVED" | "UNKNOWN" | "CONFLICT";
  source: "BARCODE" | "MANUAL" | "CONFIGURED_DEFAULT" | "NONE";
  product_code: string | null;
  product_version_id: UUID | null;
};

export type MediaMetadata = {
  media_id: UUID;
  kind: MediaKind;
  lifecycle: MediaLifecycle;
  relative_path: string;
  mime_type: string;
  size_bytes: number;
  checksum_sha256: string;
};

export type ProductDetection = {
  frame_id: UUID;
  product_class: string;
  confidence: number;
  bbox: BoundingBox;
  model_version_id: UUID;
  quality: FrameQuality;
};

export type ROIResult = {
  frame_id: UUID;
  product_bbox: BoundingBox;
  roi_bbox: BoundingBox;
  roi_width: number;
  roi_height: number;
  orientation_degrees: number | null;
  transform_full_to_roi: [number, number, number, number, number, number];
  media_id: UUID | null;
};

export type ComponentDetection = {
  frame_id: UUID;
  component_code: string;
  confidence: number;
  roi_bbox: BoundingBox;
  full_frame_bbox: BoundingBox;
  model_version_id: UUID;
};

export const EVIDENCE_STATES = ["PRESENT", "MISSING", "UNCERTAIN"] as const;
export type EvidenceState = (typeof EVIDENCE_STATES)[number];

export type AggregatedComponentEvidence = {
  component_code: string;
  state: EvidenceState;
  best_confidence: number | null;
  usable_frame_count: number;
  detection_count: number;
  adjacent_detection_run: number;
  supporting_frame_ids: UUID[];
  policy_reason_codes: string[];
  box_area_ratios: number[];
  box_centers: number[][];
};

export type InspectionDecision = {
  internal_decision: InternalDecision;
  business_result: BusinessResult;
  missing_components: string[];
  low_confidence_components: string[];
  reason_codes: string[];
  decided_at: ISODateTime;
};

export type InspectionRecord = {
  inspection_id: UUID;
  device_id: UUID;
  device_sequence: number;
  lifecycle_status: InspectionLifecycle;
  started_at: ISODateTime;
  completed_at: ISODateTime;
  barcode_result: BarcodeResult;
  product_resolution: ProductResolution;
  product_detection: ProductDetection | null;
  roi_result: ROIResult | null;
  frame_quality_summary: FrameQualitySummary;
  application_version: string;
  product_model_version_id: UUID;
  product_model_checksum_sha256: string;
  component_model_version_id: UUID;
  component_model_checksum_sha256: string;
  rule_version_id: UUID;
  aggregation_policy_version: string;
  evidence: AggregatedComponentEvidence[];
  media: MediaMetadata[];
  decision: InspectionDecision;
  synchronization_status: SynchronizationStatus;
  processing_ms: number;
  inference_metadata?: Record<string, unknown> | null;
};

export type InspectionSummary = {
  inspection_id: UUID;
  completed_at: ISODateTime;
  business_result: BusinessResult;
  internal_decision: InternalDecision;
  barcode: string | null;
  product_code: string | null;
  sn: string | null;
  reason_summary: string[];
  latency_ms: number;
  upload_state: SynchronizationStatus;
  model_rule_versions: { product_model: string | null; component_model: string | null; rule: string | null };
};
export type Artifact = { name: string; uri: string; sha256: string; size_bytes: number };

export type ModelManifest = {
  model_version_id: UUID;
  model_id: UUID;
  semantic_version: string;
  model_version_label: string | null;
  task: "PRODUCT_DETECTION" | "COMPONENT_DETECTION";
  runtime: string;
  input_width: number;
  input_height: number;
  class_names: string[];
  artifacts: Artifact[];
  datasets: Array<{ dataset_version: string; purpose: string; manifest_uri: string }>;
  split_strategy: string;
  source_revision: string;
  training_config_revision: string;
  metrics: Array<{ name: string; value: number; scope: string }>;
  limitations: string[];
  approved_by: string | null;
  approved_at: ISODateTime | null;
  supersedes_model_version_id: UUID | null;
  created_at: ISODateTime;
};

export type UploadTask = {
  upload_task_id: UUID;
  device_id: UUID;
  inspection_id: UUID | null;
  kind: "INSPECTION" | "MEDIA" | "DEVICE_EVENT";
  object_id: UUID;
  payload_hash: string;
  status: UploadTaskState;
  idempotency_key: string;
  checksum_sha256: string | null;
  attempt_count: number;
  next_attempt_at: ISODateTime | null;
  last_error_code: string | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  completed_at: ISODateTime | null;
};

/** Operator confirmation body for a manual upload retry (design 15.3.3). */
export type RetryUploadRequest = {
  reason?: string | null;
};

export const REVIEW_DISPOSITIONS = [
  "CONFIRMED_NG",
  "CONFIRMED_OK",
  "CORRECTED_NG",
  "INCONCLUSIVE",
  "REINSPECT",
] as const;
export type ReviewDisposition = (typeof REVIEW_DISPOSITIONS)[number];

export const COMPONENT_CORRECTION_STATES = ["PRESENT", "MISSING", "UNCERTAIN"] as const;
export type ComponentCorrectionState = (typeof COMPONENT_CORRECTION_STATES)[number];

/** Per-component ground truth recorded by a reviewer (design 24.7). */
export type ComponentCorrection = {
  component_code: string;
  corrected_state: ComponentCorrectionState;
  note?: string | null;
};

/** Per-component ground truth submitted with a review (design 24.6). */
export type ComponentCorrectionRequest = {
  component_code: string;
  corrected_state: ComponentCorrectionState;
  note?: string | null;
};

/** Append-only human review of one inspection (design 24.7). */
export type ReviewRecord = {
  review_id: UUID;
  inspection_id: UUID;
  disposition: ReviewDisposition;
  reason: string | null;
  note: string | null;
  reviewer: string;
  created_at: ISODateTime;
  original_business_result: BusinessResult;
  original_internal_decision: InternalDecision;
  original_reason_codes: string[];
  component_corrections: ComponentCorrection[];
  supersedes_review_id: UUID | null;
};

/** Human disposition submission for one inspection (design 24.6). */
export type SubmitReviewRequest = {
  disposition: ReviewDisposition;
  reason?: string | null;
  note?: string | null;
  reviewer: string;
  supersedes_review_id?: UUID | null;
  component_corrections?: ComponentCorrectionRequest[];
};

/** One inspection row of the review queue with its review state (24.4). */
export type ReviewQueueItem = {
  inspection_id: UUID;
  completed_at: ISODateTime;
  business_result: BusinessResult;
  internal_decision: InternalDecision;
  barcode: string | null;
  reason_summary: string[];
  has_review: boolean;
  latest_disposition: ReviewDisposition | null;
};

export type ReviewFilter = {
  business_result?: BusinessResult;
  internal_decision?: InternalDecision;
  reviewed?: boolean;
  cursor?: string;
  limit?: number;
};

export type DeviceStatus = {
  device_id: UUID;
  observed_at: ISODateTime;
  operational_state: DeviceOperationalState;
  inspection_ready: boolean;
  sync_ready: boolean;
  camera_connected: boolean;
  model_loaded: boolean;
  central_connected: boolean;
  disk_free_bytes: number;
  upload_pending_count: number;
  upload_pending_bytes: number;
  upload_oldest_pending_at: ISODateTime | null;
  upload_attempts: number;
  upload_successes: number;
  upload_failures: number;
  upload_failure_rate: number;
  upload_last_attempt_at: ISODateTime | null;
  upload_last_success_at: ISODateTime | null;
  upload_last_error_code: string | null;
  storage_mode: "NORMAL" | "WARNING" | "CRITICAL" | "STOP";
  storage_free_bytes: number;
  storage_free_percent: number;
  storage_free_inodes: number;
  storage_inode_percent: number;
  storage_warning_free_percent: number;
  storage_critical_free_percent: number;
  storage_stop_free_percent: number;
  storage_observed_at: ISODateTime | null;
  storage_write_fault: boolean;
  cleanup_enabled: boolean;
  cleanup_eligible_count: number;
  cleanup_eligible_bytes: number;
  cleanup_deleting_count: number;
  cleanup_delete_error_count: number;
  cleanup_purged_count: number;
  cleanup_integrity_fault_count: number;
  cleanup_last_run_at: ISODateTime | null;
  cleanup_last_error_code: string | null;
  integrity_scan_last_run_at: ISODateTime | null;
  integrity_scan_checked: number;
  integrity_scan_faults: number;
  integrity_scan_checksummed: number;
  integrity_scan_skipped: number;
  integrity_scan_skipped_reason: string | null;
  integrity_verify_checksums: boolean;
  current_product_model_version_id: UUID | null;
  current_component_model_version_id: UUID | null;
  current_rule_version_id: UUID | null;
  alerts: string[];
};

export type CameraState = {
  connected: boolean;
  source_width: number;
  source_height: number;
  fps: number | null;
  last_frame_at: ISODateTime | null;
  error_code: string | null;
};

export type InspectionRuntimeState = {
  window_active: boolean;
  paused: boolean;
  faulted: boolean;
  current_inspection_id: UUID | null;
  last_result: BusinessResult | null;
  paused_reason: string | null;
  paused_by: string | null;
  paused_at: ISODateTime | null;
};

export type EffectiveConfiguration = {
  revision: string;
  checksum_sha256: string;
  managed: Record<string, unknown>;
  local_overrides: Record<string, unknown>;
};

export type LogEvent = {
  logged_at: ISODateTime;
  level: string;
  component: string;
  message: string;
  trace_id: string | null;
};

export type Problem = {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  request_id: string;
  errors?: Array<{ field: string; message: string }>;
};

export type Page<T> = {
  items: T[];
  next_cursor: string | null;
};

export type InspectionFilter = {
  business_result?: BusinessResult;
  internal_decision?: InternalDecision;
  barcode?: string;
  product?: string;
  sn?: string;
  line?: string;
  from?: ISODateTime;
  to?: ISODateTime;
  cursor?: string;
  limit?: number;
};

// ---- Operator workflow domain (production inspection dashboard) ----
//
// These types model the operator-facing workflow: a current inspection with
// rule checks, SN traceability across reinspection attempts, and production
// statistics. They are independent of the internal inspection record so the
// mock can be swapped for the future FastAPI endpoints without UI changes.

export const INSPECTION_STATUSES = ["WAITING", "PROCESSING", "PASS", "NG"] as const;
export type InspectionStatus = (typeof INSPECTION_STATUSES)[number];

export const RULE_STATUSES = ["PENDING", "CHECKING", "PASS", "NG"] as const;
export type RuleStatus = (typeof RULE_STATUSES)[number];

export type InspectionRule = {
  id: string;
  name: string;
  status: RuleStatus;
  result_message: string;
};

export type CurrentInspection = {
  inspection_id: UUID;
  sn: string | null;
  product_code: string;
  operator: string;
  status: InspectionStatus;
  started_at: ISODateTime;
  completed_at: ISODateTime | null;
  duration_ms: number | null;
  progress: number;
  rules: InspectionRule[];
  reason_codes: string[];
};

export type InspectionAttempt = {
  attempt: number;
  inspection_id: UUID;
  timestamp: ISODateTime;
  result: "PASS" | "NG";
  reason: string;
  operator: string;
};

export type TraceabilityView = {
  sn: string;
  final_status: "PASS" | "NG";
  attempts: InspectionAttempt[];
};

/** Image references for one inspection (original, detection result, annotations). */
export type ImageSlotStatus = "AVAILABLE" | "PURGED" | "UNAVAILABLE";

export type InspectionImages = {
  inspection_id: UUID;
  original: string;
  detection: string;
  annotated: string;
  original_status: ImageSlotStatus;
  detection_status: ImageSlotStatus;
  annotated_status: ImageSlotStatus;
};

export type StatisticsFilter = {
  from?: ISODateTime;
  to?: ISODateTime;
  line?: string;
};

export type StatisticsSummary = {
  total_inspections: number;
  pass_count: number;
  ng_count: number;
  pass_rate: number;
};

/** One analyzed frame's decision summary (web dev test harness, ADR-014). */
export type VideoFrameInspectResult = {
  index: number;
  business_result: BusinessResult;
  internal_decision: InternalDecision;
  reason_codes: string[];
};

/** Per-frame summary for an uploaded test video (ADR-014). */
export type VideoInspectResult = {
  instance_id: string;
  analyzed_frames: number;
  ok_count: number;
  ng_count: number;
  frames: VideoFrameInspectResult[];
  truncated: boolean;
};
