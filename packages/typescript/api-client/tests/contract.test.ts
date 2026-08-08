import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";
import type { components } from "../src/edge/generated/api";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const OPENAPI_PATH = resolve(HERE, "../../../../apps/edge-service/openapi/edge-openapi.json");

function loadSpec(): Record<string, unknown> {
  return JSON.parse(readFileSync(OPENAPI_PATH, "utf-8")) as Record<string, unknown>;
}

function schemas(): Record<string, unknown> {
  const spec = loadSpec();
  const componentsSpec = spec.components;
  if (typeof componentsSpec !== "object" || componentsSpec === null) return {};
  const schemasSpec = (componentsSpec as Record<string, unknown>).schemas;
  if (typeof schemasSpec !== "object" || schemasSpec === null) return {};
  return schemasSpec as Record<string, unknown>;
}

describe("edge OpenAPI contract (F9)", () => {
  it("describes named schemas instead of arbitrary objects", () => {
    const schemaSet = schemas();
    for (const name of [
      "Page_InspectionSummary_",
      "InspectionRecord",
      "DeviceStatus",
      "Problem",
      "InspectionSummary",
      "StatisticsSummary",
      "TraceabilityView",
    ]) {
      expect(schemaSet[name], `schema ${name}`).toBeDefined();
    }
  });

  it("keeps the evidence schema synchronized with the Python domain model", () => {
    const evidence = schemas().AggregatedComponentEvidence as
      | { properties?: Record<string, unknown> }
      | undefined;
    expect(evidence?.properties).toBeDefined();
    expect(Object.keys(evidence?.properties ?? {})).toEqual(
      expect.arrayContaining(["box_area_ratios", "box_centers"]),
    );
  });
});

describe("generated TypeScript types accept the real server payloads", () => {
  it("accepts component evidence with box_area_ratios and box_centers", () => {
    type Evidence = components["schemas"]["AggregatedComponentEvidence"];
    const evidence: Evidence = {
      component_code: "component_a",
      state: "PRESENT",
      best_confidence: 0.9,
      usable_frame_count: 1,
      detection_count: 1,
      adjacent_detection_run: 1,
      supporting_frame_ids: ["00000000-0000-4000-8000-0000000000aa"],
      policy_reason_codes: [],
      box_area_ratios: [0.5],
      box_centers: [[0.5, 0.5]],
    };
    expect(evidence.box_area_ratios).toEqual([0.5]);
  });

  it("accepts an inspection summary as returned by the list endpoint", () => {
    type Summary = components["schemas"]["InspectionSummary"];
    const summary: Summary = {
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
    expect(summary.business_result).toBe("OK");
  });
});
