import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const read = (path) => readFileSync(resolve(cwd(), path), "utf8");
const main = read("src/main.tsx");
const css = read("src/styles/ui-specialized-consistency.css");

describe("specialized UI consistency", () => {
  it("loads after the general feature normalization", () => {
    const feature = main.indexOf('import "./styles/ui-feature-consistency.css";');
    const specialized = main.indexOf('import "./styles/ui-specialized-consistency.css";');
    expect(feature).toBeGreaterThanOrEqual(0);
    expect(specialized).toBeGreaterThan(feature);
  });

  it.each([
    ".docker-detail-hero",
    ".docker-detail-container-icon",
    ".docker-detail-tabs",
    ".docker-detail-section",
    ".docker-detail-stat-strip",
    ".hosts-installer-actions",
    ".hosts-group-picker-options",
    ".hosts-search-select-options",
  ])("normalizes specialized surface: %s", (selector) => {
    expect(css).toContain(selector);
  });

  it("removes feature-local elevation and oversized radii", () => {
    expect(css).toContain("box-shadow: none");
    expect(css).toContain("var(--radius-panel)");
    expect(css).toContain("var(--radius-control)");
    expect(css).toContain("var(--surface-elevated)");
    expect(css).not.toContain("!important");
  });

  it("responds to the actual application window", () => {
    expect(css).toContain("@container app-window (max-width: 47.5rem)");
    expect(css).toContain("@container app-window (max-width: 34rem)");
  });
});
