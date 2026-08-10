import { describe, expect, it } from "vitest";

import { THEME_STORAGE_KEY, isThemeName, storedTheme } from "../src/theme";

describe("edge web theme selection", () => {
  it("accepts only supported themes", () => {
    expect(isThemeName("industrial")).toBe(true);
    expect(isThemeName("light")).toBe(true);
    expect(isThemeName("dark")).toBe(true);
    expect(isThemeName("neon")).toBe(false);
  });

  it("uses Industrial Minimal when preference is absent or invalid", () => {
    expect(storedTheme(null)).toBe("industrial");
    expect(storedTheme({ getItem: () => "neon" })).toBe("industrial");
  });

  it("reads a persisted supported preference", () => {
    expect(storedTheme({ getItem: (key) => (key === THEME_STORAGE_KEY ? "dark" : null) })).toBe(
      "dark",
    );
  });
});
