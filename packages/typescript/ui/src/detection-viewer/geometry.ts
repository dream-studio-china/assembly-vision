// Detection overlay geometry (docs/design/16-edge-dashboard.md 16.4.1).
//
// Boxes are always expressed in source-image coordinates and mapped to the
// displayed view with contain scaling; the UI never receives pre-scaled
// server coordinates.

export type Size = { width: number; height: number };

export type Box = {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
};

export type ContainFit = {
  scale: number;
  offsetX: number;
  offsetY: number;
};

/** Letterbox fit that maps a source frame onto a view without distortion. */
export function containFit(source: Size, view: Size): ContainFit {
  if (source.width <= 0 || source.height <= 0 || view.width <= 0 || view.height <= 0) {
    return { scale: 0, offsetX: 0, offsetY: 0 };
  }
  const scale = Math.min(view.width / source.width, view.height / source.height);
  const fittedWidth = source.width * scale;
  const fittedHeight = source.height * scale;
  return {
    scale,
    offsetX: (view.width - fittedWidth) / 2,
    offsetY: (view.height - fittedHeight) / 2,
  };
}

/** Map a source-coordinate box into displayed view coordinates. */
export function mapBoxToView(box: Box, source: Size, view: Size): Box {
  const { scale, offsetX, offsetY } = containFit(source, view);
  return {
    x_min: offsetX + box.x_min * scale,
    y_min: offsetY + box.y_min * scale,
    x_max: offsetX + box.x_max * scale,
    y_max: offsetY + box.y_max * scale,
  };
}

/** Pixel rectangle used by absolutely-positioned overlay elements. */
export type Rect = { x: number; y: number; width: number; height: number };

export function boxToRect(box: Box, source: Size, view: Size): Rect {
  const mapped = mapBoxToView(box, source, view);
  return {
    x: mapped.x_min,
    y: mapped.y_min,
    width: Math.max(0, mapped.x_max - mapped.x_min),
    height: Math.max(0, mapped.y_max - mapped.y_min),
  };
}

/**
 * Clip a view-space rect to the letterboxed image area. Overlays outside the
 * fitted image (in the letterbox bars) are never rendered.
 */
export function clipToImageRect(rect: Rect, source: Size, view: Size): Rect {
  const { offsetX, offsetY } = containFit(source, view);
  const right = offsetX + source.width * containFit(source, view).scale;
  const bottom = offsetY + source.height * containFit(source, view).scale;
  const x = Math.max(rect.x, offsetX);
  const y = Math.max(rect.y, offsetY);
  const maxX = Math.min(rect.x + rect.width, right);
  const maxY = Math.min(rect.y + rect.height, bottom);
  return { x, y, width: Math.max(0, maxX - x), height: Math.max(0, maxY - y) };
}

export function hasValidDimensions(box: Box): boolean {
  return box.x_max > box.x_min && box.y_max > box.y_min;
}
