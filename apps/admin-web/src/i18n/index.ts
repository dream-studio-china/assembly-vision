/**
 * Central dashboard internationalization (docs/design/17-central-admin-dashboard.md).
 *
 * English is the source locale and the default. Every message key is the
 * English text itself (`t("History")`), so code stays readable and the other
 * locale files simply translate the same keys. Missing keys fall back to
 * English via vue-i18n's fallback locale.
 *
 * The default locale is configurable per build through
 * `VITE_DEFAULT_LOCALE` in `.env.development` / `.env.production`
 * (en | zh-CN | zh-HK | ja); an unset or unsupported value falls back to
 * English. A user-selected locale persists in browser storage and always
 * wins over the build default.
 */
import { createI18n } from "vue-i18n";
import { ref } from "vue";
import en from "./locales/en";
import zhCN from "./locales/zh-CN";
import zhHK from "./locales/zh-HK";
import ja from "./locales/ja";

export const LOCALE_STORAGE_KEY = "assemblyvision.admin.locale";

export const SUPPORTED_LOCALES = [
  { value: "en", label: "English" },
  { value: "zh-CN", label: "简体中文（中国内地）" },
  { value: "zh-HK", label: "繁體中文（中國香港）" },
  { value: "ja", label: "日本語" },
] as const;

export type Locale = (typeof SUPPORTED_LOCALES)[number]["value"];

export function isSupportedLocale(value: string | null | undefined): value is Locale {
  return SUPPORTED_LOCALES.some((locale) => locale.value === value);
}

/** Build-time default language from `VITE_DEFAULT_LOCALE`; English when unset. */
export function defaultLocale(): Locale {
  const value = import.meta.env.VITE_DEFAULT_LOCALE as string | undefined;
  return isSupportedLocale(value) ? value : "en";
}

/** Resolve the persisted locale, falling back to the configured default. */
export function storedLocale(storage: Pick<Storage, "getItem"> | null): Locale {
  const value = storage?.getItem(LOCALE_STORAGE_KEY);
  return isSupportedLocale(value) ? value : defaultLocale();
}

export const i18n = createI18n({
  legacy: false,
  locale: defaultLocale(),
  fallbackLocale: "en",
  messages: {
    en,
    "zh-CN": zhCN,
    "zh-HK": zhHK,
    ja,
  },
});

/** Currently selected locale; bound by the header language selector. */
export const activeLocale = ref<Locale>(defaultLocale());

/**
 * Switch the interface language. The document `lang` attribute is kept in
 * sync so screen readers and the browser translate correctly.
 */
export function applyLocale(locale: Locale, storage: Pick<Storage, "setItem"> | null = null): void {
  activeLocale.value = locale;
  i18n.global.locale.value = locale;
  if (typeof document !== "undefined") {
    document.documentElement.lang = locale;
  }
  storage?.setItem(LOCALE_STORAGE_KEY, locale);
}

/** Restore the persisted locale (or English) before the app mounts. */
export function initializeLocale(): Locale {
  let storage: Storage | null = null;
  try {
    storage = typeof window === "undefined" ? null : window.localStorage;
  } catch {
    // Private browsing or a restricted kiosk must still render the default locale.
  }
  const locale = storedLocale(storage);
  applyLocale(locale, storage);
  return locale;
}

export default i18n;
