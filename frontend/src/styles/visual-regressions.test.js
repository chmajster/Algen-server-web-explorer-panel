import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(cwd(), "src/styles/visual-regressions.css"), "utf8");
const compatCss = readFileSync(resolve(cwd(), "src/styles/legacy-window-compat.css"), "utf8");
const main = readFileSync(resolve(cwd(), "src/main.tsx"), "utf8");
const packageJson = JSON.parse(readFileSync(resolve(cwd(), "package.json"), "utf8"));

describe("visual regression corrections", () => {
  it("keeps compatibility corrections after the regular visual regression layer", () => {
    expect(main).toContain('import "./styles/visual-regressions.css";\nimport "./styles/legacy-window-compat.css";');
  });

  it("uses selected accent colors without low-contrast primary button fills", () => {
    expect(css).toContain("background: color-mix(in srgb, var(--accent) 62%, #000)");
    expect(css).toContain("color: var(--text-on-accent)");
    expect(css).not.toContain("background: linear-gradient(#2aaae0, #168fc7)");
  });

  it("keeps close controls readable on danger hover", () => {
    expect(css).toContain(".window-controls .window-close:hover");
    expect(css).toContain("color: #fff");
  });

  it("fixes legacy network dialog dark mode and modal layering", () => {
    expect(css).toContain(".desktop.dark .network-modal footer button:not(.button-primary):not(.button-danger)");
    expect(css).toContain("z-index: var(--webnas-layer-modal, 6000)");
    expect(css).toContain("z-index: var(--webnas-layer-system-critical, 10000)");
  });

  it("restores touch-sized controls without hiding taskbar indicators", () => {
    expect(css).toContain("--control-height: 2.75rem");
    expect(css).not.toContain("display: none;\n  }\n\n  .desktop .taskbar-primary");
  });

  it("styles bootstrap retry and synchronizes browser theme chrome", () => {
    expect(main).toContain('retry.className = "button button-primary boot-retry"');
    expect(main).toContain("installThemeColorSync");
    expect(main).toContain('meta.content = desktop?.classList.contains("dark") ? "#20252a" : "#f4f5f6"');
  });

  it("maps legacy feature tokens to canonical theme and accent tokens", () => {
    const aliases = [
      "--panel: var(--surface-elevated)",
      "--input: var(--surface-secondary)",
      "--muted: var(--text-secondary)",
      "--input-bg: var(--surface-secondary)",
      "--border-color: var(--border-subtle)",
      "--surface-1: var(--surface-elevated)",
      "--surface-2: var(--surface-secondary)",
      "--accent-color: var(--accent)",
      "--background: var(--surface-primary)",
      "--panel-bg: var(--surface-elevated)",
      "--window-bg: var(--surface-elevated)",
      "--success-color: var(--success)",
      "--warning-color: var(--warning)",
      "--danger-color: var(--danger)",
    ];

    for (const alias of aliases) expect(compatCss).toContain(alias);
    expect(compatCss).toContain(".desktop.desktop {");
  });

  it("reacts to resizable application-window width with cascade-safe selectors", () => {
    for (const breakpoint of [920, 900, 800, 760, 680, 480, 430, 1024, 768]) {
      expect(compatCss).toContain(`@container app-window (max-width: ${breakpoint}px)`);
    }

    for (const selector of [
      ".desktop .image-converter-layout",
      ".desktop .alert-manager__summary",
      ".desktop .security-stat-grid",
      ".desktop .dhcp-config-grid",
      ".desktop .cron-fields",
      ".desktop .infra-manager-header",
      ".desktop .ldap-summary-grid",
      ".desktop .auth-mode-grid",
    ]) expect(compatCss).toContain(selector);
  });

  it("lets the Playwright configuration control CI reporters", () => {
    expect(packageJson.scripts["test:e2e:ci"]).toBe("playwright test");
  });
});
