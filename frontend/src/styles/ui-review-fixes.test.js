import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const read = (path) => readFileSync(resolve(cwd(), path), "utf8");
const main = read("src/main.tsx");
const css = read("src/styles/ui-review-fixes.css");

describe("UI review regression fixes", () => {
  it("loads review fixes after all normalization layers", () => {
    const specialized = main.indexOf('import "./styles/ui-specialized-consistency.css";');
    const fixes = main.indexOf('import "./styles/ui-review-fixes.css";');
    expect(specialized).toBeGreaterThanOrEqual(0);
    expect(fixes).toBeGreaterThan(specialized);
  });

  it("keeps stale monitor content in the flexible fourth row", () => {
    expect(css).toContain("grid-template-rows: auto auto auto minmax(0, 1fr)");
    expect(css).toContain(".desktop .monitor-content");
    expect(css).toContain("grid-row: 4");
  });

  it("preserves primary and danger semantic hover colors", () => {
    expect(css).toContain(".button-primary, button.button-primary");
    expect(css).toContain(".button-danger, button.button-danger");
    expect(css).toContain("var(--text-on-accent)");
    expect(css).toContain("var(--text-on-danger)");
  });

  it("keeps transfer labels paired with values", () => {
    expect(css).toContain("grid-template-columns: minmax(7rem, auto) minmax(0, 1fr)");
    expect(css).toContain(".desktop .transfer-details dt");
    expect(css).toContain(".desktop .transfer-details dd");
    expect(css).toContain("@container app-window (max-width: 36rem)");
  });

  it("does not use important overrides", () => {
    expect(css).not.toContain("!important");
  });
});
