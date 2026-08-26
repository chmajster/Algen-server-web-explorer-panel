import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const read = (path) => readFileSync(resolve(cwd(), path), "utf8");
const main = read("src/main.tsx");
const css = read("src/styles/ui-feature-consistency.css");

describe("remaining feature UI consistency", () => {
  it("loads after the shared consistency layer", () => {
    const shared = main.indexOf('import "./styles/ui-consistency.css";');
    const feature = main.indexOf('import "./styles/ui-feature-consistency.css";');
    expect(shared).toBeGreaterThanOrEqual(0);
    expect(feature).toBeGreaterThan(shared);
  });

  it.each([
    ".settings-header",
    ".activity-header",
    ".activity-summary",
    ".transfer-center",
    ".transfer-actions",
    ".network-mounts-page-header",
    ".network-mount-card",
    ".network-settings-tabs",
  ])("normalizes the remaining feature surface: %s", (selector) => {
    expect(css).toContain(selector);
  });

  it("uses the shared compact design tokens", () => {
    expect(css).toContain("var(--control-height)");
    expect(css).toContain("var(--radius-control)");
    expect(css).toContain("var(--radius-panel)");
    expect(css).toContain("var(--surface-elevated)");
    expect(css).toContain("var(--border-subtle)");
    expect(css).toContain("var(--accent)");
    expect(css).not.toContain("!important");
  });

  it("uses window-relative responsive breakpoints", () => {
    expect(css).toContain("@container app-window (max-width: 47.5rem)");
    expect(css).toContain("@container app-window (max-width: 36rem)");
    expect(css).toContain("@container app-window (max-width: 28rem)");
  });
});
