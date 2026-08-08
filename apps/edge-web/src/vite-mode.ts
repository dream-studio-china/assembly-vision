/**
 * Production data-mode enforcement (AUDIT-001 4.5).
 *
 * The dashboard data mode is explicit: `VITE_API_MODE=http` talks to the edge
 * backend, `mock` is the deterministic development client. A production bundle
 * that silently falls back to mock mode would render fabricated data as if it
 * were real, so production builds must fail unless the mode is exactly `http`.
 */
export function assertProductionHttpMode(
  mode: string | undefined,
  isProduction: boolean,
): void {
  if (isProduction && mode !== "http") {
    throw new Error(
      "production builds must set VITE_API_MODE=http; mock mode is a development client only",
    );
  }
}
