import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const read = (path) => readFileSync(resolve(cwd(), path), "utf8");
const app = read("src/styles/app.css");
const modules = read("src/styles/modules.css");

describe("shared button appearance", () => {
  it("removes native browser chrome and provides reusable button variants", () => {
    expect(app).toMatch(/button\s*\{[^}]*appearance:\s*none[^}]*background:\s*transparent[^}]*\}/);
    expect(app).toContain(".button, .button-secondary, .button-primary, .button-danger");
    expect(app).toContain(".button-danger:hover:not(:disabled)");
  });

  it.each([
    ".hosts-header-actions > button",
    ".hosts-pagination button",
    ".hosts-table-actions button",
    ".hosts-environment-card > footer button",
    ".data-card > button",
    ".hosts-installer-actions > button",
    ".hosts-connection-test > button",
    ".hosts-fingerprint-confirm > button",
    ".hosts-wizard-footer > button",
    ".hosts-data-table td > button",
    ".hosts-secret-once + button",
  ])("gives Hosts Manager actions a designed neutral style: %s", (selector) => {
    expect(modules).toContain(selector);
  });

  it("includes visible hover and pressed states for neutral Hosts Manager actions", () => {
    expect(modules).toContain(":hover:not(:disabled)");
    expect(modules).toContain(":active:not(:disabled)");
    expect(modules).toContain("border-color: color-mix(in srgb, var(--accent) 45%");
  });
});
