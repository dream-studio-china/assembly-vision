import { describe, expect, it } from "vitest";

import { formatScopeLabel } from "../src/lib/format";

describe("formatScopeLabel", () => {
  it("combines site and line into a bounded label", () => {
    expect(formatScopeLabel("Pilot site", "Line 1")).toBe("Pilot site / Line 1");
  });

  it("handles empty parts without crashing", () => {
    expect(formatScopeLabel("", "")).toBe(" / ");
  });
});
