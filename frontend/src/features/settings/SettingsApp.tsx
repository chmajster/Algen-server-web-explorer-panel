import {
  Accessibility, AlertTriangle, Bell, CheckCircle2, CircleUserRound, FileCog, FolderOpen, Info, Languages, MonitorCog, Network,
  Palette, RefreshCw, Search, Settings, ShieldCheck, SlidersHorizontal, Terminal, Users, X
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  api, type AutoUpdateSettings, type ProxmoxSafety, type SettingsMe, type SettingsPatch,
  type SystemStatus, type UpdateProgress, type UpdateStatus
} from "../../api";
import { defaultUserPreferences } from "../../app/defaultSettings";
import type { AppId, ToastFn, Translate } from "../../app/types";
import { HostInformationSection } from "./HostInformationSection";
import { NetworkSettingsSection } from "./NetworkSettingsSection";
import { NetworkMountsSettingsSection } from "../mounts/NetworkMountsSettingsSection";

export type SettingsCategory = "system" | "personalization" | "files" | "transfers" | "notifications" | "accessibility" | "language" | "account" | "identity" | "network" | "networkResources" | "administration" | "about";
type SaveState = "idle" | "saving" | "saved" | "error";
type UpdateDialogState = { phase: "checking" | "running" | "completed" | "failed" | "no-update"; progress: UpdateProgress | null; message: string };

const categoryIcons: Record<SettingsCategory, ReactNode> = {
  system: <MonitorCog />, personalization: <Palette />, files: <FileCog />, transfers: <RefreshCw />,
  notifications: <Bell />, accessibility: <Accessibility />, language: <Languages />, account: <CircleUserRound />,
  identity: <Users />, network: <Network />, networkResources: <FolderOpen />, administration: <ShieldCheck />, about: <Info />,
};

const categorySettings: Record<SettingsCategory, string[]> = {
  system: ["hostInformation", "hostname", "operatingSystem", "cpuModel", "physicalCores", "logicalThreads", "totalMemory", "graphicsProcessors", "architecture", "ipAddresses", "applicationVersion", "systemUptime", "availableDiskSpace", "startupBehavior", "restoreWindows", "emptyDesktop", "showNotificationCenter", "showClockSeconds", "dateFormat", "welcomeWidget", "resetInterface"],
  personalization: ["theme", "accentColor", "wallpaper", "wallpaperUrl", "wallpaperFit", "windowTransparency", "animations", "taskbarAlignment", "desktopShortcuts", "desktopShortcutSize", "desktopWidgets"],
  files: ["defaultView", "compactRows", "showHiddenFiles", "confirmDelete", "confirmOverwrite", "pageSize", "defaultSort", "sortDirection", "rememberLastPath"],
  transfers: ["transferSuccess", "transferError", "openFailedTransfer", "showTransferIndicator", "rememberTransferFilter"],
  notifications: ["notificationsEnabled", "transferNotifications", "errorNotifications", "adminNotifications", "notificationLimit", "notificationAutoHide"],
  accessibility: ["interfaceScale", "largerText", "reduceMotion", "highContrast", "strongActiveBorders", "alwaysShowFocus"],
  language: ["language", "dateFormat", "timeFormat", "firstDayOfWeek"], account: ["username", "groups", "changePassword"],
  identity: ["usersAndGroups"], network: ["networkMonitor", "dnsDiagnostics", "routingTable"], networkResources: ["networkResources"], administration: ["serviceInformation", "updates", "automaticUpdates", "proxmoxSafeMode"], about: ["applicationName", "version", "technologies", "license", "repository"],
};

function SettingRow({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return <div className="setting-row"><div><strong>{title}</strong>{description && <small>{description}</small>}</div><div className="setting-control">{children}</div></div>;
}

function Switch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="settings-switch"><input type="checkbox" aria-label={label} checked={checked} onChange={(event) => onChange(event.target.checked)} /><span aria-hidden="true" /></label>;
}

function Select({ label, value, onChange, children }: { label: string; value: string | number; onChange: (value: string) => void; children: ReactNode }) {
  return <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>{children}</select>;
}

function Card({ title, children }: { title?: string; children: ReactNode }) {
  return <section className="settings-card">{title && <h3>{title}</h3>}{children}</section>;
}

function UpdateProgressDialog({ value, t, onClose }: { value: UpdateDialogState; t: Translate; onClose: () => void }) {
  const logRef = useRef<HTMLPreElement | null>(null);
  const active = value.phase === "checking" || value.phase === "running";
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [value.progress?.lines]);
  return <div className="modal-backdrop update-progress-backdrop"><section className="modal-panel update-progress-dialog" role="dialog" aria-modal="true" aria-labelledby="update-progress-title">
    <header className="modal-header"><h2 id="update-progress-title">{t("settings.updateProgressTitle")}</h2><button className="icon-button" type="button" aria-label={t("action.close")} onClick={onClose}><X /></button></header>
    <div className="modal-body update-progress-body">
      <div className={`update-progress-state ${value.phase}`} aria-live="polite">{active ? <RefreshCw className="spin" /> : value.phase === "failed" ? <AlertTriangle /> : <CheckCircle2 />}<div><strong>{t(`settings.updatePhase.${value.phase}`)}</strong><span>{value.message}</span></div></div>
      <div className={`update-progress-meter ${active ? "active" : ""} ${value.phase === "failed" ? "failed" : ""}`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value.phase === "checking" ? 15 : value.phase === "running" ? undefined : 100}><span style={{ width: value.phase === "checking" ? "15%" : value.phase === "running" ? "62%" : "100%" }} /></div>
      {value.progress && <dl className="update-progress-meta"><div><dt>PID</dt><dd>{value.progress.pid || "—"}</dd></div><div><dt>{t("settings.updateStartedAt")}</dt><dd>{value.progress.started_at ? new Date(value.progress.started_at * 1000).toLocaleString() : "—"}</dd></div><div><dt>{t("settings.updateExitCode")}</dt><dd>{value.progress.exit_code ?? "—"}</dd></div><div><dt>{t("settings.updateLogPath")}</dt><dd><code>{value.progress.log}</code></dd></div></dl>}
      <section className="update-live-log"><header><Terminal /><strong>{t("settings.updateLiveLog")}</strong></header><pre ref={logRef}>{value.progress?.lines.length ? value.progress.lines.join("\n") : t(active ? "settings.updateWaitingForLog" : "settings.updateNoLog")}</pre></section>
    </div>
    <footer className="modal-footer"><button type="button" onClick={onClose}>{active ? t("settings.closeAndRunInBackground") : t("action.close")}</button></footer>
  </section></div>;
}

function PasswordSection({ t, toast }: { t: Translate; toast: ToastFn }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [saving, setSaving] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setSaving(true);
    try { await api.changeMyPassword(current, next); setCurrent(""); setNext(""); toast(t("settings.passwordChanged")); }
    catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error"); }
    finally { setSaving(false); }
  }
  return <Card title={t("settings.changePassword")}><form className="password-settings" onSubmit={(event) => void submit(event)}><label>{t("settings.currentPassword")}<input type="password" autoComplete="current-password" required value={current} onChange={(event) => setCurrent(event.target.value)} /></label><label>{t("settings.newPassword")}<input type="password" autoComplete="new-password" required minLength={8} value={next} onChange={(event) => setNext(event.target.value)} /></label><button className="button-primary" type="submit" disabled={saving}>{saving ? t("settings.saving") : t("settings.changePassword")}</button></form></Card>;
}

function AdministrationSection({ locale, t, toast, onOpenApp }: { locale: "pl-PL" | "en-US"; t: Translate; toast: ToastFn; onOpenApp: (app: AppId) => void }) {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [updates, setUpdates] = useState<UpdateStatus | null>(null);
  const [automatic, setAutomatic] = useState<AutoUpdateSettings | null>(null);
  const [proxmox, setProxmox] = useState<ProxmoxSafety | null>(null);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [runningUpdate, setRunningUpdate] = useState(false);
  const [updateDialog, setUpdateDialog] = useState<UpdateDialogState | null>(null);
  const [updateError, setUpdateError] = useState("");
  useEffect(() => {
    let live = true;
    Promise.allSettled([api.systemStatus(), api.checkUpdates(), api.autoUpdate(), api.proxmoxSafety()]).then((results) => {
      if (!live) return;
      if (results[0].status === "fulfilled") setStatus(results[0].value);
      if (results[1].status === "fulfilled") { setUpdates(results[1].value); setUpdateError(results[1].value.error || ""); }
      else setUpdateError(results[1].reason instanceof Error ? results[1].reason.message : t("settings.updateUnavailable"));
      if (results[2].status === "fulfilled") setAutomatic(results[2].value);
      if (results[3].status === "fulfilled") setProxmox(results[3].value);
      setLoading(false);
    });
    return () => { live = false; };
  }, [t]);
  async function refreshUpdates() {
    setChecking(true); setUpdateError("");
    try { const value = await api.checkUpdates(); setUpdates(value); setUpdateError(value.error || ""); }
    catch (error) { setUpdateError(error instanceof Error ? error.message : t("settings.updateUnavailable")); }
    finally { setChecking(false); }
  }
  async function saveAutomatic(patch: Partial<Pick<AutoUpdateSettings, "enabled" | "interval_hours" | "update_config">>) {
    if (!automatic) return;
    const before = automatic; const next = { ...automatic, ...patch }; setAutomatic(next);
    try { setAutomatic(await api.saveAutoUpdate({ enabled: next.enabled, interval_hours: next.interval_hours, update_config: next.update_config })); toast(t("settings.saved"), "ok", "admin"); }
    catch (error) { setAutomatic(before); toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin"); }
  }
  async function runUpdateNow() {
    if (!window.confirm(t("settings.confirmUpdateNow"))) return;
    setRunningUpdate(true);
    setUpdateDialog({ phase: "checking", progress: null, message: t("settings.updateCheckingDetails") });
    try {
      const result = await api.runAutoUpdate(false);
      toast(result.updated ? t("settings.updateStarted") : t("settings.noUpdateAvailable"), "ok", "admin");
      setAutomatic(await api.autoUpdate());
      if (!result.updated) { await refreshUpdates(); setUpdateDialog({ phase: "no-update", progress: null, message: t("settings.noUpdateAvailable") }); }
      else setUpdateDialog({ phase: "running", progress: null, message: t("settings.updateInstallerRunning") });
    } catch (error) { const message = error instanceof Error ? error.message : t("error.generic"); toast(message, "error", "admin"); setUpdateDialog({ phase: "failed", progress: null, message }); }
    finally { setRunningUpdate(false); }
  }
  useEffect(() => {
    if (updateDialog?.phase !== "running") return;
    let live = true;
    const poll = async () => {
      try {
        const progress = await api.updateProgress();
        if (!live) return;
        if (progress.state === "completed") setUpdateDialog({ phase: "completed", progress, message: t("settings.updateCompletedDetails") });
        else if (progress.state === "failed") setUpdateDialog({ phase: "failed", progress, message: t("settings.updateFailedDetails") });
        else setUpdateDialog({ phase: "running", progress, message: t("settings.updateInstallerRunning") });
      } catch {
        if (live) setUpdateDialog((current) => current?.phase === "running" ? { ...current, message: t("settings.updateReconnecting") } : current);
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1200);
    return () => { live = false; window.clearInterval(timer); };
  }, [updateDialog?.phase, t]);
  const dateTime = (value: number | null | undefined) => value ? new Date(value * 1000).toLocaleString() : t("common.none");
  const releaseDate = (value: number | null | undefined) => {
    if (!value) return "—";
    const date = new Date(value * 1000);
    let remaining = Math.max(0, Date.now() - date.getTime());
    const units: Array<[string, number]> = [[locale === "pl-PL" ? "r." : "y", 365 * 86_400_000], ["d", 86_400_000], [locale === "pl-PL" ? "godz." : "h", 3_600_000], ["min", 60_000], ["s", 1000]];
    const matched = units.findIndex(([, size]) => remaining >= size);
    const first = matched < 0 ? units.length - 1 : matched;
    const parts: string[] = [];
    for (const [label, size] of units.slice(first, first + 3)) {
      const amount = Math.floor(remaining / size);
      remaining -= amount * size;
      parts.push(`${amount} ${label}`);
    }
    return `${date.toLocaleString(locale, { dateStyle: "medium", timeStyle: "medium" })} (${parts.join(" ")} ${t("desktop.timeAgo")})`;
  };
  if (loading) return <div className="loading-state">{t("status.loading")}</div>;
  return <div className="settings-card-stack">
    <Card title={t("settings.serviceInformation")}><dl className="settings-details"><dt>{t("settings.service")}</dt><dd>{status?.service || "WebNAS"}</dd><dt>{t("settings.version")}</dt><dd>{status?.version || "—"}</dd><dt>{t("settings.port")}</dt><dd>{status?.port || "—"}</dd><dt>{t("settings.dataDirectory")}</dt><dd>{status?.data_dir || "—"}</dd></dl></Card>
    <Card title={t("settings.updates")}><div className="update-settings-status"><SettingRow title={t("settings.updateStatus")} description={updateError || (updates?.update_available ? t("settings.updateAvailable") : updates ? t("settings.upToDate") : t("settings.updateUnavailable"))}><span className={`settings-status-pill ${updateError ? "danger" : updates?.update_available ? "warning" : "success"}`}>{updateError ? "!" : updates?.update_available ? t("common.yes") : t("common.no")}</span></SettingRow><button type="button" disabled={checking} onClick={() => void refreshUpdates()}><RefreshCw className={checking ? "spin" : ""} />{t("settings.checkNow")}</button></div>{updates && <dl className="settings-details update-version-details"><dt>{t("settings.updateSource")}</dt><dd>{updates.source_url ? <a href={updates.source_url} target="_blank" rel="noreferrer">{updates.source || updates.source_url}</a> : updates.source || "—"}</dd><dt>{t("settings.releaseDate")}</dt><dd>{releaseDate(updates.released_at)}</dd><dt>{t("settings.updateBranch")}</dt><dd>{updates.branch}</dd><dt>{t("settings.installedRevision")}</dt><dd><code>{updates.local === "unknown" ? t("settings.unknownRevision") : updates.local.slice(0, 12)}</code></dd><dt>{t("settings.availableRevision")}</dt><dd><code>{updates.remote ? updates.remote.slice(0, 12) : "—"}</code></dd></dl>}{automatic && <div className="auto-update-settings"><SettingRow title={t("settings.automaticUpdates")} description={t("settings.automaticUpdatesHint")}><Switch label={t("settings.automaticUpdates")} checked={automatic.enabled} onChange={(value) => void saveAutomatic({ enabled: value })} /></SettingRow><SettingRow title={t("settings.updateInterval")}><Select label={t("settings.updateInterval")} value={automatic.interval_hours} onChange={(value) => void saveAutomatic({ interval_hours: Number(value) })}>{[1, 6, 12, 24, 48, 72, 168].map((hours) => <option key={hours} value={hours}>{hours < 24 ? `${hours} h` : `${hours / 24} d`}</option>)}</Select></SettingRow><SettingRow title={t("settings.updateConfiguration")} description={t("settings.updateConfigurationHint")}><Switch label={t("settings.updateConfiguration")} checked={automatic.update_config} onChange={(value) => void saveAutomatic({ update_config: value })} /></SettingRow><dl className="settings-details"><dt>{t("settings.lastChecked")}</dt><dd>{dateTime(automatic.last_checked)}</dd><dt>{t("settings.lastUpdateRun")}</dt><dd>{dateTime(automatic.last_run)}</dd><dt>{t("settings.nextCheck")}</dt><dd>{automatic.enabled ? dateTime(automatic.next_check) : t("common.disabled")}</dd></dl>{automatic.last_error && <p className="update-settings-error">{automatic.last_error}</p>}<div className="update-now-action"><button className="button-primary update-now-button" type="button" disabled={runningUpdate} onClick={() => void runUpdateNow()}><RefreshCw className={runningUpdate ? "spin" : ""} />{t("settings.updateNow")}</button><small>{t("settings.manualUpdatePreservesConfig")}</small></div></div>}</Card>
    <Card title={t("settings.proxmoxSafeMode")}><SettingRow title={t("settings.proxmoxDetected")} description={proxmox?.safe_mode_enabled ? t("settings.proxmoxProtectionActive") : t("settings.proxmoxProtectionInactive")}><span className={`settings-status-pill ${proxmox?.safe_mode_enabled ? "success" : "neutral"}`}>{proxmox?.is_proxmox ? t("common.yes") : t("common.no")}</span></SettingRow></Card>
    <Card title={t("settings.administrationApps")}><div className="settings-app-links">{(["services", "logs", "identity"] as AppId[]).map((app) => <button key={app} type="button" onClick={() => onOpenApp(app)}>{app === "identity" ? <Users /> : <SlidersHorizontal />}{t(`app.${app}`)}</button>)}</div></Card>
    {updateDialog && <UpdateProgressDialog value={updateDialog} t={t} onClose={() => setUpdateDialog(null)} />}
  </div>;
}

export function SettingsAppView({ settings, initialSection = "system", t, toast, onSettingsChange, onOpenApp }: {
  settings: SettingsMe;
  initialSection?: SettingsCategory;
  t: Translate;
  toast: ToastFn;
  onSettingsChange: (patch: SettingsPatch) => Promise<void>;
  onOpenApp: (app: AppId) => void;
}) {
  const [category, setCategory] = useState<SettingsCategory>(initialSection);
  const [query, setQuery] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState("");
  const [wallpaperDraft, setWallpaperDraft] = useState(settings.wallpaper);
  const wallpaperTimer = useRef<number | null>(null);
  const saveStatusTimer = useRef<number | null>(null);
  const categories = useMemo(() => (Object.keys(categoryIcons) as SettingsCategory[]).filter((item) => settings.is_admin || !["identity", "network", "networkResources", "administration"].includes(item)), [settings.is_admin]);
  const normalizedQuery = query.trim().toLocaleLowerCase(settings.language);
  const searchResults = useMemo(() => normalizedQuery ? categories.flatMap((item) => categorySettings[item].map((key) => ({ category: item, key, label: t(`settings.${key}`) })).filter((entry) => entry.label.toLocaleLowerCase(settings.language).includes(normalizedQuery) || t(`settings.category.${item}`).toLocaleLowerCase(settings.language).includes(normalizedQuery))) : [], [categories, normalizedQuery, settings.language, t]);

  useEffect(() => setWallpaperDraft(settings.wallpaper), [settings.wallpaper]);
  useEffect(() => () => { if (wallpaperTimer.current) window.clearTimeout(wallpaperTimer.current); if (saveStatusTimer.current) window.clearTimeout(saveStatusTimer.current); }, []);

  async function save(patch: SettingsPatch) {
    if (saveStatusTimer.current) window.clearTimeout(saveStatusTimer.current);
    setSaveState("saving"); setSaveError("");
    try { await onSettingsChange(patch); setSaveState("saved"); saveStatusTimer.current = window.setTimeout(() => setSaveState("idle"), 1800); }
    catch (error) { const message = error instanceof Error ? error.message : t("error.generic"); setSaveError(message); setSaveState("error"); toast(message, "error"); }
  }
  function saveWallpaper(value: string) {
    setWallpaperDraft(value);
    if (wallpaperTimer.current) window.clearTimeout(wallpaperTimer.current);
    wallpaperTimer.current = window.setTimeout(() => void save({ wallpaper: value }), 400);
  }
  function choose(next: SettingsCategory) { setCategory(next); setQuery(""); }
  const yesNo = (key: keyof SettingsPatch, title: string, description?: string) => <SettingRow title={title} description={description}><Switch label={title} checked={Boolean(settings[key as keyof SettingsMe])} onChange={(value) => void save({ [key]: value })} /></SettingRow>;

  function content() {
    if (category === "system") return <div className="settings-card-stack"><Card title={t("settings.startupBehavior")}><SettingRow title={t("settings.restoreWindows")} description={t("settings.restoreWindowsHint")}><Select label={t("settings.startupBehavior")} value={settings.startup_windows} onChange={(value) => void save({ startup_windows: value as SettingsMe["startup_windows"] })}><option value="last">{t("settings.restoreWindows")}</option><option value="none">{t("settings.emptyDesktop")}</option></Select></SettingRow></Card><Card>{yesNo("show_notifications", t("settings.showNotificationCenter"))}{yesNo("clock_show_seconds", t("settings.showClockSeconds"))}{yesNo("show_welcome_widget", t("settings.welcomeWidget"))}<SettingRow title={t("settings.dateFormat")}><Select label={t("settings.dateFormat")} value={settings.date_format} onChange={(value) => void save({ date_format: value as SettingsMe["date_format"] })}><option value="locale">{t("settings.formatLocale")}</option><option value="short">{t("settings.formatShort")}</option><option value="long">{t("settings.formatLong")}</option><option value="iso">ISO 8601</option></Select></SettingRow></Card><Card><SettingRow title={t("settings.resetInterface")} description={t("settings.resetInterfaceHint")}><button className="settings-reset" type="button" onClick={() => void save(defaultUserPreferences)}><RefreshCw />{t("settings.restoreDefaults")}</button></SettingRow></Card></div>;
    if (category === "personalization") return <div className="settings-card-stack"><Card title={t("settings.theme")}><SettingRow title={t("settings.theme")}><Select label={t("settings.theme")} value={settings.theme} onChange={(value) => void save({ theme: value as SettingsMe["theme"] })}><option value="system">{t("settings.systemTheme")}</option><option value="light">{t("settings.light")}</option><option value="dark">{t("settings.dark")}</option></Select></SettingRow><SettingRow title={t("settings.accentColor")}><div className="accent-palette" role="radiogroup" aria-label={t("settings.accentColor")}>{(["blue", "teal", "green", "violet", "rose", "orange"] as const).map((color) => <button key={color} type="button" role="radio" aria-label={t(`settings.accent.${color}`)} aria-checked={settings.accent_color === color} className={`accent-${color} ${settings.accent_color === color ? "selected" : ""}`} onClick={() => void save({ accent_color: color })} />)}</div></SettingRow></Card><Card title={t("settings.wallpaper")}><div className="wallpaper-preview" style={wallpaperDraft ? { backgroundImage: `url(${JSON.stringify(wallpaperDraft)})` } : undefined}><span>WebNAS</span></div><SettingRow title={t("settings.wallpaperUrl")}><div className="wallpaper-input"><input aria-label={t("settings.wallpaperUrl")} value={wallpaperDraft} maxLength={2000000} placeholder="https://…" onChange={(event) => saveWallpaper(event.target.value)} /><button type="button" title={t("settings.removeWallpaper")} aria-label={t("settings.removeWallpaper")} disabled={!wallpaperDraft} onClick={() => saveWallpaper("")}><X /></button></div></SettingRow><SettingRow title={t("settings.wallpaperFit")}><Select label={t("settings.wallpaperFit")} value={settings.wallpaper_fit} onChange={(value) => void save({ wallpaper_fit: value as SettingsMe["wallpaper_fit"] })}>{["cover", "contain", "stretch", "center"].map((value) => <option key={value} value={value}>{t(`settings.fit.${value}`)}</option>)}</Select></SettingRow></Card><Card>{yesNo("window_transparency", t("settings.windowTransparency"))}{yesNo("animations_enabled", t("settings.animations"))}<SettingRow title={t("settings.taskbarAlignment")}><Select label={t("settings.taskbarAlignment")} value={settings.taskbar_alignment} onChange={(value) => void save({ taskbar_alignment: value as SettingsMe["taskbar_alignment"] })}><option value="left">{t("settings.alignLeft")}</option><option value="center">{t("settings.alignCenter")}</option></Select></SettingRow>{yesNo("show_desktop_shortcuts", t("settings.desktopShortcuts"))}{yesNo("widgets_enabled", t("settings.desktopWidgets"))}<SettingRow title={t("settings.desktopShortcutSize")}><Select label={t("settings.desktopShortcutSize")} value={settings.desktop_shortcut_size} onChange={(value) => void save({ desktop_shortcut_size: value as SettingsMe["desktop_shortcut_size"] })}>{["small", "medium", "large"].map((value) => <option key={value} value={value}>{t(`settings.size.${value}`)}</option>)}</Select></SettingRow></Card></div>;
    if (category === "files") return <Card><SettingRow title={t("settings.defaultView")}><Select label={t("settings.defaultView")} value={settings.file_default_view} onChange={(value) => void save({ file_default_view: value as SettingsMe["file_default_view"] })}><option value="list">{t("view.list")}</option><option value="grid">{t("view.medium")}</option><option value="large">{t("view.large")}</option></Select></SettingRow>{yesNo("file_compact_rows", t("settings.compactRows"))}{yesNo("file_show_hidden", t("settings.showHiddenFiles"))}{yesNo("file_confirm_delete", t("settings.confirmDelete"))}{yesNo("file_confirm_overwrite", t("settings.confirmOverwrite"))}<SettingRow title={t("settings.pageSize")}><Select label={t("settings.pageSize")} value={settings.file_page_size} onChange={(value) => void save({ file_page_size: Number(value) as SettingsMe["file_page_size"] })}>{[25, 50, 100, 200].map((value) => <option key={value}>{value}</option>)}</Select></SettingRow><SettingRow title={t("settings.defaultSort")}><Select label={t("settings.defaultSort")} value={settings.file_default_sort} onChange={(value) => void save({ file_default_sort: value as SettingsMe["file_default_sort"] })}>{["name", "size", "type", "modified"].map((value) => <option key={value} value={value}>{t(`column.${value}`)}</option>)}</Select></SettingRow><SettingRow title={t("settings.sortDirection")}><Select label={t("settings.sortDirection")} value={settings.file_sort_direction} onChange={(value) => void save({ file_sort_direction: value as SettingsMe["file_sort_direction"] })}><option value="asc">{t("settings.ascending")}</option><option value="desc">{t("settings.descending")}</option></Select></SettingRow>{yesNo("file_remember_last_path", t("settings.rememberLastPath"))}</Card>;
    if (category === "transfers") return <Card>{yesNo("transfer_success_notifications", t("settings.transferSuccess"))}{yesNo("transfer_error_notifications", t("settings.transferError"))}{yesNo("transfer_open_failed_details", t("settings.openFailedTransfer"))}{yesNo("show_transfer_indicator", t("settings.showTransferIndicator"))}{yesNo("transfer_remember_filter", t("settings.rememberTransferFilter"))}</Card>;
    if (category === "notifications") return <Card>{yesNo("show_notifications", t("settings.notificationsEnabled"))}{yesNo("notification_transfer", t("settings.transferNotifications"))}{yesNo("notification_errors", t("settings.errorNotifications"))}{yesNo("notification_admin", t("settings.adminNotifications"))}<SettingRow title={t("settings.notificationLimit")}><Select label={t("settings.notificationLimit")} value={settings.notification_limit} onChange={(value) => void save({ notification_limit: Number(value) })}>{[3, 5, 7, 10].map((value) => <option key={value}>{value}</option>)}</Select></SettingRow>{yesNo("notification_auto_hide", t("settings.notificationAutoHide"))}</Card>;
    if (category === "accessibility") return <Card><SettingRow title={t("settings.interfaceScale")}><Select label={t("settings.interfaceScale")} value={settings.interface_scale} onChange={(value) => void save({ interface_scale: Number(value) as SettingsMe["interface_scale"] })}>{[90, 100, 110, 125].map((value) => <option key={value} value={value}>{value}%</option>)}</Select></SettingRow>{yesNo("larger_text", t("settings.largerText"))}{yesNo("reduced_motion", t("settings.reduceMotion"), t("settings.systemPreferencesRespected"))}{yesNo("high_contrast", t("settings.highContrast"), t("settings.systemPreferencesRespected"))}{yesNo("strong_active_borders", t("settings.strongActiveBorders"))}{yesNo("always_show_focus", t("settings.alwaysShowFocus"))}</Card>;
    if (category === "language") return <Card><SettingRow title={t("settings.language")}><Select label={t("settings.language")} value={settings.language} onChange={(value) => void save({ language: value as SettingsMe["language"] })}><option value="pl-PL">Polski</option><option value="en-US">English</option></Select></SettingRow><SettingRow title={t("settings.dateFormat")}><Select label={t("settings.dateFormat")} value={settings.date_format} onChange={(value) => void save({ date_format: value as SettingsMe["date_format"] })}><option value="locale">{t("settings.formatLocale")}</option><option value="short">{t("settings.formatShort")}</option><option value="long">{t("settings.formatLong")}</option><option value="iso">ISO 8601</option></Select></SettingRow><SettingRow title={t("settings.timeFormat")}><Select label={t("settings.timeFormat")} value={settings.time_format} onChange={(value) => void save({ time_format: value as SettingsMe["time_format"] })}><option value="24">24 h</option><option value="12">12 h</option></Select></SettingRow><SettingRow title={t("settings.firstDayOfWeek")}><Select label={t("settings.firstDayOfWeek")} value={settings.first_day_of_week} onChange={(value) => void save({ first_day_of_week: value as SettingsMe["first_day_of_week"] })}><option value="locale">{t("settings.formatLocale")}</option><option value="monday">{t("settings.monday")}</option><option value="sunday">{t("settings.sunday")}</option></Select></SettingRow></Card>;
    if (category === "account") return <div className="settings-card-stack"><Card title={t("settings.accountInformation")}><dl className="settings-details"><dt>{t("settings.username")}</dt><dd>{settings.username}</dd><dt>UID</dt><dd>{settings.uid}</dd><dt>GID</dt><dd>{settings.gid}</dd><dt>{t("settings.homeDirectory")}</dt><dd>{settings.home}</dd><dt>{t("settings.shell")}</dt><dd>{settings.shell}</dd><dt>{t("settings.groupsLabel")}</dt><dd>{settings.groups.join(", ") || "—"}</dd><dt>{t("settings.administratorStatus")}</dt><dd>{settings.is_admin ? t("common.yes") : t("common.no")}</dd></dl></Card><PasswordSection t={t} toast={toast} /></div>;
    if (category === "identity") return <Card title={t("app.identity")}><SettingRow title={t("settings.usersAndGroups")} description={t("settings.usersAndGroupsHint")}><div className="settings-app-links"><button type="button" onClick={() => onOpenApp("identity")}><Users />{t("settings.openUsersAndGroups")}</button></div></SettingRow></Card>;
    if (category === "network") return <NetworkSettingsSection isAdmin={settings.is_admin} t={t} />;
    if (category === "networkResources") return <NetworkMountsSettingsSection isAdmin={settings.is_admin} t={t} toast={toast} />;
    if (category === "administration") return <AdministrationSection locale={settings.language} t={t} toast={toast} onOpenApp={onOpenApp} />;
    return <div className="settings-card-stack"><Card title="WebNAS"><dl className="settings-details"><dt>{t("settings.applicationName")}</dt><dd>WebNAS</dd><dt>{t("settings.version")}</dt><dd>0.1.0</dd><dt>{t("settings.frontendEnvironment")}</dt><dd>{window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1" ? "development" : "production"}</dd><dt>{t("settings.backendEnvironment")}</dt><dd>FastAPI / Linux</dd><dt>{t("settings.technologies")}</dt><dd>React · TypeScript · FastAPI · lucide-react</dd><dt>{t("settings.license")}</dt><dd>{t("settings.licenseInfo")}</dd></dl><a className="settings-repository" href="https://github.com/chmajster/Algen-server-web-explorer-panel" target="_blank" rel="noreferrer">{t("settings.repository")}</a></Card></div>;
  }

  return <section className="settings-app">
    <aside className="settings-sidebar"><div className="settings-profile"><Settings /><span><strong>{t("app.settings")}</strong><small>{settings.username}</small></span></div><div className="settings-search"><Search /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("settings.search")} aria-label={t("settings.search")} />{query && <button type="button" aria-label={t("action.clear")} onClick={() => setQuery("")}><X /></button>}</div><nav aria-label={t("settings.categories")}>{categories.map((item) => <button key={item} type="button" className={category === item ? "active" : ""} aria-current={category === item ? "page" : undefined} onClick={() => choose(item)}>{categoryIcons[item]}<span>{t(`settings.category.${item}`)}</span></button>)}</nav></aside>
    <main className="settings-main"><header className="settings-header"><div><small>{t("app.settings")}</small><h2>{normalizedQuery ? t("settings.searchResults") : t(`settings.category.${category}`)}</h2></div><div className={`settings-save-state ${saveState}`} role="status" aria-live="polite">{saveState === "saving" ? t("settings.saving") : saveState === "saved" ? t("settings.saved") : saveState === "error" ? `${t("settings.saveError")}: ${saveError}` : ""}</div><Select label={t("settings.categories")} value={category} onChange={(value) => choose(value as SettingsCategory)}>{categories.map((item) => <option key={item} value={item}>{t(`settings.category.${item}`)}</option>)}</Select></header><div className="settings-content">{!normalizedQuery && category === "system" && <HostInformationSection language={settings.language} t={t} />}{normalizedQuery ? <div className="settings-search-results">{searchResults.length ? searchResults.map((result) => <button key={`${result.category}:${result.key}`} type="button" onClick={() => choose(result.category)}>{categoryIcons[result.category]}<span><strong>{result.label}</strong><small>{t(`settings.category.${result.category}`)}</small></span></button>) : <div className="empty-state">{t("settings.noSearchResults")}</div>}</div> : content()}</div></main>
  </section>;
}
