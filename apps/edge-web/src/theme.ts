import { ref } from "vue";

export const THEME_STORAGE_KEY = "assemblyvision.edge.theme";

export const themes = [
  { value: "industrial", label: "Industrial Minimal" },
  { value: "light", label: "Modern Light" },
  { value: "dark", label: "Modern Dark" },
] as const;

export type ThemeName = (typeof themes)[number]["value"];

export const activeTheme = ref<ThemeName>("industrial");

export function isThemeName(value: string | null | undefined): value is ThemeName {
  return themes.some((theme) => theme.value === value);
}

export function storedTheme(storage: Pick<Storage, "getItem"> | null): ThemeName {
  const value = storage?.getItem(THEME_STORAGE_KEY);
  return isThemeName(value) ? value : "industrial";
}

export function applyTheme(theme: ThemeName, storage: Pick<Storage, "setItem"> | null = null): void {
  activeTheme.value = theme;
  if (typeof document !== "undefined") {
    document.documentElement.dataset.theme = theme;
  }
  storage?.setItem(THEME_STORAGE_KEY, theme);
}

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

export function chartTokens(): {
  accent: string;
  ok: string;
  ng: string;
  text: string;
  border: string;
} {
  // Reading the ref makes ECharts option computeds rerun on a theme change.
  void activeTheme.value;
  if (typeof document === "undefined") {
    return { accent: "#126c87", ok: "#237a43", ng: "#b52d2b", text: "#59656a", border: "#adb8bb" };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    accent: token("--accent", "#126c87"),
    ok: token("--status-ok", "#237a43"),
    ng: token("--status-ng", "#b52d2b"),
    text: token("--text-muted", "#59656a"),
    border: token("--border", "#adb8bb"),
  };
}
