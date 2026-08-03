import { AlignCenter, AlignLeft, AppWindow, Bell, ChevronUp, Clock3, LayoutGrid, ListTodo, LogOut, Maximize2, Minimize2, Moon, Pin, PinOff, Power, Settings2, Sun, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import type { SettingsMe } from "../api";
import { ContextMenu, type ContextMenuItem } from "../components/ContextMenu";
import type { AppDefinition, AppId, Translate, WindowInstance } from "./types";

export type TaskbarWindowAction = "focus" | "minimize" | "toggleMaximize" | "close";
type TaskbarContext = { x: number; y: number; app: AppDefinition | null; moduleId?: string; portalTarget: Element | null };
type TaskbarItem = { key: string; app: AppDefinition; moduleId?: string };

export function Taskbar({ apps, pinned, pinnedModules, moduleNames, windows, activeId, profile, resolvedTheme, clockText, dateText, clockDateTime, activeTransfers, activeActions, launcherOpen, notificationsOpen, actionsOpen, calendarOpen, actionButtonRef, clockButtonRef, t, onToggleLauncher, onToggleNotifications, onToggleActions, onToggleCalendar, onOpenLocalPanel, onToggleTheme, onApp, onModule, onOpenNew, onOpenModuleNew, onTogglePin, onToggleModulePin, onWindow, onCloseApp, onCloseModule, onTaskbarSettings, onAlignment, onShutdown, onLogout }: {
  apps: AppDefinition[];
  pinned: Set<AppId>;
  pinnedModules: Set<string>;
  moduleNames: Map<string, string>;
  windows: WindowInstance[];
  activeId: string;
  profile: SettingsMe;
  resolvedTheme: "light" | "dark";
  clockText: string;
  dateText: string;
  clockDateTime: string;
  activeTransfers: number;
  activeActions: number;
  launcherOpen: boolean;
  notificationsOpen: boolean;
  actionsOpen: boolean;
  calendarOpen: boolean;
  actionButtonRef: RefObject<HTMLButtonElement>;
  clockButtonRef: RefObject<HTMLButtonElement>;
  t: Translate;
  onToggleLauncher: () => void;
  onToggleNotifications: () => void;
  onToggleActions: () => void;
  onToggleCalendar: () => void;
  onOpenLocalPanel: () => void;
  onToggleTheme: () => void;
  onApp: (app: AppId) => void;
  onModule: (moduleId: string) => void;
  onOpenNew: (app: AppId) => void;
  onOpenModuleNew: (moduleId: string) => void;
  onTogglePin: (app: AppId) => void;
  onToggleModulePin: (moduleId: string) => void;
  onWindow: (item: WindowInstance, action: TaskbarWindowAction) => void;
  onCloseApp: (app: AppId) => void;
  onCloseModule: (moduleId: string) => void;
  onTaskbarSettings: () => void;
  onAlignment: (alignment: "left" | "center") => void;
  onShutdown?: () => void;
  onLogout: () => void;
}) {
  const [sessionOpen, setSessionOpen] = useState(false);
  const [context, setContext] = useState<TaskbarContext | null>(null);
  const sessionRef = useRef<HTMLDivElement>(null);
  const visibleItems = useMemo(() => {
    const byId = new Map(apps.map((app) => [app.id, app]));
    const result: TaskbarItem[] = [];
    const seen = new Set<string>();
    for (const id of pinned) {
      const app = byId.get(id);
      if (app && !app.hidden && !seen.has(id)) { result.push({ key: id, app }); seen.add(id); }
    }
    const moduleApp = byId.get("module");
    if (moduleApp) {
      for (const moduleId of pinnedModules) {
        const key = `module:${moduleId}`;
        if (moduleNames.has(moduleId) && !seen.has(key)) { result.push({ key, app: moduleApp, moduleId }); seen.add(key); }
      }
    }
    for (const item of [...windows].sort((left, right) => left.zIndex - right.zIndex)) {
      const app = byId.get(item.app);
      const key = item.app === "module" && item.moduleId ? `module:${item.moduleId}` : item.app;
      if (app && !seen.has(key)) { result.push({ key, app, moduleId: item.app === "module" ? item.moduleId : undefined }); seen.add(key); }
    }
    return result;
  }, [apps, moduleNames, pinned, pinnedModules, windows]);
  const activeWindow = windows.find((item) => item.id === activeId);

  useEffect(() => {
    function close(event: MouseEvent) { if (!sessionRef.current?.contains(event.target as Node)) setSessionOpen(false); }
    function key(event: KeyboardEvent) { if (event.key === "Escape") setSessionOpen(false); }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", key); };
  }, []);
  useEffect(() => {
    if (!launcherOpen && !notificationsOpen && !actionsOpen && !calendarOpen) return;
    setSessionOpen(false);
    setContext(null);
  }, [actionsOpen, calendarOpen, launcherOpen, notificationsOpen]);

  function openContext(value: TaskbarContext) {
    onOpenLocalPanel();
    setSessionOpen(false);
    setContext(value);
  }

  function appMenu(app: AppDefinition, moduleId?: string): ContextMenuItem[] {
    const appWindows = windows.filter((item) => item.app === app.id && (!moduleId || item.moduleId === moduleId)).sort((left, right) => right.zIndex - left.zIndex);
    const single = appWindows.length === 1 ? appWindows[0] : null;
    const items: ContextMenuItem[] = [];
    const pinnable = !app.hidden || Boolean(moduleId);
    const isPinned = moduleId ? pinnedModules.has(moduleId) : pinned.has(app.id);
    if (pinnable) items.push({ label: t("taskbar.openNewWindow"), icon: <AppWindow />, action: () => moduleId ? onOpenModuleNew(moduleId) : onOpenNew(app.id) });
    if (appWindows.length > 1) {
      appWindows.forEach((item, index) => items.push({ label: moduleId ? `${moduleLabel(moduleId)} (${appWindows.length - index})` : `${t(app.labelKey)} (${appWindows.length - index})`, icon: app.icon, action: () => onWindow(item, "focus") }));
      items.push({ label: t("taskbar.minimizeAll"), icon: <Minimize2 />, separator: true, action: () => appWindows.forEach((item) => onWindow(item, "minimize")) });
    } else if (single) {
      items.push({ label: t("taskbar.showWindow"), icon: <AppWindow />, disabled: !single.minimized && activeId === single.id, action: () => onWindow(single, "focus") });
      items.push({ label: t("window.minimize"), icon: <Minimize2 />, disabled: single.minimized, action: () => onWindow(single, "minimize") });
      items.push({ label: t(single.restoreRect ? "window.restore" : "window.maximize"), icon: <Maximize2 />, action: () => onWindow(single, "toggleMaximize") });
    }
    if (pinnable) items.push({ label: t(isPinned ? "taskbar.unpinFromTaskbar" : "taskbar.pinToTaskbar"), icon: isPinned ? <PinOff /> : <Pin />, separator: true, action: () => moduleId ? onToggleModulePin(moduleId) : onTogglePin(app.id) });
    if (appWindows.length > 0) items.push({ label: t(appWindows.length > 1 ? "taskbar.closeAllWindows" : "taskbar.closeWindow"), icon: <X />, danger: true, separator: app.hidden, action: () => moduleId ? onCloseModule(moduleId) : onCloseApp(app.id) });
    items.push({ label: t("taskbar.settings"), icon: <Settings2 />, separator: true, action: onTaskbarSettings });
    return items;
  }

  function moduleLabel(moduleId: string) {
    return moduleNames.get(moduleId) || moduleId.split("-").map((part) => part ? part[0].toUpperCase() + part.slice(1) : part).join(" ");
  }

  function taskbarMenu(): ContextMenuItem[] {
    return [
      { label: `${profile.taskbar_alignment === "left" ? "✓ " : ""}${t("settings.alignLeft")}`, icon: <AlignLeft />, action: () => onAlignment("left") },
      { label: `${profile.taskbar_alignment === "center" ? "✓ " : ""}${t("settings.alignCenter")}`, icon: <AlignCenter />, action: () => onAlignment("center") },
      { label: t("taskbar.settings"), icon: <Settings2 />, separator: true, action: onTaskbarSettings },
    ];
  }

  return <footer className={`taskbar taskbar-${profile.taskbar_alignment}`} aria-label={t("desktop.taskbar")} onContextMenu={(event) => { event.preventDefault(); openContext({ x: event.clientX, y: event.clientY, app: null, portalTarget: event.currentTarget.parentElement }); }}>
    <div className="taskbar-primary">
      <button className={`taskbar-start ${launcherOpen ? "active" : ""}`} type="button" title={t("desktop.mainMenu")} aria-label={t("desktop.mainMenu")} aria-expanded={launcherOpen} onClick={onToggleLauncher}><LayoutGrid /></button>
      <div className="taskbar-items" aria-label={t("desktop.runningApps")}>
        {visibleItems.map(({ key, app, moduleId }) => {
          const appWindows = windows.filter((item) => item.app === app.id && (!moduleId || item.moduleId === moduleId));
          const running = appWindows.length > 0;
          const active = activeWindow?.app === app.id && (!moduleId || activeWindow.moduleId === moduleId) && !activeWindow.minimized;
          const minimized = running && appWindows.every((item) => item.minimized);
          const label = moduleId ? moduleLabel(moduleId) : t(app.labelKey);
          const itemPinned = moduleId ? pinnedModules.has(moduleId) : pinned.has(app.id);
          return <button key={key} type="button" className={`${itemPinned ? "pinned" : ""} ${active ? "active" : ""} ${running ? "running" : ""} ${minimized ? "minimized" : ""}`} title={label} aria-label={label} aria-pressed={active} onClick={() => moduleId ? onModule(moduleId) : onApp(app.id)} onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); openContext({ x: event.clientX, y: event.clientY, app, moduleId, portalTarget: event.currentTarget.closest(".taskbar")?.parentElement ?? null }); }}>
            {app.icon}<span>{label}</span>{running && <i aria-hidden="true" />}{appWindows.length > 1 && <b aria-label={`${t("taskbar.windowCount")}: ${appWindows.length}`}>{appWindows.length}</b>}
          </button>;
        })}
      </div>
    </div>
    <div className="system-tray">
      {profile.show_transfer_indicator && <button className="transfer-indicator" type="button" title={t("transfers.title")} aria-label={`${t("transfers.title")}: ${activeTransfers}`} onClick={() => onApp("transfers")}><Clock3 />{activeTransfers > 0 && <b>{activeTransfers}</b>}</button>}
      {profile.show_background_actions_indicator && <button ref={actionButtonRef} className={`actions-indicator ${actionsOpen ? "active" : ""}`} type="button" title={t("actions.title")} aria-label={`${t("actions.title")}: ${activeActions}`} aria-expanded={actionsOpen} aria-controls="actions-center" onClick={() => { setSessionOpen(false); setContext(null); onToggleActions(); }}><ListTodo />{activeActions > 0 && <b>{activeActions > 99 ? "99+" : activeActions}</b>}</button>}
      {profile.show_notifications && <button className={notificationsOpen ? "active" : ""} type="button" title={t("desktop.notifications")} aria-label={t("desktop.notifications")} aria-expanded={notificationsOpen} onClick={onToggleNotifications}><Bell /></button>}
      <button className="theme-toggle" type="button" title={t("notify.theme")} aria-label={t("notify.theme")} onClick={onToggleTheme}>{resolvedTheme === "dark" ? <Sun /> : <Moon />}</button>
      <div ref={sessionRef} className="session-menu-wrap">
        <button className={`taskbar-user ${sessionOpen ? "active" : ""}`} type="button" aria-label={t("desktop.sessionMenu")} aria-expanded={sessionOpen} onClick={() => { setContext(null); if (!sessionOpen) onOpenLocalPanel(); setSessionOpen((value) => !value); }}><UserRound /><span>{profile.username}</span><ChevronUp /></button>
        {sessionOpen && <div className="session-menu" role="menu"><header><UserRound /><span><strong>{profile.username}</strong><small>{profile.is_admin ? t("desktop.administrator") : t("desktop.standardUser")}</small></span></header>{onShutdown && <button type="button" role="menuitem" onClick={onShutdown}><Power />{t("shutdown.button")}</button>}<button type="button" role="menuitem" onClick={onLogout}><LogOut />{t("notify.logout")}</button></div>}
      </div>
      <button
        ref={clockButtonRef}
        className={`system-clock ${calendarOpen ? "active" : ""}`}
        type="button"
        title={t("calendar.open")}
        aria-label={t("calendar.open")}
        aria-expanded={calendarOpen}
        aria-controls="calendar-flyout"
        onClick={() => {
          setSessionOpen(false);
          setContext(null);
          onToggleCalendar();
        }}
      >
        <time dateTime={clockDateTime}><span>{clockText}</span><small>{dateText}</small></time>
      </button>
    </div>
    {context && <ContextMenu className="taskbar-context-menu" portalTarget={context.portalTarget} x={context.x} y={context.y} items={context.app ? appMenu(context.app, context.moduleId) : taskbarMenu()} onClose={() => setContext(null)} />}
  </footer>;
}
