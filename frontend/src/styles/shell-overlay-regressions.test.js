import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const read = (path) => readFileSync(resolve(cwd(), path), "utf8");
const contextMenuHost = read("src/components/SystemContextMenuHost.tsx");
const contextMenuCss = read("src/components/system-context-menu.css");
const responsiveCss = read("src/styles/responsive.css");
const taskbarCss = read("src/styles/shell-taskbar.css");

describe("shell overlay visual regressions", () => {
  it("reclamps desktop context menus when the visible viewport changes", () => {
    expect(contextMenuHost).toContain("window.visualViewport");
    expect(contextMenuHost).toContain('window.addEventListener("resize", updatePosition)');
    expect(contextMenuHost).toContain('window.addEventListener("orientationchange", updatePosition)');
    expect(contextMenuHost).toContain('visualViewport?.addEventListener("resize", updatePosition)');
    expect(contextMenuHost).toContain('visualViewport?.addEventListener("scroll", updatePosition)');
    expect(contextMenuHost).toContain("viewport.offsetLeft + viewport.width");
    expect(contextMenuHost).toContain("viewport.offsetTop + viewport.height");
  });

  it("uses the visual viewport for context-menu sizing and contains scrolling", () => {
    expect(contextMenuCss).toContain("calc(100dvw - 1rem)");
    expect(contextMenuCss).toContain("max-height: min(78dvh, 44rem)");
    expect(contextMenuCss).toContain("overscroll-behavior: contain");
    expect(contextMenuCss).toContain("scrollbar-gutter: stable");
  });

  it("keeps mobile context menus inside safe areas without inherited minimum width", () => {
    expect(contextMenuCss).toContain("env(safe-area-inset-left, 0px)");
    expect(contextMenuCss).toContain("env(safe-area-inset-right, 0px)");
    expect(contextMenuCss).toContain("env(safe-area-inset-bottom, 0px)");
    expect(contextMenuCss).toContain("min-width: 0");
    expect(contextMenuCss).toContain("max-height: min(70dvh, 38rem)");
  });

  it("keeps taskbar window previews inside dynamic and safe viewport bounds", () => {
    expect(taskbarCss).toContain("calc(100dvw - 1rem)");
    expect(taskbarCss).toContain("max-height: min(72dvh, 44rem)");
    expect(taskbarCss).toContain("env(safe-area-inset-left, 0px)");
    expect(taskbarCss).toContain("env(safe-area-inset-right, 0px)");
    expect(taskbarCss).toContain("grid-template-columns: minmax(0, 1fr)");
    expect(taskbarCss).toContain("max-height: 55dvh");
  });

  it("uses dynamic viewport units throughout the compact shell breakpoint", () => {
    expect(responsiveCss).toContain("max-height: calc(100dvh - var(--taskbar-height) - 0.75rem)");
    expect(responsiveCss).toContain("width: calc(100dvw - 0.75rem)");
    expect(responsiveCss).toContain("width: min(23rem, calc(100dvw - 0.75rem))");
    expect(responsiveCss).toContain("width: min(21.75rem, calc(100dvw - 0.75rem))");
    expect(responsiveCss).not.toContain("100vh");
    expect(responsiveCss).not.toContain("100vw");
  });
});
