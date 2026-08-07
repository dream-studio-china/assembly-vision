import { describe, expect, it } from "vitest";
import { resolveLoadTarget } from "../src/load-target";

const DIST = "/repo/apps/edge-web/dist/index.html";

describe("resolveLoadTarget", () => {
  it("loads the bundled dashboard in production", () => {
    expect(resolveLoadTarget({ dev: false, devUrl: "http://localhost:5173", distIndexPath: DIST })).toBe(DIST);
  });

  it("loads the Vite dev server in development", () => {
    expect(resolveLoadTarget({ dev: true, devUrl: "http://localhost:5173", distIndexPath: DIST })).toBe(
      "http://localhost:5173",
    );
  });

  it("honors a custom dev server URL", () => {
    expect(resolveLoadTarget({ dev: true, devUrl: "http://127.0.0.1:5174", distIndexPath: DIST })).toBe(
      "http://127.0.0.1:5174",
    );
  });
});
