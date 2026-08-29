import { describe, expect, it } from "vitest";
import en from "./locales/en-US.json";
import pl from "./locales/pl-PL.json";
import { loadLanguage, translate } from "./i18n";

describe("translations", () => {
  it("keeps Polish and English dictionaries complete", async () => {
    await Promise.all([loadLanguage("pl-PL"), loadLanguage("en-US")]);
    expect(Object.keys(pl).sort()).toEqual(Object.keys(en).sort());
    expect(translate("pl-PL", "app.fileManager")).toBe("Menedżer plików");
    expect(translate("en-US", "status.ready")).toBe("Ready");
  });
});
