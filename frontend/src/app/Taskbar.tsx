import { Bell, ChevronUp, Clock3, LayoutGrid, LogOut, Moon, Sun, UserRound } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { SettingsMe } from "../api";
import type { AppDefinition, AppId, Translate, WindowInstance } from "./types";

export function Taskbar({ apps, pinned, windows, activeId, profile, resolvedTheme, clockText, dateText, activeTransfers, launcherOpen, notificationsOpen, t, onToggleLauncher, onToggleNotifications, onToggleTheme, onApp, onLogout }: {
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
  onLogout: () => void;
}) {
  const [sessionOpen, setSessionOpen] = useState(false);
  const sessionRef = useRef<HTMLDivElement>(null);
  const visibleApps = useMemo(() => apps.filter((app) => (!app.hidden && pinned.has(app.id)) || windows.some((item) => item.app === app.id)), [apps, pinned, windows]);
  const activeWindow = windows.find((item) => item.id === activeId);

  useEffect(() => {
    function close(event: MouseEvent) { if (!sessionRef.current?.contains(event.target as Node)) setSessionOpen(false); }
    function key(event: KeyboardEvent) { if (event.key === "Escape") setSessionOpen(false); }
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", key); };
  }, []);

  return <footer className={`taskbar taskbar-${profile.taskbar_alignment}`} aria-label={t("desktop.taskbar")}>
    <div className="taskbar-primary">
      <button className={`taskbar-start ${launcherOpen ? "active" : ""}`} type="button" title={t("desktop.mainMenu")} aria-label={t("desktop.mainMenu")} aria-expanded={launcherOpen} onClick={onToggleLauncher}><LayoutGrid /></button>
      <div className="taskbar-items" aria-label={t("desktop.runningApps")}>
        {visibleApps.map((app) => {
          const appWindows = windows.filter((item) => item.app === app.id);
          const running = appWindows.length > 0;
          const active = activeWindow?.app === app.id && !activeWindow.minimized;
          return <button key={app.id} type="button" className={`${active ? "active" : ""} ${running ? "running" : ""}`} title={t(app.labelKey)} aria-label={t(app.labelKey)} aria-pressed={active} onClick={() => onApp(app.id)}>
            {app.icon}<span>{t(app.labelKey)}</span>{running && <i aria-hidden="true" />}{appWindows.length > 1 && <b>{appWindows.length}</b>}
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
  </footer>;
}
