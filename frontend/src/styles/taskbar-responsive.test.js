import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const responsive = readFileSync(resolve(cwd(), "src/styles/responsive.css"), "utf8");

describe("responsive taskbar overflow handling", () => {
  it("switches taskbar applications and Modules to compact icon-only controls before labels overflow", () => {
    expect(responsive).toContain("@media (max-width: 1400px)");
    expect(responsive).toContain(".desktop .taskbar-items button span,\n  .desktop .taskbar-modules-button > span");
    expect(responsive).toContain(".desktop .taskbar-items button,\n  .desktop .taskbar-modules-button");
    expect(responsive).toMatch(/@media \(max-width: 1400px\)[\s\S]*min-width:\s*2\.75rem;/);
  });

  it("keeps compact taskbar items horizontally reachable when many applications are pinned", () => {
    expect(responsive).toMatch(/@media \(max-width: 1400px\)[\s\S]*\.desktop \.taskbar-items\s*\{[\s\S]*overflow-x:\s*auto;/);
    expect(responsive).toContain("scrollbar-width: none");
    expect(responsive).toContain(".desktop .taskbar-items::-webkit-scrollbar");
  });

  it("allows common long module names more room on wide desktops", () => {
    expect(responsive).toMatch(/\.desktop \.taskbar-items button\s*\{\s*max-width:\s*11\.75rem;/);
  });

  it("falls back to the main launcher for Modules on very narrow phones", () => {
    expect(responsive).toMatch(/@media \(max-width: 420px\)[\s\S]*\.desktop \.taskbar-modules-wrap\s*\{\s*display:\s*none;/);
  });
});
