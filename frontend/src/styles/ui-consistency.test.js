import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const read = (path) => readFileSync(resolve(cwd(), path), "utf8");
const main = read("src/main.tsx");
const css = read("src/styles/ui-consistency.css");

describe("final UI consistency layer", () => {
  it("loads after the DSM presentation layer", () => {
    const dsm = main.indexOf('import "./styles/dsm.css";');
    const consistency = main.indexOf('import "./styles/ui-consistency.css";');
    expect(dsm).toBeGreaterThanOrEqual(0);
    expect(consistency).toBeGreaterThan(dsm);
  });

  it.each([
    ".monitor-controls > button",
    ".data-actions > button",
    ".data-row > button",
    ".identity-toolbar button",
    ".logs-toolbar button",
    ".network-toolbar button",
    ".apmid-toolbar button",
    ".file-toolbar > button",
  ])("normalizes previously inconsistent actions: %s", (selector) => {
    expect(css).toContain(selector);
  });

  it("provides consistent interaction and destructive states", () => {
    expect(css).toContain(":hover:not(:disabled)");
    expect(css).toContain(":active:not(:disabled)");
    expect(css).toContain("button.danger");
    expect(css).toContain("var(--danger)");
  });

  it("finishes the Resource Monitor presentation", () => {
    expect(css).toContain(".monitor-content");
    expect(css).toContain(".monitor-overview-grid");
    expect(css).toContain(".monitor-storage-grid");
    expect(css).toContain(".monitor-network-grid");
    expect(css).toContain(".monitor-table-wrap");
    expect(css).toContain(".monitor-sparkline");
    expect(css).toContain("@container app-window (max-width: 42rem)");
  });

  it("keeps the layer token-driven and override-free", () => {
    expect(css).toContain("var(--surface-elevated)");
    expect(css).toContain("var(--border-subtle)");
    expect(css).toContain("var(--accent)");
    expect(css).not.toContain("!important");
  });
});
