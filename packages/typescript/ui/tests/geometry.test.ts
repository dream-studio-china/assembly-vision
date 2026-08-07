import { describe, expect, it } from "vitest";
import { boxToRect, clipToImageRect, containFit, mapBoxToView } from "../src/detection-viewer/geometry";

const SOURCE = { width: 800, height: 600 };
const VIEW = { width: 400, height: 300 };

describe("containFit", () => {
  it("letterboxes a taller view with horizontal centering", () => {
    const fit = containFit(SOURCE, { width: 400, height: 200 });
    // height-limited: scale = 200/600 = 1/3; fitted width = 266.67; offsetX = (400-266.67)/2
    expect(fit.scale).toBeCloseTo(1 / 3);
    expect(fit.offsetX).toBeCloseTo((400 - 800 / 3) / 2);
    expect(fit.offsetY).toBeCloseTo(0);
  });

  it("maps 800x600 into 400x300 with exact scale 0.5 and no offset", () => {
    const fit = containFit(SOURCE, VIEW);
    expect(fit.scale).toBeCloseTo(0.5);
    expect(fit.offsetX).toBeCloseTo(0);
    expect(fit.offsetY).toBeCloseTo(0);
  });

  it("centers a tall source horizontally", () => {
    const fit = containFit({ width: 400, height: 800 }, VIEW);
    // height-limited: scale = 300/800 = 0.375; fitted width = 150; offsetX = 125
    expect(fit.scale).toBeCloseTo(0.375);
    expect(fit.offsetX).toBeCloseTo(125);
    expect(fit.offsetY).toBeCloseTo(0);
  });

  it("guards degenerate sizes", () => {
    expect(containFit({ width: 0, height: 0 }, VIEW).scale).toBe(0);
    expect(containFit(SOURCE, { width: 0, height: 0 }).scale).toBe(0);
  });
});

describe("mapBoxToView / boxToRect", () => {
  it("maps a source box into the 0.5-scale view", () => {
    const rect = boxToRect({ x_min: 100, y_min: 80, x_max: 700, y_max: 520 }, SOURCE, VIEW);
    expect(rect.x).toBeCloseTo(50);
    expect(rect.y).toBeCloseTo(40);
    expect(rect.width).toBeCloseTo(300);
    expect(rect.height).toBeCloseTo(220);
  });

  it("mapBoxToView preserves ordering", () => {
    const mapped = mapBoxToView({ x_min: 10, y_min: 10, x_max: 20, y_max: 20 }, SOURCE, VIEW);
    expect(mapped.x_max).toBeGreaterThan(mapped.x_min);
    expect(mapped.y_max).toBeGreaterThan(mapped.y_min);
  });
});

describe("clipToImageRect", () => {
  it("clips an overlay that spills into the letterbox bar", () => {
    const rect = { x: -20, y: 40, width: 100, height: 100 };
    const clipped = clipToImageRect(rect, SOURCE, VIEW);
    expect(clipped.x).toBeCloseTo(0);
    expect(clipped.width).toBeCloseTo(80);
  });
});
