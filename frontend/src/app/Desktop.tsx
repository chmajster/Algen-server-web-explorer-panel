import { Bell, ShieldCheck, X } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState, type CSSProperties } from "react";
import { api, logout, type AppJob, type SettingsMe, type SettingsPatch, type Task } from "../api";
import { AppIcon } from "../components/AppIcon";
import { ConnectionRefreshScope } from "../features/connection/ConnectionStatusMonitor";
import type { SettingsCategory } from "../features/settings/SettingsApp";
import type { PolicySubject } from "../features/admin/IdentityApp";
import type { UploadControls } from "../features/transfers/useUploadManager";
import { ActionsCenter } from "../features/actions/ActionsCenter";
import { useBackgroundActions } from "../features/actions/useBackgroundActions";
import { backgroundOnly, deepLinkForAction } from "../features/actions/windowTargets";
import { isActiveAction, type BackgroundAction } from "../features/actions/types";
import type { Language } from "../i18n";
import { AppLauncher } from "./AppLauncher";
import { CalendarFlyout } from "./CalendarFlyout";
import { appById, apps } from "./catalog";
import { DesktopWindow } from "./DesktopWindow";
import { interfaceFontStacks } from "./interfaceFonts";
import { interfaceScaleFactor, migrateLegacyInterfaceScale } from "./interfaceScale";
import { Taskbar, type TaskbarWindowAction } from "./Taskbar";
import type { AppId, RecentApp, Theme, Toast, ToastFn, Translate, User, WindowInstance } from "./types";
import { initialWindowState, restoreWindowState, windowReducer, type ViewportMetrics } from "./windowState";
import { measureWorkspaceMetrics, navbarElements, sameViewportMetrics } from "./workspaceMetrics";

const ActivityCenter = lazy(() => import("../features/activity/ActivityCenter").then((module) => ({ default: module.ActivityCenter })));
const DesktopWidgets = lazy(() => import("../features/widgets/DesktopWidgets").then((module) => ({ default: module.DesktopWidgets })));
const FileManager = lazy(() => import("../features/files/FileManager").then((module) => ({ default: module.FileManager })));
const IdentityApp = lazy(() => import("../features/admin/IdentityApp").then((module) => ({ default: module.IdentityApp })));
const LogsApp = lazy(() => import("../features/logs/LogsApp").then((module) => ({ default: module.LogsApp })));
const MonitorApp = lazy(() => import("../features/admin/MonitorApp").then((module) => ({ default: module.MonitorApp })));
const ModuleApp = lazy(() => import("../features/modules/ModuleApp").then((module) => ({ default: module.ModuleApp })));
const ModuleHub = lazy(() => import("../features/modules/ModuleHub").then((module) => ({ default: module.ModuleHub })));
const PackageCenterApp = lazy(() => import("../features/package-center/PackageCenterApp").then((module) => ({ default: module.PackageCenterApp })));
const ServicesApp = lazy(() => import("../features/admin/SystemApps").then((module) => ({ default: module.ServicesApp })));
const SettingsAppView = lazy(() => import("../features/settings/SettingsApp").then((module) => ({ default: module.SettingsAppView })));
const TransferCenter = lazy(() => import("../features/transfers/TransferCenter").then((module) => ({ default: module.TransferCenter })));
const settingsCategories = new Set<SettingsCategory>(["system", "personalization", "files", "transfers", "notifications", "accessibility", "language", "account", "identity", "network", "networkResources", "updates", "policies", "administration", "about"]);
const isSettingsCategory = (value: string | undefined): value is SettingsCategory => Boolean(value && settingsCategories.has(value as SettingsCategory));
const policySubject = (value?: string): PolicySubject | undefined => {
  const match = /^policy:(user|group):(.+)$/.exec(value || "");
  return match ? { type: match[1] as PolicySubject["type"], id: match[2] } : undefined;
};

function wallpaperStyle(profile: SettingsMe): CSSProperties {
  if (!profile.wallpaper) return {};
  const size = profile.wallpaper_fit === "stretch" ? "100% 100%" : profile.wallpaper_fit === "center" ? "auto" : profile.wallpaper_fit;
  return { backgroundImage: `url(${JSON.stringify(profile.wallpaper)})`, backgroundSize: size, backgroundPosition: "center", backgroundRepeat: "no-repeat" };
}

function dateText(date: Date, profile: SettingsMe) {
  if (profile.date_format === "iso") return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  const options: Intl.DateTimeFormatOptions = profile.date_format === "long" ? { weekday: "short", day: "numeric", month: "long" } : profile.date_format === "locale" ? {} : { day: "2-digit", month: "2-digit", year: "numeric" };
  return date.toLocaleDateString(profile.language, options);
}

export function Desktop({ user, profile, language, theme, tasks, uploadControls, toasts, t, toast, onSettingsChange, onTheme, onLoggedOut }: {
  user: User;
  profile: SettingsMe;
  language: Language;
  theme: Theme;
  tasks: Task[];
  uploadControls: UploadControls;
  toasts: Toast[];
  t: Translate;
  toast: ToastFn;
  onSettingsChange: (patch: SettingsPatch) => Promise<void>;
  onTheme: (theme: Theme) => void;
  onLoggedOut: () => void;
}) {
  const migratedProfileScale = migrateLegacyInterfaceScale(profile.interface_scale, profile.larger_text);
  const interfaceScale = interfaceScaleFactor(migratedProfileScale);
  const [viewport, setViewport] = useState<ViewportMetrics>(() => ({
    width: window.innerWidth,
    height: window.innerHeight,
    bottom: 58 * interfaceScale,
    scale: interfaceScale,
  }));
  const desktopRef = useRef<HTMLDivElement>(null);
  const surfaceRef = useRef<HTMLElement>(null);
  const initialViewportMetrics = useRef(viewport);
  const storageKey = `webnas_windows_${user.username}`;
  const sessionWindowKey = `${storageKey}_session`;
  const recentAppsKey = `webnas_recent_apps_${user.username}`;
  const [state, dispatch] = useReducer(windowReducer, initialWindowState);
  const [launcherOpen, setLauncherOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [selectedShortcut, setSelectedShortcut] = useState<AppId | null>(null);
  const [dirtyWindows, setDirtyWindows] = useState<Set<string>>(new Set());
  const legacyPinnedKey = `webnas_pinned_apps_${user.username}`;
  const [pinned, setPinned] = useState<Set<AppId>>(() => {
    try {
      const legacy = localStorage.getItem(legacyPinnedKey);
      const values = legacy ? JSON.parse(legacy) as unknown : profile.pinned_apps;
      return new Set(Array.isArray(values) ? values.filter((value): value is AppId => typeof value === "string" && apps.some((app) => app.id === value)) : profile.pinned_apps);
    } catch { return new Set(profile.pinned_apps); }
  });
  const [pinnedModules, setPinnedModules] = useState<Set<string>>(() => new Set(profile.pinned_modules));
  const [startPinned, setStartPinned] = useState<Set<AppId>>(() => new Set(profile.start_pinned_apps));
  const [desktopShortcuts, setDesktopShortcuts] = useState<Set<AppId>>(() => new Set(profile.desktop_shortcut_apps));
  const [recentApps, setRecentApps] = useState<RecentApp[]>(() => {
    try {
      const value = JSON.parse(localStorage.getItem(recentAppsKey) || "[]") as unknown;
      return Array.isArray(value) ? value.filter((item): item is RecentApp => Boolean(item && typeof item === "object" && "id" in item && "usedAt" in item && typeof item.id === "string" && typeof item.usedAt === "number" && apps.some((app) => app.id === item.id))).slice(0, 8) : [];
    } catch { return []; }
  });
  const [moduleNames, setModuleNames] = useState<Map<string, string>>(new Map());
  const [apmidAvailable, setApmidAvailable] = useState(false);
  const [apmidResolved, setApmidResolved] = useState(false);
  const migrateLegacyPins = useRef(localStorage.getItem(legacyPinnedKey) !== null);
  const scaleMigrationAttempt = useRef("");
  const [clock, setClock] = useState(new Date());
  const [systemDark, setSystemDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  const [windowsHydrated, setWindowsHydrated] = useState(false);
  const windowStateRef = useRef(state);
  const previousTaskStatus = useRef<Map<string, Task["status"]>>(new Map());
  const tasksInitialized = useRef(false);
  const previousModuleJobs = useRef<Map<string, AppJob["status"]>>(new Map());
  const previousModuleHealth = useRef<Map<string, string>>(new Map());
  const moduleNotificationsInitialized = useRef(false);
  const apmidUnavailableHandled = useRef(false);
  const notifiedModuleEvents = useRef<Set<string>>(new Set());
  const notificationRef = useRef<HTMLElement>(null);
  const actionButtonRef = useRef<HTMLButtonElement>(null);
  const clockButtonRef = useRef<HTMLButtonElement>(null);
  const canUseApp = useCallback((appId: AppId) => { const definition = appById[appId]; return Boolean(definition && (!definition.admin || profile.is_admin) && (!definition.permission || profile.permissions.includes(definition.permission)) && (!definition.permissionAny || definition.permissionAny.some((permission) => profile.permissions.includes(permission)))); }, [profile.is_admin, profile.permissions]);
  const moduleAppAvailable = useCallback((appId: AppId) => (appId !== "ansible" || moduleNames.has("ansible-controller")) && (appId !== "hosts" || moduleNames.has("hosts-manager")) && (appId !== "apmid" || apmidAvailable), [apmidAvailable, moduleNames]);
  const availableApps = useMemo(() => apps.filter((app) => !app.hidden && canUseApp(app.id) && moduleAppAvailable(app.id)), [canUseApp, moduleAppAvailable]);
  const taskbarApps = useMemo(() => apps.filter((app) => canUseApp(app.id) && moduleAppAvailable(app.id)), [canUseApp, moduleAppAvailable]);
  const resolvedTheme = theme === "system" ? (systemDark ? "dark" : "light") : theme;
  const activeTransfers = tasks.filter((task) => ["queued", "running", "paused"].includes(task.status)).length;
  const backgroundManager = useBackgroundActions({ tasks, profile, moduleNames, t });
  const backgroundActions = useMemo(() => backgroundOnly(backgroundManager.actions, state.windows, state.activeId), [backgroundManager.actions, state.activeId, state.windows]);
  const activeBackgroundActions = backgroundActions.filter(isActiveAction).length;

  useEffect(() => { windowStateRef.current = state; }, [state]);

  useEffect(() => {
    const sessionState = sessionStorage.getItem(sessionWindowKey);
    const restoredState = restoreWindowState(sessionState || (profile.startup_windows === "last" ? localStorage.getItem(storageKey) : null), initialViewportMetrics.current);
    const windows = restoredState.windows.filter((item) => canUseApp(item.app));
    dispatch({ type: "hydrate", state: { ...restoredState, windows, activeId: windows.some((item) => item.id === restoredState.activeId) ? restoredState.activeId : "" } });
    setWindowsHydrated(true);
  }, [canUseApp, profile.startup_windows, sessionWindowKey, storageKey]);
  useEffect(() => {
    if (!windowsHydrated) return;
    const serialized = JSON.stringify(state);
    sessionStorage.setItem(sessionWindowKey, serialized);
    if (profile.startup_windows === "last") localStorage.setItem(storageKey, serialized);
  }, [profile.startup_windows, sessionWindowKey, state, storageKey, windowsHydrated]);
  useEffect(() => {
    const persistCurrentWindows = () => {
      if (!windowsHydrated) return;
      const serialized = JSON.stringify(windowStateRef.current);
      sessionStorage.setItem(sessionWindowKey, serialized);
      if (profile.startup_windows === "last") localStorage.setItem(storageKey, serialized);
    };
    const persistWhenHidden = () => { if (document.visibilityState === "hidden") persistCurrentWindows(); };
    window.addEventListener("pagehide", persistCurrentWindows);
    window.addEventListener("beforeunload", persistCurrentWindows);
    document.addEventListener("visibilitychange", persistWhenHidden);
    return () => {
      window.removeEventListener("pagehide", persistCurrentWindows);
      window.removeEventListener("beforeunload", persistCurrentWindows);
      document.removeEventListener("visibilitychange", persistWhenHidden);
    };
  }, [profile.startup_windows, sessionWindowKey, storageKey, windowsHydrated]);
  useEffect(() => {
    if (!migrateLegacyPins.current) return;
    migrateLegacyPins.current = false;
    setStartPinned(new Set(pinned));
    setDesktopShortcuts(new Set(pinned));
    void onSettingsChange({ pinned_apps: [...pinned], start_pinned_apps: [...pinned], desktop_shortcut_apps: [...pinned] }).then(() => localStorage.removeItem(legacyPinnedKey)).catch(() => undefined);
  }, [legacyPinnedKey, onSettingsChange, pinned]);
  useEffect(() => {
    const migrationKey = `${profile.interface_scale}:${profile.larger_text}`;
    if ((!profile.larger_text && migratedProfileScale === profile.interface_scale) || scaleMigrationAttempt.current === migrationKey) return;
    scaleMigrationAttempt.current = migrationKey;
    void onSettingsChange({
      interface_scale: migratedProfileScale,
      ...(profile.larger_text ? { larger_text: false } : {}),
    }).catch(() => undefined);
  }, [migratedProfileScale, onSettingsChange, profile.interface_scale, profile.larger_text]);
  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), profile.clock_show_seconds ? 1000 : 30000);
    return () => window.clearInterval(timer);
  }, [profile.clock_show_seconds]);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const change = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  useLayoutEffect(() => {
    const desktop = desktopRef.current;
    const surface = surfaceRef.current;
    if (!desktop || !surface) return;

    let animationFrame = 0;
    const measure = () => {
      const next = measureWorkspaceMetrics(desktop, surface, interfaceScale);
      initialViewportMetrics.current = next;
      setViewport((current) => sameViewportMetrics(current, next) ? current : next);
    };
    const scheduleMeasure = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(measure);
    };
    const resizeObserver = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(scheduleMeasure);
    resizeObserver?.observe(desktop);
    resizeObserver?.observe(surface);
    const observeChrome = () => {
      const taskbar = desktop.querySelector<HTMLElement>(".taskbar");
      if (taskbar) resizeObserver?.observe(taskbar);
      navbarElements().forEach((navbar) => resizeObserver?.observe(navbar));
      scheduleMeasure();
    };
    const mutationObserver = typeof MutationObserver === "undefined" ? null : new MutationObserver(observeChrome);
    if (document.body) mutationObserver?.observe(document.body, { childList: true, subtree: true });

    measure();
    observeChrome();
    window.addEventListener("resize", scheduleMeasure);
    window.addEventListener("orientationchange", scheduleMeasure);
    window.visualViewport?.addEventListener("resize", scheduleMeasure);
    return () => {
      window.cancelAnimationFrame(animationFrame);
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
      window.removeEventListener("resize", scheduleMeasure);
      window.removeEventListener("orientationchange", scheduleMeasure);
      window.visualViewport?.removeEventListener("resize", scheduleMeasure);
    };
  }, [interfaceScale]);
  useEffect(() => {
    dispatch({ type: "viewport", viewport });
  }, [viewport]);
  useEffect(() => {
    if (profile.show_notifications) return;
    setNotificationsOpen(false);
  }, [profile.show_notifications]);
  useEffect(() => {
    if (profile.show_background_actions_indicator) return;
    setActionsOpen(false);
  }, [profile.show_background_actions_indicator]);
  useEffect(() => {
    if (!notificationsOpen) return;
    function click(event: MouseEvent) { if (!notificationRef.current?.contains(event.target as Node) && !(event.target as HTMLElement).closest(".system-tray")) setNotificationsOpen(false); }
    function key(event: KeyboardEvent) { if (event.key === "Escape") setNotificationsOpen(false); }
    document.addEventListener("mousedown", click); document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", click); document.removeEventListener("keydown", key); };
  }, [notificationsOpen]);

  const openApp = useCallback((app: AppId, initialPath?: string, moduleId?: string) => {
    if (!canUseApp(app) || !moduleAppAvailable(app)) { toast(t("error.permissionRequired"), "error"); return; }
    const usedAt = Date.now();
    setRecentApps((current) => {
      const next = [{ id: app, usedAt }, ...current.filter((item) => item.id !== app)].slice(0, 8);
      localStorage.setItem(recentAppsKey, JSON.stringify(next));
      return next;
    });
    dispatch({ type: "open", app, initialPath, moduleId, viewport });
    setLauncherOpen(false);
    setNotificationsOpen(false);
    setActionsOpen(false);
    setCalendarOpen(false);
  }, [canUseApp, moduleAppAvailable, recentAppsKey, t, toast, viewport]);
  const openActionTarget = useCallback((action: BackgroundAction) => {
    if (!canUseApp(action.target.app)) {
      toast(t("error.permissionRequired"), "error");
      void backgroundManager.refresh();
      return;
    }
    dispatch({
      type: "openOrFocus",
      app: action.target.app,
      initialPath: action.target.initialPath,
      moduleId: action.target.moduleId,
      deepLink: deepLinkForAction(action),
      viewport,
    });
    backgroundManager.markOpened(action);
    setActionsOpen(false);
  }, [backgroundManager, canUseApp, t, toast, viewport]);
  useEffect(() => {
    if (!tasksInitialized.current) {
      tasks.forEach((task) => previousTaskStatus.current.set(task.id, task.status));
      tasksInitialized.current = true;
      return;
    }
    tasks.forEach((task) => {
      const previous = previousTaskStatus.current.get(task.id);
      if (previous && previous !== task.status && task.status === "completed" && profile.show_notifications && profile.notification_transfer && profile.transfer_success_notifications) toast(t("transfers.completedNotification"), "ok", "transfer");
      if (previous && previous !== task.status && task.status === "failed") {
        if (profile.show_notifications && profile.notification_transfer && profile.transfer_error_notifications) toast(t("transfers.failedNotification"), "error", "transfer");
        if (profile.transfer_open_failed_details) openApp("transfers");
      }
      previousTaskStatus.current.set(task.id, task.status);
    });
  }, [openApp, profile.notification_transfer, profile.show_notifications, profile.transfer_error_notifications, profile.transfer_open_failed_details, profile.transfer_success_notifications, t, tasks, toast]);
  useEffect(() => {
    if (!profile.permissions.includes("modules.view")) return;
    async function refreshModules() {
      try {
        const modules = await api.modules();
        setModuleNames(new Map(modules.filter((item) => item.state.installed).map((item) => [item.id, item.manifest.name])));
        const jobs = modules.flatMap((item) => item.jobs);
        if (!moduleNotificationsInitialized.current) {
          jobs.forEach((job) => previousModuleJobs.current.set(job.id, job.status));
          modules.forEach((item) => previousModuleHealth.current.set(item.id, item.module_status.health));
          moduleNotificationsInitialized.current = true;
          modules.filter((item) => item.state.update_available).forEach((item) => notifyOnce(`update:${item.id}:${item.state.available_version}`, t("module.notification.updateAvailable").replace("{name}", item.manifest.name), "ok", item.id));
          return;
        }
        jobs.forEach((job) => {
          const previous = previousModuleJobs.current.get(job.id);
          if (previous && previous !== job.status && ["completed", "failed"].includes(job.status)) {
            const module = modules.find((item) => item.id === job.module_id);
            const name = module?.manifest.name || job.module_id;
            const key = `job:${job.id}:${job.status}`;
            const template = job.status === "failed" ? t("module.notification.operationFailed") : job.action === "diagnostics" ? t("module.notification.diagnosticsCompleted") : t("module.notification.operationCompleted");
            notifyOnce(key, template.replace("{name}", name), job.status === "failed" ? "error" : "ok", job.module_id);
            if (job.action === "restore" && job.status === "failed") notifyOnce(`restore:${job.id}`, t("module.notification.restoreFailed").replace("{name}", name), "error", job.module_id);
            if (job.log_tail.some((line) => line.line.toLowerCase().includes("rolled back"))) notifyOnce(`rollback:${job.id}`, t("module.notification.rollback").replace("{name}", name), "error", job.module_id);
          }
          previousModuleJobs.current.set(job.id, job.status);
        });
        modules.forEach((item) => {
          const previous = previousModuleHealth.current.get(item.id);
          if (previous && previous !== item.module_status.health && item.module_status.health === "failed") notifyOnce(`health:${item.id}:${item.module_status.last_action_time || item.module_status.health_message}`, t("module.notification.serviceFailed").replace("{name}", item.manifest.name), "error", item.id);
          if (item.module_status.configuration_valid === false) notifyOnce(`config:${item.id}:${item.module_status.last_action_time || item.module_status.last_error}`, t("module.notification.invalidConfiguration").replace("{name}", item.manifest.name), "error", item.id);
          if (item.state.update_available) notifyOnce(`update:${item.id}:${item.state.available_version}`, t("module.notification.updateAvailable").replace("{name}", item.manifest.name), "ok", item.id);
          previousModuleHealth.current.set(item.id, item.module_status.health);
        });
      } catch {
        // Package Center and module apps surface request failures directly.
      }
    }
    function notifyOnce(key: string, message: string, type: "ok" | "error", moduleId: string) {
      if (notifiedModuleEvents.current.has(key)) return;
      notifiedModuleEvents.current.add(key);
      if (profile.show_notifications && profile.notification_admin) toast(message, type, "admin", moduleId);
    }
    void refreshModules();
    const timer = window.setInterval(() => { if (!document.hidden) void refreshModules(); }, 5000);
    return () => window.clearInterval(timer);
  }, [profile.notification_admin, profile.permissions, profile.show_notifications, t, toast]);
  useEffect(() => {
    let active = true;
    let polling = false;
    async function refreshApmidAccess() {
      if (polling) return;
      polling = true;
      try {
        const value = await api.apmidAccess();
        if (active) { setApmidAvailable(value.installed && value.allowed); setApmidResolved(true); }
      } catch {
        // Keep the last confirmed state during a transient backend outage.
      } finally { polling = false; }
    }
    const changed = () => { void refreshApmidAccess(); };
    void refreshApmidAccess();
    const timer = window.setInterval(() => { if (!document.hidden) void refreshApmidAccess(); }, 5000);
    window.addEventListener("webnas:modules-changed", changed);
    return () => { active = false; window.clearInterval(timer); window.removeEventListener("webnas:modules-changed", changed); };
  }, []);
  useEffect(() => {
    if (apmidAvailable) { apmidUnavailableHandled.current = false; return; }
    if (!apmidResolved || apmidUnavailableHandled.current) return;
    apmidUnavailableHandled.current = true;
    state.windows.filter((item) => item.app === "apmid").forEach((item) => dispatch({ type: "close", id: item.id }));
    const nextPinned = new Set(pinned); nextPinned.delete("apmid"); setPinned(nextPinned);
    const nextStart = new Set(startPinned); nextStart.delete("apmid"); setStartPinned(nextStart);
    const nextDesktop = new Set(desktopShortcuts); nextDesktop.delete("apmid"); setDesktopShortcuts(nextDesktop);
    if (pinned.has("apmid") || startPinned.has("apmid") || desktopShortcuts.has("apmid")) {
      void onSettingsChange({ pinned_apps: [...nextPinned], start_pinned_apps: [...nextStart], desktop_shortcut_apps: [...nextDesktop] }).catch(() => undefined);
    }
  }, [apmidAvailable, apmidResolved, desktopShortcuts, onSettingsChange, pinned, startPinned, state.windows]);

  function selectTask(item: WindowInstance) {
    if (state.activeId === item.id && !item.minimized) dispatch({ type: "minimize", id: item.id });
    else dispatch({ type: "focus", id: item.id });
  }
  function selectApp(app: AppId) {
    const existing = state.windows.filter((item) => item.app === app).sort((a, b) => b.zIndex - a.zIndex)[0];
    if (existing) selectTask(existing); else openApp(app);
  }
  function selectModule(moduleId: string) {
    const existing = state.windows.filter((item) => item.app === "module" && item.moduleId === moduleId).sort((a, b) => b.zIndex - a.zIndex)[0];
    if (existing) selectTask(existing); else openApp("module", undefined, moduleId);
  }
  function togglePin(app: AppId) {
    const previous = new Set(pinned);
    const next = new Set(pinned);
    if (next.has(app)) next.delete(app); else next.add(app);
    setPinned(next);
    localStorage.setItem(legacyPinnedKey, JSON.stringify([...next]));
    void onSettingsChange({ pinned_apps: [...next] }).then(() => localStorage.removeItem(legacyPinnedKey)).catch((error: unknown) => {
      setPinned(previous);
      localStorage.setItem(legacyPinnedKey, JSON.stringify([...previous]));
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    });
  }
  function toggleStartPin(app: AppId) {
    const previous = new Set(startPinned);
    const next = new Set(startPinned);
    if (next.has(app)) next.delete(app); else next.add(app);
    setStartPinned(next);
    void onSettingsChange({ start_pinned_apps: [...next] }).catch((error: unknown) => {
      setStartPinned(previous);
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    });
  }
  function toggleModulePin(moduleId: string) {
    const previous = new Set(pinnedModules);
    const next = new Set(pinnedModules);
    if (next.has(moduleId)) next.delete(moduleId); else next.add(moduleId);
    setPinnedModules(next);
    void onSettingsChange({ pinned_modules: [...next] }).catch((error: unknown) => {
      setPinnedModules(previous);
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    });
  }
  function toggleDesktopShortcut(app: AppId) {
    const previous = new Set(desktopShortcuts);
    const next = new Set(desktopShortcuts);
    if (next.has(app)) next.delete(app); else next.add(app);
    setDesktopShortcuts(next);
    void onSettingsChange({ desktop_shortcut_apps: [...next] }).catch((error: unknown) => {
      setDesktopShortcuts(previous);
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    });
  }
  function signOut() { const draftPrefix = `webnas_window_draft_${user.username}_`; Object.keys(sessionStorage).filter((key) => key.startsWith(draftPrefix)).forEach((key) => sessionStorage.removeItem(key)); sessionStorage.removeItem(sessionWindowKey); void logout().finally(onLoggedOut); }
  function moduleDirty(item: WindowInstance, dirty: boolean) { setDirtyWindows((current) => { const next = new Set(current); if (dirty) next.add(item.id); else next.delete(item.id); return next; }); }
  function closeWindow(item: WindowInstance) { if (dirtyWindows.has(item.id) && !window.confirm(t("module.unsavedClose"))) return; const draftPrefix = `webnas_window_draft_${user.username}_${item.id}`; Object.keys(sessionStorage).filter((key) => key.startsWith(draftPrefix)).forEach((key) => sessionStorage.removeItem(key)); setDirtyWindows((current) => { const next = new Set(current); next.delete(item.id); return next; }); dispatch({ type: "close", id: item.id }); }
  function taskbarWindow(item: WindowInstance, action: TaskbarWindowAction) {
    if (action === "close") closeWindow(item);
    else if (action === "focus") dispatch({ type: "focus", id: item.id });
    else if (action === "minimize") dispatch({ type: "minimize", id: item.id });
    else dispatch({ type: "toggleMaximize", id: item.id, viewport });
  }
  function closeAppWindows(app: AppId) { state.windows.filter((item) => item.app === app).forEach(closeWindow); }
  function closeModuleWindows(moduleId: string) { state.windows.filter((item) => item.app === "module" && item.moduleId === moduleId).forEach(closeWindow); }
  function changeTaskbarAlignment(alignment: "left" | "center") { void onSettingsChange({ taskbar_alignment: alignment }).catch((error: unknown) => toast(error instanceof Error ? error.message : t("error.generic"), "error")); }
  function renderApp(item: WindowInstance) {
    switch (item.app) {
      case "files": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><FileManager homePath={user.home} initialPath={item.initialPath} settings={profile} tasks={tasks} isAdmin={profile.is_admin} t={t} toast={toast} onUpload={uploadControls.add} onUploadCancel={uploadControls.cancel} onUploadRetry={uploadControls.retry} onSettingsChange={onSettingsChange} onOpenFolderWindow={(path) => openApp("files", path)} onShareSamba={(path) => openApp("module", path, "samba")} /></Suspense>;
      case "transfers": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><TransferCenter tasks={tasks} settings={profile} selectedTaskId={item.deepLink?.type === "transfer" ? item.deepLink.id : undefined} t={t} toast={toast} uploadControls={uploadControls} onSelectedTaskClose={() => dispatch({ type: "clearDeepLink", id: item.id })} /></Suspense>;
      case "activity": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><ActivityCenter locale={profile.language} t={t} /></Suspense>;
      case "identity": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><IdentityApp permissions={profile.permissions} t={t} toast={toast} onOpenPolicies={(subject) => openApp("settings", "policies", `policy:${subject.type}:${subject.id}`)} /></Suspense>;
      case "users": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><IdentityApp permissions={profile.permissions} initialTab="users" t={t} toast={toast} onOpenPolicies={(subject) => openApp("settings", "policies", `policy:${subject.type}:${subject.id}`)} /></Suspense>;
      case "groups": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><IdentityApp permissions={profile.permissions} initialTab="groups" t={t} toast={toast} onOpenPolicies={(subject) => openApp("settings", "policies", `policy:${subject.type}:${subject.id}`)} /></Suspense>;
      case "mounts": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><SettingsAppView settings={profile} initialSection="networkResources" t={t} toast={toast} onSettingsChange={onSettingsChange} onOpenApp={openApp} /></Suspense>;
      case "samba": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><ModuleApp moduleId="samba" initialPath={item.initialPath} deepLink={item.deepLink} draftKey={`webnas_window_draft_${user.username}_${item.id}`} permissions={profile.permissions} t={t} toast={toast} onOpenFolder={(path) => openApp("files", path)} onDirtyChange={(dirty) => moduleDirty(item, dirty)} onDeepLinkClose={() => dispatch({ type: "clearDeepLink", id: item.id })} /></Suspense>;
      case "modules": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><ModuleHub t={t} toast={toast} onOpen={(moduleId) => openApp("module", undefined, moduleId)} /></Suspense>;
      case "containers": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><ModuleApp moduleId="docker" deepLink={item.deepLink} draftKey={`webnas_window_draft_${user.username}_${item.id}`} permissions={profile.permissions} t={t} toast={toast} onOpenFolder={(path) => openApp("files", path)} onDirtyChange={(dirty) => moduleDirty(item, dirty)} onDeepLinkClose={() => dispatch({ type: "clearDeepLink", id: item.id })} /></Suspense>;
      case "ansible": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><ModuleApp moduleId="ansible-controller" deepLink={item.deepLink} draftKey={`webnas_window_draft_${user.username}_${item.id}`} permissions={profile.permissions} t={t} toast={toast} onOpenFolder={(path) => openApp("files", path)} onDirtyChange={(dirty) => moduleDirty(item, dirty)} onDeepLinkClose={() => dispatch({ type: "clearDeepLink", id: item.id })} /></Suspense>;
      case "hosts": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><ModuleApp moduleId="hosts-manager" deepLink={item.deepLink} draftKey={`webnas_window_draft_${user.username}_${item.id}`} permissions={profile.permissions} t={t} toast={toast} onOpenFolder={(path) => openApp("files", path)} onDirtyChange={(dirty) => moduleDirty(item, dirty)} onDeepLinkClose={() => dispatch({ type: "clearDeepLink", id: item.id })} /></Suspense>;
      case "apmid": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><ModuleApp moduleId="apmid" permissions={profile.permissions} t={t} toast={toast} onOpenFolder={(path) => openApp("files", path)} onDirtyChange={(dirty) => moduleDirty(item, dirty)} /></Suspense>;
      case "access": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><SettingsAppView settings={profile} initialSection="policies" t={t} toast={toast} onSettingsChange={onSettingsChange} onOpenApp={openApp} /></Suspense>;
      case "services": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><ServicesApp t={t} toast={toast} /></Suspense>;
      case "store": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><PackageCenterApp selectedJobId={item.deepLink?.type === "package-job" ? item.deepLink.jobId || item.deepLink.id : undefined} t={t} toast={toast} onOpenModule={(moduleId) => openApp("module", undefined, moduleId)} onSelectedJobClose={() => dispatch({ type: "clearDeepLink", id: item.id })} /></Suspense>;
      case "logs": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><LogsApp permissions={profile.permissions} t={t} toast={toast} /></Suspense>;
      case "settings": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><SettingsAppView settings={profile} initialSection={isSettingsCategory(item.initialPath) ? item.initialPath : "system"} initialPolicySubject={policySubject(item.moduleId)} deepLink={item.deepLink} t={t} toast={toast} onSettingsChange={onSettingsChange} onOpenApp={openApp} onDeepLinkClose={() => dispatch({ type: "clearDeepLink", id: item.id })} onSectionChange={(section) => { dispatch({ type: "setInitialPath", id: item.id, initialPath: section }); if (item.deepLink && section !== item.deepLink.section) dispatch({ type: "clearDeepLink", id: item.id }); }} /></Suspense>;
      case "monitor": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><MonitorApp t={t} /></Suspense>;
      case "module": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><ModuleApp moduleId={item.moduleId || ""} initialPath={item.initialPath} deepLink={item.deepLink} draftKey={`webnas_window_draft_${user.username}_${item.id}`} permissions={profile.permissions} t={t} toast={toast} onOpenFolder={(path) => openApp("files", path)} onDirtyChange={(dirty) => moduleDirty(item, dirty)} onDeepLinkClose={() => dispatch({ type: "clearDeepLink", id: item.id })} /></Suspense>;
    }
  }

  useLayoutEffect(() => {
    const root = document.documentElement;
    const previousFont = root.style.getPropertyValue("--font-family-ui");
    const previousUiScale = root.style.getPropertyValue("--ui-scale");
    root.style.setProperty("--font-family-ui", interfaceFontStacks[profile.interface_font]);
    root.style.setProperty("--ui-scale", String(interfaceScale));
    return () => {
      if (previousFont) root.style.setProperty("--font-family-ui", previousFont);
      else root.style.removeProperty("--font-family-ui");
      if (previousUiScale) root.style.setProperty("--ui-scale", previousUiScale);
      else root.style.removeProperty("--ui-scale");
    };
  }, [interfaceScale, profile.interface_font]);
  const rootStyle = {
    "--ui-scale": interfaceScale,
    "--font-family-ui": interfaceFontStacks[profile.interface_font],
  } as CSSProperties;
  const rootClasses = ["desktop", resolvedTheme, `accent-${profile.accent_color}`, `taskbar-align-${profile.taskbar_alignment}`, profile.window_transparency ? "" : "no-transparency", profile.animations_enabled && !profile.reduced_motion ? "" : "no-animations", profile.high_contrast ? "high-contrast" : "", profile.strong_active_borders ? "strong-active-borders" : "", profile.always_show_focus ? "always-show-focus" : ""].filter(Boolean).join(" ");
  const visibleToasts = profile.show_notifications ? toasts.filter((item) => (item.type !== "error" || profile.notification_errors) && (item.category !== "admin" || profile.notification_admin) && (item.category !== "transfer" || profile.notification_transfer)).slice(-profile.notification_limit) : [];
  const clockText = clock.toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit", second: profile.clock_show_seconds ? "2-digit" : undefined, hour12: profile.time_format === "12" });

  return <div ref={desktopRef} className={rootClasses} style={rootStyle}>
    <main ref={surfaceRef} className="desktop-surface" style={wallpaperStyle(profile)} onPointerDown={(event) => { if (event.target === event.currentTarget) setSelectedShortcut(null); }}>
      {profile.show_desktop_shortcuts && <div className={`desktop-shortcuts shortcuts-${profile.desktop_shortcut_size}`} aria-label={t("desktop.shortcuts")}>{availableApps.filter((app) => desktopShortcuts.has(app.id)).map((app) => <AppIcon key={app.id} label={t(app.labelKey)} icon={app.icon} selected={selectedShortcut === app.id} onSelect={() => setSelectedShortcut(app.id)} onOpen={() => openApp(app.id)} />)}</div>}
      {profile.show_welcome_widget && <div className="desktop-welcome"><span>WebNAS</span><strong>{t("desktop.welcome")}, {user.username}</strong><small>{t("desktop.welcomeHint")}</small></div>}
      <Suspense fallback={null}><DesktopWidgets profile={profile} tasks={tasks} toasts={toasts} t={t} onSettingsChange={onSettingsChange} /></Suspense>
      {state.windows.filter((item) => !item.minimized).map((item) => <DesktopWindow key={item.id} window={item} active={state.activeId === item.id} viewport={viewport} animationsEnabled={profile.animations_enabled && !profile.reduced_motion} t={t} onFocus={() => dispatch({ type: "focus", id: item.id })} onClose={() => closeWindow(item)} onMinimize={() => dispatch({ type: "minimize", id: item.id })} onCommit={(rect, restoreRect) => dispatch({ type: "commit", id: item.id, rect, restoreRect })} onToggleMaximize={() => dispatch({ type: "toggleMaximize", id: item.id, viewport })}><ConnectionRefreshScope active={state.activeId === item.id}>{renderApp(item)}</ConnectionRefreshScope></DesktopWindow>)}
    </main>
    {launcherOpen && <AppLauncher apps={availableApps} startPinned={startPinned} desktopShortcuts={desktopShortcuts} taskbarPinned={pinned} recentApps={recentApps} profile={profile} t={t} onOpen={openApp} onOpenProfile={() => openApp("settings", "account")} onToggleStartPin={toggleStartPin} onToggleDesktopShortcut={toggleDesktopShortcut} onToggleTaskbarPin={togglePin} onLogout={signOut} onClose={() => setLauncherOpen(false)} />}
    <Taskbar apps={taskbarApps} pinned={pinned} pinnedModules={pinnedModules} moduleNames={moduleNames} windows={state.windows} activeId={state.activeId} profile={profile} resolvedTheme={resolvedTheme} clockText={clockText} dateText={dateText(clock, profile)} clockDateTime={clock.toISOString()} activeTransfers={activeTransfers} activeActions={activeBackgroundActions} launcherOpen={launcherOpen} notificationsOpen={notificationsOpen} actionsOpen={actionsOpen} calendarOpen={calendarOpen} actionButtonRef={actionButtonRef} clockButtonRef={clockButtonRef} t={t} onToggleLauncher={() => { setNotificationsOpen(false); setActionsOpen(false); setCalendarOpen(false); setLauncherOpen((value) => !value); }} onToggleNotifications={() => { setLauncherOpen(false); setActionsOpen(false); setCalendarOpen(false); setNotificationsOpen((value) => !value); }} onToggleActions={() => { setLauncherOpen(false); setNotificationsOpen(false); setCalendarOpen(false); setActionsOpen((value) => !value); }} onToggleCalendar={() => { setLauncherOpen(false); setNotificationsOpen(false); setActionsOpen(false); setCalendarOpen((value) => !value); }} onOpenLocalPanel={() => { setLauncherOpen(false); setNotificationsOpen(false); setActionsOpen(false); setCalendarOpen(false); }} onToggleTheme={() => onTheme(resolvedTheme === "dark" ? "light" : "dark")} onApp={selectApp} onModule={selectModule} onOpenNew={(app) => openApp(app)} onOpenModuleNew={(moduleId) => openApp("module", undefined, moduleId)} onTogglePin={togglePin} onToggleModulePin={toggleModulePin} onWindow={taskbarWindow} onCloseApp={closeAppWindows} onCloseModule={closeModuleWindows} onTaskbarSettings={() => openApp("settings", "personalization")} onAlignment={changeTaskbarAlignment} onLogout={signOut} />
    {actionsOpen && <ActionsCenter actions={backgroundActions} locale={profile.language} t={t} triggerRef={actionButtonRef} onOpen={openActionTarget} onDismiss={backgroundManager.dismiss} onClose={() => setActionsOpen(false)} />}
    {calendarOpen && <CalendarFlyout now={clock} locale={profile.language} t={t} triggerRef={clockButtonRef} onClose={() => setCalendarOpen(false)} />}
    {notificationsOpen && <aside ref={notificationRef} className="notification-center" aria-label={t("desktop.notifications")}><header><div><Bell /><strong>{t("desktop.notifications")}</strong></div><button type="button" aria-label={t("action.close")} onClick={() => setNotificationsOpen(false)}><X /></button></header>{visibleToasts.length === 0 && (!profile.notification_transfer || tasks.length === 0) ? <div className="empty-state">{t("desktop.noNotifications")}</div> : <>{visibleToasts.slice().reverse().map((item) => <article className={item.type} key={item.id} role={item.moduleId ? "button" : undefined} tabIndex={item.moduleId ? 0 : undefined} onClick={() => { if (!item.moduleId) return; openApp("module", undefined, item.moduleId); setNotificationsOpen(false); }} onKeyDown={(event) => { if (item.moduleId && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); openApp("module", undefined, item.moduleId); setNotificationsOpen(false); } }}><strong>{item.type === "error" ? t("status.error") : "WebNAS"}</strong><span>{item.text}</span></article>)}{profile.notification_transfer && tasks.slice(-profile.notification_limit).reverse().map((task) => <article key={task.id}><strong>{t(`transfers.${task.type}`)}</strong><span>{t(`task.${task.status}`)} · {Math.round(task.progress_percent ?? task.progress ?? 0)}%</span></article>)}</>}</aside>}
    <div className="toasts" role="status" aria-live="polite">{visibleToasts.map((item) => <div className={item.type} key={item.id}>{item.type === "error" && <ShieldCheck />}{item.text}</div>)}</div>
  </div>;
}
