import { afterAll, afterEach, describe, expect, it, vi } from "vitest";
import en from "../src/i18n/locales/en";
import zhCN from "../src/i18n/locales/zh-CN";
import zhHK from "../src/i18n/locales/zh-HK";
import ja from "../src/i18n/locales/ja";
import { applyLocale, defaultLocale, i18n, isSupportedLocale, storedLocale, SUPPORTED_LOCALES } from "../src/i18n";

afterAll(() => {
  // Leave the global locale on the default so other tests in the same worker
  // never observe a translated catalog.
  applyLocale("en");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

function keys(messages: object): string[] {
  return Object.keys(messages).sort();
}

const LOCALES = {
  en,
  "zh-CN": zhCN,
  "zh-HK": zhHK,
  ja,
} as const;

describe("i18n locale catalogs", () => {
  it("covers exactly the four requested locales with English as the default", () => {
    expect(SUPPORTED_LOCALES.map((l) => l.value)).toEqual(["en", "zh-CN", "zh-HK", "ja"]);
    expect(i18n.global.locale.value).toBe("en");
    expect(i18n.global.fallbackLocale.value).toBe("en");
  });

  it("keeps every non-English catalog key-aligned with the English source", () => {
    const english = keys(en);
    for (const [locale, messages] of Object.entries(LOCALES)) {
      if (locale === "en") continue;
      expect(keys(messages), `${locale} must not miss English keys`).toEqual(english);
    }
  });

  it("uses the English text itself as the key (identity values in en)", () => {
    for (const [key, value] of Object.entries(en)) {
      expect(value, `en value for "${key}" must equal the key`).toBe(key);
    }
  });

  it("translates spot-checked strings per locale", () => {
    const samples: Array<[string, Record<string, string>]> = [
      ["en", { Overview: "Overview", "Inspection history": "Inspection history" }],
      ["zh-CN", { Overview: "总览", "Inspection history": "检验历史记录" }],
      ["zh-HK", { Overview: "總覽", "Inspection history": "檢驗歷史記錄" }],
      ["ja", { Overview: "概要", "Inspection history": "検査履歴" }],
    ];
    for (const [locale, expected] of samples) {
      for (const [key, translation] of Object.entries(expected)) {
        applyLocale(locale as (typeof SUPPORTED_LOCALES)[number]["value"]);
        expect(i18n.global.t(key), `${locale} must translate "${key}"`).toBe(translation);
      }
    }
  });

  it("resolves interpolation parameters in every locale", () => {
    for (const locale of ["en", "zh-CN", "zh-HK", "ja"]) {
      applyLocale(locale as (typeof SUPPORTED_LOCALES)[number]["value"]);
      const value = i18n.global.t("Inspection {id}", { id: "abc-123" });
      expect(value).toContain("abc-123");
    }
  });

  it("falls back to the key itself for unknown messages", () => {
    applyLocale("en");
    expect(i18n.global.t("NONEXISTENT_KEY_123")).toBe("NONEXISTENT_KEY_123");
  });
});

describe("locale selection", () => {
  it("defaults to English when nothing is stored", () => {
    expect(storedLocale(null)).toBe("en");
    expect(storedLocale({ getItem: () => null })).toBe("en");
    expect(storedLocale({ getItem: () => "unknown-locale" })).toBe("en");
  });

  it("reads the build-time default language from VITE_DEFAULT_LOCALE", () => {
    expect(defaultLocale()).toBe("en");
    vi.stubEnv("VITE_DEFAULT_LOCALE", "zh-CN");
    expect(defaultLocale()).toBe("zh-CN");
    vi.stubEnv("VITE_DEFAULT_LOCALE", "ja");
    expect(defaultLocale()).toBe("ja");
    // An unsupported value falls back to English.
    vi.stubEnv("VITE_DEFAULT_LOCALE", "fr");
    expect(defaultLocale()).toBe("en");
  });

  it("uses the configured default when no user locale is stored", () => {
    vi.stubEnv("VITE_DEFAULT_LOCALE", "zh-HK");
    expect(storedLocale(null)).toBe("zh-HK");
    expect(storedLocale({ getItem: () => "unknown-locale" })).toBe("zh-HK");
  });

  it("restores a supported stored locale over the configured default", () => {
    vi.stubEnv("VITE_DEFAULT_LOCALE", "ja");
    expect(storedLocale({ getItem: () => "zh-HK" })).toBe("zh-HK");
    expect(storedLocale({ getItem: () => "en" })).toBe("en");
  });

  it("persists the selection on applyLocale", () => {
    const written: Record<string, string> = {};
    const storage = {
      setItem: (key: string, value: string) => {
        written[key] = value;
      },
    };
    applyLocale("zh-CN", storage);
    expect(written["assemblyvision.admin.locale"]).toBe("zh-CN");
    expect(i18n.global.locale.value).toBe("zh-CN");
  });

  it("validates locale values against the supported set", () => {
    expect(isSupportedLocale("en")).toBe(true);
    expect(isSupportedLocale("zh-HK")).toBe(true);
    expect(isSupportedLocale("fr")).toBe(false);
    expect(isSupportedLocale(undefined)).toBe(false);
  });
});
