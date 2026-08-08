import { describe, expect, it } from "vitest";

import { assertProductionHttpMode } from "../src/vite-mode";

describe("production data-mode enforcement (AUDIT-001 4.5)", () => {
  it("accepts http mode in production", () => {
    expect(() => assertProductionHttpMode("http", true)).not.toThrow();
  });

  it("rejects an unset mode in production", () => {
    expect(() => assertProductionHttpMode(undefined, true)).toThrow(/VITE_API_MODE=http/);
  });

  it("rejects mock mode in production", () => {
    expect(() => assertProductionHttpMode("mock", true)).toThrow(/VITE_API_MODE=http/);
  });

  it("allows mock mode in development", () => {
    expect(() => assertProductionHttpMode("mock", false)).not.toThrow();
  });

  it("allows an unset mode in development", () => {
    expect(() => assertProductionHttpMode(undefined, false)).not.toThrow();
  });
});
