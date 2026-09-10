import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const read = (path) => readFileSync(join(cwd(), path), "utf8");

const settingsWindow = read("src/features/settings/settings-window.css");
const securityTools = read("src/modules/security-tools.css");
const widgets = read("src/styles/widgets.css");
const fileManager = read("src/styles/file-manager.css");
const dialogs = read("src/styles/dialog-compat.css");
const tokens = read("src/styles/tokens.css");

describe("visual audit follow-up regressions", () => {
  it("gives compact Settings rules enough specificity to beat shared DSM styles", () => {
    expect(settingsWindow).toContain(".desktop .window-content > .settings-app");
    expect(settingsWindow).toContain(".desktop .window-content > .settings-app > .settings-sidebar");
    expect(settingsWindow).toContain("display: none;");
    expect(settingsWindow).toContain("grid-template-columns: minmax(0, 1fr);");
  });

  it("keeps security tools on canonical light/dark theme tokens", () => {
    expect(securityTools).toContain("background: var(--surface-primary);");
    expect(securityTools).toContain("background: var(--surface-elevated);");
    expect(securityTools).toContain("background: var(--surface-secondary);");
    expect(securityTools).not.toMatch(/var\(--surface-(?:canvas|raised|sunken),/);
    expect(securityTools).not.toContain("#0f1115");
    expect(securityTools).not.toContain("#171b22");
    expect(securityTools).not.toContain("#0d1015");
  });

  it("uses canonical tokens for desktop widgets", () => {
    for (const legacy of ["--border)", "--surface)", "--surface-muted)", "--text)", "--radius-lg)", "--shadow-sm)"]) {
      expect(widgets).not.toContain(`var(${legacy}`);
    }
    expect(widgets).toContain("var(--border-subtle)");
    expect(widgets).toContain("var(--surface-elevated)");
    expect(widgets).toContain("var(--text-primary)");
  });

  it("keeps the phone File Manager tree in document flow instead of over the file list", () => {
    expect(fileManager).toContain(".file-workspace:has(> .directory-tree)");
    expect(fileManager).toContain("grid-template-rows: minmax(8rem, 34%) minmax(0, 1fr);");
    expect(fileManager).toContain("position: relative;");
    expect(fileManager).toContain("grid-row: 2;");
  });

  it("keeps simple mobile input and confirmation dialogs content-sized", () => {
    expect(dialogs).toContain(":has(> .modal-body > .input-dialog-form)");
    expect(dialogs).toContain(":has(> .modal-body > p:only-child)");
    expect(dialogs).toContain("height: auto !important;");
    expect(dialogs).toContain("transform: translate(-50%, -50%) !important;");
  });

  it("defines compatibility aliases for legacy token names", () => {
    for (const token of [
      "--surface", "--surface-muted", "--surface-overlay", "--surface-canvas", "--surface-raised", "--surface-sunken",
      "--border", "--text", "--radius-lg", "--shadow-sm", "--shadow-small", "--shadow-medium", "--shadow-large",
      "--shadow-overlay", "--shadow-control", "--accent-soft", "--accent-contrast", "--button-primary-text",
    ]) {
      expect(tokens).toContain(`${token}:`);
    }
  });
});
