import type { ApiClient } from "./ApiClient";
import { ApiError } from "./ApiError";
import type {
  AggregatedComponentEvidence,
  BarcodeResult,
  BoundingBox,
  BusinessResult,
  CameraState,
  CurrentInspection,
  DeviceStatus,
  EffectiveConfiguration,
  EvidenceState,
  InspectionDecision,
  InspectionFilter,
  InspectionImages,
  InspectionRecord,
  InspectionRuntimeState,
  InspectionRule,
  InspectionSummary,
  InternalDecision,
  LogEvent,
  MediaMetadata,
  Page,
  ProductResolution,
  StatisticsFilter,
  StatisticsSummary,
  TraceabilityView,
  UploadTask,
  VideoInspectResult,
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
    box_area_ratios: state === "PRESENT" ? [0.5] : [],
    box_centers: state === "PRESENT" ? [[0.5, 0.5]] : [],
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
    sn: SN_BY_SEQ[r.device_sequence] ?? null,
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

const UPLOADS: UploadTask[] = [  {
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

// ---- Operator workflow mock data (production inspection dashboard) ----

const SN_BY_SEQ: Record<number, string> = {
  1: "SN-0001",
  2: "SN-0003",
  3: "SN-0002",
  4: "SN-0001",
  5: "SN-0003",
  6: "SN-0002",
  7: "SN-0001",
};

const OPERATOR = "operator-01";

/** Deterministic reinspection history per SN (product traceability). */
const TRACEABILITY: Record<string, TraceabilityView> = {
  "SN-0001": {
    sn: "SN-0001",
    final_status: "PASS",
    attempts: [
      {
        attempt: 1,
        inspection_id: UUID("104"),
        timestamp: ISO(-1800),
        result: "NG",
        reason: "Missing component",
        operator: OPERATOR,
      },
      {
        attempt: 2,
        inspection_id: UUID("106"),
        timestamp: ISO(-1200),
        result: "PASS",
        reason: "",
        operator: OPERATOR,
      },
    ],
  },
  "SN-0002": {
    sn: "SN-0002",
    final_status: "NG",
    attempts: [
      {
        attempt: 1,
        inspection_id: UUID("103"),
        timestamp: ISO(-2400),
        result: "NG",
        reason: "Manual not detected",
        operator: OPERATOR,
      },
      {
        attempt: 2,
        inspection_id: UUID("105"),
        timestamp: ISO(-1800),
        result: "NG",
        reason: "Manual not detected",
        operator: OPERATOR,
      },
    ],
  },
  "SN-0003": {
    sn: "SN-0003",
    final_status: "PASS",
    attempts: [
      {
        attempt: 1,
        inspection_id: UUID("102"),
        timestamp: ISO(-3600),
        result: "PASS",
        reason: "",
        operator: OPERATOR,
      },
    ],
  },
};

/** Operator queue walked by continue/confirm actions, cycling through states. */
type QueueItem = { sn: string | null; result: "PASS" | "NG"; reason: string };
const OPERATOR_QUEUE: QueueItem[] = [
  { sn: "SN-0001", result: "NG", reason: "Missing component" },
  { sn: "SN-0003", result: "PASS", reason: "" },
  { sn: null, result: "PASS", reason: "" }, // idle: waiting for a product
  { sn: "SN-0002", result: "NG", reason: "Manual not detected" },
];

const RULE_TEMPLATES: Array<{ id: string; name: string }> = [
  { id: "presence", name: "Component presence check" },
  { id: "manual", name: "Document / manual check" },
  { id: "label", name: "Label placement check" },
];

function buildRules(
  status: CurrentInspection["status"],
  ngRuleId: string | null,
  reason: string,
): InspectionRule[] {
  return RULE_TEMPLATES.map((template) => {
    if (status === "WAITING") {
      return { ...template, status: "PENDING", result_message: "Waiting for product" };
    }
    if (status === "PROCESSING") {
      const inspecting = template.id === "manual" || template.id === "presence";
      return {
        ...template,
        status: inspecting ? "CHECKING" : "PASS",
        result_message: inspecting ? "Inspecting..." : "OK",
      };
    }
    if (status === "NG" && template.id === ngRuleId) {
      return { ...template, status: "NG", result_message: reason };
    }
    return { ...template, status: "PASS", result_message: "OK" };
  });
}

function buildCurrent(sn: string | null, status: CurrentInspection["status"], reason = ""): CurrentInspection {
  const ngRule = status === "NG" ? (reason.includes("Manual") ? "manual" : "presence") : null;
  const inspecting = status === "PROCESSING";
  return {
    inspection_id: inspecting || status === "WAITING" ? UUID("500") : UUID("510"),
    sn,
    product_code: sn === null ? "" : "model_a",
    operator: OPERATOR,
    status,
    started_at: ISO(-8),
    completed_at: status === "PROCESSING" || status === "WAITING" ? null : ISO(0),
    duration_ms: status === "PROCESSING" || status === "WAITING" ? null : 4850,
    progress: status === "PROCESSING" ? 0.65 : status === "WAITING" ? 0 : 1,
    rules: buildRules(status, ngRule, reason),
    reason_codes: status === "NG" ? [reason.replace(/ /g, "_").toUpperCase()] : [],
  };
}

/** SVG data-URL mock frames: plain camera, detection boxes, annotated overlay. */
function frameSvg(width: number, height: number, overlay: string): string {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${overlay}</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

const PRODUCT_BOX = `<rect x="120" y="90" width="560" height="430" fill="none" stroke="#43a047" stroke-width="4"/><text x="126" y="116" fill="#43a047" font-size="20">product</text>`;
const COMPONENT_BOXES = `<rect x="150" y="130" width="90" height="60" fill="none" stroke="#ff5252" stroke-width="3"/><text x="156" y="154" fill="#ff5252" font-size="16">component_a</text><rect x="320" y="150" width="80" height="50" fill="none" stroke="#ff5252" stroke-width="3"/><text x="326" y="174" fill="#ff5252" font-size="16">component_b</text><rect x="500" y="420" width="120" height="60" fill="none" stroke="#ff5252" stroke-width="3"/><text x="506" y="444" fill="#ff5252" font-size="16">manual</text>`;
const GRID = Array.from({ length: 6 }, (_, i) => `<rect x="0" y="${(i * 100) % 600}" width="800" height="2" fill="#1f2329"/><rect x="${(i * 130) % 800}" y="0" width="2" height="600" fill="#1f2329"/>`).join("");

function mockImages(inspectionId: string): InspectionImages {
  const base = GRID + PRODUCT_BOX;
  return {
    inspection_id: inspectionId,
    original: frameSvg(800, 600, GRID),
    detection: frameSvg(800, 600, base + COMPONENT_BOXES),
    annotated: frameSvg(800, 600, base + COMPONENT_BOXES + `<text x="20" y="40" fill="#fff" font-size="22">${inspectionId.slice(-6)}</text>`),
    original_status: "AVAILABLE",
    detection_status: "AVAILABLE",
    annotated_status: "AVAILABLE",
  };
}

const LINE = "LINE-1";

const INITIAL_LOGS: LogEvent[] = [
  { logged_at: ISO(-2), level: "INFO", component: "edge.rule", message: "rule evaluation completed", trace_id: null },
  { logged_at: ISO(-6), level: "INFO", component: "edge.detection", message: "components: component_a 0.91, component_b 0.84, manual 0.96", trace_id: null },
  { logged_at: ISO(-9), level: "INFO", component: "edge.detection", message: "product detected (conf 0.93)", trace_id: null },
  { logged_at: ISO(-12), level: "INFO", component: "edge.inspection", message: "inspection started SN-0001", trace_id: null },
  { logged_at: ISO(-60), level: "WARN", component: "edge.upload", message: "upload retry scheduled", trace_id: null },
];

/**
 * In-memory edge client used to develop and test the dashboard without a
 * backend. Data is deterministic and realistic for the MVP scope.
 */
export class MockApiClient implements ApiClient {
  #records: InspectionRecord[] = RECORDS;
  #uploads: UploadTask[] = UPLOADS;
  #paused = false;
  #current: CurrentInspection = buildCurrent("SN-0001", "PROCESSING");
  #queueIndex = 0;
  #logs: LogEvent[] = INITIAL_LOGS;

  #log(level: "INFO" | "WARN" | "ERROR", component: string, message: string): void {
    this.#logs = [{ logged_at: ISO(0), level, component, message, trace_id: null }, ...this.#logs];
  }
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
    return { items: this.#logs.slice(0, limit ?? 50), next_cursor: null };
  }

  // ---- Operator workflow ----

  async getCurrentInspection(): Promise<CurrentInspection> {
    return this.#current;
  }

  async confirmInspectionResult(): Promise<CurrentInspection> {
    if (this.#current.status !== "PROCESSING") return this.#current;
    const item = OPERATOR_QUEUE[this.#queueIndex];
    this.#current = buildCurrent(item.sn, item.result, item.reason);
    this.#log("INFO", "edge.inspection", `inspection ${this.#current.sn ?? "-"} confirmed ${this.#current.status}`);
    return this.#current;
  }

  async continueNextInspection(): Promise<CurrentInspection> {
    this.#queueIndex = (this.#queueIndex + 1) % OPERATOR_QUEUE.length;
    const item = OPERATOR_QUEUE[this.#queueIndex];
    this.#current = buildCurrent(item.sn, "PROCESSING");
    this.#log("INFO", "edge.inspection", "advancing to next product");
    return this.#current;
  }

  async triggerManualInspection(): Promise<CurrentInspection> {
    const item = OPERATOR_QUEUE[this.#queueIndex];
    this.#current = buildCurrent(item.sn, "PROCESSING");
    this.#log("INFO", "edge.inspection", "manual inspection triggered");
    return this.#current;
  }

  async getInspectionImages(inspectionId: string): Promise<InspectionImages> {
    await this.getInspection(inspectionId); // 404 on unknown
    return mockImages(inspectionId);
  }

  async getTraceability(sn: string): Promise<TraceabilityView> {
    const view = TRACEABILITY[sn];
    if (!view) throw new ApiError(404, "SN_NOT_FOUND", `no traceability for ${sn}`);
    return view;
  }

  async getStatistics(filter?: StatisticsFilter): Promise<StatisticsSummary> {
    let records = this.#records;
    if (filter?.from) records = records.filter((r) => r.completed_at >= (filter.from as string));
    if (filter?.to) records = records.filter((r) => r.completed_at <= (filter.to as string));
    void LINE;
    const passCount = records.filter((r) => r.decision.business_result === "OK").length;
    const total = records.length;
    return {
      total_inspections: total,
      pass_count: passCount,
      ng_count: total - passCount,
      pass_rate: total === 0 ? 0 : passCount / total,
    };
  }

  // The web dev test harness only exists in the HTTP client; the in-memory
  // mock has no inference backend (ADR-014).
  devInspectFrame(): Promise<InspectionRecord> {
    return Promise.reject(
      new ApiError(404, "DEV_TOOLS_DISABLED", "dev test tools require the HTTP client"),
    );
  }

  devInspectVideo(): Promise<VideoInspectResult> {
    return Promise.reject(
      new ApiError(404, "DEV_TOOLS_DISABLED", "dev test tools require the HTTP client"),
    );
  }
}
