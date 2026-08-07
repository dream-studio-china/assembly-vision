import { MockApiClient } from "@assemblyvision/api-client";
import { HttpApiClient } from "@assemblyvision/api-client";
import type { ApiClient } from "@assemblyvision/api-client";

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
 * build: the build must pass `VITE_API_MODE=http`.
 */
let client: ApiClient | null = null;
const mode = (import.meta.env.VITE_API_MODE as string | undefined) ?? "mock";

export function isMockMode(): boolean {
  return mode === "mock";
}

export function getApiClient(): ApiClient {
  if (client !== null) return client;
  if (mode === "http") {
    const baseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";
    client = new HttpApiClient(baseUrl);
  } else {
    client = new MockApiClient();
  }
  return client;
}
