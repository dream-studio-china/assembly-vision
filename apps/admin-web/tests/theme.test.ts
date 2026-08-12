import { describe, expect, it } from "vitest";

import { THEME_STORAGE_KEY, isThemeName, storedTheme, toggleTheme, activeTheme, applyTheme } from "../src/theme";

describe("admin web theme selection", () => {
  it("accepts only the supported black/white themes", () => {
    expect(isThemeName("light")).toBe(true);
    expect(isThemeName("dark")).toBe(true);
    expect(isThemeName("industrial")).toBe(false);
    expect(isThemeName("neon")).toBe(false);
  });

  it("uses the light (white) theme when preference is absent or invalid", () => {
    expect(storedTheme(null)).toBe("light");
    expect(storedTheme({ getItem: () => "neon" })).toBe("light");
  });

  it("reads a persisted supported preference", () => {
    expect(storedTheme({ getItem: (key) => (key === THEME_STORAGE_KEY ? "dark" : null) })).toBe(
      "dark",
    );
  });

  it("toggles between the white and black themes", () => {
    applyTheme("light");
    expect(toggleTheme()).toBe("dark");
    expect(activeTheme.value).toBe("dark");
    expect(toggleTheme()).toBe("light");
  });

  it("persists the selection on toggleTheme", () => {
    const written: Record<string, string> = {};
    const storage = {
      setItem: (key: string, value: string) => {
        written[key] = value;
      },
    };
    toggleTheme(storage);
    expect(written[THEME_STORAGE_KEY]).toBe("dark");
    toggleTheme(storage);
    expect(written[THEME_STORAGE_KEY]).toBe("light");
  });
});
