import { Bell, ShieldCheck, X } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useReducer, useRef, useState, type CSSProperties } from "react";
import { api, logout, type AppJob, type SettingsMe, type SettingsPatch, type Task } from "../api";
import { AppIcon } from "../components/AppIcon";
import { LogsAppView, MonitorApp, ServicesApp, SettingsAppView } from "../features/admin/SystemApps";
import { FileManager } from "../features/files/FileManager";
import { TransferCenter } from "../features/transfers/TransferCenter";
import { DesktopWidgets } from "../features/widgets/DesktopWidgets";
import type { UploadControls } from "../features/transfers/useUploadManager";
import type { Language } from "../i18n";
import { AppLauncher } from "./AppLauncher";
import { appById, apps } from "./catalog";
import { DesktopWindow } from "./DesktopWindow";
import { Taskbar } from "./Taskbar";
import type { AppId, Theme, Toast, ToastFn, Translate, User, WindowInstance } from "./types";
import { initialWindowState, restoreWindowState, windowReducer } from "./windowState";

const ActivityCenter = lazy(() => import("../features/activity/ActivityCenter").then((module) => ({ default: module.ActivityCenter })));
const IdentityApp = lazy(() => import("../features/admin/IdentityApp").then((module) => ({ default: module.IdentityApp })));
const ModuleApp = lazy(() => import("../features/modules/ModuleApp").then((module) => ({ default: module.ModuleApp })));
const ModuleHub = lazy(() => import("../features/modules/ModuleHub").then((module) => ({ default: module.ModuleHub })));
const PackageCenterApp = lazy(() => import("../features/package-center/PackageCenterApp").then((module) => ({ default: module.PackageCenterApp })));

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
  const storageKey = `webnas_windows_${user.username}`;
  const [state, dispatch] = useReducer(windowReducer, initialWindowState);
  const [launcherOpen, setLauncherOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [selectedShortcut, setSelectedShortcut] = useState<AppId | null>(null);
  const [dirtyWindows, setDirtyWindows] = useState<Set<string>>(new Set());
  const [pinned, setPinned] = useState<Set<AppId>>(() => new Set(JSON.parse(localStorage.getItem(`webnas_pinned_apps_${user.username}`) || '["files","transfers","monitor","settings"]')));
  const [clock, setClock] = useState(new Date());
  const [systemDark, setSystemDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  const restored = useRef(false);
  const previousTaskStatus = useRef<Map<string, Task["status"]>>(new Map());
  const tasksInitialized = useRef(false);
  const previousModuleJobs = useRef<Map<string, AppJob["status"]>>(new Map());
  const previousModuleHealth = useRef<Map<string, string>>(new Map());
  const moduleNotificationsInitialized = useRef(false);
  const notifiedModuleEvents = useRef<Set<string>>(new Set());
  const notificationRef = useRef<HTMLElement>(null);
  const canUseApp = useCallback((appId: AppId) => { const definition = appById[appId]; return Boolean(definition && (!definition.admin || profile.is_admin) && (!definition.permission || profile.permissions.includes(definition.permission)) && (!definition.permissionAny || definition.permissionAny.some((permission) => profile.permissions.includes(permission)))); }, [profile.is_admin, profile.permissions]);
  const availableApps = useMemo(() => apps.filter((app) => !app.hidden && canUseApp(app.id)), [canUseApp]);
  const taskbarApps = useMemo(() => apps.filter((app) => canUseApp(app.id)), [canUseApp]);
  const resolvedTheme = theme === "system" ? (systemDark ? "dark" : "light") : theme;
  const activeTransfers = tasks.filter((task) => ["queued", "running", "paused"].includes(task.status)).length;

  useEffect(() => {
    const restoredState = profile.startup_windows === "last" ? restoreWindowState(localStorage.getItem(storageKey)) : initialWindowState;
    const windows = restoredState.windows.filter((item) => canUseApp(item.app));
    dispatch({ type: "hydrate", state: { ...restoredState, windows, activeId: windows.some((item) => item.id === restoredState.activeId) ? restoredState.activeId : "" } });
    restored.current = true;
  }, [canUseApp, profile.startup_windows, storageKey]);
  useEffect(() => {
    if (!restored.current) return;
    const timer = window.setTimeout(() => localStorage.setItem(storageKey, JSON.stringify(state)), 240);
    return () => window.clearTimeout(timer);
  }, [state, storageKey]);
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
  useEffect(() => {
    const resize = () => dispatch({ type: "viewport", viewport: { width: window.innerWidth, height: window.innerHeight } });
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  useEffect(() => {
    if (profile.show_notifications) return;
    setNotificationsOpen(false);
  }, [profile.show_notifications]);
  useEffect(() => {
    if (!notificationsOpen) return;
    function click(event: MouseEvent) { if (!notificationRef.current?.contains(event.target as Node) && !(event.target as HTMLElement).closest(".system-tray")) setNotificationsOpen(false); }
    function key(event: KeyboardEvent) { if (event.key === "Escape") setNotificationsOpen(false); }
    document.addEventListener("mousedown", click); document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", click); document.removeEventListener("keydown", key); };
  }, [notificationsOpen]);

  const openApp = useCallback((app: AppId, initialPath?: string, moduleId?: string) => {
    if (!canUseApp(app)) { toast(t("error.permissionRequired"), "error"); return; }
    dispatch({ type: "open", app, initialPath, moduleId, viewport: { width: window.innerWidth, height: window.innerHeight } });
    setLauncherOpen(false);
  }, [canUseApp, t, toast]);
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

  function selectTask(item: WindowInstance) {
    if (state.activeId === item.id && !item.minimized) dispatch({ type: "minimize", id: item.id });
    else dispatch({ type: "focus", id: item.id });
  }
  function selectApp(app: AppId) {
    const existing = state.windows.filter((item) => item.app === app).sort((a, b) => b.zIndex - a.zIndex)[0];
    if (existing) selectTask(existing); else openApp(app);
  }
  function togglePin(app: AppId) {
    setPinned((current) => { const next = new Set(current); if (next.has(app)) next.delete(app); else next.add(app); localStorage.setItem(`webnas_pinned_apps_${user.username}`, JSON.stringify([...next])); return next; });
  }
  function signOut() { void logout().finally(onLoggedOut); }
  function moduleDirty(item: WindowInstance, dirty: boolean) { setDirtyWindows((current) => { const next = new Set(current); if (dirty) next.add(item.id); else next.delete(item.id); return next; }); }
  function closeWindow(item: WindowInstance) { if (dirtyWindows.has(item.id) && !window.confirm(t("module.unsavedClose"))) return; setDirtyWindows((current) => { const next = new Set(current); next.delete(item.id); return next; }); dispatch({ type: "close", id: item.id }); }
  function renderApp(item: WindowInstance) {
    switch (item.app) {
      case "files": return <FileManager homePath={user.home} initialPath={item.initialPath} settings={profile} tasks={tasks} isAdmin={profile.is_admin} t={t} toast={toast} onUpload={uploadControls.add} onUploadCancel={uploadControls.cancel} onUploadRetry={uploadControls.retry} onSettingsChange={onSettingsChange} onOpenFolderWindow={(path) => openApp("files", path)} onShareSamba={(path) => openApp("samba", path)} />;
      case "transfers": return <TransferCenter tasks={tasks} settings={profile} t={t} toast={toast} uploadControls={uploadControls} />;
      case "activity": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><ActivityCenter locale={profile.language} t={t} /></Suspense>;
      case "identity": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><IdentityApp permissions={profile.permissions} t={t} toast={toast} /></Suspense>;
      case "users": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><IdentityApp permissions={profile.permissions} initialTab="users" t={t} toast={toast} /></Suspense>;
      case "groups": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><IdentityApp permissions={profile.permissions} initialTab="groups" t={t} toast={toast} /></Suspense>;
      case "mounts": return <SettingsAppView settings={profile} initialSection="network" t={t} toast={toast} onSettingsChange={onSettingsChange} onOpenApp={openApp} />;
      case "samba": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><ModuleApp moduleId="samba" initialPath={item.initialPath} permissions={profile.permissions} t={t} toast={toast} onOpenFolder={(path) => openApp("files", path)} onDirtyChange={(dirty) => moduleDirty(item, dirty)} /></Suspense>;
      case "modules": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><ModuleHub t={t} toast={toast} onOpen={(moduleId) => openApp(moduleId === "samba" ? "samba" : "module", undefined, moduleId)} /></Suspense>;
      case "access": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><IdentityApp permissions={profile.permissions} initialTab="roles" t={t} toast={toast} /></Suspense>;
      case "services": return <ServicesApp t={t} toast={toast} />;
      case "store": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><PackageCenterApp t={t} toast={toast} onOpenModule={(moduleId) => { if (moduleId === "samba") openApp("samba"); else openApp("module", undefined, moduleId); }} /></Suspense>;
      case "logs": return <LogsAppView t={t} />;
      case "settings": return <SettingsAppView settings={profile} t={t} toast={toast} onSettingsChange={onSettingsChange} onOpenApp={openApp} />;
      case "monitor": return <MonitorApp t={t} />;
      case "module": return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><ModuleApp moduleId={item.moduleId || ""} initialPath={item.initialPath} permissions={profile.permissions} t={t} toast={toast} onOpenFolder={(path) => openApp("files", path)} onDirtyChange={(dirty) => moduleDirty(item, dirty)} /></Suspense>;
    }
  }

  const interfaceScale = profile.interface_scale / 100;
  const textScale = interfaceScale * (profile.larger_text ? 1.125 : 1);
  const rootStyle = {
    "--ui-scale": interfaceScale,
    "--interface-font-size": `${16 * textScale}px`,
    "--taskbar-height-scaled": `${58 * interfaceScale}px`,
    "--taskbar-item-size-scaled": `${44 * interfaceScale}px`,
    "--window-titlebar-height-scaled": `${44 * interfaceScale}px`,
  } as CSSProperties;
  const rootClasses = ["desktop", resolvedTheme, `accent-${profile.accent_color}`, `taskbar-align-${profile.taskbar_alignment}`, profile.window_transparency ? "" : "no-transparency", profile.animations_enabled && !profile.reduced_motion ? "" : "no-animations", profile.high_contrast ? "high-contrast" : "", profile.larger_text ? "larger-text" : "", profile.strong_active_borders ? "strong-active-borders" : "", profile.always_show_focus ? "always-show-focus" : ""].filter(Boolean).join(" ");
  const visibleToasts = profile.show_notifications ? toasts.filter((item) => (item.type !== "error" || profile.notification_errors) && (item.category !== "admin" || profile.notification_admin) && (item.category !== "transfer" || profile.notification_transfer)).slice(-profile.notification_limit) : [];
  const clockText = clock.toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit", second: profile.clock_show_seconds ? "2-digit" : undefined, hour12: profile.time_format === "12" });

  return <div className={rootClasses} style={rootStyle}>
    <main className="desktop-surface" style={wallpaperStyle(profile)} onPointerDown={(event) => { if (event.target === event.currentTarget) setSelectedShortcut(null); }}>
      {profile.show_desktop_shortcuts && <div className={`desktop-shortcuts shortcuts-${profile.desktop_shortcut_size}`} aria-label={t("desktop.shortcuts")}>{availableApps.filter((app) => pinned.has(app.id)).map((app) => <AppIcon key={app.id} label={t(app.labelKey)} icon={app.icon} selected={selectedShortcut === app.id} onSelect={() => setSelectedShortcut(app.id)} onOpen={() => openApp(app.id)} />)}</div>}
      {profile.show_welcome_widget && <div className="desktop-welcome"><span>WebNAS</span><strong>{t("desktop.welcome")}, {user.username}</strong><small>{t("desktop.welcomeHint")}</small></div>}
      <DesktopWidgets profile={profile} tasks={tasks} toasts={toasts} t={t} onSettingsChange={onSettingsChange} />
      {state.windows.filter((item) => !item.minimized).map((item) => <DesktopWindow key={item.id} window={item} active={state.activeId === item.id} animationsEnabled={profile.animations_enabled && !profile.reduced_motion} t={t} onFocus={() => dispatch({ type: "focus", id: item.id })} onClose={() => closeWindow(item)} onMinimize={() => dispatch({ type: "minimize", id: item.id })} onCommit={(rect, restoreRect) => dispatch({ type: "commit", id: item.id, rect, restoreRect })} onToggleMaximize={() => dispatch({ type: "toggleMaximize", id: item.id, viewport: { width: window.innerWidth, height: window.innerHeight } })}>{renderApp(item)}</DesktopWindow>)}
    </main>
    {launcherOpen && <AppLauncher apps={availableApps} pinned={pinned} profile={profile} t={t} onOpen={openApp} onTogglePin={togglePin} onLogout={signOut} onClose={() => setLauncherOpen(false)} />}
    <Taskbar apps={taskbarApps} pinned={pinned} windows={state.windows} activeId={state.activeId} profile={profile} resolvedTheme={resolvedTheme} clockText={clockText} dateText={dateText(clock, profile)} activeTransfers={activeTransfers} launcherOpen={launcherOpen} notificationsOpen={notificationsOpen} t={t} onToggleLauncher={() => { setNotificationsOpen(false); setLauncherOpen((value) => !value); }} onToggleNotifications={() => { setLauncherOpen(false); setNotificationsOpen((value) => !value); }} onToggleTheme={() => onTheme(resolvedTheme === "dark" ? "light" : "dark")} onApp={selectApp} onLogout={signOut} />
    {notificationsOpen && <aside ref={notificationRef} className="notification-center" aria-label={t("desktop.notifications")}><header><div><Bell /><strong>{t("desktop.notifications")}</strong></div><button type="button" aria-label={t("action.close")} onClick={() => setNotificationsOpen(false)}><X /></button></header>{visibleToasts.length === 0 && (!profile.notification_transfer || tasks.length === 0) ? <div className="empty-state">{t("desktop.noNotifications")}</div> : <>{visibleToasts.slice().reverse().map((item) => <article className={item.type} key={item.id} role={item.moduleId ? "button" : undefined} tabIndex={item.moduleId ? 0 : undefined} onClick={() => { if (!item.moduleId) return; openApp(item.moduleId === "samba" ? "samba" : "module", undefined, item.moduleId); setNotificationsOpen(false); }} onKeyDown={(event) => { if (item.moduleId && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); openApp(item.moduleId === "samba" ? "samba" : "module", undefined, item.moduleId); setNotificationsOpen(false); } }}><strong>{item.type === "error" ? t("status.error") : "WebNAS"}</strong><span>{item.text}</span></article>)}{profile.notification_transfer && tasks.slice(-profile.notification_limit).reverse().map((task) => <article key={task.id}><strong>{t(`transfers.${task.type}`)}</strong><span>{t(`task.${task.status}`)} · {Math.round(task.progress_percent ?? task.progress ?? 0)}%</span></article>)}</>}</aside>}
    <div className="toasts" role="status" aria-live="polite">{visibleToasts.map((item) => <div className={item.type} key={item.id}>{item.type === "error" && <ShieldCheck />}{item.text}</div>)}</div>
  </div>;
}
