import { AlignCenter, AlignLeft, AppWindow, Bell, ChevronUp, Clock3, LayoutGrid, LogOut, Maximize2, Minimize2, Moon, Pin, PinOff, Settings2, Sun, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { SettingsMe } from "../api";
import { ContextMenu, type ContextMenuItem } from "../components/ContextMenu";
import type { AppDefinition, AppId, Translate, WindowInstance } from "./types";

export type TaskbarWindowAction = "focus" | "minimize" | "toggleMaximize" | "close";
type TaskbarContext = { x: number; y: number; app: AppDefinition | null };

export function Taskbar({ apps, pinned, windows, activeId, profile, resolvedTheme, clockText, dateText, activeTransfers, launcherOpen, notificationsOpen, t, onToggleLauncher, onToggleNotifications, onToggleTheme, onApp, onOpenNew, onTogglePin, onWindow, onCloseApp, onTaskbarSettings, onAlignment, onLogout }: {
  apps: AppDefinition[];
  pinned: Set<AppId>;
  windows: WindowInstance[];
  activeId: string;
  profile: SettingsMe;
  resolvedTheme: "light" | "dark";
  clockText: string;
  dateText: string;
  activeTransfers: number;
  launcherOpen: boolean;
  notificationsOpen: boolean;
  t: Translate;
  onToggleLauncher: () => void;
  onToggleNotifications: () => void;
  onToggleTheme: () => void;
  onApp: (app: AppId) => void;
  onOpenNew: (app: AppId) => void;
  onTogglePin: (app: AppId) => void;
  onWindow: (item: WindowInstance, action: TaskbarWindowAction) => void;
  onCloseApp: (app: AppId) => void;
  onTaskbarSettings: () => void;
  onAlignment: (alignment: "left" | "center") => void;
  onLogout: () => void;
}) {
  const [sessionOpen, setSessionOpen] = useState(false);
  const [context, setContext] = useState<TaskbarContext | null>(null);
  const sessionRef = useRef<HTMLDivElement>(null);
  const visibleApps = useMemo(() => {
    const byId = new Map(apps.map((app) => [app.id, app]));
    const result: AppDefinition[] = [];
    const seen = new Set<AppId>();
    for (const id of pinned) {
      const app = byId.get(id);
      if (app && !app.hidden && !seen.has(id)) { result.push(app); seen.add(id); }
    }
    for (const item of [...windows].sort((left, right) => left.zIndex - right.zIndex)) {
      const app = byId.get(item.app);
      if (app && !seen.has(app.id)) { result.push(app); seen.add(app.id); }
    }
    return result;
  }, [apps, pinned, windows]);
  const activeWindow = windows.find((item) => item.id === activeId);

  useEffect(() => {
    function close(event: MouseEvent) { if (!sessionRef.current?.contains(event.target as Node)) setSessionOpen(false); }
    function key(event: KeyboardEvent) { if (event.key === "Escape") setSessionOpen(false); }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", key); };
  }, []);

  function appMenu(app: AppDefinition): ContextMenuItem[] {
    const appWindows = windows.filter((item) => item.app === app.id).sort((left, right) => right.zIndex - left.zIndex);
    const single = appWindows.length === 1 ? appWindows[0] : null;
    const items: ContextMenuItem[] = [];
    if (!app.hidden) items.push({ label: t("taskbar.openNewWindow"), icon: <AppWindow />, action: () => onOpenNew(app.id) });
    if (appWindows.length > 1) {
      appWindows.forEach((item, index) => items.push({ label: item.moduleId ? `${t(app.labelKey)} — ${item.moduleId}` : `${t(app.labelKey)} (${appWindows.length - index})`, icon: app.icon, action: () => onWindow(item, "focus") }));
      items.push({ label: t("taskbar.minimizeAll"), icon: <Minimize2 />, separator: true, action: () => appWindows.forEach((item) => onWindow(item, "minimize")) });
    } else if (single) {
      items.push({ label: t("taskbar.showWindow"), icon: <AppWindow />, disabled: !single.minimized && activeId === single.id, action: () => onWindow(single, "focus") });
      items.push({ label: t("window.minimize"), icon: <Minimize2 />, disabled: single.minimized, action: () => onWindow(single, "minimize") });
      items.push({ label: t(single.restoreRect ? "window.restore" : "window.maximize"), icon: <Maximize2 />, action: () => onWindow(single, "toggleMaximize") });
    }
    if (!app.hidden) items.push({ label: t(pinned.has(app.id) ? "taskbar.unpinFromTaskbar" : "taskbar.pinToTaskbar"), icon: pinned.has(app.id) ? <PinOff /> : <Pin />, separator: true, action: () => onTogglePin(app.id) });
    if (appWindows.length > 0) items.push({ label: t(appWindows.length > 1 ? "taskbar.closeAllWindows" : "taskbar.closeWindow"), icon: <X />, danger: true, separator: app.hidden, action: () => onCloseApp(app.id) });
    items.push({ label: t("taskbar.settings"), icon: <Settings2 />, separator: true, action: onTaskbarSettings });
    return items;
  }

  function taskbarMenu(): ContextMenuItem[] {
    return [
      { label: `${profile.taskbar_alignment === "left" ? "✓ " : ""}${t("settings.alignLeft")}`, icon: <AlignLeft />, action: () => onAlignment("left") },
      { label: `${profile.taskbar_alignment === "center" ? "✓ " : ""}${t("settings.alignCenter")}`, icon: <AlignCenter />, action: () => onAlignment("center") },
      { label: t("taskbar.settings"), icon: <Settings2 />, separator: true, action: onTaskbarSettings },
    ];
  }

  return <footer className={`taskbar taskbar-${profile.taskbar_alignment}`} aria-label={t("desktop.taskbar")} onContextMenu={(event) => { event.preventDefault(); setContext({ x: event.clientX, y: event.clientY, app: null }); }}>
    <div className="taskbar-primary">
      <button className={`taskbar-start ${launcherOpen ? "active" : ""}`} type="button" title={t("desktop.mainMenu")} aria-label={t("desktop.mainMenu")} aria-expanded={launcherOpen} onClick={onToggleLauncher}><LayoutGrid /></button>
      <div className="taskbar-items" aria-label={t("desktop.runningApps")}>
        {visibleApps.map((app) => {
          const appWindows = windows.filter((item) => item.app === app.id);
          const running = appWindows.length > 0;
          const active = activeWindow?.app === app.id && !activeWindow.minimized;
          const minimized = running && appWindows.every((item) => item.minimized);
          return <button key={app.id} type="button" className={`${pinned.has(app.id) ? "pinned" : ""} ${active ? "active" : ""} ${running ? "running" : ""} ${minimized ? "minimized" : ""}`} title={t(app.labelKey)} aria-label={t(app.labelKey)} aria-pressed={active} onClick={() => onApp(app.id)} onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); setContext({ x: event.clientX, y: event.clientY, app }); }}>
            {app.icon}<span>{t(app.labelKey)}</span>{running && <i aria-hidden="true" />}{appWindows.length > 1 && <b aria-label={`${t("taskbar.windowCount")}: ${appWindows.length}`}>{appWindows.length}</b>}
          </button>;
        })}
      </div>
    </div>
    <div className="system-tray">
      {profile.show_transfer_indicator && <button className="transfer-indicator" type="button" title={t("transfers.title")} aria-label={`${t("transfers.title")}: ${activeTransfers}`} onClick={() => onApp("transfers")}><Clock3 />{activeTransfers > 0 && <b>{activeTransfers}</b>}</button>}
      {profile.show_notifications && <button className={notificationsOpen ? "active" : ""} type="button" title={t("desktop.notifications")} aria-label={t("desktop.notifications")} aria-expanded={notificationsOpen} onClick={onToggleNotifications}><Bell /></button>}
      <button type="button" title={t("notify.theme")} aria-label={t("notify.theme")} onClick={onToggleTheme}>{resolvedTheme === "dark" ? <Sun /> : <Moon />}</button>
      <div ref={sessionRef} className="session-menu-wrap">
        <button className={`taskbar-user ${sessionOpen ? "active" : ""}`} type="button" aria-label={t("desktop.sessionMenu")} aria-expanded={sessionOpen} onClick={() => setSessionOpen((value) => !value)}><UserRound /><span>{profile.username}</span><ChevronUp /></button>
        {sessionOpen && <div className="session-menu" role="menu"><header><UserRound /><span><strong>{profile.username}</strong><small>{profile.is_admin ? t("desktop.administrator") : t("desktop.standardUser")}</small></span></header><button type="button" role="menuitem" onClick={onLogout}><LogOut />{t("notify.logout")}</button></div>}
      </div>
      <time className="system-clock" dateTime={new Date().toISOString()}><span>{clockText}</span><small>{dateText}</small></time>
    </div>
    {context && <ContextMenu x={context.x} y={context.y} items={context.app ? appMenu(context.app) : taskbarMenu()} onClose={() => setContext(null)} />}
  </footer>;
}
