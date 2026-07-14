import { Bell, Clock3, LogOut, Menu, Moon, Sun, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { logout, type SettingsMe, type Task } from "../api";
import { AppIcon } from "../components/AppIcon";
import { FileManager } from "../features/files/FileManager";
import { GroupsApp, LogsAppView, MonitorApp, MountsApp, SambaAppView, ServicesApp, SettingsAppView, StoreAppView, UsersApp } from "../features/admin/SystemApps";
import { forgetAdminPassword } from "../features/admin/adminCredentials";
import { TransferCenter } from "../features/transfers/TransferCenter";
import type { UploadControls } from "../features/transfers/useUploadManager";
import type { Language } from "../i18n";
import { AppLauncher } from "./AppLauncher";
import { apps } from "./catalog";
import { DesktopWindow } from "./DesktopWindow";
import { Taskbar } from "./Taskbar";
import type { AppId, Theme, Toast, ToastFn, Translate, User, WindowInstance } from "./types";
import { initialWindowState, restoreWindowState, windowReducer } from "./windowState";

export function Desktop({ user, profile, language, theme, tasks, uploadControls, toasts, t, toast, onLanguage, onTheme, onLoggedOut }: {
  user: User;
  profile: SettingsMe;
  language: Language;
  theme: Theme;
  tasks: Task[];
  uploadControls: UploadControls;
  toasts: Toast[];
  t: Translate;
  toast: ToastFn;
  onLanguage: (language: Language) => void;
  onTheme: (theme: Theme) => void;
  onLoggedOut: () => void;
}) {
  const storageKey = `webnas_windows_${user.username}`;
  const [state, dispatch] = useReducer(windowReducer, initialWindowState);
  const [launcherOpen, setLauncherOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [pinned, setPinned] = useState<Set<AppId>>(() => new Set(JSON.parse(localStorage.getItem("webnas_pinned_apps") || '["files","transfers","monitor","settings"]')));
  const [clock, setClock] = useState(new Date());
  const restored = useRef(false);
  const availableApps = useMemo(() => apps.filter((app) => !app.admin || profile.is_admin), [profile.is_admin]);
  const resolvedTheme = theme === "system" ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : theme;
  const activeTransfers = tasks.filter((task) => ["queued", "running", "paused"].includes(task.status)).length;

  useEffect(() => {
    dispatch({ type: "hydrate", state: profile.startup_windows === "last" ? restoreWindowState(localStorage.getItem(storageKey)) : initialWindowState });
    restored.current = true;
  }, [profile.startup_windows, storageKey]);
  useEffect(() => {
    if (!restored.current) return;
    const timer = setTimeout(() => localStorage.setItem(storageKey, JSON.stringify(state)), 240);
    return () => clearTimeout(timer);
  }, [state, storageKey]);
  useEffect(() => { const timer = setInterval(() => setClock(new Date()), 30000); return () => clearInterval(timer); }, []);
  function openApp(app: AppId, initialPath?: string) { dispatch({ type: "open", app, initialPath, viewport: { width: window.innerWidth, height: window.innerHeight } }); }
  function selectTask(item: WindowInstance) {
    if (state.activeId === item.id && !item.minimized) dispatch({ type: "minimize", id: item.id });
    else dispatch({ type: "focus", id: item.id });
  }
  function togglePin(app: AppId) {
    setPinned((current) => { const next = new Set(current); if (next.has(app)) next.delete(app); else next.add(app); localStorage.setItem("webnas_pinned_apps", JSON.stringify([...next])); return next; });
  }
  function renderApp(item: WindowInstance) {
    switch (item.app) {
      case "files": return <FileManager homePath={user.home} initialPath={item.initialPath} tasks={tasks} isAdmin={profile.is_admin} t={t} toast={toast} onUpload={uploadControls.add} onOpenFolderWindow={(path) => openApp("files", path)} onShareSamba={() => openApp("samba")} />;
      case "transfers": return <TransferCenter tasks={tasks} t={t} toast={toast} uploadControls={uploadControls} />;
      case "users": return <UsersApp t={t} toast={toast} />;
      case "groups": return <GroupsApp t={t} toast={toast} />;
      case "mounts": return <MountsApp t={t} toast={toast} />;
      case "samba": return <SambaAppView t={t} toast={toast} />;
      case "services": return <ServicesApp t={t} toast={toast} />;
      case "store": return <StoreAppView t={t} toast={toast} />;
      case "logs": return <LogsAppView t={t} />;
      case "settings": return <SettingsAppView language={language} theme={theme} t={t} toast={toast} onLanguage={onLanguage} onTheme={onTheme} />;
      case "monitor": return <MonitorApp t={t} />;
    }
  }

  return <div className={`desktop ${resolvedTheme}`}>
    <header className="system-bar">
      <button className={`main-menu-button ${launcherOpen ? "active" : ""}`} type="button" aria-label={t("desktop.mainMenu")} aria-expanded={launcherOpen} onClick={() => setLauncherOpen((value) => !value)}><Menu /><strong>WebNAS</strong></button>
      <div className="system-bar-center"><span>{t("desktop.workspace")}</span></div>
      <div className="system-tray">
        <button className="transfer-indicator" title={t("transfers.title")} onClick={() => openApp("transfers")}><Clock3 />{activeTransfers > 0 && <b>{activeTransfers}</b>}</button>
        <button title={t("desktop.notifications")} aria-expanded={notificationsOpen} onClick={() => setNotificationsOpen((value) => !value)}><Bell />{toasts.length > 0 && <i />}</button>
        <button title={t("notify.theme")} onClick={() => onTheme(resolvedTheme === "dark" ? "light" : "dark")}>{resolvedTheme === "dark" ? <Sun /> : <Moon />}</button>
        <span className="system-clock">{clock.toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" })}<small>{clock.toLocaleDateString(language, { day: "2-digit", month: "short" })}</small></span>
        <span className="current-user"><UserRound /><span>{user.username}</span></span>
        <button title={t("notify.logout")} onClick={() => logout().finally(() => { forgetAdminPassword(); onLoggedOut(); })}><LogOut /></button>
      </div>
    </header>
    {launcherOpen && <AppLauncher apps={availableApps} pinned={pinned} t={t} onOpen={openApp} onTogglePin={togglePin} onClose={() => setLauncherOpen(false)} />}
    <main className="desktop-surface">
      <div className="desktop-shortcuts" aria-label={t("desktop.shortcuts")}>{availableApps.filter((app) => pinned.has(app.id)).map((app) => <AppIcon key={app.id} label={t(app.labelKey)} icon={app.icon} onOpen={() => openApp(app.id)} />)}</div>
      <div className="desktop-welcome"><span>WebNAS</span><strong>{t("desktop.welcome")}, {user.username}</strong><small>{t("desktop.welcomeHint")}</small></div>
      {state.windows.filter((item) => !item.minimized).map((item) => <DesktopWindow key={item.id} window={item} active={state.activeId === item.id} t={t} onFocus={() => dispatch({ type: "focus", id: item.id })} onClose={() => dispatch({ type: "close", id: item.id })} onMinimize={() => dispatch({ type: "minimize", id: item.id })} onCommit={(rect, restoreRect) => dispatch({ type: "commit", id: item.id, rect, restoreRect })} onToggleMaximize={() => dispatch({ type: "toggleMaximize", id: item.id, viewport: { width: window.innerWidth, height: window.innerHeight } })}>{renderApp(item)}</DesktopWindow>)}
    </main>
    <Taskbar windows={state.windows} activeId={state.activeId} t={t} onSelect={selectTask} />
    {notificationsOpen && <aside className="notification-center"><header><strong>{t("desktop.notifications")}</strong><button onClick={() => setNotificationsOpen(false)}><X /></button></header>{toasts.length === 0 && tasks.length === 0 ? <div className="empty-state">{t("desktop.noNotifications")}</div> : <>{toasts.slice().reverse().map((item) => <article className={item.type} key={item.id}>{item.text}</article>)}{tasks.slice(-5).reverse().map((task) => <article key={task.id}><strong>{t(`transfers.${task.type}`)}</strong><span>{t(`task.${task.status}`)} · {Math.round(task.progress_percent ?? task.progress ?? 0)}%</span></article>)}</>}</aside>}
    <div className="toasts" role="status" aria-live="polite">{toasts.map((item) => <div className={item.type} key={item.id}>{item.text}</div>)}</div>
  </div>;
}
