import { describe, expect, it } from "vitest";
import { initialWindowState, restoreWindowState, windowReducer, workspaceRect } from "./windowState";

const viewport = { width: 1440, height: 900 };

describe("window manager reducer", () => {
  it("opens multiple instances and keeps the focused window on top", () => {
    let state = windowReducer(initialWindowState, { type: "open", app: "files", viewport });
    state = windowReducer(state, { type: "open", app: "files", viewport });
    expect(state.windows).toHaveLength(2);
    expect(state.activeId).toBe("files-2");
    const firstZ = state.windows[0].zIndex;
    state = windowReducer(state, { type: "focus", id: "files-1" });
    expect(state.activeId).toBe("files-1");
    expect(state.windows[0].zIndex).toBeGreaterThan(firstZ);
    expect(state.windows[0].zIndex).toBeGreaterThan(state.windows[1].zIndex);
  });

  it("minimizes, restores through focus, and closes a window", () => {
    let state = windowReducer(initialWindowState, { type: "open", app: "settings", viewport });
    state = windowReducer(state, { type: "minimize", id: "settings-1" });
    expect(state.windows[0].minimized).toBe(true);
    expect(state.activeId).toBe("");
    state = windowReducer(state, { type: "focus", id: "settings-1" });
    expect(state.windows[0].minimized).toBe(false);
    state = windowReducer(state, { type: "close", id: "settings-1" });
    expect(state.windows).toHaveLength(0);
  });

  it("restores and reuses a minimized action target without opening a duplicate", () => {
    const deepLink = { type: "package-job" as const, id: "job-7", actionKey: "module:job-7", jobId: "job-7", issuedAt: 7 };
    let state = windowReducer(initialWindowState, { type: "open", app: "module", moduleId: "samba", viewport });
    state = windowReducer(state, { type: "minimize", id: "module-1" });
    state = windowReducer(state, { type: "openOrFocus", app: "module", moduleId: "samba", deepLink, viewport });

    expect(state.windows).toHaveLength(1);
    expect(state.activeId).toBe("module-1");
    expect(state.windows[0]).toMatchObject({ minimized: false, moduleId: "samba", deepLink });
  });

  it("opens a new exact action target only when its module window does not exist", () => {
    const firstLink = { type: "package-job" as const, id: "job-a", actionKey: "module:job-a", issuedAt: 1 };
    const secondLink = { type: "package-job" as const, id: "job-b", actionKey: "module:job-b", issuedAt: 2 };
    let state = windowReducer(initialWindowState, { type: "openOrFocus", app: "module", moduleId: "samba", deepLink: firstLink, viewport });
    state = windowReducer(state, { type: "openOrFocus", app: "module", moduleId: "docker", deepLink: secondLink, viewport });

    expect(state.windows).toHaveLength(2);
    expect(state.windows.map((item) => item.moduleId)).toEqual(["samba", "docker"]);
    expect(state.windows[1].deepLink).toEqual(secondLink);
  });

  it("keeps independent operation progress windows and focuses an existing job", () => {
    const firstLink = { type: "package-job" as const, id: "job-a", actionKey: "operation:job-a", jobId: "job-a", issuedAt: 1 };
    const secondLink = { type: "package-job" as const, id: "job-b", actionKey: "operation:job-b", jobId: "job-b", issuedAt: 2 };
    let state = windowReducer(initialWindowState, { type: "openOrFocus", app: "operation-progress", deepLink: firstLink, viewport });
    state = windowReducer(state, { type: "openOrFocus", app: "operation-progress", deepLink: secondLink, viewport });
    state = windowReducer(state, { type: "minimize", id: "operation-progress-1" });
    state = windowReducer(state, { type: "openOrFocus", app: "operation-progress", deepLink: firstLink, viewport });

    expect(state.windows).toHaveLength(2);
    expect(state.activeId).toBe("operation-progress-1");
    expect(state.windows[0].minimized).toBe(false);
    expect(state.windows.map((item) => item.deepLink?.jobId)).toEqual(["job-a", "job-b"]);
  });

  it("persists the active path independently for each application window", () => {
    let state = windowReducer(initialWindowState, { type: "open", app: "settings", viewport });
    state = windowReducer(state, { type: "setInitialPath", id: "settings-1", initialPath: "administration" });
    const restored = restoreWindowState(JSON.stringify(state));

    expect(restored.windows[0].initialPath).toBe("administration");
  });

  it("restores legacy saved windows without deep-link metadata", () => {
    const raw = JSON.stringify({
      windows: [{ id: "settings-1", app: "settings", rect: { x: 40, y: 60, width: 800, height: 500 }, minimized: false, zIndex: 11 }],
      activeId: "settings-1",
      counter: 1,
      topZ: 11,
    });

    const restored = restoreWindowState(raw, viewport);

    expect(restored.windows[0].deepLink).toBeUndefined();
    expect(restored.activeId).toBe("settings-1");
  });

  it("maximizes and restores the previous rectangle", () => {
    let state = windowReducer(initialWindowState, { type: "open", app: "monitor", viewport });
    const previous = state.windows[0].rect;
    state = windowReducer(state, { type: "toggleMaximize", id: "monitor-1", viewport });
    expect(state.windows[0].rect).toEqual(workspaceRect(viewport));
    expect(state.windows[0].restoreRect).toEqual(previous);
    state = windowReducer(state, { type: "toggleMaximize", id: "monitor-1", viewport });
    expect(state.windows[0].rect).toEqual(previous);
    expect(state.windows[0].restoreRect).toBeUndefined();
  });

  it("maximizes below a dynamically measured navbar", () => {
    const viewportWithNavbar = { width: 1440, height: 900, top: 72, bottom: 58 };
    let state = windowReducer(initialWindowState, { type: "open", app: "monitor", viewport: viewportWithNavbar });
    const previous = state.windows[0].rect;

    state = windowReducer(state, { type: "toggleMaximize", id: "monitor-1", viewport: viewportWithNavbar });
    expect(state.windows[0].rect).toEqual({ x: 0, y: 72, width: 1440, height: 770 });

    state = windowReducer(state, { type: "toggleMaximize", id: "monitor-1", viewport: viewportWithNavbar });
    expect(state.windows[0].rect).toEqual(previous);
  });

  it("updates every maximized window when the navbar or viewport changes", () => {
    let state = windowReducer(initialWindowState, { type: "open", app: "monitor", viewport });
    state = windowReducer(state, { type: "toggleMaximize", id: "monitor-1", viewport });
    state = windowReducer(state, { type: "open", app: "settings", viewport });
    state = windowReducer(state, { type: "toggleMaximize", id: "settings-2", viewport });

    const resizedViewport = { width: 390, height: 844, top: 88, bottom: 58 };
    state = windowReducer(state, { type: "viewport", viewport: resizedViewport });

    expect(state.windows.map((item) => item.rect)).toEqual([
      { x: 0, y: 88, width: 390, height: 698 },
      { x: 0, y: 88, width: 390, height: 698 },
    ]);
  });

  it("preserves maximize geometry through minimize and taskbar restore", () => {
    const viewportWithNavbar = { width: 1280, height: 720, top: 64, bottom: 58 };
    let state = windowReducer(initialWindowState, { type: "open", app: "settings", viewport: viewportWithNavbar });
    const previous = state.windows[0].rect;
    state = windowReducer(state, { type: "toggleMaximize", id: "settings-1", viewport: viewportWithNavbar });
    state = windowReducer(state, { type: "minimize", id: "settings-1" });
    state = windowReducer(state, { type: "focus", id: "settings-1" });

    expect(state.windows[0].minimized).toBe(false);
    expect(state.windows[0].rect).toEqual({ x: 0, y: 64, width: 1280, height: 598 });

    state = windowReducer(state, { type: "toggleMaximize", id: "settings-1", viewport: viewportWithNavbar });
    expect(state.windows[0].rect).toEqual(previous);
  });

  it("keeps the exact restore rectangle while a maximized viewport is resized", () => {
    const initialViewport = { width: 1440, height: 900, top: 64, bottom: 58 };
    let state = windowReducer(initialWindowState, { type: "open", app: "monitor", viewport: initialViewport });
    const previous = state.windows[0].rect;
    state = windowReducer(state, { type: "toggleMaximize", id: "monitor-1", viewport: initialViewport });
    state = windowReducer(state, { type: "viewport", viewport: { width: 390, height: 844, top: 88, bottom: 58 } });
    state = windowReducer(state, { type: "viewport", viewport: initialViewport });

    expect(state.windows[0].restoreRect).toEqual(previous);
    state = windowReducer(state, { type: "toggleMaximize", id: "monitor-1", viewport: initialViewport });
    expect(state.windows[0].rect).toEqual(previous);
  });

  it("keeps a dragged window titlebar below the navbar", () => {
    const viewportWithNavbar = { width: 1024, height: 768, top: 80, bottom: 58 };
    const raw = JSON.stringify({ windows: [{ id: "logs-1", app: "logs", rect: { x: 30, y: -500, width: 800, height: 500 }, minimized: false, zIndex: 12 }], activeId: "logs-1", counter: 1, topZ: 12 });
    const state = restoreWindowState(raw, viewportWithNavbar);

    expect(state.windows[0].rect.y).toBe(90);
  });

  it("restores persisted state and clamps an off-screen rectangle", () => {
    const raw = JSON.stringify({ windows: [{ id: "logs-3", app: "logs", rect: { x: 99999, y: -20, width: 800, height: 500 }, minimized: false, zIndex: 12 }], activeId: "logs-3", counter: 3, topZ: 12 });
    const state = restoreWindowState(raw);
    expect(state.activeId).toBe("logs-3");
    expect(state.windows[0].rect.x).toBeLessThan(window.innerWidth);
    expect(state.windows[0].rect.y).toBeGreaterThanOrEqual(10);
  });

  it.each([
    [1920, 1080], [1440, 900], [1280, 720], [1024, 768], [390, 844],
  ])("keeps application windows inside a %sx%s viewport", (width, height) => {
    const state = windowReducer(initialWindowState, { type: "open", app: "files", viewport: { width, height } });
    const rect = state.windows[0].rect;

    expect(rect.x).toBeGreaterThanOrEqual(10);
    expect(rect.y).toBeGreaterThanOrEqual(10);
    expect(rect.x + rect.width).toBeLessThanOrEqual(width - 10);
    expect(rect.y + rect.height).toBeLessThanOrEqual(height - 74);
  });

  it.each([0.5, 1, 1.5, 2])("clamps restored windows for interface scale %s", (scale) => {
    const scaledViewport = { width: 1024, height: 768, bottom: 68 * scale, scale };
    const raw = JSON.stringify({ windows: [{ id: "settings-1", app: "settings", rect: { x: 900, y: 700, width: 900, height: 700 }, minimized: false, zIndex: 11 }], activeId: "settings-1", counter: 1, topZ: 11 });
    const state = restoreWindowState(raw, scaledViewport);
    const rect = state.windows[0].rect;
    expect(rect.x).toBeGreaterThanOrEqual(10 * scale);
    expect(rect.y).toBeGreaterThanOrEqual(10 * scale);
    expect(rect.x + rect.width).toBeLessThanOrEqual(1024 - 10 * scale);
    expect(rect.y + rect.height).toBeLessThanOrEqual(768 - 68 * scale);
  });
});
