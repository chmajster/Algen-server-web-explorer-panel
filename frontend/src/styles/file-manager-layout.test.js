import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const styles = readFileSync(resolve(cwd(), "src/styles/file-manager.css"), "utf8");

function rule(selector) {
  const start = styles.indexOf(`${selector} {`);
  expect(start).toBeGreaterThanOrEqual(0);
  return styles.slice(start, styles.indexOf("}", start));
}

describe("file manager path layout", () => {
  it("centers the breadcrumb bar with symmetric vertical spacing", () => {
    const breadcrumbs = rule(".desktop .breadcrumbs");
    expect(breadcrumbs).toContain("margin: 0.21875rem 0.625rem");
    expect(breadcrumbs).toContain("padding: 0 0.5rem");
  });

  it("centers breadcrumb labels and actions within the bar", () => {
    expect(rule(".desktop .crumb-list, .desktop .breadcrumb-actions, .desktop .breadcrumbs form")).toContain("align-items: center");
    const buttons = rule(".desktop .crumb-list button");
    expect(buttons).toContain("display: inline-flex");
    expect(buttons).toContain("align-items: center");
    expect(buttons).toContain("justify-content: center");
  });
});
