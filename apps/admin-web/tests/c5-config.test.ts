import { afterAll, describe, expect, it } from "vitest";
import en from "../src/i18n/locales/en";
import zhCN from "../src/i18n/locales/zh-CN";
import zhHK from "../src/i18n/locales/zh-HK";
import ja from "../src/i18n/locales/ja";

const NOTICE_KEY =
  "Desired configuration only. Packages are installed manually in M1. Assignment is not proof of download, validation, or activation.";

afterAll(() => {
  // Leave the global locale untouched; this test never switches locales.
});

describe("C5 configuration governance copy", () => {
  it("carries the mandatory manual-install notice in English", () => {
    expect(en[NOTICE_KEY]).toBe(NOTICE_KEY);
  });

  it("translates the manual-install notice in every supported locale", () => {
    expect(zhCN[NOTICE_KEY]).toMatch(/人工安装|手动安装/);
    expect(zhHK[NOTICE_KEY]).toMatch(/人手安裝/);
    expect(ja[NOTICE_KEY]).toMatch(/手動でインストール/);
  });

  it("keeps the assignment-never-activation wording in every locale", () => {
    for (const catalog of [en, zhCN, zhHK, ja]) {
      expect(catalog[NOTICE_KEY]).toMatch(/not proof|不代表|証明では/);
    }
  });
});
