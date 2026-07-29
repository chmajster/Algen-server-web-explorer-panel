import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const read = (path) => readFileSync(resolve(cwd(), path), "utf8");
const css = (name) => read(`src/styles/${name}`);
const tokens = css("tokens.css");
const base = css("base.css");
const responsive = css("responsive.css");
const modules = css("modules.css");
const settings = css("settings.css");
const identity = css("identity.css");
const desktopSource = read("src/app/Desktop.tsx");
const scaleSource = read("src/app/interfaceScale.ts");
const settingsSource = read("src/features/settings/SettingsApp.tsx");
const styleFiles = [
  ...readdirSync(resolve(cwd(), "src/styles")).filter((name) => name.endsWith(".css")).map((name) => `src/styles/${name}`),
  "src/features/docker/docker-manager.css",
  "src/features/package-center/package-center.css",
];
const allStyles = styleFiles.map(read).join("\n");
const sourceFiles = (directory) => readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
  const path = resolve(directory, entry.name);
  return entry.isDirectory() ? sourceFiles(path) : [path];
});
const componentSources = sourceFiles(resolve(cwd(), "src"))
  .filter((name) => /\.(?:ts|tsx)$/.test(name) && !/\.test\.(?:ts|tsx)$/.test(name))
  .map((name) => readFileSync(name, "utf8"))
  .join("\n");

describe("global interface scale and typography", () => {
  it.each([
    "--ui-scale", "--font-family-ui", "--font-family-monospace",
    "--font-size-xs", "--font-size-sm", "--font-size-md", "--font-size-base",
    "--font-size-lg", "--font-size-xl", "--font-size-2xl", "--font-size-3xl",
    "--line-height-tight", "--line-height-heading", "--line-height-normal", "--line-height-relaxed",
    "--control-height", "--control-padding-x", "--control-padding-y", "--icon-size",
    "--spacing-xs", "--spacing-sm", "--spacing-md", "--spacing-lg",
    "--taskbar-height", "--taskbar-item-size", "--window-titlebar-height", "--window-border-radius",
  ])("defines the shared %s token", (token) => {
    expect(tokens).toContain(token);
  });

  it("uses ui-scale as the single rem multiplier", () => {
    expect(tokens).toContain("font-size: calc(100% * var(--ui-scale))");
    expect(tokens).toContain("font-size: var(--font-size-md)");
    expect(`${tokens}\n${base}\n${desktopSource}`).not.toContain("--text-scale");
    expect(`${base}\n${desktopSource}`).not.toContain("larger-text");
    expect(desktopSource).not.toContain("--interface-scale");
  });

  it("connects typography, controls, icons and spacing to the same root rem scale", () => {
    for (const declaration of [
      "--font-size-md: 0.875rem",
      "--control-height: 2.25rem",
      "--icon-size: 1.125rem",
      "--spacing-md: 0.75rem",
      "--taskbar-height: 3.625rem",
      "--window-titlebar-height: 2.75rem",
    ]) {
      expect(tokens).toContain(declaration);
    }
    expect(tokens.match(/font-size:\s*calc\(100%\s*\*\s*var\(--ui-scale\)\)/)).toBeTruthy();
    expect(tokens).not.toMatch(/--[\w-]+-scaled\s*:/);
  });

  it("supports only the validated 80%, 90%, 100%, 110% and 125% levels", () => {
    expect(scaleSource).toContain("INTERFACE_SCALE_OPTIONS = [80, 90, 100, 110, 125]");
    expect(scaleSource).toContain("ALLOWED_UI_SCALES = [0.8, 0.9, 1, 1.1, 1.25]");
    expect(scaleSource).toContain("if (!Number.isFinite(parsed)) return INTERFACE_SCALE_DEFAULT");
  });

  it("applies the variable centrally and synchronously on the desktop and document root", () => {
    expect(desktopSource).toContain('"--ui-scale": interfaceScale');
    expect(desktopSource).toContain('root.style.setProperty("--ui-scale", String(interfaceScale))');
    expect(desktopSource).toContain("useLayoutEffect(() =>");
    expect(settingsSource).toContain("INTERFACE_SCALE_OPTIONS.map");
  });

  it("uses shared typography tokens instead of arbitrary local font sizes", () => {
    const stylesWithoutTokens = styleFiles.filter((name) => !name.endsWith("tokens.css")).map(read).join("\n");
    expect(stylesWithoutTokens).not.toMatch(/font-size\s*:\s*[^;{}]*px/i);
    expect(stylesWithoutTokens).not.toMatch(/font-size\s*:\s*(?:\d*\.?\d+)(?:rem|em)\b/i);
    expect(stylesWithoutTokens).not.toMatch(/font\s*:\s*(?:\d{3}\s+)?(?:\d*\.?\d+)(?:rem|em)\b/i);
    expect(componentSources).not.toMatch(/\bfontSize\s*:/);
  });

  it("makes shared form controls inherit the interface font and typography scale", () => {
    for (const selector of [".desktop button", ".desktop input", ".desktop select", ".desktop textarea"]) {
      expect(base).toContain(selector);
    }
    expect(base).toContain("font-family: var(--font-family-ui)");
    expect(base).toContain("font-size: var(--font-size-md)");
    expect(base).toContain("line-height: var(--line-height-normal)");
    expect(base).toContain("min-height: var(--control-height)");
  });

  it("scales tables and keeps them horizontally scrollable", () => {
    expect(base).toContain(".desktop table {");
    expect(base).toContain(".desktop th {");
    expect(base).toContain(".desktop td {");
    expect(base).toContain("padding: var(--spacing-sm) var(--spacing-md)");
    expect(base).toContain('[class*="table-wrap"]');
    expect(base).toContain("overflow-x: auto");
    expect(allStyles).not.toMatch(/\bzoom\s*:/i);
    expect(`${tokens}\n${base}`).not.toMatch(/transform\s*:\s*scale(?:3d|x|y)?\s*\(/i);
  });

  it("uses window container queries for module-level responsive behavior", () => {
    expect(responsive).toContain("@container app-window");
    expect(responsive).toContain(".desktop .settings-app");
    expect(responsive).toContain(".desktop .file-workspace");
    expect(responsive).toContain(".docker-manager-layout");
    expect(responsive).toContain(".package-toolbar");
  });

  it("keeps Hosts Manager dimensions tied to global tokens", () => {
    const hostsRules = [...modules.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
      .filter(([, selectors]) => selectors.includes(".hosts-manager-app"))
      .map((match) => match[0])
      .join("\n");

    for (const token of [
      "--hosts-control-height: var(--control-height)",
      "--hosts-icon-size: var(--icon-size)",
      "--hosts-panel-padding: var(--panel-padding)",
    ]) {
      expect(hostsRules).toContain(token);
    }
    expect(hostsRules).not.toContain("--ui-scale:");
    expect(hostsRules).toContain("min-width: max-content");
  });

  it("keeps policy views and native controls on global tokens", () => {
    const policyRules = settings.slice(
      settings.indexOf(".desktop .policy-browser {"),
      settings.indexOf(".desktop .docker-policy-editor {"),
    );

    expect(policyRules).toContain("height: var(--control-height)");
    expect(policyRules).toContain("font-size: var(--font-size-base)");
    expect(policyRules).not.toMatch(/font-size\s*:\s*[^;{}]*px/i);
  });

  it("keeps embedded access policies responsive without breaking table cells", () => {
    expect(settings).toContain(".desktop .access-policy-browser { grid-template-columns: minmax(11.25rem,25%) minmax(0,75%); }");
    expect(settings).toContain(".desktop .access-policy-detail { min-width: 0; overflow: hidden; }");
    expect(identity).toContain(".access-policy-editor { grid-template-rows: auto minmax(0,1fr); overflow: hidden; }");
    expect(identity).toContain(".identity-role-matrix td:first-child { min-width: 15rem; }");
  });
});
