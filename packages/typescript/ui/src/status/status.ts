// Decision status presentation (docs/design/16-edge-dashboard.md 16.4.2).
//
// Color is never the only indicator: text, icon, and shape carry the meaning
// so the UI stays usable without relying on color vision.

export type DecisionStatus = "OK" | "NG" | "UNCERTAIN";

export type StatusPresentation = {
  label: string;
  tone: "success" | "danger" | "warning";
  icon: string;
  /** Short explanation used on the live screen for NC/uncertain states. */
  note: string | null;
};

const PRESENTATIONS: Record<DecisionStatus, StatusPresentation> = {
  OK: { label: "OK", tone: "success", icon: "circle-check", note: null },
  NG: { label: "NG", tone: "danger", icon: "circle-alert", note: "Missing or unverifiable components" },
  UNCERTAIN: {
    label: "UNCERTAIN",
    tone: "warning",
    icon: "warning",
    note: "Treated as NG on the production line",
  },
};

export function statusPresentation(status: DecisionStatus): StatusPresentation {
  return PRESENTATIONS[status];
}

/** Business result with the UNCERTAIN nuance mapped back for display. */
export function toDecisionStatus(businessResult: "OK" | "NG", internalDecision: "OK" | "NG" | "UNCERTAIN"): DecisionStatus {
  if (businessResult === "OK") return "OK";
  return internalDecision === "UNCERTAIN" ? "UNCERTAIN" : "NG";
}
