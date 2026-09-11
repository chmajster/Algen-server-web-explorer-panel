import { useEffect, useMemo, useRef, type Dispatch, type SetStateAction } from "react";
import type { SettingsMe } from "../../api";
import { apps } from "../registry/builtinModules";
import type { AppId, Toast, Translate } from "../types";
import type { ViewportMetrics, WindowAction, WindowState } from "../windowState";
import { WebNAS } from "./WebNASShell";
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

export function useShellBindings(bindings: Bindings) {
  const {
    state, viewport, dispatch, profile, t, toasts, pinned, startPinned, canUseApp, openApp,
    togglePin, toggleStartPin, setLauncherOpen, setNotificationsOpen, setActionsOpen,
    setCalendarOpen, setShutdownOpen, signOut, restartApplication, restartSystem,
  } = bindings;
  const toastIds = useRef(new Set<number>());

  const permittedApps = useMemo(() => apps.filter((app) => !app.hidden && canUseApp(app.id)), [canUseApp]);

  // Window state is owned by DesktopController. Keeping a second persisted copy in
  // shell preferences caused a late backend hydrate to overwrite the current tab's
  // session/local state after reload.
  useEffect(() => {
    WebNAS.window.bind(state, viewport);
  }, [state, viewport]);

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
