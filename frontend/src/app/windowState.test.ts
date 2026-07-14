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

  it("restores persisted state and clamps an off-screen rectangle", () => {
    const raw = JSON.stringify({ windows: [{ id: "logs-3", app: "logs", rect: { x: 99999, y: -20, width: 800, height: 500 }, minimized: false, zIndex: 12 }], activeId: "logs-3", counter: 3, topZ: 12 });
    const state = restoreWindowState(raw);
    expect(state.activeId).toBe("logs-3");
    expect(state.windows[0].rect.x).toBeLessThan(window.innerWidth);
    expect(state.windows[0].rect.y).toBeGreaterThanOrEqual(56);
  });
});
