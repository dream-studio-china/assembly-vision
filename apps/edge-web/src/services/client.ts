import { MockApiClient } from "@assemblyvision/api-client";
import { HttpApiClient } from "@assemblyvision/api-client";
import type { ApiClient } from "@assemblyvision/api-client";

/**
 * Single client factory for the dashboard.
 *
 * When `VITE_API_BASE_URL` is set the app talks to a real FastAPI backend via
 * the HTTP client; otherwise it runs entirely against the in-memory mock.
 * Page and store code never see which implementation is active.
 */
let client: ApiClient | null = null;

export function getApiClient(): ApiClient {
  if (client !== null) return client;
  const baseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined;
  client = baseUrl ? new HttpApiClient(baseUrl) : new MockApiClient();
  return client;
}
