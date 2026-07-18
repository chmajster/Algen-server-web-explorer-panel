import { ArrowRight, LayoutGrid, LogOut, Monitor, PanelBottom, Pin, Search, ShieldCheck, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { SettingsMe } from "../api";
import { ContextMenu, type ContextMenuItem } from "../components/ContextMenu";
import type { AppDefinition, AppId, RecentApp, Translate } from "./types";

type LauncherContext = { x: number; y: number; app: AppDefinition; portalTarget: Element | null };

export function AppLauncher({ apps, startPinned, desktopShortcuts, taskbarPinned, recentApps = [], profile, t, onOpen, onOpenProfile, onToggleStartPin, onToggleDesktopShortcut, onToggleTaskbarPin, onLogout, onClose }: {
  apps: AppDefinition[];
  startPinned: Set<AppId>;
  desktopShortcuts: Set<AppId>;
  taskbarPinned: Set<AppId>;
  recentApps?: RecentApp[];
  profile: SettingsMe;
  t: Translate;
  onOpen: (app: AppId) => void;
  onOpenProfile?: () => void;
  onToggleStartPin: (app: AppId) => void;
  onToggleDesktopShortcut: (app: AppId) => void;
  onToggleTaskbarPin: (app: AppId) => void;
  onLogout: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [context, setContext] = useState<LauncherContext | null>(null);
  const normalized = query.trim().toLocaleLowerCase(profile.language);
  const filtered = useMemo(() => apps.filter((app) => t(app.labelKey).toLocaleLowerCase(profile.language).includes(normalized)), [apps, normalized, profile.language, t]);
  const pinnedApps = filtered.filter((app) => startPinned.has(app.id));
  const recent = recentApps.map((item) => ({ item, app: apps.find((app) => app.id === item.id) })).filter((value): value is { item: RecentApp; app: AppDefinition } => Boolean(value.app)).slice(0, 4);
  const allVisible = showAll || Boolean(normalized);

  function relativeTime(timestamp: number) {
    const elapsed = Math.max(0, Date.now() - timestamp);
    if (elapsed < 60_000) return t("desktop.justNow");
    if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} min ${t("desktop.timeAgo")}`;
    if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)} h ${t("desktop.timeAgo")}`;
    return `${Math.floor(elapsed / 86_400_000)} d ${t("desktop.timeAgo")}`;
  }

  useEffect(() => {
    searchRef.current?.focus();
  }, []);
  useEffect(() => {
    function click(event: MouseEvent) {
      if (event.target instanceof Element && event.target.closest(".launcher-context-menu")) return;
      if (!ref.current?.contains(event.target as Node)) onClose();
    }
    function key(event: KeyboardEvent) { if (event.key === "Escape") { if (context) setContext(null); else onClose(); } }
    document.addEventListener("mousedown", click);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", click); document.removeEventListener("keydown", key); };
  }, [context, onClose]);

  function open(app: AppId) { setContext(null); onOpen(app); onClose(); }
  function contextItems(app: AppDefinition): ContextMenuItem[] {
    return [
      { label: t(desktopShortcuts.has(app.id) ? "desktop.removeFromDesktop" : "desktop.addToDesktop"), icon: <Monitor />, action: () => onToggleDesktopShortcut(app.id) },
      { label: t(startPinned.has(app.id) ? "desktop.unpinFromStart" : "desktop.pinToStart"), icon: <LayoutGrid />, action: () => onToggleStartPin(app.id) },
      { label: t(taskbarPinned.has(app.id) ? "taskbar.unpinFromTaskbar" : "taskbar.pinToTaskbar"), icon: <PanelBottom />, action: () => onToggleTaskbarPin(app.id) },
    ];
  }
  function appButton(app: AppDefinition, compact = false) {
    return <article className={`launcher-app ${app.admin ? "administrative" : ""} ${compact ? "compact" : ""}`} key={app.id}>
      <button className="launcher-open" type="button" onClick={() => open(app.id)} onContextMenu={compact ? (event) => { event.preventDefault(); event.stopPropagation(); setContext({ x: event.clientX, y: event.clientY, app, portalTarget: event.currentTarget.closest(".desktop") }); } : undefined}>{app.icon}<span>{t(app.labelKey)}</span>{app.admin && <small><ShieldCheck />{t("desktop.adminApp")}</small>}</button>
      <button className={`launcher-pin ${startPinned.has(app.id) ? "active" : ""}`} type="button" aria-label={`${startPinned.has(app.id) ? t("desktop.unpinFromStart") : t("desktop.pinToStart")} ${t(app.labelKey)}`} title={startPinned.has(app.id) ? t("desktop.unpinFromStart") : t("desktop.pinToStart")} onClick={() => onToggleStartPin(app.id)}><Pin /></button>
    </article>;
  }

  return <div ref={ref} className="app-launcher" role="dialog" aria-modal="false" aria-label={t("desktop.mainMenu")}>
    <div className="launcher-search"><Search /><input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("desktop.searchApps")} aria-label={t("desktop.searchApps")} />{query && <button type="button" aria-label={t("action.clear")} onClick={() => setQuery("")}><X /></button>}</div>
    {!allVisible && <><header className="launcher-section-title"><strong>{t("desktop.pinned")}</strong><button type="button" onClick={() => setShowAll(true)}>{t("desktop.allApps")}<ArrowRight /></button></header><div className="launcher-grid">{pinnedApps.map((app) => appButton(app))}</div><header className="launcher-section-title launcher-recent-title"><strong>{t("desktop.recentlyUsed")}</strong></header>{recent.length > 0 ? <div className="launcher-recent-list">{recent.map(({ item, app }) => <button type="button" key={app.id} onClick={() => open(app.id)}>{app.icon}<span><strong>{t(app.labelKey)}</strong><small>{relativeTime(item.usedAt)}</small></span></button>)}</div> : <p className="launcher-recent-empty">{t("desktop.noRecentApps")}</p>}</>}
    {allVisible && <><header className="launcher-section-title"><strong>{t("desktop.allApps")}</strong>{showAll && !normalized && <button type="button" onClick={() => setShowAll(false)}>{t("action.back")}</button>}</header><div className="launcher-list">{filtered.length > 0 ? filtered.map((app) => appButton(app, true)) : <p className="launcher-empty">{t("desktop.noAppsFound")}</p>}</div></>}
    <footer className="launcher-footer"><button className="launcher-profile" type="button" title={t("desktop.openUserSettings")} aria-label={`${t("desktop.openUserSettings")}: ${profile.username}`} onClick={() => { onOpenProfile?.(); onClose(); }}><UserRound /><span><strong>{profile.username}</strong><small>{profile.is_admin ? <><ShieldCheck />{t("desktop.administrator")}</> : t(`rbac.role.${profile.role}`)}</small></span></button><button className="launcher-logout" type="button" title={t("notify.logout")} aria-label={t("notify.logout")} onClick={onLogout}><LogOut /></button></footer>
    {context && <ContextMenu className="launcher-context-menu" portalTarget={context.portalTarget} x={context.x} y={context.y} items={contextItems(context.app)} onClose={() => setContext(null)} />}
  </div>;
}
