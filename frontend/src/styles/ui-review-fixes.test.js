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

  it("keeps stale Activity content in the flexible fifth row", () => {
    expect(css).toContain("grid-template-rows: auto auto auto auto minmax(0, 1fr) auto");
    expect(css).toContain(".desktop .activity-feed");
    expect(css).toContain("grid-row: 5");
    expect(css).toContain(".desktop .activity-footer");
    expect(css).toContain("grid-row: 6");
  });

  it("does not impose Resource Monitor table width on Network diagnostics", () => {
    expect(css).toContain(".desktop .network-settings .monitor-table-wrap table");
    expect(css).toContain("min-width: 0");
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

  it("spaces portal-backed Settings sections in normal document flow", () => {
    expect(css).toContain('.settings-content:has(> [data-testid="authentication-settings-card"])');
    expect(css).toContain(".settings-content:has(> .administration-dashboard)");
    expect(css).toContain("gap: 0.875rem");
  });

  it("uses app-window breakpoints for Settings instead of relying on browser viewport width", () => {
    expect(css).toContain("@container app-window (max-width: 70rem)");
    expect(css).toContain("@container app-window (max-width: 60rem)");
    expect(css).toContain("@container app-window (max-width: 52rem)");
    expect(css).toContain("@container app-window (max-width: 42rem)");
    expect(css).toContain(".desktop .admin-content-grid");
    expect(css).toContain(".desktop .ldap-summary-grid");
  });

  it("allows authentication and LDAP grids to shrink without horizontal overflow", () => {
    expect(css).toContain("grid-template-columns: auto minmax(0, 1fr) auto");
    expect(css).toContain(".desktop .ldap-diagnostic-row");
    expect(css).toContain("overflow-wrap: anywhere");
    expect(css).toContain(".desktop .auth-users-table td");
  });

  it("keeps the LDAP action bar from covering narrow-window form content", () => {
    expect(css).toContain(".desktop .ldap-action-bar");
    expect(css).toContain("position: static");
    expect(css).toContain("grid-template-columns: repeat(2, minmax(0, 1fr))");
  });

  it("gives HTTPS paths a shrinkable responsive control column", () => {
    expect(css).toContain('[data-testid="https-settings-card"] .setting-row');
    expect(css).toContain('input[type="text"], code');
    expect(css).toContain("max-width: none");
    expect(css).toContain("white-space: normal");
  });

  it("does not use important overrides", () => {
    expect(css).not.toContain("!important");
  });
});
