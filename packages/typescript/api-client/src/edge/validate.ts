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
  logPage: (body) => pageOf(body, validateLogEvent),
  effectiveConfiguration: validateEffectiveConfiguration,
  inspectionImages: validateInspectionImages,
  traceabilityView: validateTraceabilityView,
  statisticsSummary: validateStatisticsSummary,
};
