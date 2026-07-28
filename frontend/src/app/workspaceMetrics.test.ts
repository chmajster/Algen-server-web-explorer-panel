import { afterEach, describe, expect, it, vi } from "vitest";
import { measureWorkspaceMetrics } from "./workspaceMetrics";

function rect(left: number, top: number, width: number, height: number): DOMRect {
  return {
    x: left,
    y: top,
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
    toJSON: () => ({}),
  } as DOMRect;
}

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

describe("workspace measurement", () => {
  it("uses the real navbar and overlapping taskbar edges", () => {
    const desktop = document.createElement("div");
    const surface = document.createElement("main");
    const navbar = document.createElement("header");
    const taskbar = document.createElement("footer");
    navbar.dataset.mainNavbar = "";
    taskbar.className = "taskbar";
    desktop.append(surface, taskbar);
    document.body.append(navbar, desktop);
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue(rect(0, 0, 1440, 900));
    vi.spyOn(navbar, "getBoundingClientRect").mockReturnValue(rect(0, 0, 1440, 72));
    vi.spyOn(taskbar, "getBoundingClientRect").mockReturnValue(rect(0, 842, 1440, 58));

    expect(measureWorkspaceMetrics(desktop, surface, 1)).toEqual({
      width: 1440,
      height: 900,
      top: 72,
      right: 0,
      bottom: 58,
      left: 0,
      originX: 0,
      originY: 0,
      scale: 1,
    });
  });

  it("recalculates when the navbar height changes", () => {
    const desktop = document.createElement("div");
    const surface = document.createElement("main");
    const navbar = document.createElement("nav");
    navbar.className = "main-navbar";
    desktop.append(surface);
    document.body.append(navbar, desktop);
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue(rect(0, 0, 390, 844));
    const navbarRect = vi.spyOn(navbar, "getBoundingClientRect");
    navbarRect.mockReturnValueOnce(rect(0, 0, 390, 56)).mockReturnValueOnce(rect(0, 0, 390, 88));

    expect(measureWorkspaceMetrics(desktop, surface, 1).top).toBe(56);
    expect(measureWorkspaceMetrics(desktop, surface, 1).top).toBe(88);
  });

  it("does not subtract the navbar twice when the surface already starts below it", () => {
    const desktop = document.createElement("div");
    const surface = document.createElement("main");
    const navbar = document.createElement("header");
    navbar.setAttribute("role", "banner");
    desktop.append(surface);
    document.body.append(navbar, desktop);
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue(rect(0, 64, 1280, 656));
    vi.spyOn(navbar, "getBoundingClientRect").mockReturnValue(rect(0, 0, 1280, 64));

    const metrics = measureWorkspaceMetrics(desktop, surface, 1);
    expect(metrics.top).toBe(0);
    expect(metrics.originY).toBe(64);
    expect(metrics.height).toBe(656);
  });
});
