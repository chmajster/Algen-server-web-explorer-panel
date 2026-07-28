import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const css = (name) => readFileSync(resolve(cwd(), `src/styles/${name}`), "utf8");
const tokens = css("tokens.css");
const base = css("base.css");
const responsive = css("responsive.css");

describe("global interface scale and typography", () => {
  it.each([
    "--ui-scale", "--text-scale", "--font-family-ui", "--font-family-monospace",
    "--control-height", "--icon-size", "--panel-padding", "--sidebar-width",
    "--taskbar-height", "--taskbar-item-size", "--window-titlebar-height",
  ])("defines the shared %s token", (token) => {
    expect(tokens).toContain(token);
  });

  it("keeps text scaling independent from rem-based interface scaling", () => {
    expect(tokens).toContain("font-size: calc(1rem * var(--text-scale))");
    expect(base).toContain(".desktop.larger-text { --text-scale: 1.125; }");
    expect(base).not.toContain("--ui-scale: 1.125");
  });

  it("makes shared form controls inherit the selected interface font", () => {
    for (const selector of [".desktop button", ".desktop input", ".desktop select", ".desktop textarea", ".desktop table"]) {
      expect(base).toContain(selector);
    }
    expect(base).toContain("font-family: var(--font-family-ui)");
  });

  it("uses window container queries for module-level responsive behavior", () => {
    expect(responsive).toContain("@container app-window");
    expect(responsive).toContain(".desktop .settings-app");
    expect(responsive).toContain(".desktop .file-workspace");
    expect(responsive).toContain(".docker-manager-layout");
    expect(responsive).toContain(".package-toolbar");
  });
});
