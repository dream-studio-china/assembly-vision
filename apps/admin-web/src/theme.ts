/**
 * Admin dashboard theme (docs/design/17-central-admin-dashboard.md).
 *
 * The interface is a flat industrial look with zero shadows and zero
 * rounded corners; only the palette differs between the white (light) and
 * black (dark) themes. The active theme is set as the `data-theme` attribute
 * on `<html>` and persisted in browser storage, mirroring the edge dashboard
 * theme system (design 16.2.1).
 */
import { ref } from "vue";

export const THEME_STORAGE_KEY = "assemblyvision.admin.theme";

export const themes = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
] as const;

export type ThemeName = (typeof themes)[number]["value"];

export const activeTheme = ref<ThemeName>("light");

export function isThemeName(value: string | null | undefined): value is ThemeName {
  return themes.some((theme) => theme.value === value);
}

/** Resolve the persisted theme, falling back to the white (light) default. */
export function storedTheme(storage: Pick<Storage, "getItem"> | null): ThemeName {
  const value = storage?.getItem(THEME_STORAGE_KEY);
  return isThemeName(value) ? value : "light";
}

/** Apply a theme and optionally persist it. */
export function applyTheme(theme: ThemeName, storage: Pick<Storage, "setItem"> | null = null): void {
  activeTheme.value = theme;
  if (typeof document !== "undefined") {
    document.documentElement.dataset.theme = theme;
  }
  storage?.setItem(THEME_STORAGE_KEY, theme);
}

/** Restore the persisted theme (or the light default) before the app mounts. */
export function initializeTheme(): ThemeName {
  let storage: Storage | null = null;
  try {
    storage = typeof window === "undefined" ? null : window.localStorage;
  } catch {
    // Private browsing or a restricted kiosk must still render the default theme.
  }
  const theme = storedTheme(storage);
  applyTheme(theme, storage);
  return theme;
}

/** Toggle between the white and black themes. */
export function toggleTheme(storage: Pick<Storage, "setItem"> | null = null): ThemeName {
  const next = activeTheme.value === "light" ? "dark" : "light";
  applyTheme(next, storage);
  return next;
}
