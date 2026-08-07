import type { Box } from "./geometry";

export type OverlayKind = "product" | "component" | "roi";

/** A detection overlay in source-image coordinates. */
export type ViewerBox = {
  id: string;
  kind: OverlayKind;
  label: string;
  box: Box;
  /** Frame that produced this box; overlays not matching the displayed frame are discarded. */
  frameId: string;
};

export const OVERLAY_COLORS: Record<OverlayKind, string> = {
  product: "#00c853",
  component: "#ff5252",
  roi: "#2196f3",
};
