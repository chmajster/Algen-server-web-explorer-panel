import { ArrowRight, LayoutGrid, LoaderCircle, LogOut, Monitor, PanelBottom, Pin, Power, RefreshCw, RotateCcw, Search, ShieldCheck, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type SettingsMe } from "../api";
import { ContextMenu, type ContextMenuItem } from "../components/ContextMenu";
import { powerClient } from "../modules/power/api/client";
import type { AppDefinition, AppId, RecentApp, Translate } from "./types";
import "./app-launcher-power.css";
import "./app-launcher-shortcuts.css";

type LauncherContext = { x: number; y: number; app: AppDefinition; portalTarget: Element | null };

function isExpectedRestartDisconnect(error: unknown) {
  return error instanceof TypeError || (error instanceof ApiError && [502, 504].includes(error.status));
}

export function AppLauncher({ apps, startPinned, desktopShortcuts, taskbarPinned, recentApps = [], profile, t, onOpen, onOpenProfile, onToggleStartPin, onToggleDesktopShortcut, onToggleTaskbarPin, onShutdown, onRestart, onRestartApplication, onLogout, onClose }: {
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
  onShutdown?: () => void;
  onRestart?: () => void;
  onRestartApplication?: () => Promise<void>;
  onLogout: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const powerActionsRef = useRef<HTMLDivElement>(null);
  const powerMenuRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [context, setContext] = useState<LauncherContext | null>(null);
  const [powerMenuOpen, setPowerMenuOpen] = useState(false);
  const [powerBusy, setPowerBusy] = useState<"application" | null>(null);
  const [powerError, setPowerError] = useState("");
  const [installedModules, setInstalledModules] = useState<Set<string> | null>(null);
  const [renderedAt] = useState(() => Date.now());
  const normalized = query.trim().toLocaleLowerCase(profile.language);
  const installedApps = useMemo(
    () => apps.filter((app) => !app.moduleId || installedModules?.has(app.moduleId)),
    [apps, installedModules],
  );
  const filtered = useMemo(() => installedApps.filter((app) => t(app.labelKey).toLocaleLowerCase(profile.language).includes(normalized)), [installedApps, normalized, profile.language, t]);
  const alphabeticalApps = useMemo(() => {
    const collator = new Intl.Collator(profile.language, { sensitivity: "base", numeric: true });
    return [...filtered].sort((first, second) => collator.compare(t(first.labelKey), t(second.labelKey)) || first.id.localeCompare(second.id));
  }, [filtered, profile.language, t]);
  const pinnedApps = filtered.filter((app) => startPinned.has(app.id));
  const recent = recentApps.map((item) => ({ item, app: installedApps.find((app) => app.id === item.id) })).filter((value): value is { item: RecentApp; app: AppDefinition } => Boolean(value.app)).slice(0, 4);
  const allVisible = showAll || Boolean(normalized);
  const canRestartApplication = profile.permissions.includes("system.restart");

  function relativeTime(timestamp: number) {
    const elapsed = Math.max(0, renderedAt - timestamp);
    if (elapsed < 60_000) return t("desktop.justNow");
    if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} min ${t("desktop.timeAgo")}`;
    if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)} h ${t("desktop.timeAgo")}`;
    return `${Math.floor(elapsed / 86_400_000)} d ${t("desktop.timeAgo")}`;
  }

  useEffect(() => {
    searchRef.current?.focus();
  }, []);
  useEffect(() => {
    let active = true;
    let loading = false;
    const refreshInstalledModules = async () => {
      if (loading) return;
      loading = true;
      try {
        const modules = await api.modules();
        if (active) setInstalledModules(new Set(modules.filter((item) => item.state.installed).map((item) => item.id)));
      } catch {
        // Fail closed: an unverified managed module must not be exposed in Start.
      } finally {
        loading = false;
      }
    };
    const changed = () => { void refreshInstalledModules(); };
    void refreshInstalledModules();
    window.addEventListener("webnas:modules-changed", changed);
    return () => { active = false; window.removeEventListener("webnas:modules-changed", changed); };
  }, []);
  useEffect(() => {
    function click(event: MouseEvent) {
      if (event.target instanceof Element && event.target.closest(".launcher-context-menu")) return;
      if (powerMenuOpen && !powerActionsRef.current?.contains(event.target as Node)) setPowerMenuOpen(false);
      if (!ref.current?.contains(event.target as Node)) onClose();
    }
    function key(event: KeyboardEvent) { if (event.key === "Escape") { if (powerMenuOpen) setPowerMenuOpen(false); else if (context) setContext(null); else onClose(); } }
    document.addEventListener("mousedown", click);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", click); document.removeEventListener("keydown", key); };
  }, [context, onClose, powerMenuOpen]);
  useEffect(() => {
    if (powerMenuOpen) powerMenuRef.current?.querySelector<HTMLButtonElement>("button")?.focus({ preventScroll: true });
  }, [powerMenuOpen]);

  function open(app: AppId) { setContext(null); onOpen(app); onClose(); }
  function showContext(event: React.MouseEvent<HTMLElement>, app: AppDefinition) {
    event.preventDefault();
    event.stopPropagation();
    setContext({ x: event.clientX, y: event.clientY, app, portalTarget: event.currentTarget.closest(".desktop") });
  }
  function contextItems(app: AppDefinition): ContextMenuItem[] {
    return [
      { label: t(desktopShortcuts.has(app.id) ? "desktop.removeFromDesktop" : "desktop.addToDesktop"), icon: <Monitor />, action: () => onToggleDesktopShortcut(app.id) },
      { label: t(startPinned.has(app.id) ? "desktop.unpinFromStart" : "desktop.pinToStart"), icon: <LayoutGrid />, action: () => onToggleStartPin(app.id) },
      { label: t(taskbarPinned.has(app.id) ? "taskbar.unpinFromTaskbar" : "taskbar.pinToTaskbar"), icon: <PanelBottom />, action: () => onToggleTaskbarPin(app.id) },
    ];
  }
  function appButton(app: AppDefinition, compact = false) {
    const onDesktop = desktopShortcuts.has(app.id);
    const desktopLabel = t(onDesktop ? "desktop.removeFromDesktop" : "desktop.addToDesktop");
    return <article className={`launcher-app ${app.admin ? "administrative" : ""} ${compact ? "compact" : ""}`} key={app.id}>
      <button className="launcher-open" type="button" onClick={() => open(app.id)} onContextMenu={(event) => showContext(event, app)}>{app.icon}<span>{t(app.labelKey)}</span>{app.admin && <small><ShieldCheck />{t("desktop.adminApp")}</small>}</button>
      <button className={`launcher-desktop-pin ${onDesktop ? "active" : ""}`} type="button" aria-pressed={onDesktop} aria-label={`${desktopLabel} ${t(app.labelKey)}`} title={desktopLabel} onClick={() => onToggleDesktopShortcut(app.id)}><Monitor /></button>
      <button className={`launcher-pin ${startPinned.has(app.id) ? "active" : ""}`} type="button" aria-label={`${startPinned.has(app.id) ? t("desktop.unpinFromStart") : t("desktop.pinToStart")} ${t(app.labelKey)}`} title={startPinned.has(app.id) ? t("desktop.unpinFromStart") : t("desktop.pinToStart")} onClick={() => onToggleStartPin(app.id)}><Pin /></button>
    </article>;
  }

  async function restartApplication() {
    if (powerBusy) return;
    setPowerBusy("application");
    setPowerError("");
    try {
      await (onRestartApplication ? onRestartApplication() : powerClient.restartApplication());
      setPowerMenuOpen(false);
      onClose();
    } catch (error) {
      if (isExpectedRestartDisconnect(error)) {
        // nginx can lose the upstream before the restart endpoint sends its
        // response. The global connection monitor handles reconnection.
        setPowerMenuOpen(false);
        onClose();
      } else {
        setPowerError(error instanceof Error ? error.message : t("error.generic"));
      }
    } finally {
      setPowerBusy(null);
    }
  }

  return <div ref={ref} className="app-launcher" role="dialog" aria-modal="false" aria-label={t("desktop.mainMenu")}>
    <div className="launcher-search"><Search /><input ref={searchRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("desktop.searchApps")} aria-label={t("desktop.searchApps")} />{query && <button type="button" aria-label={t("action.clear")} onClick={() => setQuery("")}><X /></button>}</div>
    {!allVisible && <><header className="launcher-section-title"><strong>{t("desktop.pinned")}</strong><button type="button" onClick={() => setShowAll(true)}>{t("desktop.allApps")}<ArrowRight /></button></header><div className="launcher-grid">{pinnedApps.map((app) => appButton(app))}</div><header className="launcher-section-title launcher-recent-title"><strong>{t("desktop.recentlyUsed")}</strong></header>{recent.length > 0 ? <div className="launcher-recent-list">{recent.map(({ item, app }) => <button type="button" key={app.id} onClick={() => open(app.id)} onContextMenu={(event) => showContext(event, app)}>{app.icon}<span><strong>{t(app.labelKey)}</strong><small>{relativeTime(item.usedAt)}</small></span></button>)}</div> : <p className="launcher-recent-empty">{t("desktop.noRecentApps")}</p>}</>}
    {allVisible && <><header className="launcher-section-title"><strong>{t("desktop.allApps")}</strong>{showAll && !normalized && <button type="button" onClick={() => setShowAll(false)}>{t("action.back")}</button>}</header><div className="launcher-list">{alphabeticalApps.length > 0 ? alphabeticalApps.map((app) => appButton(app, true)) : <p className="launcher-empty">{t("desktop.noAppsFound")}</p>}</div></>}
    <footer className="launcher-footer"><button className="launcher-profile" type="button" title={t("desktop.openUserSettings")} aria-label={`${t("desktop.openUserSettings")}: ${profile.username}`} onClick={() => { onOpenProfile?.(); onClose(); }}><UserRound /><span><strong>{profile.username}</strong><small>{profile.is_admin ? <><ShieldCheck />{t("desktop.administrator")}</> : t(`rbac.role.${profile.role}`)}</small></span></button><div ref={powerActionsRef} className="launcher-power-actions">{(onShutdown || onRestart || canRestartApplication) && <><button className="launcher-shutdown" type="button" title={t("shutdown.powerMenu")} aria-label={t("shutdown.powerMenu")} aria-haspopup="menu" aria-expanded={powerMenuOpen} onClick={() => { setPowerError(""); setPowerMenuOpen((value) => !value); }}><Power /></button>{powerMenuOpen && <div ref={powerMenuRef} className="launcher-power-menu" role="menu" aria-label={t("shutdown.powerMenu")} onKeyDown={(event) => {
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
      if (!buttons.length) return;
      const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : event.key === "ArrowDown" ? (current + 1) % buttons.length : (current - 1 + buttons.length) % buttons.length;
      buttons[next]?.focus();
    }}>{canRestartApplication && <button className="launcher-restart-application" type="button" role="menuitem" disabled={powerBusy !== null} onClick={() => void restartApplication()}>{powerBusy === "application" ? <LoaderCircle className="is-spinning" /> : <RefreshCw />}{t("shutdown.restart")} WebNAS</button>}{onRestart && <button type="button" role="menuitem" disabled={powerBusy !== null} onClick={() => { setPowerMenuOpen(false); onRestart(); }}><RotateCcw />{t("shutdown.restart")} system</button>}{onShutdown && <button type="button" role="menuitem" disabled={powerBusy !== null} onClick={() => { setPowerMenuOpen(false); onShutdown(); }}><Power />{t("shutdown.close")}</button>}{powerError && <p className="launcher-power-error" role="alert">{powerError}</p>}</div>}</>}<button className="launcher-logout" type="button" title={t("notify.logout")} aria-label={t("notify.logout")} onClick={onLogout}><LogOut /></button></div></footer>
    {context && <ContextMenu className="launcher-context-menu" portalTarget={context.portalTarget} x={context.x} y={context.y} items={contextItems(context.app)} onClose={() => setContext(null)} />}
  </div>;
}
