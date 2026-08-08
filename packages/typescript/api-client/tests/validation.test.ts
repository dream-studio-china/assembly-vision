import { describe, expect, it } from "vitest";

import { ApiError } from "../src/edge/ApiError";
import { HttpApiClient } from "../src/edge/HttpApiClient";

/**
 * F9: HTTP payloads are validated at the client boundary. A successful status
 * with a drifted or malformed body must be rejected instead of silently cast
 * to the declared TypeScript type.
 */

function stubFetch(body: unknown): typeof fetch {
  return (async () =>
    ({
      ok: true,
      status: 200,
      json: async () => body,
    })) as unknown as typeof fetch;
}

function clientFor(body: unknown): HttpApiClient {
  return new HttpApiClient("http://edge.test", stubFetch(body));
}

const VALID_SUMMARY = {
  inspection_id: "00000000-0000-4000-8000-0000000000aa",
  completed_at: "2026-08-04T10:12:31.442Z",
  business_result: "OK",
  internal_decision: "OK",
  barcode: "SN-0001",
  product_code: "model_a",
  sn: "SN-0001",
  reason_summary: [],
  latency_ms: 12,
  upload_state: "LOCAL_ONLY",
  model_rule_versions: {},
};

const VALID_RECORD = {
  inspection_id: "00000000-0000-4000-8000-0000000000aa",
  device_id: "00000000-0000-4000-8000-0000000000bb",
  device_sequence: 1,
  lifecycle_status: "COMPLETED",
  started_at: "2026-08-04T10:12:31.442Z",
  completed_at: "2026-08-04T10:12:31.442Z",
  barcode_result: { status: "READ", value: "SN-0001", symbology: null },
  product_resolution: {
    status: "RESOLVED",
    source: "CONFIGURED_DEFAULT",
    product_code: "model_a",
    product_version_id: null,
  },
  product_detection: null,
  roi_result: null,
  frame_quality_summary: {
    total_frame_count: 1,
    usable_frame_count: 1,
    rejected_frame_count: 0,
    reasons: [],
  },
  application_version: "0.1.0",
  product_model_version_id: "00000000-0000-4000-8000-0000000000cc",
  product_model_checksum_sha256: "0".repeat(64),
  component_model_version_id: "00000000-0000-4000-8000-0000000000dd",
  component_model_checksum_sha256: "0".repeat(64),
  rule_version_id: "00000000-0000-4000-8000-0000000000ee",
  aggregation_policy_version: "single-frame-mvp-1",
  evidence: [],
  media: [],
  decision: {
    internal_decision: "OK",
    business_result: "OK",
    missing_components: [],
    low_confidence_components: [],
    reason_codes: [],
    decided_at: "2026-08-04T10:12:31.442Z",
  },
  synchronization_status: "LOCAL_ONLY",
  processing_ms: 12,
};

describe("HttpApiClient runtime response validation (F9)", () => {
  it("accepts a valid device status payload", async () => {
    const client = clientFor({
      device_id: "00000000-0000-4000-8000-0000000000bb",
      observed_at: "2026-08-04T10:12:31.442Z",
      operational_state: "READY",
      inspection_ready: true,
      sync_ready: false,
      camera_connected: true,
      model_loaded: true,
      central_connected: false,
      disk_free_bytes: 1024,
      upload_pending_count: 0,
      alerts: [],
    });
    await expect(client.getDeviceStatus()).resolves.toBeDefined();
  });

  it("rejects a device status missing a required field", async () => {
    const client = clientFor({
      device_id: "00000000-0000-4000-8000-0000000000bb",
      observed_at: "2026-08-04T10:12:31.442Z",
      operational_state: "READY",
      inspection_ready: true,
    });
    await expect(client.getDeviceStatus()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("accepts a valid inspection page", async () => {
    const client = clientFor({ items: [VALID_SUMMARY], next_cursor: null });
    const page = await client.listInspections();
    expect(page.items).toHaveLength(1);
  });

  it("rejects an inspection page whose items are not an array", async () => {
    const client = clientFor({ items: "not-an-array" });
    await expect(client.listInspections()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("rejects a malformed item inside an inspection page", async () => {
    const client = clientFor({ items: [{ inspection_id: "x" }] });
    await expect(client.listInspections()).rejects.toBeInstanceOf(ApiError);
  });

  it("accepts a valid inspection record", async () => {
    const client = clientFor(VALID_RECORD);
    await expect(client.getInspection("00000000-0000-4000-8000-0000000000aa")).resolves.toBeDefined();
  });

  it("rejects an inspection record missing its decision", async () => {
    const truncated = { ...VALID_RECORD } as Record<string, unknown>;
    delete truncated.decision;
    const client = clientFor(truncated);
    await expect(client.getInspection("00000000-0000-4000-8000-0000000000aa")).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("accepts a valid statistics summary", async () => {
    const client = clientFor({ total_inspections: 4, pass_count: 3, ng_count: 1, pass_rate: 0.75 });
    await expect(client.getStatistics()).resolves.toBeDefined();
  });

  it("rejects a statistics summary with a non-number count", async () => {
    const client = clientFor({ total_inspections: "4", pass_count: 3, ng_count: 1, pass_rate: 0.75 });
    await expect(client.getStatistics()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });

  it("accepts valid inspection images including slot statuses", async () => {
    const client = clientFor({
      inspection_id: "00000000-0000-4000-8000-0000000000aa",
      original: "",
      detection: "",
      annotated: "",
      original_status: "PURGED",
      detection_status: "UNAVAILABLE",
      annotated_status: "AVAILABLE",
    });
    await expect(client.getInspectionImages("00000000-0000-4000-8000-0000000000aa")).resolves.toBeDefined();
  });

  it("rejects inspection images missing a slot status", async () => {
    const client = clientFor({
      inspection_id: "00000000-0000-4000-8000-0000000000aa",
      original: "",
      detection: "",
      annotated: "",
      original_status: "PURGED",
      detection_status: "UNAVAILABLE",
    });
    await expect(client.getInspectionImages("00000000-0000-4000-8000-0000000000aa")).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });
});

describe("dev video result decision validation (F12)", () => {
  const baseResult = {
    instance_id: "line-1",
    analyzed_frames: 1,
    ok_count: 0,
    ng_count: 1,
    truncated: false,
    frames: [
      { index: 1, business_result: "NG", internal_decision: "UNCERTAIN", reason_codes: ["TEST"] },
    ],
  };

  it("accepts a video result with valid OK/NG/UNCERTAIN decisions", async () => {
    const client = clientFor(baseResult);
    await expect(client.devInspectVideo("line-1", new Blob(["x"]))).resolves.toBeDefined();
  });

  it("accepts a video result without the optional truncated field", async () => {
    const { truncated, ...rest } = baseResult;
    void truncated;
    const client = clientFor(rest);
    await expect(client.devInspectVideo("line-1", new Blob(["x"]))).resolves.toBeDefined();
  });

  it("rejects a video result whose truncated field is not a boolean", async () => {
    const client = clientFor({ ...baseResult, truncated: "yes" });
    await expect(client.devInspectVideo("line-1", new Blob(["x"]))).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("rejects a frame whose business_result is UNCERTAIN", async () => {
    const client = clientFor({
      ...baseResult,
      frames: [{ ...baseResult.frames[0], business_result: "UNCERTAIN" }],
    });
    await expect(client.devInspectVideo("line-1", new Blob(["x"]))).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });

  it("rejects a frame with an unknown internal_decision", async () => {
    const client = clientFor({
      ...baseResult,
      frames: [{ ...baseResult.frames[0], internal_decision: "MAYBE" }],
    });
    await expect(client.devInspectVideo("line-1", new Blob(["x"]))).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });
});
