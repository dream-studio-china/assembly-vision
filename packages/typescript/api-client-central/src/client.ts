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
export type ComponentPage = components["schemas"]["ComponentPage"];
export type ProductPage = components["schemas"]["ProductPage"];
export type ProductDetail = components["schemas"]["ProductDetailOut"];
export type ProductVersion = components["schemas"]["ProductVersionOut"];
export type ProductVersionCreate = components["schemas"]["ProductVersionCreate"];
export type RulePage = components["schemas"]["RulePage"];
export type RuleDetail = components["schemas"]["RuleDetailOut"];
export type RuleVersion = components["schemas"]["RuleVersionOut"];
export type RuleVersionCreate = components["schemas"]["RuleVersionCreate"];
export type ModelPage = components["schemas"]["ModelPage"];
export type ModelDetail = components["schemas"]["ModelDetailOut"];
export type ModelVersion = components["schemas"]["ModelVersionOut"];
export type ModelManifest = components["schemas"]["ModelManifestIn"];
export type DesiredConfiguration = components["schemas"]["DesiredConfigurationOut"];
export type DesiredConfigurationIn = components["schemas"]["DesiredConfigurationIn"];
export type DesiredConfigurationPage = components["schemas"]["DesiredConfigurationPage"];

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

  // -- metadata governance (C5) -------------------------------------------

  async listComponents(): Promise<ComponentPage> {
    return this.request<ComponentPage>("/components");
  }

  async listProducts(): Promise<ProductPage> {
    return this.request<ProductPage>("/products");
  }

  async getProduct(productId: number): Promise<ProductDetail> {
    return this.request<ProductDetail>(`/products/${productId}`);
  }

  async getProductVersion(versionId: string): Promise<ProductVersion> {
    return this.request<ProductVersion>(`/product-versions/${versionId}`);
  }

  async listRules(): Promise<RulePage> {
    return this.request<RulePage>("/rules");
  }

  async getRule(ruleId: number): Promise<RuleDetail> {
    return this.request<RuleDetail>(`/rules/${ruleId}`);
  }

  async getRuleVersion(versionId: string): Promise<RuleVersion> {
    return this.request<RuleVersion>(`/rule-versions/${versionId}`);
  }

  async listModels(): Promise<ModelPage> {
    return this.request<ModelPage>("/models");
  }

  async getModel(modelId: number): Promise<ModelDetail> {
    return this.request<ModelDetail>(`/models/${modelId}`);
  }

  async getModelVersion(versionId: string): Promise<ModelVersion> {
    return this.request<ModelVersion>(`/model-versions/${versionId}`);
  }

  async listDesiredConfigurations(): Promise<DesiredConfigurationPage> {
    return this.request<DesiredConfigurationPage>("/device-configurations");
  }

  async getDesiredConfiguration(deviceId: string): Promise<DesiredConfiguration> {
    return this.request<DesiredConfiguration>(
      `/devices/${deviceId}/desired-configuration`,
    );
  }

  async putDesiredConfiguration(
    deviceId: string,
    body: DesiredConfigurationIn,
    ifMatch: number,
  ): Promise<DesiredConfiguration> {
    return this.request<DesiredConfiguration>(`/devices/${deviceId}/desired-configuration`, {
      method: "PUT",
      headers: { "If-Match": String(ifMatch) },
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
