import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import type { components, paths } from "../src/central/generated/api";

const GENERATED = fileURLToPath(new URL("../src/central/generated/api.ts", import.meta.url));

describe("central OpenAPI generated types", () => {
  it("commits a non-empty generated artifact", () => {
    const source = readFileSync(GENERATED, "utf8");
    expect(source.length).toBeGreaterThan(1000);
    expect(source).toContain("api/v1/health/live");
    expect(source).toContain("api/v1/health/ready");
  });

  it("exposes the health path contract", () => {
    type HealthPath = keyof paths;
    const livePath: "/api/v1/health/live" extends HealthPath ? true : false = true;
    const readyPath: "/api/v1/health/ready" extends HealthPath ? true : false = true;
    expect(livePath).toBe(true);
    expect(readyPath).toBe(true);
  });

  it("exposes the readiness component type", () => {
    type Readiness = components["schemas"]["ReadinessReport"];
    type Status = Readiness["status"];
    const ok: "ok" extends Status ? true : false = true;
    expect(ok).toBe(true);
  });
});
