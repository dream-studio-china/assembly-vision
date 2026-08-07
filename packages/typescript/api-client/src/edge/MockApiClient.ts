import type { ApiClient } from "./ApiClient";
import { ApiError } from "./ApiError";
import type {
  AggregatedComponentEvidence,
  BarcodeResult,
  BoundingBox,
  BusinessResult,
  CameraState,
  DeviceStatus,
  EffectiveConfiguration,
  EvidenceState,
  InspectionDecision,
  InspectionFilter,
  InspectionRecord,
  InspectionRuntimeState,
  InspectionSummary,
  InternalDecision,
  LogEvent,
  MediaMetadata,
  Page,
  ProductResolution,
  UploadTask,
} from "./types";

const DEVICE_ID = "11111111-1111-4111-8111-111111111111";
const UUID = (n: string) => `00000000-0000-4000-8000-${n.padStart(12, "0")}`;
const NOW = new Date();
const ISO = (offsetSec: number) => new Date(NOW.getTime() + offsetSec * 1000).toISOString();

function box(x1: number, y1: number, x2: number, y2: number, w: number, h: number): BoundingBox {
  return { x_min: x1, y_min: y1, x_max: x2, y_max: y2, image_width: w, image_height: h };
}

function evidence(code: string, state: EvidenceState, confidence: number | null): AggregatedComponentEvidence {
  return {
    component_code: code,
    state,
    best_confidence: confidence,
    usable_frame_count: 1,
    detection_count: state === "PRESENT" ? 1 : 0,
    adjacent_detection_run: state === "PRESENT" ? 1 : 0,
    supporting_frame_ids: [UUID("1")],
    policy_reason_codes: state === "MISSING" ? ["COMPONENT_MISSING"] : [],
  };
}

function decision(business: BusinessResult, missing: string[], reasonCodes: string[]): InspectionDecision {
  const internal: InternalDecision = business === "OK" ? "OK" : "NG";
  return {
    internal_decision: internal,
    business_result: business,
    missing_components: missing,
    low_confidence_components: [],
    reason_codes: reasonCodes,
    decided_at: ISO(0),
  };
}

function record(seq: number, business: BusinessResult, missing: string[], reasonCodes: string[]): InspectionRecord {
  const ok = business === "OK";
  return {
    inspection_id: UUID(String(100 + seq)),
    device_id: DEVICE_ID,
    device_sequence: seq,
    lifecycle_status: "COMPLETED",
    started_at: ISO(-seq * 30 - 2),
    completed_at: ISO(-seq * 30),
    barcode_result: { status: "NOT_REQUIRED", value: null, symbology: null } as BarcodeResult,
    product_resolution: {
      status: "RESOLVED",
      source: "CONFIGURED_DEFAULT",
      product_code: "model_a",
      product_version_id: null,
    } as ProductResolution,
    product_detection: ok
      ? {
          frame_id: UUID("1"),
          product_class: "product",
          confidence: 0.93,
          bbox: box(120, 90, 680, 520, 800, 600),
          model_version_id: UUID("11"),
          quality: { usable: true, blur_score: 0.0, brightness_mean: 128, saturation_fraction: 0.2, occlusion_fraction: null, reason_codes: [] },
        }
      : null,
    roi_result: ok
      ? {
          frame_id: UUID("1"),
          product_bbox: box(120, 90, 680, 520, 800, 600),
          roi_bbox: box(80, 60, 720, 550, 800, 600),
          roi_width: 640,
          roi_height: 490,
          orientation_degrees: null,
          transform_full_to_roi: [1, 0, -80, 0, 1, -60],
          media_id: UUID(String(200 + seq)),
        }
      : null,
    frame_quality_summary: { total_frame_count: 1, usable_frame_count: 1, rejected_frame_count: 0, reasons: [] },
    application_version: "0.1.0",
    product_model_version_id: UUID("11"),
    product_model_checksum_sha256: "0".repeat(64),
    component_model_version_id: UUID("12"),
    component_model_checksum_sha256: "0".repeat(64),
    rule_version_id: UUID("13"),
    aggregation_policy_version: "single-frame-mvp-1",
    evidence: ok
      ? [evidence("component_a", "PRESENT", 0.91), evidence("component_b", "PRESENT", 0.84), evidence("manual", "PRESENT", 0.96)]
      : [evidence("component_a", "PRESENT", 0.91), evidence("component_b", "MISSING", null), evidence("manual", "PRESENT", 0.9)],
    media: ok
      ? [
          {
            media_id: UUID(String(200 + seq)),
            kind: "KEY_FRAME",
            lifecycle: "AVAILABLE",
            relative_path: `${UUID(String(100 + seq))}/key_frame.jpg`,
            mime_type: "image/jpeg",
            size_bytes: 128_000,
            checksum_sha256: "0".repeat(64),
          } as MediaMetadata,
        ]
      : [],
    decision: decision(business, missing, reasonCodes),
    synchronization_status: seq % 3 === 0 ? "QUEUED" : "LOCAL_ONLY",
    processing_ms: 320 + seq * 7,
  };
}

const RECORDS: InspectionRecord[] = [
  record(1, "OK", [], []),
  record(2, "OK", [], []),
  record(3, "NG", ["component_b"], ["COMPONENT_MISSING:component_b"]),
  record(4, "NG", ["component_b", "manual"], ["COMPONENT_MISSING:component_b", "COMPONENT_MISSING:manual"]),
  record(5, "OK", [], []),
  record(6, "OK", [], []),
  record(7, "NG", ["component_a"], ["COMPONENT_MISSING:component_a"]),
];

function summary(r: InspectionRecord): InspectionSummary {
  return {
    inspection_id: r.inspection_id,
    completed_at: r.completed_at,
    business_result: r.decision.business_result,
    internal_decision: r.decision.internal_decision,
    barcode: r.barcode_result.value,
    product_code: r.product_resolution.product_code,
    reason_summary: r.decision.reason_codes,
    latency_ms: r.processing_ms,
    upload_state: r.synchronization_status,
    model_rule_versions: {
      product_model: "product-yolo-1.0.0",
      component_model: "component-yolo-1.0.0",
      rule: "model-a-presence:3",
    },
  };
}

const UPLOADS: UploadTask[] = [
  {
    upload_task_id: UUID("300"),
    device_id: DEVICE_ID,
    inspection_id: UUID("104"),
    kind: "INSPECTION",
    object_id: UUID("104"),
    payload_hash: "abc123",
    status: "RETRY_WAIT",
    idempotency_key: "inspection:device:104",
    checksum_sha256: "0".repeat(64),
    attempt_count: 3,
    next_attempt_at: ISO(120),
    last_error_code: "TIMEOUT",
    created_at: ISO(-600),
    updated_at: ISO(-30),
    completed_at: null,
  },
  {
    upload_task_id: UUID("301"),
    device_id: DEVICE_ID,
    inspection_id: UUID("103"),
    kind: "MEDIA",
    object_id: UUID("203"),
    payload_hash: "def456",
    status: "PENDING",
    idempotency_key: "media:device:203",
    checksum_sha256: "0".repeat(64),
    attempt_count: 0,
    next_attempt_at: ISO(30),
    last_error_code: null,
    created_at: ISO(-120),
    updated_at: ISO(-120),
    completed_at: null,
  },
  {
    upload_task_id: UUID("302"),
    device_id: DEVICE_ID,
    inspection_id: UUID("102"),
    kind: "INSPECTION",
    object_id: UUID("102"),
    payload_hash: "1234ab",
    status: "SUCCEEDED",
    idempotency_key: "inspection:device:102",
    checksum_sha256: "0".repeat(64),
    attempt_count: 2,
    next_attempt_at: null,
    last_error_code: null,
    created_at: ISO(-1200),
    updated_at: ISO(-300),
    completed_at: ISO(-300),
  },
];

/**
 * In-memory edge client used to develop and test the dashboard without a
 * backend. Data is deterministic and realistic for the MVP scope.
 */
export class MockApiClient implements ApiClient {
  #records: InspectionRecord[] = RECORDS;
  #uploads: UploadTask[] = UPLOADS;
  #paused = false;

  async getHealthLive(): Promise<{ status: string }> {
    return { status: "ok" };
  }

  async getHealthReady(): Promise<DeviceStatus> {
    return this.getDeviceStatus();
  }

  async getDeviceStatus(): Promise<DeviceStatus> {
    return {
      device_id: DEVICE_ID,
      observed_at: ISO(0),
      operational_state: this.#paused ? "PAUSED" : "READY",
      inspection_ready: !this.#paused,
      sync_ready: true,
      camera_connected: true,
      model_loaded: true,
      central_connected: false,
      disk_free_bytes: 42 * 1024 ** 3,
      upload_pending_count: 2,
      current_product_model_version_id: UUID("11"),
      current_component_model_version_id: UUID("12"),
      current_rule_version_id: UUID("13"),
      alerts: [],
    };
  }

  async getCameraState(): Promise<CameraState> {
    return {
      connected: true,
      source_width: 800,
      source_height: 600,
      fps: 15,
      last_frame_at: ISO(-1),
      error_code: null,
    };
  }

  async getInspectionState(): Promise<InspectionRuntimeState> {
    return {
      window_active: false,
      paused: this.#paused,
      faulted: false,
      current_inspection_id: null,
      last_result: this.#records[0].decision.business_result,
      paused_reason: this.#paused ? "operator requested" : null,
      paused_by: this.#paused ? "operator" : null,
      paused_at: this.#paused ? ISO(-60) : null,
    };
  }

  async pauseInspection(reason: string) {
    if (this.#paused) {
      throw new ApiError(409, "ALREADY_PAUSED", "inspection is already paused");
    }
    this.#paused = true;
    return {
      accepted: true,
      operation_id: UUID("400"),
      detail: reason,
      state: await this.getInspectionState(),
    };
  }

  async resumeInspection(reason: string) {
    if (!this.#paused) {
      throw new ApiError(409, "PRECONDITION_FAILED", "inspection is not paused");
    }
    this.#paused = false;
    return {
      accepted: true,
      operation_id: UUID("401"),
      detail: reason,
      state: await this.getInspectionState(),
    };
  }

  async listInspections(filter?: InspectionFilter): Promise<Page<InspectionSummary>> {
    let items = this.#records.map(summary);
    if (filter?.business_result) items = items.filter((i) => i.business_result === filter.business_result);
    if (filter?.internal_decision) items = items.filter((i) => i.internal_decision === filter.internal_decision);
    if (filter?.product) items = items.filter((i) => i.product_code === filter.product);
    return { items, next_cursor: null };
  }

  async getInspection(inspectionId: string): Promise<InspectionRecord> {
    const found = this.#records.find((r) => r.inspection_id === inspectionId);
    if (!found) throw new ApiError(404, "INSPECTION_NOT_FOUND", `no inspection ${inspectionId}`);
    return found;
  }

  async listInspectionMedia(inspectionId: string): Promise<MediaMetadata[]> {
    const found = await this.getInspection(inspectionId);
    return found.media;
  }

  async listUploads(cursor?: string, limit?: number): Promise<Page<UploadTask>> {
    void cursor;
    const items = this.#uploads.slice(0, limit ?? 50);
    return { items, next_cursor: null };
  }

  async retryUpload(uploadTaskId: string, reason: string) {
    void reason;
    const task = this.#uploads.find((u) => u.upload_task_id === uploadTaskId);
    if (!task) throw new ApiError(404, "TASK_NOT_FOUND", `no upload task ${uploadTaskId}`);
    if (task.status === "RETRY_WAIT" || task.status === "PERMANENT_FAILURE") {
      task.status = "PENDING";
      task.attempt_count += 1;
      task.next_attempt_at = ISO(15);
      task.last_error_code = null;
    }
    return { accepted: true, operation_id: UUID("402"), detail: null, task };
  }

  async getEffectiveConfiguration(): Promise<EffectiveConfiguration> {
    return {
      revision: "config-1",
      checksum_sha256: "0".repeat(64),
      managed: {
        application_version: "0.1.0",
        product_detection: { model_version: "product-yolo-1.0.0", confidence_threshold: 0.7 },
        component_detection: { model_version: "component-yolo-1.0.0" },
      },
      local_overrides: {},
    };
  }

  async listLogs(cursor?: string, limit?: number): Promise<Page<LogEvent>> {
    void cursor;
    const items: LogEvent[] = [
      { logged_at: ISO(-10), level: "INFO", component: "edge.pipeline", message: "inspection completed", trace_id: null },
      { logged_at: ISO(-40), level: "WARN", component: "edge.upload", message: "upload retry scheduled", trace_id: null },
    ].slice(0, limit ?? 50);
    return { items, next_cursor: null };
  }
}
