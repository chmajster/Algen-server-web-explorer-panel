import type { AppId, WindowDeepLink, WindowInstance, WindowRect } from "./types";

export const DESKTOP_TOP = 10;
export const DESKTOP_BOTTOM = 64;
const MARGIN = 10;
export type ViewportMetrics = {
  width: number;
  height: number;
  top?: number;
  right?: number;
  bottom?: number;
  left?: number;
  originX?: number;
  originY?: number;
  scale?: number;
};

export type WindowState = { windows: WindowInstance[]; activeId: string; counter: number; topZ: number };
export type WindowAction =
  | { type: "hydrate"; state: WindowState }
  | { type: "open"; app: AppId; initialPath?: string; moduleId?: string; viewport?: ViewportMetrics }
  | { type: "openOrFocus"; app: AppId; initialPath?: string; moduleId?: string; deepLink: WindowDeepLink; viewport?: ViewportMetrics }
  | { type: "close"; id: string }
  | { type: "focus"; id: string }
  | { type: "minimize"; id: string }
  | { type: "setInitialPath"; id: string; initialPath: string }
  | { type: "setDeepLink"; id: string; deepLink: WindowDeepLink }
  | { type: "clearDeepLink"; id: string }
  | { type: "commit"; id: string; rect: WindowRect; restoreRect?: WindowRect }
  | { type: "toggleMaximize"; id: string; viewport: ViewportMetrics }
  | { type: "viewport"; viewport: ViewportMetrics };

export const initialWindowState: WindowState = { windows: [], activeId: "", counter: 0, topZ: 10 };

export function workspaceRect(viewport: ViewportMetrics = { width: window.innerWidth, height: window.innerHeight }): WindowRect {
  const scale = viewport.scale ?? 1;
  const top = Math.max(0, viewport.top ?? 0);
  const right = Math.max(0, viewport.right ?? 0);
  const bottom = Math.max(0, viewport.bottom ?? DESKTOP_BOTTOM * scale);
  const left = Math.max(0, viewport.left ?? 0);
  return {
    x: left,
    y: top,
    width: Math.max(0, viewport.width - left - right),
    height: Math.max(0, viewport.height - top - bottom)
  };
}

export function clampRect(rect: WindowRect, minWidth = 360, minHeight = 280, viewport: ViewportMetrics = { width: window.innerWidth, height: window.innerHeight }): WindowRect {
  const available = workspaceRect(viewport);
  const scale = viewport.scale ?? 1;
  const marginX = Math.min(MARGIN * scale, available.width / 2);
  const marginY = Math.min(MARGIN * scale, available.height / 2);
  const workspace = {
    x: available.x + marginX,
    y: available.y + marginY,
    width: Math.max(0, available.width - marginX * 2),
    height: Math.max(0, available.height - marginY * 2),
  };
  const effectiveMinWidth = Math.min(workspace.width, minWidth * scale);
  const effectiveMinHeight = Math.min(workspace.height, minHeight * scale);
  const width = Math.min(workspace.width, Math.max(effectiveMinWidth, rect.width));
  const height = Math.min(workspace.height, Math.max(effectiveMinHeight, rect.height));
  return {
    x: Math.min(Math.max(workspace.x, rect.x), workspace.x + workspace.width - width),
    y: Math.min(Math.max(workspace.y, rect.y), workspace.y + workspace.height - height),
    width,
    height
  };
}

function defaultRect(app: AppId, count: number, viewport?: ViewportMetrics): WindowRect {
  const large = app === "files" || app === "settings" || app === "samba" || app === "store" || app === "module" || app === "identity";
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
  if (action.type === "viewport") {
    return {
      ...state,
      windows: state.windows.map((item) => ({
        ...item,
        rect: item.restoreRect ? workspaceRect(action.viewport) : clampRect(item.rect, item.app === "files" ? 680 : 360, item.app === "files" ? 440 : 280, action.viewport),
        restoreRect: item.restoreRect,
      })),
    };
  }
  if (action.type === "open" || action.type === "openOrFocus") {
    if (action.type === "openOrFocus") {
      const existing = state.windows
        .filter((item) => item.app === action.app
          && (action.app !== "module" || item.moduleId === action.moduleId)
          && (action.app !== "operation-progress" || item.deepLink?.id === action.deepLink.id))
        .sort((left, right) => right.zIndex - left.zIndex)[0];
      if (existing) {
        const topZ = state.topZ + 1;
        return {
          ...state,
          activeId: existing.id,
          topZ,
          windows: state.windows.map((item) => item.id === existing.id ? {
            ...item,
            minimized: false,
            zIndex: topZ,
            initialPath: action.initialPath ?? item.initialPath,
            deepLink: action.deepLink,
          } : item),
        };
      }
    }
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
        initialPath: action.initialPath,
        moduleId: action.moduleId,
        deepLink: action.type === "openOrFocus" ? action.deepLink : undefined,
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
  if (action.type === "setInitialPath") {
    return { ...state, windows: state.windows.map((item) => item.id === action.id ? { ...item, initialPath: action.initialPath } : item) };
  }
  if (action.type === "setDeepLink") {
    return { ...state, windows: state.windows.map((item) => item.id === action.id ? { ...item, deepLink: action.deepLink } : item) };
  }
  if (action.type === "clearDeepLink") {
    return { ...state, windows: state.windows.map((item) => item.id === action.id ? { ...item, deepLink: undefined } : item) };
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

export function restoreWindowState(raw: string | null, viewport?: ViewportMetrics): WindowState {
  if (!raw) return initialWindowState;
  try {
    const value = JSON.parse(raw) as WindowState;
    if (!Array.isArray(value.windows)) return initialWindowState;
    const windows = value.windows.filter((item) => item.id && item.app && item.rect).map((item) => ({
      ...item,
      rect: clampRect(item.rect, item.app === "files" ? 680 : 360, item.app === "files" ? 440 : 280, viewport),
      restoreRect: item.restoreRect ? clampRect(item.restoreRect, item.app === "files" ? 680 : 360, item.app === "files" ? 440 : 280, viewport) : undefined,
    }));
    return { windows, activeId: windows.some((item) => item.id === value.activeId) ? value.activeId : "", counter: value.counter || windows.length, topZ: value.topZ || 10 };
  } catch {
    return initialWindowState;
  }
}
