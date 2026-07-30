import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const styles = readFileSync(resolve(cwd(), "src/styles/logs.css"), "utf8");
const rule = (selector) => {
  const start = styles.indexOf(`${selector} {`);
  expect(start).toBeGreaterThanOrEqual(0);
  return styles.slice(start, styles.indexOf("}", start));
};

describe("logs responsive layout", () => {
  it("keeps the application and its independently scrolling regions bounded", () => {
    expect(rule(".logs-app")).toContain("display: flex");
    expect(rule(".logs-app")).toContain("overflow: hidden");
    expect(rule(".logs-source-tree")).toContain("overflow-y: auto");
    expect(rule(".logs-saved-list")).toContain("overflow-y: auto");
    expect(rule(".logs-list")).toContain("overflow-y: auto");
  });

  it("preserves usable sidebar, toolbar control and log column sizes", () => {
    expect(rule(".logs-sidebar")).toContain("width: 17rem");
    expect(rule(".logs-sidebar")).toContain("min-width: 13.75rem");
    expect(rule(".logs-sidebar")).toContain("max-width: 22.5rem");
    expect(rule(".logs-toolbar")).toContain("flex-wrap: wrap");
    expect(rule(".logs-toolbar .logs-icon-button")).toContain("width: 2.25rem");
    const columns = styles.match(/\.log-row,\s*\.logs-table-head\s*{([^}]*)}/s)?.[1];
    expect(columns).toContain(
      "grid-template-columns: 12.25rem 6rem minmax(8.125rem, 11rem) 4rem minmax(0, 1fr)",
    );
  });

  it("defines desktop, tablet and mobile adaptations without hiding actions", () => {
    expect(styles).toContain("@container logs-layout (max-width: 65rem)");
    expect(styles).toContain("@container logs-layout (max-width: 56rem)");
    expect(styles).toContain("@container logs-layout (max-width: 48rem)");
    expect(styles).toContain("@container logs-layout (max-width: 40rem)");
    expect(styles).not.toMatch(/\.logs-toolbar-(?:export|display|filter|live)-group\s*{[^}]*display:\s*none/s);
  });
});
