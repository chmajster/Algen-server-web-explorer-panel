import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(cwd(), "src/styles/visual-regressions.css"), "utf8");
const main = readFileSync(resolve(cwd(), "src/main.tsx"), "utf8");
const packageJson = JSON.parse(readFileSync(resolve(cwd(), "package.json"), "utf8"));

describe("visual regression corrections", () => {
  it("keeps the final correction layer last", () => {
    expect(main).toContain('import "./styles/shell-taskbar.css";\nimport "./styles/visual-regressions.css";');
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

  it("prevents narrow taskbar collisions and restores touch-sized controls", () => {
    expect(css).toContain("@media (max-width: 360px)");
    expect(css).toContain(".transfer-indicator, .actions-indicator");
    expect(css).toContain("--control-height: 2.75rem");
  });

  it("styles bootstrap retry and synchronizes browser theme chrome", () => {
    expect(main).toContain('retry.className = "button button-primary boot-retry"');
    expect(main).toContain("installThemeColorSync");
    expect(main).toContain('meta.content = desktop?.classList.contains("dark") ? "#20252a" : "#f4f5f6"');
  });

  it("lets the Playwright configuration control CI reporters", () => {
    expect(packageJson.scripts["test:e2e:ci"]).toBe("playwright test");
  });
});
