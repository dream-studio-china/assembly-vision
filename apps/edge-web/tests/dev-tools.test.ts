import { describe, expect, it } from "vitest";
import { productBoxStyle } from "../src/services/devOverlay";

function recordWithBox(box: {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
  image_width: number;
  image_height: number;
}): Parameters<typeof productBoxStyle>[0] {
  return {
    product_detection: { bbox: box },
  } as Parameters<typeof productBoxStyle>[0];
}

describe("productBoxStyle (ADR-014 dev overlay)", () => {
  it("returns null when there is no product detection", () => {
    expect(productBoxStyle(null)).toBeNull();
    expect(productBoxStyle({ product_detection: null } as never)).toBeNull();
  });

  it("computes percentage geometry from full-frame coordinates", () => {
    const style = productBoxStyle(
      recordWithBox({ x_min: 100, y_min: 50, x_max: 700, y_max: 550, image_width: 1000, image_height: 1000 }),
    );
    expect(style).toEqual({
      left: "10%",
      top: "5%",
      width: "60%",
      height: "50%",
    });
  });

  it("returns null for degenerate image dimensions", () => {
    expect(
      productBoxStyle(
        recordWithBox({ x_min: 0, y_min: 0, x_max: 10, y_max: 10, image_width: 0, image_height: 100 }),
      ),
    ).toBeNull();
  });
});
