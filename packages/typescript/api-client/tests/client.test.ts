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

  it("404s for unknown inspections", async () => {
    const client = new MockApiClient();
    await expect(client.getInspection("00000000-0000-4000-8000-ffffffffffff")).rejects.toBeInstanceOf(ApiError);
  });

  it("walks the operator workflow through confirm and continue", async () => {
    const client = new MockApiClient();
    const initial = await client.getCurrentInspection();
    expect(initial.status).toBe("PROCESSING");

    const confirmed = await client.confirmInspectionResult();
    expect(["PASS", "NG"]).toContain(confirmed.status);
    expect(confirmed.progress).toBe(1);

    const next = await client.continueNextInspection();
    expect(next.status).toBe("PROCESSING");
  });

  it("emits runtime logs as the operator workflow advances", async () => {
    const client = new MockApiClient();
    const before = (await client.listLogs()).items;
    await client.confirmInspectionResult();
    await client.continueNextInspection();
    const after = (await client.listLogs()).items;
    expect(after.length).toBeGreaterThan(before.length);
    expect(after[0].message).toContain("advancing to next product");
    expect(after.some((l) => l.message.includes("confirmed"))).toBe(true);
  });

  it("returns traceability with reinspection attempts", async () => {
    const client = new MockApiClient();
    const view = await client.getTraceability("SN-0001");
    expect(view.final_status).toBe("PASS");
    expect(view.attempts.length).toBe(2);
    expect(view.attempts[0].result).toBe("NG");
    expect(view.attempts[1].result).toBe("PASS");
    await expect(client.getTraceability("SN-UNKNOWN")).rejects.toMatchObject({ code: "SN_NOT_FOUND" });
  });

  it("computes statistics from the record set", async () => {
    const client = new MockApiClient();
    const stats = await client.getStatistics();
    expect(stats.total_inspections).toBeGreaterThan(0);
    expect(stats.pass_count + stats.ng_count).toBe(stats.total_inspections);
    expect(stats.pass_rate).toBeGreaterThanOrEqual(0);
    expect(stats.pass_rate).toBeLessThanOrEqual(1);
  });

  it("returns inspection images for a known inspection", async () => {
    const client = new MockApiClient();
    const page = await client.listInspections();
    const images = await client.getInspectionImages(page.items[0].inspection_id);
    expect(images.original.startsWith("data:image/svg+xml")).toBe(true);
    expect(images.detection).toBeTruthy();
    expect(images.annotated).toBeTruthy();
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
