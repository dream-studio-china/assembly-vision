/** Format a bounded site/line scope label for the overview (C1a). */
export function formatScopeLabel(site: string, line: string): string {
  return `${site} / ${line}`;
}

/**
 * Format an integer with locale-aware thousand separators
 * (e.g. `1,005,222,118`). Null, undefined, and non-finite values render as
 * an en dash, matching the existing empty-state convention.
 */
export function formatNumber(value: number | null | undefined, locale?: string): string {
  if (value == null || !Number.isFinite(value)) {
    return "–";
  }
  return Math.round(value).toLocaleString(locale);
}

/**
 * Format a millisecond value with locale-aware thousand separators
 * (e.g. `1,005,222,118 ms`). Null, undefined, and non-finite values render
 * as an en dash, matching the existing empty-state convention.
 */
export function formatMillis(value: number | null | undefined, locale?: string): string {
  const formatted = formatNumber(value, locale);
  return formatted === "–" ? formatted : `${formatted} ms`;
}
