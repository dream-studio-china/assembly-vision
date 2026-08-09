import { MockApiClient } from "@assemblyvision/api-client";
import { HttpApiClient } from "@assemblyvision/api-client";
import type { ApiClient } from "@assemblyvision/api-client";
import { assertProductionHttpMode } from "../vite-mode";

/**
 * Single client factory for the dashboard.
 *
 * Data mode is explicit (F5, ADR-012):
 * - `VITE_API_MODE=http` talks to the FastAPI backend. An omitted
 *   `VITE_API_BASE_URL` means same-origin `/api/v1` so the bundle served by
 *   `assemblyvision serve` reads its own API.
 * - `VITE_API_MODE=mock` (or unset, the dev default) runs against the
 *   deterministic in-memory mock.
 *
 * An absent base URL alone never silently selects the mock in a production
 * build: the build must pass `VITE_API_MODE=http` (enforced by the Vite
 * plugin and re-checked here in the shipped bundle).
 *
 * Token-protected development across origins: the viewer session cookie is
 * same-origin, so a Vite dev server pointed at a remote edge host keeps the
 * bearer token in memory (never persisted) and attaches it to every request.
 * Same-origin deployments keep the HttpOnly-cookie flow and never see the
 * token.
 */
let client: ApiClient | null = null;
let viewerToken: string | null = null;
const mode = (import.meta.env.VITE_API_MODE as string | undefined) ?? "mock";
assertProductionHttpMode(mode, import.meta.env.PROD);

export function isMockMode(): boolean {
  return mode === "mock";
}

export function isHttpMode(): boolean {
  return mode === "http";
}

export function getApiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
}

/**
 * Browser WebSocket URL for the runtime event channel.
 *
 * The API base URL is an origin without a path prefix, so the /api/v1 prefix
 * is preserved explicitly here (PR-023 F01). The same-origin fallback derives
 * the ws/wss scheme from the page itself.
 */
export function getRuntimeWsUrl(): string {
  const base = getApiBaseUrl();
  if (base.startsWith("http")) {
    const url = new URL(base);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = "/api/v1/ws/runtime";
    return url.toString();
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/v1/ws/runtime`;
}

/**
 * Exchange the in-memory viewer credential for a one-time runtime ticket.
 *
 * Browser WebSocket cannot set an Authorization header and cross-origin
 * connections do not receive the same-origin session cookie, so the dashboard
 * obtains a short-lived ticket over authenticated REST and sends it as the
 * negotiated WebSocket subprotocol, never in the URL (PR-023 F01).
 */
export async function requestRuntimeTicket(): Promise<string> {
  const response = await fetch(`${getApiBaseUrl()}/api/v1/ws/runtime/ticket`, {
    method: "POST",
    headers: viewerToken ? { Authorization: `Bearer ${viewerToken}` } : undefined,
    credentials: isCrossOriginHttp() ? "omit" : "same-origin",
  });
  if (!response.ok) {
    throw new Error("The edge runtime ticket was not accepted.");
  }
  const body = (await response.json()) as { ticket: string };
  return body.ticket;
}

function isCrossOrigin(): boolean {
  const base = getApiBaseUrl();
  if (!base || typeof window === "undefined") return false;
  return new URL(base, window.location.origin).origin !== window.location.origin;
}

/** True when the HTTP client talks to a different origin than the page. */
export function isCrossOriginHttp(): boolean {
  return isHttpMode() && isCrossOrigin();
}

export async function createViewerSession(token: string): Promise<void> {
  const crossOrigin = isCrossOriginHttp();
  const response = await fetch(`${getApiBaseUrl()}/api/v1/auth/session`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    credentials: crossOrigin ? "omit" : "same-origin",
  });
  if (!response.ok) {
    throw new Error("The edge viewer token was not accepted.");
  }
  // Same-origin deployments exchange the token for the HttpOnly session
  // cookie; cross-origin dev cannot receive that cookie, so the token stays in
  // memory for the lifetime of the page and is attached to each request.
  viewerToken = crossOrigin ? token : null;
}

/** Fetch protected media content and return a renderable blob URL. */
export async function loadMediaBlobUrl(url: string): Promise<string> {
  const pageOrigin = window.location.origin;
  const target = new URL(url, pageOrigin);
  const apiOrigin = new URL(getApiBaseUrl() || "/", pageOrigin).origin;
  // Never attach the viewer credential to a foreign origin: only the page
  // origin or the configured edge API origin may receive it (AUDIT-001 4.5).
  if (target.origin !== pageOrigin && target.origin !== apiOrigin) {
    throw new Error(`refusing to fetch media from foreign origin ${target.origin}`);
  }
  const response = await fetch(url, {
    headers: viewerToken ? { Authorization: `Bearer ${viewerToken}` } : undefined,
    credentials: isCrossOriginHttp() ? "omit" : "same-origin",
  });
  if (!response.ok) {
    throw new Error(`media load failed with status ${response.status}`);
  }
  return URL.createObjectURL(await response.blob());
}

export function getApiClient(): ApiClient {
  if (client !== null) return client;
  if (mode === "http") {
    client = new HttpApiClient(getApiBaseUrl(), undefined, () => viewerToken ?? undefined);
  } else {
    client = new MockApiClient();
  }
  return client;
}
