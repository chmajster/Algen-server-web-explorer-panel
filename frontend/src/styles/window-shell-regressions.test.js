import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const read = (path) => readFileSync(resolve(cwd(), path), "utf8");
const windows = read("src/styles/windows.css");
const mobile = read("src/styles/mobile-shell.css");

describe("window shell visual regressions", () => {
  it("keeps window chrome controls from shrinking into the title", () => {
    expect(windows).toContain(".desktop .window-app-icon { flex: 0 0 auto; }");
    expect(windows).toContain(".desktop .window-controls { align-self: stretch; flex: 0 0 auto; gap: 0; }");
    expect(windows).toContain("flex: 0 0 2.5rem");
  });

  it("keeps fullscreen titlebars inside device safe areas", () => {
    expect(windows).toContain("env(safe-area-inset-left, 0px)");
    expect(windows).toContain("env(safe-area-inset-right, 0px)");
    expect(windows).toContain(".desktop .desktop-window.mobile-fullscreen .window-titlebar");
  });

  it("does not disable touch gestures on fullscreen mobile titlebars", () => {
    expect(windows).toContain("touch-action: manipulation");
    expect(mobile).toContain(".desktop-window .window-titlebar { min-height: 3rem; touch-action: manipulation; }");
    expect(mobile).not.toContain("touch-action: none");
  });

  it("targets the resize handle class actually rendered by DesktopWindow", () => {
    expect(mobile).toContain(".desktop-window .resize-handle");
    expect(mobile).not.toContain(".window-resize-handle");
  });

  it("uses dynamic viewport units for the mobile and tablet shell", () => {
    expect(mobile).toContain("width: 100dvw");
    expect(mobile).toContain("height: 100dvh");
    expect(mobile).toContain("max-width: calc(100dvw - 1rem)");
    expect(mobile).toContain("max-height: calc(100dvh - 4.5rem)");
  });
});
