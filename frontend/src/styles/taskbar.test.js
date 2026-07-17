import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const taskbarCss = readFileSync(resolve(cwd(), "src/styles/taskbar.css"), "utf8");

describe("taskbar layout styles", () => {
  it("pins the taskbar to a fixed-height strip at the bottom of the desktop", () => {
    expect(taskbarCss).toContain(".desktop > .taskbar");
    expect(taskbarCss).toMatch(/\.desktop > \.taskbar\s*\{[^}]*position:\s*absolute/);
    expect(taskbarCss).toMatch(/\.desktop > \.taskbar\s*\{[^}]*bottom:\s*0/);
    expect(taskbarCss).toMatch(/\.desktop > \.taskbar\s*\{[^}]*max-height:\s*var\(--taskbar-height-scaled\)/);
  });
});
