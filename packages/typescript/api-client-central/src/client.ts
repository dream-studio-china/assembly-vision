/**
 * Central API client for the admin-web pilot (C3).
 *
 * Authenticates the pilot administrator through the short-lived HttpOnly
 * session cookie (exchanged via POST /auth/session), so browser fetches never
 * store the long-lived bearer credential. Server errors surface as typed
 * problem responses.
 */
import type { components } from "./central/generated/api";

export type AdminMe = components["schemas"]["AdminMe"];
export type InspectionPage = components["schemas"]["InspectionPage"];
export type InspectionSummary = components["schemas"]["InspectionSummaryOut"];
export type InspectionDetail = components["schemas"]["InspectionDetailOut"];
export type DashboardSummary = components["schemas"]["DashboardSummaryOut"];
export type DashboardTimeseries = components["schemas"]["DashboardTimeseriesOut"];
export type DeviceStatus = components["schemas"]["DeviceStatusOut"];
export type Review = components["schemas"]["ReviewOut"];
export type ReviewQueuePage = components["schemas"]["ReviewQueuePage"];
export type ReviewSubmit = components["schemas"]["ReviewSubmit"];
export type Site = components["schemas"]["SiteOut"];
export type Line = components["schemas"]["LineOut"];
export type Device = components["schemas"]["DeviceOut"];
export type Problem = components["schemas"]["Problem"];

export interface InspectionQuery {
  site_id?: number;
  line_id?: number;
  device_row_id?: number;
  from_at?: string;
  to_at?: string;
  barcode?: string;
  product?: string;
  business_result?: "OK" | "NG";
  internal_decision?: "OK" | "NG" | "UNCERTAIN";
  reason?: string;
  model_version?: string;
  rule_version?: string;
  cursor?: string;
  limit?: number;
}

export interface DashboardQuery {
  site_id?: number;
  line_id?: number;
  device_row_id?: number;
  from_at?: string;
  to_at?: string;
  business_result?: "OK" | "NG";
}

export class CentralApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, detail: string) {
    super(detail);
    this.status = status;
    this.code = code;
  }
}

function toQuery(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const raw = search.toString();
  return raw ? `?${raw}` : "";
}

export class CentralApiClient {
  constructor(private readonly baseUrl = "/api/v1") {}

  async login(token: string): Promise<void> {
    await this.request<void>("/auth/session", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
  }

  async getMe(): Promise<AdminMe> {
    return this.request<AdminMe>("/auth/me");
  }

  async logout(): Promise<void> {
    // Revokes the session cookie server-side and clears it (idempotent).
    await this.request<void>("/auth/session/revoke", { method: "POST" });
  }

  async listInspections(query: InspectionQuery = {}): Promise<InspectionPage> {
    return this.request<InspectionPage>(`/inspections${toQuery(query)}`);
  }

  async getInspection(inspectionId: string): Promise<InspectionDetail> {
    return this.request<InspectionDetail>(`/inspections/${inspectionId}`);
  }

  async getDashboardSummary(query: DashboardQuery = {}): Promise<DashboardSummary> {
    return this.request<DashboardSummary>(`/dashboard/summary${toQuery(query)}`);
  }

  async getDashboardTimeseries(query: DashboardQuery = {}): Promise<DashboardTimeseries> {
    return this.request<DashboardTimeseries>(`/dashboard/timeseries${toQuery(query)}`);
  }

  async getDashboardDevices(): Promise<DeviceStatus[]> {
    return this.request<DeviceStatus[]>("/dashboard/devices");
  }

  async listSites(): Promise<Site[]> {
    return this.request<Site[]>("/sites");
  }

  async listLines(siteId?: number): Promise<Line[]> {
    return this.request<Line[]>(`/lines${toQuery({ site_id: siteId })}`);
  }

  async listDevices(): Promise<Device[]> {
    return this.request<Device[]>("/devices");
  }

  async listReviewQueue(cursor?: string, limit = 50): Promise<ReviewQueuePage> {
    return this.request<ReviewQueuePage>(`/reviews/queue${toQuery({ cursor, limit })}`);
  }

  async listReviewHistory(inspectionId: string): Promise<Review[]> {
    return this.request<Review[]>(`/inspections/${inspectionId}/reviews`);
  }

  async submitReview(
    inspectionId: string,
    body: ReviewSubmit,
    idempotencyKey: string,
    ifMatch?: number,
  ): Promise<Review> {
    const headers: Record<string, string> = { "Idempotency-Key": idempotencyKey };
    if (ifMatch !== undefined) {
      headers["If-Match"] = String(ifMatch);
    }
    return this.request<Review>(`/inspections/${inspectionId}/reviews`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    if (response.status === 204) {
      return undefined as T;
    }
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      const body = (await response.json()) as T | Problem;
      if (!response.ok) {
        const problem = body as Problem;
        throw new CentralApiError(response.status, problem.code, problem.detail);
      }
      return body as T;
    }
    if (!response.ok) {
      throw new CentralApiError(response.status, `HTTP_${response.status}`, response.statusText);
    }
    throw new CentralApiError(response.status, "INVALID_RESPONSE", "unexpected response type");
  }
}

export const apiClient = new CentralApiClient();
