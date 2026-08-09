import { beforeEach, describe, expect, it, vi } from "vitest";

async function load() {
  vi.resetModules();
  const api = await import("@assemblyvision/api-client");
  const mod = await import("../src/services/client");
  return {
    getApiClient: mod.getApiClient,
    isMockMode: mod.isMockMode,
    isCrossOriginHttp: mod.isCrossOriginHttp,
    createViewerSession: mod.createViewerSession,
    loadMediaBlobUrl: mod.loadMediaBlobUrl,
    getRuntimeWsUrl: mod.getRuntimeWsUrl,
    requestRuntimeTicket: mod.requestRuntimeTicket,
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
    const { getApiClient, isMockMode, HttpApiClient } = await load();
    expect(getApiClient()).toBeInstanceOf(HttpApiClient);
    expect(isMockMode()).toBe(false);
  });

  it("reports mock mode for the dev/mock client", async () => {
    const { isMockMode } = await load();
    expect(isMockMode()).toBe(true);
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

describe("token-protected cross-origin development (gap 1)", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("keeps the bearer token in memory and attaches it to requests", async () => {
    vi.stubEnv("VITE_API_MODE", "http");
    vi.stubEnv("VITE_API_BASE_URL", "http://edge-host:8000");
    vi.stubGlobal("window", { location: { origin: "http://localhost:5173" } });
    const seen: { url: string; headers: Record<string, string>; credentials?: RequestCredentials }[] =
      [];
    const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
      seen.push({
        url: String(input),
        headers: (init?.headers as Record<string, string>) ?? {},
        credentials: init?.credentials,
      });
      return new Response(undefined, { status: 204 });
    }) as typeof fetch;
    vi.stubGlobal("fetch", fetchImpl);

    const { createViewerSession, isCrossOriginHttp, getApiClient } = await load();
    expect(isCrossOriginHttp()).toBe(true);
    await createViewerSession("secret-token");

    await getApiClient().getHealthLive();
    const sessionCall = seen.find((r) => r.url.includes("/auth/session"));
    expect(sessionCall?.headers["Authorization"]).toBe("Bearer secret-token");
    const healthCall = seen.find((r) => r.url.includes("/health/live"));
    expect(healthCall?.headers["Authorization"]).toBe("Bearer secret-token");
    // Cross-origin requests cannot use the same-origin session cookie.
    expect(healthCall?.credentials).not.toBe("include");
  });

  it("keeps the HttpOnly-cookie flow and never stores the token same-origin", async () => {
    vi.stubEnv("VITE_API_MODE", "http");
    vi.stubEnv("VITE_API_BASE_URL", "");
    const seen: { url: string; headers: Record<string, string>; credentials?: RequestCredentials }[] =
      [];
    const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
      seen.push({
        url: String(input),
        headers: (init?.headers as Record<string, string>) ?? {},
        credentials: init?.credentials,
      });
      return new Response(undefined, { status: 204 });
    }) as typeof fetch;
    vi.stubGlobal("fetch", fetchImpl);

    const { createViewerSession, isCrossOriginHttp, getApiClient } = await load();
    expect(isCrossOriginHttp()).toBe(false);
    await createViewerSession("secret-token");

    await getApiClient().getHealthLive();
    const sessionCall = seen.find((r) => r.url.includes("/auth/session"));
    expect(sessionCall?.credentials).toBe("same-origin");
    const healthCall = seen.find((r) => r.url.includes("/health/live"));
    expect(healthCall?.headers["Authorization"]).toBeUndefined();
    expect(healthCall?.credentials).toBe("same-origin");
  });

  it("loads protected media into a blob URL for cross-origin rendering", async () => {
    vi.stubEnv("VITE_API_MODE", "http");
    vi.stubEnv("VITE_API_BASE_URL", "http://edge-host:8000");
    vi.stubGlobal("window", { location: { origin: "http://localhost:5173" } });
    const blob = new Blob(["image-bytes"], { type: "image/jpeg" });
    const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const headers = (init?.headers as Record<string, string>) ?? {};
      if (url.includes("/auth/session")) {
        expect(headers["Authorization"]).toBe("Bearer secret-token");
        return new Response(undefined, { status: 204 });
      }
      expect(url).toContain("/media/");
      expect(headers["Authorization"]).toBe("Bearer secret-token");
      return new Response(blob, { status: 200 });
    }) as typeof fetch;
    vi.stubGlobal("fetch", fetchImpl);
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:edge-1");

    const { createViewerSession, loadMediaBlobUrl } = await load();
    await createViewerSession("secret-token");
    await expect(loadMediaBlobUrl("http://edge-host:8000/api/v1/media/abc/content")).resolves.toBe(
      "blob:edge-1",
    );
  });

  it("rejects media loads that the token cannot authenticate", async () => {
    vi.stubEnv("VITE_API_MODE", "http");
    vi.stubEnv("VITE_API_BASE_URL", "http://edge-host:8000");
    vi.stubGlobal("window", { location: { origin: "http://localhost:5173" } });
    const fetchImpl = (async () => new Response(null, { status: 401 })) as typeof fetch;
    vi.stubGlobal("fetch", fetchImpl);

    const { loadMediaBlobUrl } = await load();
    await expect(loadMediaBlobUrl("http://edge-host:8000/api/v1/media/abc/content")).rejects.toThrow(
      "media load failed",
    );
  });

  it("refuses to fetch media from a foreign origin", async () => {
    vi.stubEnv("VITE_API_MODE", "http");
    vi.stubEnv("VITE_API_BASE_URL", "http://edge-host:8000");
    vi.stubGlobal("window", { location: { origin: "http://localhost:5173" } });
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return new Response(null, { status: 200 });
    });
    vi.stubGlobal("fetch", fetchImpl);

    const { createViewerSession, loadMediaBlobUrl } = await load();
    await createViewerSession("secret-token");
    await expect(
      loadMediaBlobUrl("https://evil.example.com/media/abc/content"),
    ).rejects.toThrow("foreign origin");
    const mediaRequests = fetchImpl.mock.calls.filter(([url]) =>
      String(url).includes("/media/"),
    );
    expect(mediaRequests).toHaveLength(0);
  });
});

describe("runtime websocket url and ticket (PR-023 F01)", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("maps an http origin base to the /api/v1 runtime path", async () => {
    vi.stubEnv("VITE_API_MODE", "http");
    vi.stubEnv("VITE_API_BASE_URL", "http://edge-host:8000");
    const { getRuntimeWsUrl } = await load();
    expect(getRuntimeWsUrl()).toBe("ws://edge-host:8000/api/v1/ws/runtime");
  });

  it("maps an https origin base to wss", async () => {
    vi.stubEnv("VITE_API_MODE", "http");
    vi.stubEnv("VITE_API_BASE_URL", "https://edge-host:8443");
    const { getRuntimeWsUrl } = await load();
    expect(getRuntimeWsUrl()).toBe("wss://edge-host:8443/api/v1/ws/runtime");
  });

  it("uses the page origin when no base url is configured", async () => {
    vi.stubEnv("VITE_API_MODE", "http");
    vi.stubEnv("VITE_API_BASE_URL", "");
    vi.stubGlobal("window", { location: { protocol: "https:", host: "edge.test" } });
    const { getRuntimeWsUrl } = await load();
    expect(getRuntimeWsUrl()).toBe("wss://edge.test/api/v1/ws/runtime");
  });

  it("requests a runtime ticket with the in-memory bearer credential", async () => {
    vi.stubEnv("VITE_API_MODE", "http");
    vi.stubEnv("VITE_API_BASE_URL", "http://edge-host:8000");
    vi.stubGlobal("window", { location: { origin: "http://localhost:5173" } });
    const seen: { url: string; headers: Record<string, string> }[] = [];
    const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
      seen.push({
        url: String(input),
        headers: (init?.headers as Record<string, string>) ?? {},
      });
      if (String(input).includes("/auth/session")) return new Response(undefined, { status: 204 });
      return new Response(JSON.stringify({ ticket: "ticket-abc", expires_at: "2026-01-01T00:00:00Z", channel: "runtime" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;
    vi.stubGlobal("fetch", fetchImpl);

    const { createViewerSession, requestRuntimeTicket } = await load();
    await createViewerSession("secret-token");
    const ticket = await requestRuntimeTicket();
    expect(ticket).toBe("ticket-abc");
    const ticketCall = seen.find((r) => r.url.includes("/ws/runtime/ticket"));
    expect(ticketCall?.url).toBe("http://edge-host:8000/api/v1/ws/runtime/ticket");
    expect(ticketCall?.headers["Authorization"]).toBe("Bearer secret-token");
  });
});
