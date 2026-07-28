import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const css = (name) => readFileSync(resolve(cwd(), `src/styles/${name}`), "utf8");
const tokens = css("tokens.css");
const base = css("base.css");
const responsive = css("responsive.css");
const modules = css("modules.css");
const settings = css("settings.css");
const identity = css("identity.css");
const allStyles = readdirSync(resolve(cwd(), "src/styles"))
  .filter((name) => name.endsWith(".css"))
  .map((name) => css(name))
  .join("\n");

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

  it("keeps Hosts Manager dimensions tied to the global rem scale", () => {
    const hostsRules = [...modules.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter(([, selectors]) => selectors.includes(".hosts-manager-app"))
      .map((match) => match[0])
      .join("\n");

    expect(modules).toContain(".hosts-manager-app {");
    for (const token of [
      "--hosts-control-height: var(--control-height)",
      "--hosts-icon-size: var(--icon-size)",
      "--hosts-panel-padding: var(--panel-padding)",
    ]) {
      expect(hostsRules).toContain(token);
    }
    expect(hostsRules).not.toMatch(/font-size\s*:\s*[^;{}]*px/i);
    expect(hostsRules).not.toMatch(/\bzoom\s*:/i);
    expect(hostsRules).not.toMatch(/transform\s*:\s*scale(?:3d|x|y)?\s*\(/i);
    expect(hostsRules).not.toContain("--ui-scale:");
    expect(hostsRules).toMatch(/(?:\d*\.?\d+rem|\d*\.?\d+em|var\(--hosts-)/);
    expect(hostsRules).toContain("min-width: max-content");
  });

  it("scopes Hosts overrides without replacing Ansible Controller rules", () => {
    expect(modules).toContain(".ansible-panel {");
    expect(modules).toContain(".hosts-manager-app .ansible-panel {");
    expect(modules).toContain(".hosts-manager-app .hosts-data-table");
  });

  it("binds policy views and their native controls directly to the root rem scale", () => {
    const policyRules = settings.slice(
      settings.indexOf(".desktop .policy-browser {"),
      settings.indexOf(".desktop .docker-policy-editor {"),
    );

    expect(policyRules).toContain("font-size: 1rem");
    expect(policyRules).toContain("height: var(--control-height)");
    expect(policyRules).toContain("font-size: var(--font-size-base)");
    expect(policyRules).not.toMatch(/font-size\s*:\s*[^;{}]*px/i);
    expect(policyRules).not.toMatch(/font-size\s*:\s*\d*\.?\d+em\b/i);
    expect(policyRules).not.toMatch(/\bzoom\s*:/i);
    expect(policyRules).not.toMatch(/transform\s*:\s*scale(?:3d|x|y)?\s*\(/i);
  });

  it("scales every select and its native options from the root rem size", () => {
    const selectRules = [...allStyles.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter(([, selectors]) => /\b(?:select|option|optgroup)(?=[\s:.[\]#>,+~]|$)/i.test(selectors))
      .map((match) => match[0])
      .join("\n");

    expect(base).toContain(".desktop select {");
    expect(base).toContain("font-size: 1rem");
    expect(base).toContain(".desktop select option");
    expect(base).toContain(".desktop select optgroup");
    expect(selectRules).not.toMatch(/font-size\s*:\s*[^;{}]*px/i);
    expect(selectRules).not.toMatch(/font-size\s*:\s*\d*\.?\d+em\b/i);
    expect(selectRules).not.toMatch(/\bzoom\s*:/i);
    expect(selectRules).not.toMatch(/transform\s*:\s*scale(?:3d|x|y)?\s*\(/i);
  });

  it("keeps every table font connected to the interface scale", () => {
    const tableRules = [...allStyles.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter(([, selectors]) => /\b(?:table|thead|tbody|tfoot|tr|th|td)(?=[\s:.[\]#>,+~]|$)/i.test(selectors))
      .map((match) => match[0])
      .join("\n");

    for (const element of ["table", "thead", "tbody", "tfoot", "tr", "th", "td"]) {
      expect(base).toContain(`.desktop ${element}`);
    }
    expect(base).toContain("font-size: inherit");
    expect(tableRules).not.toMatch(/font-size\s*:\s*[^;{}]*px/i);
    expect(tableRules).not.toMatch(/font-size\s*:\s*(?![^;{}]*rem\b)\d*\.?\d+em\b/i);
    expect(tableRules).not.toMatch(/\bzoom\s*:/i);
    expect(tableRules).not.toMatch(/transform\s*:\s*scale(?:3d|x|y)?\s*\(/i);
  });

  it("gives embedded access policies the full second column without breaking table cells", () => {
    expect(settings).toContain(".desktop .access-policy-browser { grid-template-columns: minmax(11.25rem,25%) minmax(0,75%); }");
    expect(settings).toContain(".desktop .access-policy-detail { min-width: 0; overflow: hidden; }");
    expect(identity).toContain(".access-policy-editor { grid-template-rows: auto minmax(0,1fr); overflow: hidden; }");
    expect(identity).toContain(".identity-role-matrix td:first-child { min-width: 15rem; }");
    expect(identity).not.toContain(".identity-role-matrix td:first-child { display: grid");
  });
});
