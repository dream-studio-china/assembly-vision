import { describe, expect, it, vi } from "vitest";
import type { ApiClient, InspectionRecord } from "@assemblyvision/api-client";
import { productBoxStyle } from "../src/services/devOverlay";
import { useDevInspectSession } from "../src/services/useDevInspectSession";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function frameRecord(businessResult: "OK" | "NG"): InspectionRecord {
  return {
    inspection_id: "11111111-1111-4111-8111-111111111111",
    device_id: "22222222-2222-4222-8222-222222222222",
    device_sequence: 1,
    lifecycle_status: "COMPLETED",
    started_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-01-01T00:00:01Z",
    barcode_result: { status: "NOT_REQUIRED", value: null, symbology: null },
    product_resolution: { status: "RESOLVED", source: "CONFIGURED_DEFAULT", product_code: "p", product_version_id: null },
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
      internal_decision: businessResult,
      business_result: businessResult,
      missing_components: [],
      low_confidence_components: [],
      reason_codes: [],
      decided_at: "2026-01-01T00:00:01Z",
    },
    synchronization_status: "LOCAL_ONLY",
    processing_ms: 5,
  };
}

function clientWithFrameRequests(
  responses: Array<ReturnType<typeof deferred<InspectionRecord>>>,
): ApiClient {
  const devInspectFrame = vi.fn();
  responses.forEach((response) => devInspectFrame.mockReturnValueOnce(response.promise));
  return { devInspectFrame, devInspectVideo: vi.fn() } as unknown as ApiClient;
}

describe("devInspectSession request sequencing (F10)", () => {
  it("keeps only the current upload's result when the stale one resolves later", async () => {
    const frameA = deferred<InspectionRecord>();
    const frameB = deferred<InspectionRecord>();
    const client = clientWithFrameRequests([frameA, frameB]);
    const preview = vi.fn((file: File) => `blob:${file.name}`);
    const session = useDevInspectSession(preview);

    const settleA = session.inspectFrame(client, "line-1", new File(["a"], "a.png"), { persist: true });
    const settleB = session.inspectFrame(client, "line-1", new File(["b"], "b.png"), { persist: true });

    expect(session.busy.value).toBe(true);
    expect(session.imageUrl.value).toBe("blob:b.png");

    frameB.resolve(frameRecord("NG"));
    await settleB;

    expect(session.record.value?.decision.business_result).toBe("NG");
    expect(session.imageUrl.value).toBe("blob:b.png");
    expect(session.busy.value).toBe(false);

    frameA.resolve(frameRecord("OK"));
    await settleA;

    expect(session.record.value?.decision.business_result).toBe("NG");
    expect(session.imageUrl.value).toBe("blob:b.png");
    expect(session.busy.value).toBe(false);
    expect(session.error.value).toBeNull();
  });

  it("keeps busy true while the current upload runs even if the stale one finishes first", async () => {
    const frameA = deferred<InspectionRecord>();
    const frameB = deferred<InspectionRecord>();
    const client = clientWithFrameRequests([frameA, frameB]);
    const session = useDevInspectSession((file) => `blob:${file.name}`);

    session.inspectFrame(client, "line-1", new File(["a"], "a.png"), { persist: true });
    const settleB = session.inspectFrame(client, "line-1", new File(["b"], "b.png"), { persist: true });

    frameA.resolve(frameRecord("OK"));
    await frameA.promise;

    expect(session.busy.value).toBe(true);
    expect(session.record.value).toBeNull();

    frameB.resolve(frameRecord("NG"));
    await settleB;

    expect(session.busy.value).toBe(false);
    expect(session.record.value?.decision.business_result).toBe("NG");
  });
});

function recordWithBox(box: {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  image_width: number;
  image_height: number;
}): Parameters<typeof productBoxStyle>[0] {
  return {
    product_detection: { bbox: box },
  } as Parameters<typeof productBoxStyle>[0];
}

describe("productBoxStyle (ADR-014 dev overlay)", () => {
  it("returns null when there is no product detection", () => {
    expect(productBoxStyle(null)).toBeNull();
    expect(productBoxStyle({ product_detection: null } as never)).toBeNull();
  });

  it("computes percentage geometry from full-frame coordinates", () => {
    const style = productBoxStyle(
      recordWithBox({ x_min: 100, y_min: 50, x_max: 700, y_max: 550, image_width: 1000, image_height: 1000 }),
    );
    expect(style).toEqual({
      left: "10%",
      top: "5%",
      width: "60%",
      height: "50%",
    });
  });

  it("returns null for degenerate image dimensions", () => {
    expect(
      productBoxStyle(
        recordWithBox({ x_min: 0, y_min: 0, x_max: 10, y_max: 10, image_width: 0, image_height: 100 }),
      ),
    ).toBeNull();
  });
});
