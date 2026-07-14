import type { AppId, WindowInstance, WindowRect } from "./types";

export const DESKTOP_TOP = 56;
export const DESKTOP_BOTTOM = 58;
const MARGIN = 10;

export type WindowState = { windows: WindowInstance[]; activeId: string; counter: number; topZ: number };
export type WindowAction =
  | { type: "hydrate"; state: WindowState }
  | { type: "open"; app: AppId; initialPath?: string; viewport?: { width: number; height: number } }
  | { type: "close"; id: string }
  | { type: "focus"; id: string }
  | { type: "minimize"; id: string }
  | { type: "commit"; id: string; rect: WindowRect; restoreRect?: WindowRect }
  | { type: "toggleMaximize"; id: string; viewport: { width: number; height: number } };

export const initialWindowState: WindowState = { windows: [], activeId: "", counter: 0, topZ: 10 };

export function workspaceRect(viewport = { width: window.innerWidth, height: window.innerHeight }): WindowRect {
  return {
    x: MARGIN,
    y: DESKTOP_TOP,
    width: Math.max(360, viewport.width - MARGIN * 2),
    height: Math.max(280, viewport.height - DESKTOP_TOP - DESKTOP_BOTTOM)
  };
}

export function clampRect(rect: WindowRect, minWidth = 360, minHeight = 280, viewport = { width: window.innerWidth, height: window.innerHeight }): WindowRect {
  const workspace = workspaceRect(viewport);
  const width = Math.min(workspace.width, Math.max(minWidth, rect.width));
  const height = Math.min(workspace.height, Math.max(minHeight, rect.height));
  return {
    x: Math.min(Math.max(MARGIN, rect.x), Math.max(MARGIN, viewport.width - MARGIN - width)),
    y: Math.min(Math.max(DESKTOP_TOP, rect.y), Math.max(DESKTOP_TOP, viewport.height - DESKTOP_BOTTOM - height)),
    width,
    height
  };
}

function defaultRect(app: AppId, count: number, viewport?: { width: number; height: number }): WindowRect {
  const large = app === "files" || app === "settings" || app === "samba" || app === "store";
  return clampRect({
    x: 84 + (count * 28) % 190,
    y: 78 + (count * 24) % 150,
    width: large ? 1120 : 900,
    height: large ? 700 : 600
  }, app === "files" ? 680 : 360, app === "files" ? 440 : 280, viewport);
}

function focus(state: WindowState, id: string): WindowState {
  const topZ = state.topZ + 1;
  return {
    ...state,
    activeId: id,
    topZ,
    windows: state.windows.map((item) => item.id === id ? { ...item, minimized: false, zIndex: topZ } : item)
  };
}

export function windowReducer(state: WindowState, action: WindowAction): WindowState {
  if (action.type === "hydrate") return action.state;
  if (action.type === "open") {
    const counter = state.counter + 1;
    const id = `${action.app}-${counter}`;
    const topZ = state.topZ + 1;
    const sameAppCount = state.windows.filter((item) => item.app === action.app).length;
    return {
      windows: [...state.windows, {
        id,
        app: action.app,
        rect: defaultRect(action.app, sameAppCount, action.viewport),
        minimized: false,
        zIndex: topZ,
        initialPath: action.initialPath
      }],
      activeId: id,
      counter,
      topZ
    };
  }
  if (action.type === "close") {
    const windows = state.windows.filter((item) => item.id !== action.id);
    const next = windows.filter((item) => !item.minimized).sort((a, b) => b.zIndex - a.zIndex)[0];
    return { ...state, windows, activeId: state.activeId === action.id ? next?.id || "" : state.activeId };
  }
  if (action.type === "focus") return focus(state, action.id);
  if (action.type === "minimize") {
    const windows = state.windows.map((item) => item.id === action.id ? { ...item, minimized: true } : item);
    const next = windows.filter((item) => !item.minimized && item.id !== action.id).sort((a, b) => b.zIndex - a.zIndex)[0];
    return { ...state, windows, activeId: next?.id || "" };
  }
  if (action.type === "commit") {
    return { ...state, windows: state.windows.map((item) => item.id === action.id ? { ...item, rect: action.rect, restoreRect: action.restoreRect } : item) };
  }
  const target = state.windows.find((item) => item.id === action.id);
  if (!target) return state;
  const maximized = Boolean(target.restoreRect);
  const rect = maximized ? clampRect(target.restoreRect!, target.app === "files" ? 680 : 360, target.app === "files" ? 440 : 280, action.viewport) : workspaceRect(action.viewport);
  const restoreRect = maximized ? undefined : target.rect;
  return focus({ ...state, windows: state.windows.map((item) => item.id === action.id ? { ...item, rect, restoreRect } : item) }, action.id);
}

export function restoreWindowState(raw: string | null): WindowState {
  if (!raw) return initialWindowState;
  try {
    const value = JSON.parse(raw) as WindowState;
    if (!Array.isArray(value.windows)) return initialWindowState;
    const windows = value.windows.filter((item) => item.id && item.app && item.rect).map((item) => ({ ...item, rect: clampRect(item.rect) }));
    return { windows, activeId: windows.some((item) => item.id === value.activeId) ? value.activeId : "", counter: value.counter || windows.length, topZ: value.topZ || 10 };
  } catch {
    return initialWindowState;
  }
}
