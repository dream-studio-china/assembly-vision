import { beforeEach, describe, expect, it, vi } from "vitest";

async function load() {
  vi.resetModules();
  const api = await import("@assemblyvision/api-client");
  const mod = await import("../src/services/client");
  return {
    getApiClient: mod.getApiClient,
    MockApiClient: api.MockApiClient,
    HttpApiClient: api.HttpApiClient,
  };
}

describe("dashboard client mode selection (F5)", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("defaults to the mock client when no mode is set (dev default)", async () => {
    const { getApiClient, MockApiClient } = await load();
    expect(getApiClient()).toBeInstanceOf(MockApiClient);
  });

  it("selects the mock client in explicit mock mode", async () => {
    vi.stubEnv("VITE_API_MODE", "mock");
    const { getApiClient, MockApiClient } = await load();
    expect(getApiClient()).toBeInstanceOf(MockApiClient);
  });

  it("selects the HTTP client in http mode", async () => {
    vi.stubEnv("VITE_API_MODE", "http");
    const { getApiClient, HttpApiClient } = await load();
    expect(getApiClient()).toBeInstanceOf(HttpApiClient);
  });

  it("http mode without a base URL talks to the same-origin API", async () => {
    vi.stubEnv("VITE_API_MODE", "http");
    vi.stubEnv("VITE_API_BASE_URL", "");
    const seen: string[] = [];
    const fetchImpl = ((input: RequestInfo | URL) => {
      seen.push(String(input));
      return Promise.resolve(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }) as typeof fetch;
    vi.stubGlobal("fetch", fetchImpl);

    const { getApiClient } = await load();
    const client = getApiClient();
    await client.getHealthLive();
    expect(seen).toEqual(["/api/v1/health/live"]);
  });
});
