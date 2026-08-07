import DetectionViewer from "./detection-viewer/DetectionViewer.vue";
import StatusBadge from "./status/StatusBadge.vue";

export { DetectionViewer, StatusBadge };
export {
  containFit,
  mapBoxToView,
  boxToRect,
  clipToImageRect,
  hasValidDimensions,
} from "./detection-viewer/geometry";
export type { Size, Box, Rect, ContainFit } from "./detection-viewer/geometry";
export { OVERLAY_COLORS } from "./detection-viewer/types";
export type { ViewerBox, OverlayKind } from "./detection-viewer/types";
export { statusPresentation, toDecisionStatus } from "./status/status";
export type { DecisionStatus, StatusPresentation } from "./status/status";
export { formatBytes, formatIsoTime, formatLatency, reasonCodeLabel } from "./formatters/format";
