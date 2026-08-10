/** Format a bounded site/line scope label for the overview (C1a). */
export function formatScopeLabel(site: string, line: string): string {
  return `${site} / ${line}`;
}
