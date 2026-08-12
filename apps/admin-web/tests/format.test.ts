import { describe, expect, it } from "vitest";

import { formatMillis, formatNumber, formatScopeLabel } from "../src/lib/format";

describe("formatScopeLabel", () => {
  it("combines site and line into a bounded label", () => {
    expect(formatScopeLabel("Pilot site", "Line 1")).toBe("Pilot site / Line 1");
  });

  it("handles empty parts without crashing", () => {
    expect(formatScopeLabel("", "")).toBe(" / ");
  });
});

describe("formatNumber", () => {
  it("adds locale-aware thousand separators", () => {
    expect(formatNumber(1005222118, "en")).toBe("1,005,222,118");
    expect(formatNumber(1234567, "zh-CN")).toBe("1,234,567");
  });

  it("rounds fractional values", () => {
    expect(formatNumber(42.56, "en")).toBe("43");
  });

  it("renders an en dash for null, undefined, and non-finite values", () => {
    expect(formatNumber(null, "en")).toBe("–");
    expect(formatNumber(undefined, "en")).toBe("–");
    expect(formatNumber(Number.NaN, "en")).toBe("–");
    expect(formatNumber(Number.POSITIVE_INFINITY, "en")).toBe("–");
  });

  it("follows locales with a different group separator", () => {
    expect(formatNumber(1234567, "de-DE")).toBe("1.234.567");
  });
});

describe("formatMillis", () => {
  it("adds locale-aware thousand separators", () => {
    expect(formatMillis(1005222118, "en")).toBe("1,005,222,118 ms");
    expect(formatMillis(1234567, "zh-CN")).toBe("1,234,567 ms");
  });

  it("rounds fractional values", () => {
    expect(formatMillis(42.56, "en")).toBe("43 ms");
  });

  it("renders an en dash for null, undefined, and non-finite values", () => {
    expect(formatMillis(null, "en")).toBe("–");
    expect(formatMillis(undefined, "en")).toBe("–");
    expect(formatMillis(Number.NaN, "en")).toBe("–");
    expect(formatMillis(Number.POSITIVE_INFINITY, "en")).toBe("–");
  });

  it("follows locales with a different group separator", () => {
    expect(formatMillis(1234567, "de-DE")).toBe("1.234.567 ms");
  });
});
