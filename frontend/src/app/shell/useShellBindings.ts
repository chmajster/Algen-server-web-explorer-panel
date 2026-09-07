import { useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import type { SettingsMe } from "../../api";
import { apps } from "../registry/builtinModules";
import type { AppId, Toast, Translate, WindowInstance } from "../types";
import type { ViewportMetrics, WindowAction, WindowState } from "../windowState";
import { WebNAS } from "./WebNASShell";
import { shellPreferencesClient, type PersistedShellWindow } from "./preferences";
import type { ShellEvent } from "./managers";

type Setter = Dispatch<SetStateAction<boolean>>;

type Bindings = {
  state: WindowState;
  viewport: ViewportMetrics;
  dispatch: Dispatch<WindowAction>;
  profile: SettingsMe;
  t: Translate;
  toasts: Toast[];
  pinned: Set<AppId>;
  startPinned: Set<AppId>;
  canUseApp: (app: AppId) => boolean;
  openApp: (app: AppId, initialPath?: string, moduleId?: string) => void;
  togglePin: (app: AppId) => void;
  toggleStartPin: (app: AppId) => void;
  setLauncherOpen: Setter;
  setNotificationsOpen: Setter;
  setActionsOpen: Setter;
  setCalendarOpen: Setter;
  setShutdownOpen: Setter;
  signOut: () => void;
  restartApplication: () => Promise<void>;
  restartSystem: () => void;
};

function persistedWindow(item: WindowInstance): PersistedShellWindow {
  return {
    id: item.id,
    app: item.app,
    x: Math.round(item.rect.x),
    y: Math.round(item.rect.y),
    width: Math.round(item.rect.width),
    height: Math.round(item.rect.height),
    minimized: item.minimized,
    maximized: Boolean(item.restoreRect),
    restore_x: item.restoreRect ? Math.round(item.restoreRect.x) : null,
    restore_y: item.restoreRect ? Math.round(item.restoreRect.y) : null,
    restore_width: item.restoreRect ? Math.round(item.restoreRect.width) : null,
    restore_height: item.restoreRect ? Math.round(item.restoreRect.height) : null,
    initial_path: item.initialPath ?? null,
    module_id: item.moduleId ?? null,
  };
}

function restoredWindows(items: PersistedShellWindow[], canUseApp: (app: AppId) => boolean): WindowState {
  const windows: WindowInstance[] = items
    .filter((item) => canUseApp(item.app))
    .map((item, index) => ({
      id: item.id,
      app: item.app,
      rect: { x: item.x, y: item.y, width: item.width, height: item.height },
      restoreRect: item.maximized && item.restore_x != null && item.restore_y != null && item.restore_width != null && item.restore_height != null
        ? { x: item.restore_x, y: item.restore_y, width: item.restore_width, height: item.restore_height }
        : undefined,
      minimized: item.minimized,
      zIndex: 11 + index,
      initialPath: item.initial_path ?? undefined,
      moduleId: item.module_id ?? undefined,
    }));
  const active = [...windows].filter((item) => !item.minimized).sort((a, b) => b.zIndex - a.zIndex)[0]?.id || "";
  return { windows, activeId: active, counter: windows.length, topZ: 10 + windows.length };
}

export function useShellBindings(bindings: Bindings) {
  const {
    state, viewport, dispatch, profile, t, toasts, pinned, startPinned, canUseApp, openApp,
    togglePin, toggleStartPin, setLauncherOpen, setNotificationsOpen, setActionsOpen,
    setCalendarOpen, setShutdownOpen, signOut, restartApplication, restartSystem,
  } = bindings;
  const [backendReady, setBackendReady] = useState(false);
  const saveTimer = useRef<number | null>(null);
  const restoredOnce = useRef(false);
  const toastIds = useRef(new Set<number>());

  const permittedApps = useMemo(() => apps.filter((app) => !app.hidden && canUseApp(app.id)), [canUseApp]);

  useEffect(() => {
    let active = true;
    void shellPreferencesClient.get().then((preferences) => {
      if (!active) return;
      if (!restoredOnce.current && profile.startup_windows === "last" && preferences.windows.length > 0) {
        restoredOnce.current = true;
        dispatch({ type: "hydrate", state: restoredWindows(preferences.windows, canUseApp) });
      }
      setBackendReady(true);
    }).catch(() => { if (active) setBackendReady(true); });
    return () => { active = false; };
  }, [canUseApp, dispatch, profile.startup_windows]);

  useEffect(() => {
    WebNAS.window.bind(state, viewport);
    if (!backendReady || profile.startup_windows !== "last") return;
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      saveTimer.current = null;
      void shellPreferencesClient.patch({ windows: state.windows.map(persistedWindow) }).catch(() => undefined);
    }, 300);
    return () => { if (saveTimer.current !== null) window.clearTimeout(saveTimer.current); };
  }, [backendReady, profile.startup_windows, state, viewport]);

  useEffect(() => WebNAS.window.subscribe((event: ShellEvent) => {
    if (event.type === "dispatch") dispatch(event.detail as WindowAction);
    if (event.type === "show-desktop") {
      state.windows.filter((item) => !item.minimized).forEach((item) => dispatch({ type: "minimize", id: item.id }));
    }
  }), [dispatch, state.windows]);

  useEffect(() => WebNAS.app.subscribe((event: ShellEvent) => {
    if (event.type === "open" && typeof event.detail === "string") openApp(event.detail);
  }), [openApp]);

  useEffect(() => {
    for (const app of permittedApps) {
      WebNAS.app.register({
        id: app.id,
        name: t(app.labelKey),
        version: "1.0.0",
        entry: `/apps/${app.id}`,
        permissions: [app.permission, ...(app.permissionAny || [])].filter((value): value is string => Boolean(value)),
        multiWindow: true,
        category: app.admin ? "system" : "application",
      });
    }
    return WebNAS.search.register("applications", () => permittedApps.map((app) => ({
      id: `app:${app.id}`,
      title: t(app.labelKey),
      category: "application" as const,
      keywords: [app.id, app.admin ? "admin" : ""],
      permitted: () => canUseApp(app.id),
      run: () => openApp(app.id),
    })));
  }, [canUseApp, openApp, permittedApps, t]);

  useEffect(() => WebNAS.taskbar.subscribe((event: ShellEvent) => {
    if (typeof event.detail !== "string") return;
    if (event.type === "pin" && !pinned.has(event.detail)) togglePin(event.detail);
    if (event.type === "unpin" && pinned.has(event.detail)) togglePin(event.detail);
  }), [pinned, togglePin]);

  useEffect(() => WebNAS.startMenu.subscribe((event: ShellEvent) => {
    if (event.type === "open") setLauncherOpen(true);
    else if (event.type === "close") setLauncherOpen(false);
    else if (event.type === "toggle") setLauncherOpen((value) => !value);
    else if (event.type === "pin" && typeof event.detail === "string" && !startPinned.has(event.detail)) toggleStartPin(event.detail);
    else if (event.type === "unpin" && typeof event.detail === "string" && startPinned.has(event.detail)) toggleStartPin(event.detail);
  }), [setLauncherOpen, startPinned, toggleStartPin]);

  useEffect(() => WebNAS.session.subscribe((event: ShellEvent) => {
    if (event.type === "logout") signOut();
    else if (event.type === "restart-webnas") void restartApplication();
    else if (event.type === "restart-host" && profile.permissions.includes("system.restart")) restartSystem();
    else if (event.type === "shutdown-host" && profile.permissions.includes("system.shutdown")) setShutdownOpen(true);
    else if (event.type === "lock") {
      setLauncherOpen(false); setNotificationsOpen(false); setActionsOpen(false); setCalendarOpen(false);
      window.dispatchEvent(new CustomEvent("webnas:lock-session"));
    }
  }), [profile.permissions, restartApplication, restartSystem, setActionsOpen, setCalendarOpen, setLauncherOpen, setNotificationsOpen, setShutdownOpen, signOut]);

  useEffect(() => {
    for (const item of toasts) {
      if (toastIds.current.has(item.id)) continue;
      toastIds.current.add(item.id);
      WebNAS.notification.ingestToast(item);
    }
  }, [toasts]);
}
