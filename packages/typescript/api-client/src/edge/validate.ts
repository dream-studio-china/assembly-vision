/**
 * Runtime response validation for the edge HTTP client (F9).
 *
 * The generated OpenAPI types are erased at runtime, so TypeScript
 * type-checking alone cannot detect drifted or malformed HTTP payloads. These
 * guards verify the shapes the dashboard reads at the fetch boundary and reject
 * incompatible responses with an `INVALID_RESPONSE` error instead of silently
 * casting them.
 */

type Record_ = Record<string, unknown>;

export class ResponseValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ResponseValidationError";
  }
}

export type Validator = (body: unknown) => void;

function fail(path: string, expected: string, actual: unknown): never {
  const rendered =
    actual === null ? "null" : typeof actual === "object" ? JSON.stringify(actual) : String(actual);
  throw new ResponseValidationError(`invalid response at ${path}: expected ${expected}, got ${rendered}`);
}

function expectRecord(body: unknown, path = "$"): Record_ {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    fail(path, "object", body);
  }
  return body as Record_;
}

function hasString(record: Record_, key: string, path: string): string {
  const value = record[key];
  if (typeof value !== "string") fail(`${path}.${key}`, "string", value);
  return value;
}

function hasNumber(record: Record_, key: string, path: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value)) fail(`${path}.${key}`, "number", value);
  return value;
}

function hasBoolean(record: Record_, key: string, path: string): boolean {
  const value = record[key];
  if (typeof value !== "boolean") fail(`${path}.${key}`, "boolean", value);
  return value;
}

function hasOneOf(record: Record_, key: string, values: readonly string[], path: string): string {
  const value = hasString(record, key, path);
  if (!values.includes(value)) fail(`${path}.${key}`, values.join("|"), value);
  return value;
}

function hasArray(record: Record_, key: string, path: string): unknown[] {
  const value = record[key];
  if (!Array.isArray(value)) fail(`${path}.${key}`, "array", value);
  return value;
}

function hasRecord(record: Record_, key: string, path: string): Record_ {
  const value = record[key];
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    fail(`${path}.${key}`, "object", value);
  }
  return value as Record_;
}

function pageOf(body: unknown, item: Validator, path = "$"): void {
  const record = expectRecord(body, path);
  const items = hasArray(record, "items", path);
  items.forEach((value) => item(value));
  const next = record.next_cursor;
  if (next !== undefined && next !== null && typeof next !== "string") {
    fail(`${path}.next_cursor`, "string|null", next);
  }
}

function validateHealthLive(body: unknown): void {
  const record = expectRecord(body);
  hasString(record, "status", "$");
}

function validateDeviceStatus(body: unknown): void {
  const record = expectRecord(body);
  for (const key of ["device_id", "observed_at", "operational_state"]) {
    hasString(record, key, "$");
  }
  for (const key of [
    "inspection_ready",
    "sync_ready",
    "camera_connected",
    "model_loaded",
    "central_connected",
  ]) {
    hasBoolean(record, key, "$");
  }
  for (const key of ["disk_free_bytes", "upload_pending_count"]) {
    hasNumber(record, key, "$");
  }
  hasArray(record, "alerts", "$");
}

function validateCameraState(body: unknown): void {
  const record = expectRecord(body);
  hasBoolean(record, "connected", "$");
  hasNumber(record, "source_width", "$");
  hasNumber(record, "source_height", "$");
}

function validateRuntimeState(body: unknown): void {
  const record = expectRecord(body);
  for (const key of ["window_active", "paused", "faulted"]) {
    hasBoolean(record, key, "$");
  }
}

function validateInspectionSummary(body: unknown): void {
  const record = expectRecord(body);
  for (const key of ["inspection_id", "completed_at", "upload_state"]) {
    hasString(record, key, "$");
  }
  hasOneOf(record, "business_result", ["OK", "NG"], "$");
  hasOneOf(record, "internal_decision", ["OK", "NG", "UNCERTAIN"], "$");
  hasNumber(record, "latency_ms", "$");
  hasArray(record, "reason_summary", "$");
  hasRecord(record, "model_rule_versions", "$");
}

function validateMediaMetadata(body: unknown, path = "$"): void {
  const record = expectRecord(body, path);
  for (const key of ["media_id", "relative_path", "mime_type", "checksum_sha256"]) {
    hasString(record, key, path);
  }
  hasOneOf(record, "kind", ["KEY_FRAME", "ANNOTATED_FRAME", "PRODUCT_ROI", "NG_CLIP", "ROLLING_VIDEO"], path);
  hasOneOf(record, "lifecycle", ["PENDING", "AVAILABLE", "FAILED", "PURGED"], path);
  hasNumber(record, "size_bytes", path);
}

function validateUploadTask(body: unknown): void {
  const record = expectRecord(body);
  for (const key of [
    "upload_task_id",
    "device_id",
    "kind",
    "object_id",
    "payload_hash",
    "status",
    "idempotency_key",
    "created_at",
    "updated_at",
  ]) {
    hasString(record, key, "$");
  }
  hasNumber(record, "attempt_count", "$");
}

function validateLogEvent(body: unknown): void {
  const record = expectRecord(body);
  for (const key of ["logged_at", "level", "component", "message"]) {
    hasString(record, key, "$");
  }
}

function validateEffectiveConfiguration(body: unknown): void {
  const record = expectRecord(body);
  hasString(record, "revision", "$");
  hasString(record, "checksum_sha256", "$");
  hasRecord(record, "managed", "$");
  hasRecord(record, "local_overrides", "$");
}

function validateInspectionRecord(body: unknown): void {
  const record = expectRecord(body);
  for (const key of [
    "inspection_id",
    "device_id",
    "lifecycle_status",
    "started_at",
    "completed_at",
    "application_version",
    "product_model_version_id",
    "product_model_checksum_sha256",
    "component_model_version_id",
    "component_model_checksum_sha256",
    "rule_version_id",
    "aggregation_policy_version",
    "synchronization_status",
  ]) {
    hasString(record, key, "$");
  }
  hasNumber(record, "device_sequence", "$");
  hasNumber(record, "processing_ms", "$");
  for (const key of ["barcode_result", "product_resolution", "frame_quality_summary", "decision"]) {
    hasRecord(record, key, "$");
  }  // Nested fields the dashboard actually reads are validated so a drifted
  // payload cannot render a fabricated decision or evidence state.
  const barcode = hasRecord(record, "barcode_result", "$");
  hasOneOf(barcode, "status", ["READ", "NOT_READ", "CONFLICT", "NOT_REQUIRED"], "$.barcode_result");
  const resolution = hasRecord(record, "product_resolution", "$");
  hasOneOf(resolution, "status", ["RESOLVED", "UNKNOWN", "CONFLICT"], "$.product_resolution");
  const quality = hasRecord(record, "frame_quality_summary", "$");
  hasNumber(quality, "usable_frame_count", "$.frame_quality_summary");
  const decision = hasRecord(record, "decision", "$");
  hasOneOf(decision, "internal_decision", ["OK", "NG", "UNCERTAIN"], "$.decision");
  hasOneOf(decision, "business_result", ["OK", "NG"], "$.decision");
  const evidence = hasArray(record, "evidence", "$");
  evidence.forEach((item, index) => {
    const path = `$.evidence[${index}]`;
    const entry = expectRecord(item, path);
    hasString(entry, "component_code", path);
    hasOneOf(entry, "state", ["PRESENT", "MISSING", "UNCERTAIN", "UNVERIFIABLE"], path);
  });
  const media = hasArray(record, "media", "$");
  media.forEach((item, index) => validateMediaMetadata(item, `$.media[${index}]`));
}

function validateVideoInspectResult(body: unknown): void {
  const result = expectRecord(body);
  hasString(result, "instance_id", "$");
  hasNumber(result, "analyzed_frames", "$");
  hasNumber(result, "ok_count", "$");
  hasNumber(result, "ng_count", "$");
  const truncated = result.truncated;
  if (truncated !== undefined && typeof truncated !== "boolean") {
    fail("$.truncated", "boolean", truncated);
  }
  const frames = hasArray(result, "frames", "$");
  frames.forEach((item, index) => {
    const path = `$.frames[${index}]`;
    const frame = expectRecord(item, path);
    hasNumber(frame, "index", path);
    hasOneOf(frame, "business_result", ["OK", "NG"], path);
    hasOneOf(frame, "internal_decision", ["OK", "NG", "UNCERTAIN"], path);
    hasArray(frame, "reason_codes", path);
  });
}

function validateInspectionImages(body: unknown): void {
  const record = expectRecord(body);
  for (const key of [
    "inspection_id",
    "original",
    "detection",
    "annotated",
  ]) {
    hasString(record, key, "$");
  }
  for (const key of ["original_status", "detection_status", "annotated_status"]) {
    hasOneOf(record, key, ["AVAILABLE", "PURGED", "UNAVAILABLE"], "$");
  }
}

function validateTraceabilityView(body: unknown): void {
  const record = expectRecord(body);
  hasString(record, "sn", "$");
  hasString(record, "final_status", "$");
  hasArray(record, "attempts", "$");
}

function validateStatisticsSummary(body: unknown): void {
  const record = expectRecord(body);
  for (const key of ["total_inspections", "pass_count", "ng_count", "pass_rate"]) {
    hasNumber(record, key, "$");
  }
}

const DRIFT_LEVELS = [
  "stable",
  "minor_drop",
  "noticeable_drop",
  "minor_rise",
  "noticeable_rise",
  "insufficient_data",
] as const;

function validateConfidencePeriod(record: Record_, path: string): void {
  for (const key of ["from_iso", "to_iso"]) hasString(record, key, path);
  for (const key of ["inspection_count", "evidence_count"]) hasNumber(record, key, path);
  const mean = record["weighted_mean"];
  if (mean !== null && (typeof mean !== "number" || !Number.isFinite(mean))) {
    fail(`${path}.weighted_mean`, "number|null", mean);
  }
  const median = record["median"];
  if (median !== null && (typeof median !== "number" || !Number.isFinite(median))) {
    fail(`${path}.median`, "number|null", median);
  }
}

function validateConfidenceComparison(record: Record_, path: string): void {
  const delta = record["weighted_mean_delta"];
  if (delta !== null && (typeof delta !== "number" || !Number.isFinite(delta))) {
    fail(`${path}.weighted_mean_delta`, "number|null", delta);
  }
  const relative = record["weighted_mean_relative_percent"];
  if (relative !== null && (typeof relative !== "number" || !Number.isFinite(relative))) {
    fail(`${path}.weighted_mean_relative_percent`, "number|null", relative);
  }
  hasNumber(record, "today_evidence_count", path);
  hasNumber(record, "baseline_evidence_count", path);
}

function validateComponentDrift(record: Record_, path: string): void {
  hasString(record, "component_code", path);
  for (const key of ["today_weighted_mean", "baseline_weighted_mean", "delta"]) {
    const value = record[key];
    if (value !== null && (typeof value !== "number" || !Number.isFinite(value))) {
      fail(`${path}.${key}`, "number|null", value);
    }
  }
  hasNumber(record, "today_evidence_count", path);
  hasNumber(record, "baseline_evidence_count", path);
}

function validateConfidenceDriftReport(body: unknown): void {
  const record = expectRecord(body);
  const scope = expectRecord(record["scope"], "$.scope");
  hasString(scope, "device_id", "$.scope");
  for (const key of [
    "product_code",
    "rule_version_id",
    "product_model_version_id",
    "component_model_version_id",
    "aggregation_policy_version",
  ]) {
    hasString(scope, key, "$.scope");
  }
  hasNumber(scope, "tz_offset_minutes", "$.scope");
  hasString(scope, "as_of_iso", "$.scope");

  const periods = expectRecord(record["periods"], "$.periods");
  for (const key of ["today", "yesterday", "previous_7d", "previous_30d"]) {
    validateConfidencePeriod(expectRecord(periods[key], `$.periods.${key}`), `$.periods.${key}`);
  }

  const comparison = expectRecord(record["comparison"], "$.comparison");
  for (const key of ["today_vs_yesterday", "today_vs_previous_7d", "today_vs_previous_30d"]) {
    validateConfidenceComparison(
      expectRecord(comparison[key], `$.comparison.${key}`),
      `$.comparison.${key}`,
    );
  }

  const components = hasArray(record, "components", "$");
  components.forEach((item, index) =>
    validateComponentDrift(expectRecord(item, `$.components[${index}]`), `$.components[${index}]`),
  );

  const assessment = expectRecord(record["assessment"], "$.assessment");
  hasOneOf(assessment, "level", DRIFT_LEVELS, "$.assessment");
  hasString(assessment, "detail", "$.assessment");
}

function validateReviewRecord(body: unknown): void {
  const record = expectRecord(body);
  for (const key of [
    "review_id",
    "inspection_id",
    "disposition",
    "reviewer",
    "created_at",
    "original_business_result",
    "original_internal_decision",
  ]) {
    hasString(record, key, "$");
  }
  hasOneOf(
    record,
    "disposition",
    ["CONFIRMED_NG", "CONFIRMED_OK", "CORRECTED_NG", "INCONCLUSIVE", "REINSPECT"],
    "$.disposition",
  );
  hasOneOf(record, "original_business_result", ["OK", "NG"], "$.original_business_result");
  hasOneOf(
    record,
    "original_internal_decision",
    ["OK", "NG", "UNCERTAIN"],
    "$.original_internal_decision",
  );
  hasArray(record, "original_reason_codes", "$");
  hasArray(record, "component_corrections", "$");
  if (record.reason !== null && record.reason !== undefined && typeof record.reason !== "string") {
    fail("$.reason", "string|null", record.reason);
  }
  if (record.note !== null && record.note !== undefined && typeof record.note !== "string") {
    fail("$.note", "string|null", record.note);
  }
  if (
    record.supersedes_review_id !== null &&
    record.supersedes_review_id !== undefined &&
    typeof record.supersedes_review_id !== "string"
  ) {
    fail("$.supersedes_review_id", "string|null", record.supersedes_review_id);
  }
}

function validateReviewQueueItem(body: unknown): void {
  const item = expectRecord(body);
  for (const key of ["inspection_id", "completed_at", "business_result", "internal_decision"]) {
    hasString(item, key, "$");
  }
  hasOneOf(item, "business_result", ["OK", "NG"], "$.business_result");
  hasOneOf(item, "internal_decision", ["OK", "NG", "UNCERTAIN"], "$.internal_decision");
  if (item.barcode !== null && item.barcode !== undefined && typeof item.barcode !== "string") {
    fail("$.barcode", "string|null", item.barcode);
  }
  hasArray(item, "reason_summary", "$");
  if (typeof item.has_review !== "boolean") {
    fail("$.has_review", "boolean", item.has_review);
  }
  if (
    item.latest_disposition !== null &&
    item.latest_disposition !== undefined &&
    typeof item.latest_disposition === "string" &&
    !["CONFIRMED_NG", "CONFIRMED_OK", "CORRECTED_NG", "INCONCLUSIVE", "REINSPECT"].includes(
      item.latest_disposition,
    )
  ) {
    fail("$.latest_disposition", "disposition|null", item.latest_disposition);
  }
  if (
    item.latest_disposition !== null &&
    item.latest_disposition !== undefined &&
    typeof item.latest_disposition !== "string"
  ) {
    fail("$.latest_disposition", "disposition|null", item.latest_disposition);
  }
}

export const validators: Record<string, Validator> = {
  healthLive: validateHealthLive,
  deviceStatus: validateDeviceStatus,
  cameraState: validateCameraState,
  runtimeState: validateRuntimeState,
  inspectionPage: (body) => pageOf(body, validateInspectionSummary),
  inspectionRecord: validateInspectionRecord,
  videoInspectResult: validateVideoInspectResult,
  mediaList: (body) => {
    if (!Array.isArray(body)) fail("$", "array", body);
    body.forEach((item) => validateMediaMetadata(item));
  },
  uploadPage: (body) => pageOf(body, validateUploadTask),
  uploadTask: validateUploadTask,
  reviewPage: (body) => pageOf(body, validateReviewQueueItem),
  reviewList: (body) => {
    if (!Array.isArray(body)) fail("$", "array", body);
    body.forEach((item) => validateReviewRecord(item));
  },
  reviewRecord: validateReviewRecord,
  logPage: (body) => pageOf(body, validateLogEvent),
  effectiveConfiguration: validateEffectiveConfiguration,
  inspectionImages: validateInspectionImages,
  traceabilityView: validateTraceabilityView,
  statisticsSummary: validateStatisticsSummary,
  confidenceDriftReport: validateConfidenceDriftReport,
};
