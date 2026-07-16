import { describe, expect, it } from "vitest";

import "./app.css";

function styleRule(selector: string) {
  for (const sheet of Array.from(document.styleSheets)) {
    for (const rule of Array.from(sheet.cssRules)) {
      if (rule instanceof CSSStyleRule && rule.selectorText === selector) return rule.style;
    }
  }
  return null;
}

describe("theme semantic colors", () => {
  it("keeps primary and dangerous button text contrasted in every component", () => {
    const primary = styleRule("#root .button-primary");
    const danger = styleRule("#root .button-danger");

    expect(primary?.getPropertyValue("color")).toBe("var(--text-on-accent)");
    expect(primary?.getPropertyValue("background")).toBe("var(--accent)");
    expect(danger?.getPropertyValue("color")).toBe("var(--text-on-danger)");
    expect(danger?.getPropertyValue("background")).toBe("var(--danger)");
  });
});
