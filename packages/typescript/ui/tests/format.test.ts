import { describe, expect, it } from "vitest";
import { formatBytes, formatIsoTime, formatLatency, reasonCodeLabel } from "../src/formatters/format";
import { statusPresentation, toDecisionStatus } from "../src/status/status";

describe("formatters", () => {
  it("formats bytes with binary units", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(42 * 1024 ** 3)).toBe("42.0 GB");
    expect(formatBytes(-1)).toBe("-");
  });

  it("formats latency", () => {
    expect(formatLatency(320)).toBe("320 ms");
    expect(formatLatency(null)).toBe("-");
  });

  it("formats ISO timestamps and tolerates invalid input", () => {
    expect(formatIsoTime("2026-08-07T10:00:00Z")).not.toBe("-");
    expect(formatIsoTime("not-a-date")).toBe("-");
    expect(formatIsoTime(null)).toBe("-");
  });

  it("labels reason codes and falls back to the raw code", () => {
    expect(reasonCodeLabel("COMPONENT_MISSING")).toBe("Component missing");
    expect(reasonCodeLabel("UNKNOWN_CODE")).toBe("UNKNOWN_CODE");
  });
});

describe("status", () => {
  it("keeps color-independent labels and icons", () => {
    expect(statusPresentation("OK").label).toBe("OK");
    expect(statusPresentation("NG").label).toBe("NG");
    expect(statusPresentation("UNCERTAIN").label).toBe("UNCERTAIN");
    expect(statusPresentation("NG").icon).not.toBe(statusPresentation("OK").icon);
  });

  it("maps internal uncertain to the display state", () => {
    expect(toDecisionStatus("OK", "OK")).toBe("OK");
    expect(toDecisionStatus("NG", "NG")).toBe("NG");
    expect(toDecisionStatus("NG", "UNCERTAIN")).toBe("UNCERTAIN");
  });
});
