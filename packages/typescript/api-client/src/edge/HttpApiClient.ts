import type { ApiClient } from "./ApiClient";
import { ApiError } from "./ApiError";
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
  StatisticsFilter,
  StatisticsSummary,
  TraceabilityView,
  UploadTask,
} from "./types";

function toQuery(filter: InspectionFilter | undefined): string {
  if (!filter) return "";
  const params = new URLSearchParams();
  if (filter.business_result) params.set("business_result", filter.business_result);
  if (filter.internal_decision) params.set("internal_decision", filter.internal_decision);
  if (filter.barcode) params.set("barcode", filter.barcode);
  if (filter.product) params.set("product", filter.product);
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

  constructor(baseUrl: string, fetchImpl: typeof fetch = globalThis.fetch) {
    this.#baseUrl = baseUrl.replace(/\/+$/, "");
    this.#fetchImpl = fetchImpl.bind(globalThis);
  }

  async #request<T>(path: string, init?: RequestInit): Promise<T> {
    const url = `${this.#baseUrl}/api/v1${path}`;
    let response: Response;
    try {
      response = await this.#fetchImpl(url, {
        ...init,
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", ...init?.headers },
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
    return body as T;
  }

  getHealthLive(): Promise<{ status: string }> {
    return this.#request("/health/live");
  }

  getHealthReady(): Promise<DeviceStatus> {
    return this.#request("/health/ready");
  }

  getDeviceStatus(): Promise<DeviceStatus> {
    return this.#request("/device/status");
  }

  getCameraState(): Promise<CameraState> {
    return this.#request("/camera/state");
  }

  getInspectionState(): Promise<InspectionRuntimeState> {
    return this.#request("/inspection/state");
  }

  listInspections(filter?: InspectionFilter): Promise<Page<InspectionSummary>> {
    return this.#request(`/inspections${toQuery(filter)}`);
  }

  getInspection(inspectionId: string): Promise<InspectionRecord> {
    return this.#request(`/inspections/${encodeURIComponent(inspectionId)}`);
  }

  listInspectionMedia(inspectionId: string): Promise<MediaMetadata[]> {
    return this.#request(`/inspections/${encodeURIComponent(inspectionId)}/media`);
  }

  listUploads(cursor?: string, limit?: number): Promise<Page<UploadTask>> {
    const params = new URLSearchParams();
    if (cursor) params.set("cursor", cursor);
    if (limit !== undefined) params.set("limit", String(limit));
    const qs = params.toString();
    return this.#request(`/uploads${qs ? `?${qs}` : ""}`);
  }

  getEffectiveConfiguration(): Promise<EffectiveConfiguration> {
    return this.#request("/configuration/effective");
  }

  listLogs(cursor?: string, limit?: number): Promise<Page<LogEvent>> {
    const params = new URLSearchParams();
    if (cursor) params.set("cursor", cursor);
    if (limit !== undefined) params.set("limit", String(limit));
    const qs = params.toString();
    return this.#request(`/logs${qs ? `?${qs}` : ""}`);
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
    return this.#request(`/inspections/${encodeURIComponent(inspectionId)}/images`);
  }

  getTraceability(sn: string): Promise<TraceabilityView> {
    return this.#request(`/traceability/${encodeURIComponent(sn)}`);
  }

  getStatistics(filter?: StatisticsFilter): Promise<StatisticsSummary> {
    const params = new URLSearchParams();
    if (filter?.from) params.set("from", filter.from);
    if (filter?.to) params.set("to", filter.to);
    if (filter?.line) params.set("line", filter.line);
    const qs = params.toString();
    return this.#request(`/statistics${qs ? `?${qs}` : ""}`);
  }
}

export type { CameraState, InspectionRuntimeState, UploadTask };
