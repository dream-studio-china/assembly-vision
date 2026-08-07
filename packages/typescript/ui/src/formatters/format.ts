// Shared display formatters for the edge dashboard.

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"] as const;

/** Format a byte count using binary units. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "-";
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value >= 100 || unit === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${BYTE_UNITS[unit]}`;
}

/** Format an ISO-8601 UTC timestamp in local time. */
export function formatIsoTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString();
}

/** Format a duration in milliseconds. */
export function formatLatency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "-";
  return `${Math.round(ms)} ms`;
}

/** Stable human-readable label for a reason code. */
export function reasonCodeLabel(code: string): string {
  const map: Record<string, string> = {
    COMPONENT_MISSING: "Component missing",
    COMPONENT_UNCERTAIN: "Component uncertain",
    COMPONENT_UNVERIFIABLE: "Component unverifiable",
    COMPONENT_COUNT_INVALID: "Component count invalid",
    COMPONENT_SPATIAL_INVALID: "Component position invalid",
    NO_PRODUCT: "Product not found",
    MULTIPLE_PRODUCTS: "Multiple products",
    ROI_INVALID: "Invalid ROI",
    INFERENCE_ERROR: "Inference error",
    IMAGE_READ_ERROR: "Image unreadable",
    VERSION_INCOMPATIBLE: "Model/rule incompatible",
    RULE_NOT_FOUND: "Rule not found",
    CONFIG_INVALID: "Invalid configuration",
  };
  return map[code] ?? code;
}
