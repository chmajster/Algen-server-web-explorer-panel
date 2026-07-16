import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const appCss = readFileSync(resolve(cwd(), "src/styles/app.css"), "utf8");

describe("theme semantic colors", () => {
  it("keeps primary and dangerous button text contrasted in every component", () => {
    expect(appCss).toContain("#root .button-primary");
    expect(appCss).toContain("color: var(--text-on-accent)");
    expect(appCss).toContain("background: var(--accent)");
    expect(appCss).toContain("#root .button-danger");
    expect(appCss).toContain("color: var(--text-on-danger)");
    expect(appCss).toContain("background: var(--danger)");
  });
});
