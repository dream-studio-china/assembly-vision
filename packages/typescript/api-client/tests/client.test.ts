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

  it("retries an eligible upload task and rejects non-eligible states", async () => {
    const client = new MockApiClient();
    const before = (await client.listUploads()).items.find((t) => t.status === "RETRY_WAIT");
    expect(before).toBeTruthy();
    const updated = await client.retryUpload(before!.upload_task_id);
    expect(updated.status).toBe("PENDING");
    expect(updated.attempt_count).toBe(before!.attempt_count + 1);
    // A second retry is now a conflict, mirroring the server's CAS transition.
    await expect(client.retryUpload(before!.upload_task_id)).rejects.toMatchObject({
      code: "TASK_NOT_RETRYABLE",
      status: 409,
    });
    await expect(client.retryUpload("00000000-0000-4000-8000-ffffffffffff")).rejects.toMatchObject({
      code: "NOT_FOUND",
      status: 404,
    });
  });

  it("keeps mutable upload state isolated between mock clients", async () => {
    const first = new MockApiClient();
    const task = (await first.listUploads()).items.find((t) => t.status === "RETRY_WAIT");
    expect(task).toBeTruthy();
    await first.retryUpload(task!.upload_task_id);

    const second = new MockApiClient();
    const freshTask = (await second.listUploads()).items.find((t) => t.status === "RETRY_WAIT");
    expect(freshTask).toBeTruthy();
  });

  it("submits, lists, and queues reviews for any inspection", async () => {
    const client = new MockApiClient();
    const page = await client.listInspections({ business_result: "NG" });
    const ng = page.items[0];

    const open = await client.listReviewQueue({ business_result: "NG", reviewed: false });
    expect(open.items.some((item) => item.inspection_id === ng.inspection_id)).toBe(true);
    expect(open.items.every((item) => item.has_review === false)).toBe(true);

    const review = await client.submitReview(ng.inspection_id, {
      disposition: "CONFIRMED_NG",
      reason: "defect visible",
      reviewer: "operator-1",
    });
    expect(review.original_business_result).toBe("NG");
    expect(review.reviewer).toBe("operator-1");

    const history = await client.listInspectionReviews(ng.inspection_id);
    expect(history.map((r) => r.review_id)).toEqual([review.review_id]);

    const done = await client.listReviewQueue({ business_result: "NG", reviewed: true });
    expect(done.items.some((item) => item.inspection_id === ng.inspection_id)).toBe(true);
  });

  it("mock client rejects an incompatible disposition like the server", async () => {
    const client = new MockApiClient();
    const ok = (await client.listInspections({ business_result: "OK" })).items[0];
    await expect(
      client.submitReview(ok.inspection_id, {
        disposition: "REINSPECT",
        reviewer: "operator-1",
      }),
    ).rejects.toMatchObject({ code: "REVIEW_DISPOSITION_INVALID", status: 422 });
    await expect(
      client.submitReview("00000000-0000-4000-8000-ffffffffffff", {
        disposition: "CONFIRMED_NG",
        reviewer: "operator-1",
      }),
    ).rejects.toMatchObject({ code: "INSPECTION_NOT_FOUND", status: 404 });
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

  it("posts a manual retry and validates the returned task", async () => {
    let called = "";
    let method = "";
    const task = {
      upload_task_id: "task-1",
      device_id: "00000000-0000-4000-8000-000000000001",
      inspection_id: null,
      kind: "INSPECTION",
      object_id: "00000000-0000-4000-8000-000000000002",
      payload_hash: "abc",
      status: "PENDING",
      idempotency_key: "inspection:device:104",
      checksum_sha256: "0".repeat(64),
      attempt_count: 4,
      next_attempt_at: null,
      last_error_code: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-02T00:00:00Z",
      completed_at: null,
    };
    const fetchImpl = ((input: RequestInfo | URL, init?: RequestInit) => {
      called = String(input);
      method = init?.method ?? "GET";
      return Promise.resolve(new Response(JSON.stringify(task), { status: 200 }));
    }) as typeof fetch;
    const client = new HttpApiClient("http://edge:8000", fetchImpl);
    const updated = await client.retryUpload("task-1");
    expect(method).toBe("POST");
    expect(called).toContain("/api/v1/uploads/task-1/retry");
    expect(updated.status).toBe("PENDING");
  });

  it("submits a review and loads the review queue over HTTP", async () => {
    const queueBody = { items: [], next_cursor: null };
    const reviewBody = {
      review_id: "r-1",
      inspection_id: "i-1",
      disposition: "CONFIRMED_NG",
      reason: "defect",
      note: null,
      reviewer: "operator-1",
      created_at: "2026-08-10T00:00:00Z",
      original_business_result: "NG",
      original_internal_decision: "NG",
      original_reason_codes: ["COMPONENT_MISSING:component_a"],
      component_corrections: [],
      supersedes_review_id: null,
    };
    let called = "";
    let method = "";
    let body = "";
    const fetchImpl = ((input: RequestInfo | URL, init?: RequestInit) => {
      called = String(input);
      method = init?.method ?? "GET";
      body = String(init?.body ?? "");
      const payload = called.includes("/reviews") && method === "POST" ? reviewBody : queueBody;
      return Promise.resolve(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }) as typeof fetch;
    const client = new HttpApiClient("http://edge:8000", fetchImpl);

    await client.listReviewQueue({ business_result: "NG", reviewed: false, limit: 25 });
    expect(called).toContain("/api/v1/reviews?business_result=NG&reviewed=false&limit=25");

    const review = await client.submitReview("i-1", {
      disposition: "CONFIRMED_NG",
      reason: "defect",
      reviewer: "operator-1",
    });
    expect(review.disposition).toBe("CONFIRMED_NG");
    expect(method).toBe("POST");
    expect(JSON.parse(body)).toMatchObject({
      disposition: "CONFIRMED_NG",
      reviewer: "operator-1",
      reason: "defect",
      supersedes_review_id: null,
      component_corrections: [],
    });
  });

  it("maps a 409 TASK_NOT_RETRYABLE into a typed ApiError", async () => {
    const body = {
      type: "https://assemblyvision.example/problems/task-not-retryable",
      title: "Task not retryable",
      status: 409,
      detail: "upload task is SUCCEEDED and cannot be manually retried",
      code: "TASK_NOT_RETRYABLE",
      request_id: "req-1",
    };
    const fetchImpl = fakeFetch(409, body);
    const client = new HttpApiClient("http://edge:8000", fetchImpl);
    await expect(client.retryUpload("task-9")).rejects.toMatchObject({
      code: "TASK_NOT_RETRYABLE",
      status: 409,
    });
  });

  it("throws NETWORK_ERROR when fetch rejects", async () => {
    const fetchImpl = (() => Promise.reject(new Error("down"))) as unknown as typeof fetch;
    const client = new HttpApiClient("http://edge:8000", fetchImpl);
    await expect(client.getHealthLive()).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });

  it("attaches the in-memory bearer token when a provider is given", async () => {
    let captured: Headers | undefined;
    const fetchImpl = ((input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      captured = new Headers(init?.headers);
      return Promise.resolve(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }) as typeof fetch;
    const client = new HttpApiClient("http://edge:8000", fetchImpl, () => "secret-token");
    await client.getHealthLive();
    expect(captured?.get("Authorization")).toBe("Bearer secret-token");
  });

  it("omits the Authorization header when no token is available", async () => {
    let captured: Headers | undefined;
    const fetchImpl = ((input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      captured = new Headers(init?.headers);
      return Promise.resolve(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }) as typeof fetch;
    const client = new HttpApiClient("http://edge:8000", fetchImpl);
    await client.getHealthLive();
    expect(captured?.has("Authorization")).toBe(false);
  });
});

describe("web dev test harness (ADR-014)", () => {
  const record = {
    inspection_id: "11111111-1111-4111-8111-111111111111",
    device_id: "22222222-2222-4222-8222-222222222222",
    device_sequence: 1,
    lifecycle_status: "COMPLETED",
    started_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:01Z",
    barcode_result: { status: "NOT_REQUIRED", value: null, symbology: null },
    product_resolution: { status: "RESOLVED", source: "CONFIGURED_DEFAULT", product_code: "p" },
    product_detection: null,
    roi_result: null,
    frame_quality_summary: { total_frame_count: 1, usable_frame_count: 1, rejected_frame_count: 0, reasons: [] },
    application_version: "0.1.0",
    product_model_version_id: "33333333-3333-4333-8333-333333333333",
    product_model_checksum_sha256: "0".repeat(64),
    component_model_version_id: "44444444-4444-4444-8444-444444444444",
    component_model_checksum_sha256: "0".repeat(64),
    rule_version_id: "55555555-5555-4555-8555-555555555555",
    aggregation_policy_version: "single-frame-mvp-1",
    evidence: [],
    media: [],
    decision: {
      internal_decision: "OK",
      business_result: "OK",
      missing_components: [],
      low_confidence_components: [],
      reason_codes: [],
      decided_at: "2026-01-01T00:00:01Z",
    },
    synchronization_status: "LOCAL_ONLY",
    processing_ms: 5,
  };

  it("posts raw image bytes to /dev/inspect-frame", async () => {
    let captured: { url: string; init?: RequestInit } | undefined;
    const fetchImpl = ((input: RequestInfo | URL, init?: RequestInit) => {
      captured = { url: String(input), init };
      return Promise.resolve(
        new Response(JSON.stringify(record), { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    }) as typeof fetch;
    const client = new HttpApiClient("http://edge:8000", fetchImpl);
    const result = await client.devInspectFrame(
      "line-1",
      new Blob(["jpeg"], { type: "image/jpeg" }),
      { barcode: "instance 001" },
    );
    expect(result.decision.business_result).toBe("OK");
    expect(captured?.url).toContain("/api/v1/dev/inspect-frame?instance_id=line-1");
    expect(captured?.url).toContain("barcode=instance+001");
    expect(captured?.init?.method).toBe("POST");
    expect(new Headers(captured?.init?.headers).get("Content-Type")).toBe("image/jpeg");
  });

  it("posts a video and returns the per-frame summary", async () => {
    const summary = {
      instance_id: "line-1",
      analyzed_frames: 2,
      ok_count: 1,
      ng_count: 1,
      frames: [
        { index: 1, business_result: "OK", internal_decision: "OK", reason_codes: [] },
        { index: 2, business_result: "NG", internal_decision: "NG", reason_codes: ["TEST"] },
      ],
    };
    const fetchImpl = ((_input: RequestInfo | URL, init?: RequestInit) => {
      void init;
      return Promise.resolve(
        new Response(JSON.stringify(summary), { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    }) as typeof fetch;
    const client = new HttpApiClient("http://edge:8000", fetchImpl);
    const result = await client.devInspectVideo("line-1", new Blob(["mp4"], { type: "video/mp4" }), {
      step: 2,
    });
    expect(result.analyzed_frames).toBe(2);
    expect(result.ng_count).toBe(1);
  });

  it("mock client rejects dev tools with DEV_TOOLS_DISABLED", async () => {
    const client = new MockApiClient();
    await expect(client.devInspectFrame("line-1", new Blob(["x"]))).rejects.toMatchObject({
      code: "DEV_TOOLS_DISABLED",
    });
  });

  function captureInit(status: number, body: unknown): { fetchImpl: typeof fetch; init: () => RequestInit | undefined } {
    let captured: RequestInit | undefined;
    const fetchImpl = ((_input: RequestInfo | URL, init?: RequestInit) => {
      captured = init;
      return Promise.resolve(
        new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
      );
    }) as typeof fetch;
    return { fetchImpl, init: () => captured };
  }

  it("preserves the file's own image Content-Type instead of fabricating image/jpeg (F11)", async () => {
    const { fetchImpl, init } = captureInit(200, record);
    const client = new HttpApiClient("http://edge:8000", fetchImpl);
    await client.devInspectFrame("line-1", new File(["png-bytes"], "photo.png", { type: "image/png" }));
    expect(new Headers(init()?.headers).get("Content-Type")).toBe("image/png");
  });

  it("preserves the file's own video Content-Type instead of fabricating video/mp4 (F11)", async () => {
    const summary = { instance_id: "line-1", analyzed_frames: 1, ok_count: 1, ng_count: 0, frames: [] };
    const { fetchImpl, init } = captureInit(200, summary);
    const client = new HttpApiClient("http://edge:8000", fetchImpl);
    await client.devInspectVideo("line-1", new File(["webm-bytes"], "clip.webm", { type: "video/webm" }));
    expect(new Headers(init()?.headers).get("Content-Type")).toBe("video/webm");
  });

  it("falls back to application/octet-stream when the blob has no type (F11)", async () => {
    const { fetchImpl, init } = captureInit(200, record);
    const client = new HttpApiClient("http://edge:8000", fetchImpl);
    await client.devInspectFrame("line-1", new Blob(["raw-bytes"]));
    expect(new Headers(init()?.headers).get("Content-Type")).toBe("application/octet-stream");
  });
});
