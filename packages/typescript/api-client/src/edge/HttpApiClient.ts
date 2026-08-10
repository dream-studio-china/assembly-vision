import type { ApiClient } from "./ApiClient";
import { ApiError } from "./ApiError";
import type { Validator } from "./validate";
import { validators } from "./validate";
import type {
  CameraState,
  CurrentInspection,
  DeviceStatus,
  EffectiveConfiguration,
  InspectionFilter,
  InspectionImages,
  InspectionRecord,
  InspectionRuntimeState,
  InspectionSummary,
  LogEvent,
  MediaMetadata,
  Page,
  Problem,
  RetryUploadRequest,
  StatisticsFilter,
  StatisticsSummary,
  TraceabilityView,
  UploadTask,
  VideoInspectResult,
} from "./types";

function toQuery(filter: InspectionFilter | undefined): string {
  if (!filter) return "";
  const params = new URLSearchParams();
  if (filter.business_result) params.set("business_result", filter.business_result);
  if (filter.internal_decision) params.set("internal_decision", filter.internal_decision);
  if (filter.barcode) params.set("barcode", filter.barcode);
  if (filter.product) params.set("product", filter.product);
  if (filter.sn) params.set("sn", filter.sn);
  if (filter.from) params.set("from", filter.from);
  if (filter.to) params.set("to", filter.to);
  if (filter.cursor) params.set("cursor", filter.cursor);
  if (filter.limit !== undefined) params.set("limit", String(filter.limit));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

async function parseProblem(body: unknown): Promise<Problem | null> {
  if (typeof body !== "object" || body === null) return null;
  const record = body as Record<string, unknown>;
  if (typeof record.type !== "string" || typeof record.title !== "string") return null;
  return record as unknown as Problem;
}

/** Outgoing media label for raw image/video uploads (PR-014 F11). */
function mediaContentType(blob: Blob): string {
  return blob.type || "application/octet-stream";
}

/**
 * HTTP implementation of the edge API contract against a FastAPI backend.
 *
 * `baseUrl` is the origin (and optional path prefix) of the edge service,
 * e.g. `http://edge-host:8000`. All requests go under `/api/v1`. The caller
 * provides a `fetch` implementation so tests can inject a fake; browsers and
 * Node both default to the global `fetch`.
 */
export class HttpApiClient implements ApiClient {
  readonly #baseUrl: string;
  readonly #fetchImpl: typeof fetch;
  readonly #getToken: () => string | undefined;

  constructor(
    baseUrl: string,
    fetchImpl: typeof fetch = globalThis.fetch,
    getToken: () => string | undefined = () => undefined,
  ) {
    // Strip trailing slashes linearly; a regex like /\/+$/ on uncontrolled
    // input is flagged as ReDoS-prone by CodeQL.
    let trimmed = baseUrl;
    while (trimmed.endsWith("/")) trimmed = trimmed.slice(0, -1);
    this.#baseUrl = trimmed;
    this.#fetchImpl = fetchImpl.bind(globalThis);
    this.#getToken = getToken;
  }

  async #request<T>(path: string, init?: RequestInit, validator?: Validator): Promise<T> {
    const url = `${this.#baseUrl}/api/v1${path}`;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(init?.headers as Record<string, string> | undefined),
    };
    // Cross-origin development cannot hold the same-origin viewer session
    // cookie, so an in-memory bearer token is attached to every request.
    const token = this.#getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    let response: Response;
    try {
      response = await this.#fetchImpl(url, {
        ...init,
        credentials: "same-origin",
        headers,
      });
    } catch (error) {
      throw new ApiError(0, "NETWORK_ERROR", `request failed: ${String(error)}`);
    }
    if (response.status === 204) return undefined as T;
    const body = (await response.json().catch(() => null)) as unknown;
    if (!response.ok) {
      const problem = await parseProblem(body);
      throw new ApiError(
        response.status,
        problem?.code ?? `HTTP_${response.status}`,
        problem?.detail ?? response.statusText,
        problem,
      );
    }
    if (validator) {
      try {
        validator(body);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        throw new ApiError(0, "INVALID_RESPONSE", `invalid response from ${path}: ${message}`);
      }
    }
    return body as T;
  }

  getHealthLive(): Promise<{ status: string }> {
    return this.#request("/health/live", undefined, validators.healthLive);
  }

  getHealthReady(): Promise<DeviceStatus> {
    return this.#request("/health/ready", undefined, validators.deviceStatus);
  }

  getDeviceStatus(): Promise<DeviceStatus> {
    return this.#request("/device/status", undefined, validators.deviceStatus);
  }

  getCameraState(): Promise<CameraState> {
    return this.#request("/camera/state", undefined, validators.cameraState);
  }

  getInspectionState(): Promise<InspectionRuntimeState> {
    return this.#request("/inspection/state", undefined, validators.runtimeState);
  }

  listInspections(filter?: InspectionFilter): Promise<Page<InspectionSummary>> {
    return this.#request(`/inspections${toQuery(filter)}`, undefined, validators.inspectionPage);
  }

  getInspection(inspectionId: string): Promise<InspectionRecord> {
    return this.#request(
      `/inspections/${encodeURIComponent(inspectionId)}`,
      undefined,
      validators.inspectionRecord,
    );
  }

  listInspectionMedia(inspectionId: string): Promise<MediaMetadata[]> {
    return this.#request(
      `/inspections/${encodeURIComponent(inspectionId)}/media`,
      undefined,
      validators.mediaList,
    );
  }

  listUploads(cursor?: string, limit?: number): Promise<Page<UploadTask>> {
    const params = new URLSearchParams();
    if (cursor) params.set("cursor", cursor);
    if (limit !== undefined) params.set("limit", String(limit));
    const qs = params.toString();
    return this.#request(`/uploads${qs ? `?${qs}` : ""}`, undefined, validators.uploadPage);
  }

  retryUpload(uploadTaskId: string, request?: RetryUploadRequest): Promise<UploadTask> {
    const init: RequestInit = { method: "POST" };
    if (request) {
      init.body = JSON.stringify({ reason: request.reason ?? null });
      init.headers = { "Content-Type": "application/json" };
    }
    return this.#request(
      `/uploads/${encodeURIComponent(uploadTaskId)}/retry`,
      init,
      validators.uploadTask,
    );
  }

  getEffectiveConfiguration(): Promise<EffectiveConfiguration> {
    return this.#request("/configuration/effective", undefined, validators.effectiveConfiguration);
  }

  listLogs(cursor?: string, limit?: number): Promise<Page<LogEvent>> {
    const params = new URLSearchParams();
    if (cursor) params.set("cursor", cursor);
    if (limit !== undefined) params.set("limit", String(limit));
    const qs = params.toString();
    return this.#request(`/logs${qs ? `?${qs}` : ""}`, undefined, validators.logPage);
  }

  // Operator workflow (future FastAPI endpoints; see ApiClient contract).
  getCurrentInspection(): Promise<CurrentInspection> {
    return this.#request("/inspection/current");
  }

  confirmInspectionResult(): Promise<CurrentInspection> {
    return this.#request("/inspection/confirm", { method: "POST" });
  }

  continueNextInspection(): Promise<CurrentInspection> {
    return this.#request("/inspection/next", { method: "POST" });
  }

  triggerManualInspection(): Promise<CurrentInspection> {
    return this.#request("/inspection/manual", { method: "POST" });
  }

  getInspectionImages(inspectionId: string): Promise<InspectionImages> {
    return this.#request(
      `/inspections/${encodeURIComponent(inspectionId)}/images`,
      undefined,
      validators.inspectionImages,
    );
  }

  getTraceability(sn: string): Promise<TraceabilityView> {
    return this.#request(`/traceability/${encodeURIComponent(sn)}`, undefined, validators.traceabilityView);
  }

  getStatistics(filter?: StatisticsFilter): Promise<StatisticsSummary> {
    const params = new URLSearchParams();
    if (filter?.from) params.set("from", filter.from);
    if (filter?.to) params.set("to", filter.to);
    if (filter?.line) params.set("line", filter.line);
    const qs = params.toString();
    return this.#request(`/statistics${qs ? `?${qs}` : ""}`, undefined, validators.statisticsSummary);
  }

  devInspectFrame(
    instanceId: string,
    image: Blob,
    opts?: { persist?: boolean },
  ): Promise<InspectionRecord> {
    const params = new URLSearchParams();
    if (instanceId) params.set("instance_id", instanceId);
    if (opts?.persist === false) params.set("persist", "false");
    return this.#request(
      `/dev/inspect-frame?${params.toString()}`,
      { method: "POST", body: image, headers: { "Content-Type": mediaContentType(image) } },
      validators.inspectionRecord,
    );
  }

  devInspectVideo(
    instanceId: string,
    video: Blob,
    opts?: { step?: number },
  ): Promise<VideoInspectResult> {
    const params = new URLSearchParams();
    if (instanceId) params.set("instance_id", instanceId);
    if (opts?.step !== undefined) params.set("step", String(opts.step));
    return this.#request(
      `/dev/inspect-video?${params.toString()}`,
      { method: "POST", body: video, headers: { "Content-Type": mediaContentType(video) } },
      validators.videoInspectResult,
    );
  }
}

export type { CameraState, InspectionRuntimeState, UploadTask };
