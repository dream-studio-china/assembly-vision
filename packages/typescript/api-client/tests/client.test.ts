import { describe, expect, it } from "vitest";
import { ApiError } from "../src/edge/ApiError";
import { HttpApiClient } from "../src/edge/HttpApiClient";
import { MockApiClient } from "../src/edge/MockApiClient";

function fakeFetch(status: number, body: unknown): typeof fetch {
  return (async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })) as unknown as typeof fetch;
}

describe("MockApiClient", () => {
  it("returns deterministic inspection history", async () => {
    const client = new MockApiClient();
    const page = await client.listInspections();
    expect(page.items.length).toBeGreaterThan(0);
    expect(page.items[0].business_result).toBe("OK");
  });

  it("filters by business result", async () => {
    const client = new MockApiClient();
    const page = await client.listInspections({ business_result: "NG" });
    expect(page.items.every((i) => i.business_result === "NG")).toBe(true);
  });

  it("finds an inspection record with component evidence", async () => {
    const client = new MockApiClient();
    const page = await client.listInspections();
    const record = await client.getInspection(page.items[0].inspection_id);
    expect(record.evidence.length).toBeGreaterThan(0);
    expect(record.evidence.every((e) => ["PRESENT", "MISSING", "UNCERTAIN"].includes(e.state))).toBe(true);
  });

  it("pause then resume changes operational state", async () => {
    const client = new MockApiClient();
    const paused = await client.pauseInspection("test");
    expect(paused.state?.paused).toBe(true);
    await expect(client.pauseInspection("again")).rejects.toMatchObject({ code: "ALREADY_PAUSED" });
    const resumed = await client.resumeInspection("done");
    expect(resumed.state?.paused).toBe(false);
  });

  it("rejects resume when not paused", async () => {
    const client = new MockApiClient();
    await expect(client.resumeInspection("x")).rejects.toMatchObject({ code: "PRECONDITION_FAILED" });
  });

  it("404s for unknown inspections", async () => {
    const client = new MockApiClient();
    await expect(client.getInspection("00000000-0000-4000-8000-ffffffffffff")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("HttpApiClient", () => {
  it("calls /api/v1/health/live and parses JSON", async () => {
    const fetchImpl = fakeFetch(200, { status: "ok" });
    const client = new HttpApiClient("http://edge:8000", fetchImpl);
    await expect(client.getHealthLive()).resolves.toEqual({ status: "ok" });
  });

  it("builds cursor and limit query params for uploads", async () => {
    let called = "";
    const fetchImpl = ((input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      called = String(input);
      return Promise.resolve(new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 }));
    }) as typeof fetch;
    const client = new HttpApiClient("http://edge:8000/", fetchImpl);
    await client.listUploads("abc", 25);
    expect(called).toContain("/api/v1/uploads?cursor=abc&limit=25");
  });

  it("parses problem+json errors into ApiError", async () => {
    const body = {
      type: "https://example/problems/not-found",
      title: "Not found",
      status: 404,
      detail: "no such inspection",
      code: "INSPECTION_NOT_FOUND",
      request_id: "req-1",
    };
    const fetchImpl = fakeFetch(404, body);
    const client = new HttpApiClient("http://edge:8000", fetchImpl);
    await expect(client.getInspection("nope")).rejects.toMatchObject({
      code: "INSPECTION_NOT_FOUND",
      status: 404,
    });
  });

  it("throws NETWORK_ERROR when fetch rejects", async () => {
    const fetchImpl = (() => Promise.reject(new Error("down"))) as unknown as typeof fetch;
    const client = new HttpApiClient("http://edge:8000", fetchImpl);
    await expect(client.getHealthLive()).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });
});
