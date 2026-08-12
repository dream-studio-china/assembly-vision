/**
 * Review disposition options permitted for a machine outcome (design 24.3).
 *
 * Mirrors the domain `allowed_review_dispositions` so the UI only offers
 * dispositions the server will accept: UNCERTAIN inspections may be
 * reinspected, OK audits may be corrected to NG, and plain NG may be
 * confirmed either way or declared inconclusive.
 *
 * Label values are English message keys translated through vue-i18n (labels
 * align with edge-web so both dashboards use the same wording).
 */

export type ReviewDispositionOption =
  | "CONFIRMED_NG"
  | "CONFIRMED_OK"
  | "CORRECTED_NG"
  | "INCONCLUSIVE"
  | "REINSPECT";

export const DISPOSITION_LABELS: Record<ReviewDispositionOption, string> = {
  CONFIRMED_NG: "Confirmed NG",
  CONFIRMED_OK: "Confirmed OK",
  CORRECTED_NG: "Corrected NG",
  INCONCLUSIVE: "Inconclusive",
  REINSPECT: "Reinspect",
};

export function allowedReviewDispositions(
  businessResult: string,
  internalDecision: string,
): ReviewDispositionOption[] {
  if (internalDecision === "UNCERTAIN") {
    return ["CONFIRMED_NG", "CONFIRMED_OK", "REINSPECT", "INCONCLUSIVE"];
  }
  if (businessResult === "NG") {
    return ["CONFIRMED_NG", "CONFIRMED_OK", "INCONCLUSIVE"];
  }
  return ["CONFIRMED_OK", "CORRECTED_NG", "INCONCLUSIVE"];
}

export function newIdempotencyKey(): string {
  const random = typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36);
  return `review-${random}`;
}
