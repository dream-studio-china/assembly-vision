import { beforeEach, describe, expect, it, vi } from "vitest";

async function load() {
  vi.resetModules();
  const api = await import("@assemblyvision/api-client");
  const mod = await import("../src/services/inspectionService");
  return { getStatistics: mod.inspectionService.getStatistics, HttpApiClient: api.HttpApiClient };
}

describe("statistics line filter (AUDIT-001 4.5)", () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("passes the line filter through in mock mode", async () => {
    vi.stubEnv("VITE_API_MODE", "mock");
    const seen: Array<object | undefined> = [];
    const { getStatistics } = await load();
    const api = await import("@assemblyvision/api-client");
    vi.spyOn(api.MockApiClient.prototype, "getStatistics").mockImplementation(function (
      this: InstanceType<typeof api.MockApiClient>,
      filter?: object,
    ) {
      seen.push(filter);
      return Promise.resolve({
        total_inspections: 1,
        pass_count: 1,
        ng_count: 0,
        pass_rate: 1,
      });
    });
    await getStatistics({ line: "LINE-1" });
    expect(seen).toEqual([{ line: "LINE-1" }]);
  });

  it("strips the unsupported line filter in http mode", async () => {
    vi.stubEnv("VITE_API_MODE", "http");
    const seen: Array<object | undefined> = [];
    const { getStatistics, HttpApiClient } = await load();
    vi.spyOn(HttpApiClient.prototype, "getStatistics").mockImplementation(function (
      this: InstanceType<typeof HttpApiClient>,
      filter?: object,
    ) {
      seen.push(filter);
      return Promise.resolve({
        total_inspections: 1,
        pass_count: 1,
        ng_count: 0,
        pass_rate: 1,
      });
    });
    await getStatistics({ line: "LINE-1", from: "2026-08-01T00:00:00Z" });
    expect(seen).toEqual([{ from: "2026-08-01T00:00:00Z" }]);
  });
});
