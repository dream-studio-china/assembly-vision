import type { InspectionRecord } from "@assemblyvision/api-client";

/**
 * CSS box geometry for the product detection overlay on the uploaded test
 * image. The record carries full-frame source coordinates; the overlay is
 * positioned as a percentage of the displayed image so it stays aligned under
 * any scaling (ADR-014 dev test harness).
 */
export interface BoxStyle {
  left: string;
  top: string;
  width: string;
  height: string;
}

export function productBoxStyle(record: InspectionRecord | null): BoxStyle | null {
  const detection = record?.product_detection;
  if (!detection) return null;
  const box = detection.bbox;
  if (box.image_width <= 0 || box.image_height <= 0) return null;
  return {
    left: `${(box.x_min / box.image_width) * 100}%`,
    top: `${(box.y_min / box.image_height) * 100}%`,
    width: `${((box.x_max - box.x_min) / box.image_width) * 100}%`,
    height: `${((box.y_max - box.y_min) / box.image_height) * 100}%`,
  };
}
