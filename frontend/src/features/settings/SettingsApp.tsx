import {
  Accessibility, AlertTriangle, Bell, CalendarClock, CheckCircle2, CircleUserRound, FileCog, FolderOpen, Info, Languages,
  ChevronLeft, ChevronRight, Image, MonitorCog, Network, Palette, RefreshCw, ScrollText, Search, Server, Settings, ShieldCheck, SlidersHorizontal, Terminal, Users, X
} from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  api, type AutoUpdateSettings, type DockerContainerDefaultsPolicy, type ProxmoxSafety, type SettingsMe, type SettingsPatch,
  type SystemStatus, type UpdateProgress, type UpdateStatus
} from "../../api";
import { defaultUserPreferences } from "../../app/defaultSettings";
import type { AppId, ToastFn, Translate } from "../../app/types";
import { HostInformationSection } from "./HostInformationSection";
import { NetworkSettingsSection } from "./NetworkSettingsSection";
import { NetworkMountsSettingsSection } from "../mounts/NetworkMountsSettingsSection";
import { WallpaperSettingsPage } from "./WallpaperSettingsPage";

const IdentityApp = lazy(() => import("../admin/IdentityApp").then((module) => ({ default: module.IdentityApp })));

export type SettingsCategory = "system" | "personalization" | "files" | "transfers" | "notifications" | "accessibility" | "language" | "account" | "identity" | "network" | "networkResources" | "policies" | "administration" | "about";
type SaveState = "idle" | "saving" | "saved" | "error";
type UpdateDialogState = { phase: "checking" | "running" | "completed" | "failed" | "no-update"; progress: UpdateProgress | null; message: string };
const dismissedUpdateProgressKey = "webnas.dismissed-update-progress";

const categoryIcons: Record<SettingsCategory, ReactNode> = {
  system: <MonitorCog />, personalization: <Palette />, files: <FileCog />, transfers: <RefreshCw />,
  notifications: <Bell />, accessibility: <Accessibility />, language: <Languages />, account: <CircleUserRound />,
  identity: <Users />, network: <Network />, networkResources: <FolderOpen />, policies: <ScrollText />, administration: <ShieldCheck />, about: <Info />,
};

export function isSettingsCategory(value: string | undefined): value is SettingsCategory {
  return Boolean(value && Object.prototype.hasOwnProperty.call(categoryIcons, value));
}

const categorySettings: Record<SettingsCategory, string[]> = {
  system: ["hostInformation", "hostname", "operatingSystem", "cpuModel", "physicalCores", "logicalThreads", "totalMemory", "graphicsProcessors", "architecture", "ipAddresses", "applicationVersion", "systemUptime", "availableDiskSpace", "startupBehavior", "restoreWindows", "emptyDesktop", "showNotificationCenter", "showClockSeconds", "dateFormat", "welcomeWidget", "resetInterface"],
  personalization: ["theme", "accentColor", "wallpaper", "wallpaperUrl", "wallpaperFit", "windowTransparency", "animations", "taskbarAlignment", "desktopShortcuts", "desktopShortcutSize", "desktopWidgets"],
  files: ["defaultView", "compactRows", "showHiddenFiles", "confirmDelete", "confirmOverwrite", "pageSize", "defaultSort", "sortDirection", "rememberLastPath"],
  transfers: ["transferSuccess", "transferError", "openFailedTransfer", "showTransferIndicator", "rememberTransferFilter"],
  notifications: ["notificationsEnabled", "transferNotifications", "errorNotifications", "adminNotifications", "notificationLimit", "notificationAutoHide"],
  accessibility: ["interfaceScale", "largerText", "reduceMotion", "highContrast", "strongActiveBorders", "alwaysShowFocus"],
  language: ["language", "dateFormat", "timeFormat", "firstDayOfWeek"], account: ["username", "groups", "changePassword"],
  identity: ["usersAndGroups"], network: ["networkMonitor", "dnsDiagnostics", "routingTable"], networkResources: ["networkResources"], policies: ["updatePolicies", "automaticUpdateChecks", "updateInterval", "automaticUpdates", "updateConfiguration", "containerDefaultsPolicy"], administration: ["serviceInformation", "updates", "proxmoxSafeMode"], about: ["applicationName", "version", "technologies", "license", "repository"],
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
      {value.progress && <dl className="update-progress-meta"><div><dt>PID</dt><dd>{value.progress.pid || "—"}</dd></div>{value.progress.unit && <div><dt>{t("settings.updateServiceUnit")}</dt><dd><code>{value.progress.unit}</code></dd></div>}<div><dt>{t("settings.updateStartedAt")}</dt><dd>{value.progress.started_at ? new Date(value.progress.started_at * 1000).toLocaleString() : "—"}</dd></div><div><dt>{t("settings.updateExitCode")}</dt><dd>{value.progress.exit_code ?? "—"}</dd></div><div><dt>{t("settings.updateLogPath")}</dt><dd><code>{value.progress.log}</code></dd></div></dl>}
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

function UpdatePoliciesSection({ t, toast }: { t: Translate; toast: ToastFn }) {
  const [policy, setPolicy] = useState<AutoUpdateSettings | null>(null);
  const [dockerPolicy, setDockerPolicy] = useState<DockerContainerDefaultsPolicy | null>(null);
  const [error, setError] = useState("");
  const [group, setGroup] = useState<"checking" | "installation" | "containers">("checking");
  const [selected, setSelected] = useState<"check_enabled" | "interval_hours" | "enabled" | "update_config">("check_enabled");
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    let live = true;
    api.autoUpdate().then((value) => { if (live) setPolicy(value); }).catch((reason) => { if (live) setError(reason instanceof Error ? reason.message : t("error.generic")); });
    api.dockerContainerDefaultsPolicy().then((value) => { if (live) setDockerPolicy(value); }).catch(() => undefined);
    return () => { live = false; };
  }, [t]);
  async function savePolicy(patch: Partial<Pick<AutoUpdateSettings, "check_enabled" | "enabled" | "interval_hours" | "update_config">>) {
    if (!policy) return false;
    const before = policy;
    const next = { ...policy, ...patch };
    setPolicy(next); setError("");
    try {
      setPolicy(await api.saveAutoUpdate({ check_enabled: next.check_enabled, enabled: next.enabled, interval_hours: next.interval_hours, update_config: next.update_config }));
      toast(t("settings.saved"), "ok", "admin");
      return true;
    } catch (reason) {
      setPolicy(before);
      const message = reason instanceof Error ? reason.message : t("error.generic");
      setError(message); toast(message, "error", "admin");
      return false;
    }
  }
  const dateTime = (value: number | null | undefined) => value ? new Date(value * 1000).toLocaleString() : t("common.none");
  function chooseGroup(next: "checking" | "installation" | "containers") {
    setGroup(next); if (next !== "containers") setSelected(next === "checking" ? "check_enabled" : "enabled"); setEditing(false);
  }
  if (!policy && !error) return <div className="loading-state">{t("status.loading")}</div>;
  if (!policy) return <div className="error-state" role="alert">{error}</div>;
  const policyGroups = <aside className="policy-groups">
    <header><FolderOpen />{t("settings.policyCategories")}</header>
    <button className={group === "checking" ? "active" : ""} onClick={() => chooseGroup("checking")}><FolderOpen /><span>{t("settings.policyCategoryChecking")}</span><b>2</b></button>
    <button className={group === "installation" ? "active" : ""} onClick={() => chooseGroup("installation")}><FolderOpen /><span>{t("settings.policyCategoryInstallation")}</span><b>2</b></button>
    <button className={group === "containers" ? "active" : ""} onClick={() => chooseGroup("containers")}><FolderOpen /><span>{t("settings.policyCategoryContainers")}</span><b>1</b></button>
  </aside>;
  if (group === "containers") {
    async function saveDockerPolicy() {
      if (!dockerPolicy) return;
      setError("");
      try {
        setDockerPolicy(await api.saveDockerContainerDefaultsPolicy(dockerPolicy));
        setEditing(false);
        toast(t("settings.saved"), "ok", "admin");
      } catch (reason) {
        const message = reason instanceof Error ? reason.message : t("error.generic");
        setError(message); toast(message, "error", "admin");
      }
    }
    return <section className="policy-browser">
      {policyGroups}
      <section className="policy-list"><header><SlidersHorizontal />{t("settings.policies")}<b>1</b></header><button className="active"><span><strong>{t("settings.containerDefaultsPolicy")}</strong><small>docker.container_defaults</small></span><b>{t("settings.oneActiveRule")}</b></button></section>
      <article className="policy-detail"><header><h3>{t("settings.containerDefaultsPolicy")}</h3><p>{t("settings.containerDefaultsPolicyHint")}</p><div><span><b>ID</b><code>docker.container_defaults</code></span><span><b>{t("settings.defaultValue")}</b><code>512 MiB / 1 CPU</code></span></div></header>
        <div className="policy-rules-heading"><strong>{t("settings.configuredRules")}</strong><button className="button-primary" onClick={() => setEditing(true)}>+ {t("settings.editRule")}</button></div>
        <section className="policy-rule-card"><header><span className={dockerPolicy?.resource_limits_enabled ? "enabled" : "disabled"}>{t(dockerPolicy?.resource_limits_enabled ? "common.enabled" : "common.disabled")}</span><b>{t("settings.priority")}: 100</b></header>
          {dockerPolicy && <dl><div><dt>{t("docker.field.memoryMb")}</dt><dd>{dockerPolicy.memory_mb} MiB</dd></div><div><dt>{t("docker.field.memorySwapMb")}</dt><dd>{dockerPolicy.memory_swap_mb} MiB</dd></div><div><dt>{t("docker.field.cpus")}</dt><dd>{dockerPolicy.cpus}</dd></div><div><dt>{t("docker.field.pids")}</dt><dd>{dockerPolicy.pids}</dd></div></dl>}
          <p>{t("settings.containerDefaultsPolicyHint")}</p>
          {editing && dockerPolicy && <div className="policy-rule-editor docker-policy-editor">
            <strong>{t("settings.ruleValue")}</strong>
            <label className="check-row"><input type="checkbox" checked={dockerPolicy.resource_limits_enabled} onChange={(event) => setDockerPolicy({ ...dockerPolicy, resource_limits_enabled: event.target.checked })} />{t("docker.wizard.enableLimits")}</label>
            <label>{t("docker.field.memoryMb")}<input aria-label={t("docker.field.memoryMb")} type="number" min="16" value={dockerPolicy.memory_mb} onChange={(event) => setDockerPolicy({ ...dockerPolicy, memory_mb: Number(event.target.value) })} /></label>
            <label>{t("docker.field.memorySwapMb")}<input aria-label={t("docker.field.memorySwapMb")} type="number" min={dockerPolicy.memory_mb} value={dockerPolicy.memory_swap_mb} onChange={(event) => setDockerPolicy({ ...dockerPolicy, memory_swap_mb: Number(event.target.value) })} /></label>
            <label>{t("docker.field.cpus")}<input aria-label={t("docker.field.cpus")} type="number" min="0.1" step="0.1" value={dockerPolicy.cpus} onChange={(event) => setDockerPolicy({ ...dockerPolicy, cpus: Number(event.target.value) })} /></label>
            <label>{t("docker.field.pids")}<input aria-label={t("docker.field.pids")} type="number" min="16" value={dockerPolicy.pids} onChange={(event) => setDockerPolicy({ ...dockerPolicy, pids: Number(event.target.value) })} /></label>
            <div><button className="button-primary" onClick={() => void saveDockerPolicy()}>{t("action.save")}</button><button onClick={() => setEditing(false)}>{t("action.cancel")}</button></div>
          </div>}
        </section>{error && <p className="update-settings-error">{error}</p>}
      </article>
    </section>;
  }
  const definitions = {
    check_enabled: { group: "checking" as const, label: t("settings.automaticUpdateChecks"), id: "updates.check_enabled", description: t("settings.automaticUpdateChecksHint"), defaultValue: t("common.enabled") },
    interval_hours: { group: "checking" as const, label: t("settings.updateInterval"), id: "updates.check_interval_hours", description: t("settings.updateIntervalHint"), defaultValue: "12 h" },
    enabled: { group: "installation" as const, label: t("settings.automaticUpdates"), id: "updates.auto_install", description: t("settings.automaticInstallUpdatesHint"), defaultValue: t("common.disabled") },
    update_config: { group: "installation" as const, label: t("settings.updateConfiguration"), id: "updates.update_config", description: t("settings.updateConfigurationHint"), defaultValue: t("common.disabled") },
  };
  const keys = (Object.keys(definitions) as Array<keyof typeof definitions>).filter((key) => definitions[key].group === group);
  const current = definitions[selected];
  const currentValue = selected === "interval_hours" ? `${policy.interval_hours} h` : policy[selected] ? t("common.enabled") : t("common.disabled");
  const currentEnabled = selected === "interval_hours" || Boolean(policy[selected]);
  async function updateCurrent(value: boolean | number) {
    const saved = await savePolicy({ [selected]: value });
    if (saved) setEditing(false);
  }
  return <section className="policy-browser">
    {policyGroups}
    <section className="policy-list"><header><SlidersHorizontal />{t("settings.policies")}<b>{keys.length}</b></header>{keys.map((key) => <button key={key} className={selected === key ? "active" : ""} onClick={() => { setSelected(key); setEditing(false); }}><span><strong>{definitions[key].label}</strong><small>{definitions[key].id}</small></span><b>{t("settings.oneActiveRule")}</b></button>)}</section>
    <article className="policy-detail"><header><h3>{current.label}</h3><p>{current.description}</p><div><span><b>ID</b><code>{current.id}</code></span><span><b>{t("settings.defaultValue")}</b><code>{current.defaultValue}</code></span></div></header>
      <div className="policy-rules-heading"><strong>{t("settings.configuredRules")}</strong><button className="button-primary" onClick={() => setEditing(true)}>+ {t("settings.editRule")}</button></div>
      <section className="policy-rule-card"><header><span className={currentEnabled ? "enabled" : "disabled"}>{t(currentEnabled ? "common.enabled" : "common.disabled")}</span><b>{t("settings.priority")}: 100</b></header><dl><div><dt>{t("settings.scope")}</dt><dd>{t("settings.globalScope")}</dd></div><div><dt>{t("settings.value")}</dt><dd><code>{currentValue}</code></dd></div>{selected === "check_enabled" && <><div><dt>{t("settings.lastChecked")}</dt><dd>{dateTime(policy.last_checked)}</dd></div><div><dt>{t("settings.nextCheck")}</dt><dd>{policy.check_enabled ? dateTime(policy.next_check) : t("common.disabled")}</dd></div></>}{selected === "enabled" && <div><dt>{t("settings.lastUpdateRun")}</dt><dd>{dateTime(policy.last_run)}</dd></div>}</dl><p>{current.description}</p>
        {editing && <div className="policy-rule-editor"><strong>{t("settings.ruleValue")}</strong>{selected === "interval_hours" ? <Select label={current.label} value={policy.interval_hours} onChange={(value) => void updateCurrent(Number(value))}>{[1, 6, 12, 24, 48, 72, 168].map((hours) => <option key={hours} value={hours}>{hours < 24 ? `${hours} h` : `${hours / 24} d`}</option>)}</Select> : <Switch label={current.label} checked={Boolean(policy[selected])} onChange={(value) => void updateCurrent(value)} />}<button onClick={() => setEditing(false)}>{t("action.cancel")}</button></div>}
      </section>{policy.last_error && <p className="update-settings-error">{policy.last_error}</p>}{error && <p className="update-settings-error">{error}</p>}
    </article>
  </section>;
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
  const [renderedAt] = useState(() => Date.now());
  useEffect(() => {
    let live = true;
    Promise.allSettled([api.systemStatus(), api.checkUpdates(), api.autoUpdate(), api.proxmoxSafety(), api.updateProgress()]).then((results) => {
      if (!live) return;
      if (results[0].status === "fulfilled") setStatus(results[0].value);
      if (results[1].status === "fulfilled") { setUpdates(results[1].value); setUpdateError(results[1].value.error || ""); }
      else setUpdateError(results[1].reason instanceof Error ? results[1].reason.message : t("settings.updateUnavailable"));
      if (results[2].status === "fulfilled") setAutomatic(results[2].value);
      if (results[3].status === "fulfilled") setProxmox(results[3].value);
      if (results[4].status === "fulfilled") {
        const progress = results[4].value;
        const dismissed = Number(window.sessionStorage.getItem(dismissedUpdateProgressKey) || 0);
        const recent = Boolean(progress.started_at && progress.started_at > Date.now() / 1000 - 86_400);
        if (progress.state === "running" || (recent && progress.started_at !== dismissed && (progress.state === "completed" || progress.state === "failed"))) {
          const phase = progress.state === "running" ? "running" : progress.state;
          const message = phase === "running" ? t("settings.updateInstallerRunning") : phase === "completed" ? t("settings.updateCompletedDetails") : t("settings.updateFailedDetails");
          setUpdateDialog({ phase, progress, message });
        }
      }
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
        if (progress.state === "completed") { setUpdateDialog({ phase: "completed", progress, message: t("settings.updateCompletedDetails") }); void refreshUpdates(); }
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
  const closeUpdateDialog = () => {
    if (updateDialog?.progress?.started_at) window.sessionStorage.setItem(dismissedUpdateProgressKey, String(updateDialog.progress.started_at));
    setUpdateDialog(null);
  };
  const dateTime = (value: number | null | undefined) => value ? new Date(value * 1000).toLocaleString() : t("common.none");
  const releaseDate = (value: number | null | undefined) => {
    if (!value) return "—";
    const date = new Date(value * 1000);
    let remaining = Math.max(0, renderedAt - date.getTime());
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
  const updateState = updateError ? "danger" : updates?.update_available ? "warning" : "success";
  const updateLabel = updateError || (updates?.update_available ? t("settings.updateAvailable") : updates ? t("settings.upToDate") : t("settings.updateUnavailable"));
  const adminApps: Array<{ id: AppId; icon: ReactNode; hint: string }> = [
    { id: "services", icon: <SlidersHorizontal />, hint: t("settings.administrationServicesHint") },
    { id: "logs", icon: <Terminal />, hint: t("settings.administrationLogsHint") },
  ];
  return <div className="administration-dashboard">
    <section className="admin-overview-hero">
      <div className="admin-overview-icon"><ShieldCheck /></div>
      <div className="admin-overview-copy"><small>{t("settings.administrationCenter")}</small><h3>{t("settings.administrationOverview")}</h3><p>{t("settings.administrationOverviewHint")}</p></div>
      <div className={`admin-overall-state ${updateError ? "warning" : "success"}`}><span />{updateError ? t("settings.requiresAttention") : t("settings.systemOperational")}</div>
    </section>
    <section className="admin-summary-grid" aria-label={t("settings.administrationOverview")}>
      <article><span className="admin-summary-icon service"><Server /></span><div><small>{t("settings.service")}</small><strong>{status?.service || "WebNAS"}</strong><span>{t("settings.version")} {status?.version || "—"}</span></div></article>
      <article><span className={`admin-summary-icon ${updateState}`}><RefreshCw /></span><div><small>{t("settings.updateStatus")}</small><strong>{updates?.update_available ? `${t("settings.updateAvailable")}: ${updates.remote?.slice(0, 12) || "—"}` : updateLabel}</strong><span>{updates?.source || t("settings.updateUnavailable")}</span></div></article>
      <article><span className={`admin-summary-icon ${automatic?.check_enabled ? "success" : "neutral"}`}><CalendarClock /></span><div><small>{t("settings.automaticUpdateChecks")}</small><strong>{automatic?.check_enabled ? t("common.enabled") : t("common.disabled")}</strong><span>{automatic?.check_enabled ? `${t("settings.nextCheck")}: ${dateTime(automatic.next_check)}` : t("settings.automaticUpdateChecksHint")}</span></div></article>
      <article><span className={`admin-summary-icon ${proxmox?.safe_mode_enabled ? "success" : "neutral"}`}><ShieldCheck /></span><div><small>{t("settings.proxmoxSafeMode")}</small><strong>{proxmox?.safe_mode_enabled ? t("common.enabled") : t("common.disabled")}</strong><span>{proxmox?.safe_mode_enabled ? t("settings.proxmoxProtectionActive") : t("settings.proxmoxProtectionInactive")}</span></div></article>
    </section>
    <div className="admin-content-grid">
      <Card title={t("settings.serviceInformation")}><dl className="settings-details"><dt>{t("settings.service")}</dt><dd>{status?.service || "WebNAS"}</dd><dt>{t("settings.version")}</dt><dd>{status?.version || "—"}</dd><dt>{t("settings.port")}</dt><dd>{status?.port || "—"}</dd><dt>{t("settings.dataDirectory")}</dt><dd>{status?.data_dir || "—"}</dd></dl></Card>
      <Card title={t("settings.proxmoxSafeMode")}><SettingRow title={t("settings.proxmoxDetected")} description={proxmox?.safe_mode_enabled ? t("settings.proxmoxProtectionActive") : t("settings.proxmoxProtectionInactive")}><span className={`settings-status-pill ${proxmox?.safe_mode_enabled ? "success" : "neutral"}`}>{proxmox?.is_proxmox ? t("common.yes") : t("common.no")}</span></SettingRow></Card>
    </div>
    <Card title={t("settings.updates")}><div className="update-settings-status"><SettingRow title={t("settings.updateStatus")} description={updateLabel}><span className={`settings-status-pill ${updateState}`}>{updateError ? "!" : updates?.update_available ? t("common.yes") : t("common.no")}</span></SettingRow><button type="button" disabled={checking} onClick={() => void refreshUpdates()}><RefreshCw className={checking ? "spin" : ""} />{t("settings.checkNow")}</button></div>{updates && <dl className="settings-details update-version-details"><dt>{t("settings.updateSource")}</dt><dd>{updates.source_url ? <a href={updates.source_url} target="_blank" rel="noreferrer">{updates.source || updates.source_url}</a> : updates.source || "—"}</dd><dt>{t("settings.releaseDate")}</dt><dd>{releaseDate(updates.released_at)}</dd><dt>{t("settings.updateBranch")}</dt><dd>{updates.branch}</dd><dt>{t("settings.installedRevision")}</dt><dd><span className="update-revision-value"><code>{updates.local === "unknown" ? t("settings.unknownRevision") : updates.local.slice(0, 12)}</code><small>{t("settings.publicationVersion")}: <strong>{updates.installed_version ? `v${updates.installed_version}` : "—"}</strong></small></span></dd><dt>{t("settings.availableRevision")}</dt><dd><span className="update-revision-value"><code>{updates.remote ? updates.remote.slice(0, 12) : "—"}</code><small>{t("settings.publicationVersion")}: <strong>{updates.available_version ? `v${updates.available_version}` : "—"}</strong></small></span></dd></dl>}<div className="update-now-action"><button className="button-primary update-now-button" type="button" disabled={runningUpdate} onClick={() => void runUpdateNow()}><RefreshCw className={runningUpdate ? "spin" : ""} />{t("settings.updateNow")}</button><small>{t("settings.manualUpdatePreservesConfig")}</small></div></Card>
    <Card title={t("settings.administrationApps")}><p className="admin-tools-intro">{t("settings.administrationAppsHint")}</p><div className="admin-tool-links">{adminApps.map((app) => <button key={app.id} type="button" onClick={() => onOpenApp(app.id)}><span className="admin-tool-icon">{app.icon}</span><span><strong>{t(`app.${app.id}`)}</strong><small>{app.hint}</small></span><span className="admin-tool-arrow" aria-hidden="true">›</span></button>)}</div></Card>
    {updateDialog && <UpdateProgressDialog value={updateDialog} t={t} onClose={closeUpdateDialog} />}
  </div>;
}

export function SettingsAppView({ settings, initialSection = "system", t, toast, onSettingsChange, onOpenApp, onSectionChange }: {
  settings: SettingsMe;
  initialSection?: SettingsCategory;
  t: Translate;
  toast: ToastFn;
  onSettingsChange: (patch: SettingsPatch) => Promise<void>;
  onOpenApp: (app: AppId) => void;
  onSectionChange?: (section: SettingsCategory) => void;
}) {
  const [category, setCategory] = useState<SettingsCategory>(initialSection);
  const [query, setQuery] = useState("");
  const [personalizationPage, setPersonalizationPage] = useState<"overview" | "wallpaper">("overview");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState("");
  const saveStatusTimer = useRef<number | null>(null);
  const categories = useMemo(() => (Object.keys(categoryIcons) as SettingsCategory[]).filter((item) => settings.is_admin || !["identity", "network", "networkResources", "policies", "administration"].includes(item)), [settings.is_admin]);
  const normalizedQuery = query.trim().toLocaleLowerCase(settings.language);
  const searchResults = useMemo(() => normalizedQuery ? categories.flatMap((item) => categorySettings[item].map((key) => ({ category: item, key, label: t(`settings.${key}`) })).filter((entry) => entry.label.toLocaleLowerCase(settings.language).includes(normalizedQuery) || t(`settings.category.${item}`).toLocaleLowerCase(settings.language).includes(normalizedQuery))) : [], [categories, normalizedQuery, settings.language, t]);

  useEffect(() => () => { if (saveStatusTimer.current) window.clearTimeout(saveStatusTimer.current); }, []);

  async function save(patch: SettingsPatch) {
    if (saveStatusTimer.current) window.clearTimeout(saveStatusTimer.current);
    setSaveState("saving"); setSaveError("");
    try { await onSettingsChange(patch); setSaveState("saved"); saveStatusTimer.current = window.setTimeout(() => setSaveState("idle"), 1800); }
    catch (error) { const message = error instanceof Error ? error.message : t("error.generic"); setSaveError(message); setSaveState("error"); toast(message, "error"); }
  }
  function choose(next: SettingsCategory) { setCategory(next); setPersonalizationPage("overview"); setQuery(""); onSectionChange?.(next); }
  function openWallpaper() { setCategory("personalization"); setPersonalizationPage("wallpaper"); setQuery(""); onSectionChange?.("personalization"); }
  const yesNo = (key: keyof SettingsPatch, title: string, description?: string) => <SettingRow title={title} description={description}><Switch label={title} checked={Boolean(settings[key as keyof SettingsMe])} onChange={(value) => void save({ [key]: value })} /></SettingRow>;

  function content() {
    if (category === "system") return <div className="settings-card-stack"><Card title={t("settings.startupBehavior")}><SettingRow title={t("settings.restoreWindows")} description={t("settings.restoreWindowsHint")}><Select label={t("settings.startupBehavior")} value={settings.startup_windows} onChange={(value) => void save({ startup_windows: value as SettingsMe["startup_windows"] })}><option value="last">{t("settings.restoreWindows")}</option><option value="none">{t("settings.emptyDesktop")}</option></Select></SettingRow></Card><Card>{yesNo("show_notifications", t("settings.showNotificationCenter"))}{yesNo("clock_show_seconds", t("settings.showClockSeconds"))}{yesNo("show_welcome_widget", t("settings.welcomeWidget"))}<SettingRow title={t("settings.dateFormat")}><Select label={t("settings.dateFormat")} value={settings.date_format} onChange={(value) => void save({ date_format: value as SettingsMe["date_format"] })}><option value="locale">{t("settings.formatLocale")}</option><option value="short">{t("settings.formatShort")}</option><option value="long">{t("settings.formatLong")}</option><option value="iso">ISO 8601</option></Select></SettingRow></Card><Card><SettingRow title={t("settings.resetInterface")} description={t("settings.resetInterfaceHint")}><button className="settings-reset" type="button" onClick={() => void save(defaultUserPreferences)}><RefreshCw />{t("settings.restoreDefaults")}</button></SettingRow></Card></div>;
    if (category === "personalization" && personalizationPage === "wallpaper") return <WallpaperSettingsPage settings={settings} t={t} toast={toast} onSave={save} />;
    if (category === "personalization") return <div className="settings-card-stack"><Card title={t("settings.theme")}><SettingRow title={t("settings.theme")}><Select label={t("settings.theme")} value={settings.theme} onChange={(value) => void save({ theme: value as SettingsMe["theme"] })}><option value="system">{t("settings.systemTheme")}</option><option value="light">{t("settings.light")}</option><option value="dark">{t("settings.dark")}</option></Select></SettingRow><SettingRow title={t("settings.accentColor")}><div className="accent-palette" role="radiogroup" aria-label={t("settings.accentColor")}>{(["blue", "teal", "green", "violet", "rose", "orange"] as const).map((color) => <button key={color} type="button" role="radio" aria-label={t(`settings.accent.${color}`)} aria-checked={settings.accent_color === color} className={`accent-${color} ${settings.accent_color === color ? "selected" : ""}`} onClick={() => void save({ accent_color: color })} />)}</div></SettingRow></Card><button className="personalization-link-card" type="button" onClick={openWallpaper}><span className="personalization-link-preview" style={{ backgroundImage: `url(${JSON.stringify(settings.wallpaper || "/wallpapers/aurora.svg")})` }}><Image /></span><span><strong>{t("settings.wallpaper")}</strong><small>{t("settings.wallpaperNavigationHint")}</small></span><ChevronRight /></button><Card>{yesNo("window_transparency", t("settings.windowTransparency"))}{yesNo("animations_enabled", t("settings.animations"))}<SettingRow title={t("settings.taskbarAlignment")}><Select label={t("settings.taskbarAlignment")} value={settings.taskbar_alignment} onChange={(value) => void save({ taskbar_alignment: value as SettingsMe["taskbar_alignment"] })}><option value="left">{t("settings.alignLeft")}</option><option value="center">{t("settings.alignCenter")}</option></Select></SettingRow>{yesNo("show_desktop_shortcuts", t("settings.desktopShortcuts"))}{yesNo("widgets_enabled", t("settings.desktopWidgets"))}<SettingRow title={t("settings.desktopShortcutSize")}><Select label={t("settings.desktopShortcutSize")} value={settings.desktop_shortcut_size} onChange={(value) => void save({ desktop_shortcut_size: value as SettingsMe["desktop_shortcut_size"] })}>{["small", "medium", "large"].map((value) => <option key={value} value={value}>{t(`settings.size.${value}`)}</option>)}</Select></SettingRow></Card></div>;
    if (category === "files") return <Card><SettingRow title={t("settings.defaultView")}><Select label={t("settings.defaultView")} value={settings.file_default_view} onChange={(value) => void save({ file_default_view: value as SettingsMe["file_default_view"] })}><option value="list">{t("view.list")}</option><option value="grid">{t("view.medium")}</option><option value="large">{t("view.large")}</option></Select></SettingRow>{yesNo("file_compact_rows", t("settings.compactRows"))}{yesNo("file_show_hidden", t("settings.showHiddenFiles"))}{yesNo("file_confirm_delete", t("settings.confirmDelete"))}{yesNo("file_confirm_overwrite", t("settings.confirmOverwrite"))}<SettingRow title={t("settings.pageSize")}><Select label={t("settings.pageSize")} value={settings.file_page_size} onChange={(value) => void save({ file_page_size: Number(value) as SettingsMe["file_page_size"] })}>{[25, 50, 100, 200].map((value) => <option key={value}>{value}</option>)}</Select></SettingRow><SettingRow title={t("settings.defaultSort")}><Select label={t("settings.defaultSort")} value={settings.file_default_sort} onChange={(value) => void save({ file_default_sort: value as SettingsMe["file_default_sort"] })}>{["name", "size", "type", "modified"].map((value) => <option key={value} value={value}>{t(`column.${value}`)}</option>)}</Select></SettingRow><SettingRow title={t("settings.sortDirection")}><Select label={t("settings.sortDirection")} value={settings.file_sort_direction} onChange={(value) => void save({ file_sort_direction: value as SettingsMe["file_sort_direction"] })}><option value="asc">{t("settings.ascending")}</option><option value="desc">{t("settings.descending")}</option></Select></SettingRow>{yesNo("file_remember_last_path", t("settings.rememberLastPath"))}</Card>;
    if (category === "transfers") return <Card>{yesNo("transfer_success_notifications", t("settings.transferSuccess"))}{yesNo("transfer_error_notifications", t("settings.transferError"))}{yesNo("transfer_open_failed_details", t("settings.openFailedTransfer"))}{yesNo("show_transfer_indicator", t("settings.showTransferIndicator"))}{yesNo("transfer_remember_filter", t("settings.rememberTransferFilter"))}</Card>;
    if (category === "notifications") return <Card>{yesNo("show_notifications", t("settings.notificationsEnabled"))}{yesNo("notification_transfer", t("settings.transferNotifications"))}{yesNo("notification_errors", t("settings.errorNotifications"))}{yesNo("notification_admin", t("settings.adminNotifications"))}<SettingRow title={t("settings.notificationLimit")}><Select label={t("settings.notificationLimit")} value={settings.notification_limit} onChange={(value) => void save({ notification_limit: Number(value) })}>{[3, 5, 7, 10].map((value) => <option key={value}>{value}</option>)}</Select></SettingRow>{yesNo("notification_auto_hide", t("settings.notificationAutoHide"))}</Card>;
    if (category === "accessibility") return <Card><SettingRow title={t("settings.interfaceScale")}><Select label={t("settings.interfaceScale")} value={settings.interface_scale} onChange={(value) => void save({ interface_scale: Number(value) as SettingsMe["interface_scale"] })}>{[90, 100, 110, 125].map((value) => <option key={value} value={value}>{value}%</option>)}</Select></SettingRow>{yesNo("larger_text", t("settings.largerText"))}{yesNo("reduced_motion", t("settings.reduceMotion"), t("settings.systemPreferencesRespected"))}{yesNo("high_contrast", t("settings.highContrast"), t("settings.systemPreferencesRespected"))}{yesNo("strong_active_borders", t("settings.strongActiveBorders"))}{yesNo("always_show_focus", t("settings.alwaysShowFocus"))}</Card>;
    if (category === "language") return <Card><SettingRow title={t("settings.language")}><Select label={t("settings.language")} value={settings.language} onChange={(value) => void save({ language: value as SettingsMe["language"] })}><option value="pl-PL">Polski</option><option value="en-US">English</option></Select></SettingRow><SettingRow title={t("settings.dateFormat")}><Select label={t("settings.dateFormat")} value={settings.date_format} onChange={(value) => void save({ date_format: value as SettingsMe["date_format"] })}><option value="locale">{t("settings.formatLocale")}</option><option value="short">{t("settings.formatShort")}</option><option value="long">{t("settings.formatLong")}</option><option value="iso">ISO 8601</option></Select></SettingRow><SettingRow title={t("settings.timeFormat")}><Select label={t("settings.timeFormat")} value={settings.time_format} onChange={(value) => void save({ time_format: value as SettingsMe["time_format"] })}><option value="24">24 h</option><option value="12">12 h</option></Select></SettingRow><SettingRow title={t("settings.firstDayOfWeek")}><Select label={t("settings.firstDayOfWeek")} value={settings.first_day_of_week} onChange={(value) => void save({ first_day_of_week: value as SettingsMe["first_day_of_week"] })}><option value="locale">{t("settings.formatLocale")}</option><option value="monday">{t("settings.monday")}</option><option value="sunday">{t("settings.sunday")}</option></Select></SettingRow></Card>;
    if (category === "account") return <div className="settings-card-stack"><Card title={t("settings.accountInformation")}><dl className="settings-details"><dt>{t("settings.username")}</dt><dd>{settings.username}</dd><dt>UID</dt><dd>{settings.uid}</dd><dt>GID</dt><dd>{settings.gid}</dd><dt>{t("settings.homeDirectory")}</dt><dd>{settings.home}</dd><dt>{t("settings.shell")}</dt><dd>{settings.shell}</dd><dt>{t("settings.groupsLabel")}</dt><dd>{settings.groups.join(", ") || "—"}</dd><dt>{t("settings.administratorStatus")}</dt><dd>{settings.is_admin ? t("common.yes") : t("common.no")}</dd></dl></Card><PasswordSection t={t} toast={toast} /></div>;
    if (category === "identity") return <Suspense fallback={<div className="loading-state">{t("status.loading")}</div>}><IdentityApp permissions={settings.permissions} embedded t={t} toast={toast} /></Suspense>;
    if (category === "network") return <NetworkSettingsSection isAdmin={settings.is_admin} t={t} />;
    if (category === "networkResources") return <NetworkMountsSettingsSection isAdmin={settings.is_admin} t={t} toast={toast} />;
    if (category === "policies") return <UpdatePoliciesSection t={t} toast={toast} />;
    if (category === "administration") return <AdministrationSection locale={settings.language} t={t} toast={toast} onOpenApp={onOpenApp} />;
    return <div className="settings-card-stack"><Card title="WebNAS"><dl className="settings-details"><dt>{t("settings.applicationName")}</dt><dd>WebNAS</dd><dt>{t("settings.version")}</dt><dd>0.1.0</dd><dt>{t("settings.frontendEnvironment")}</dt><dd>{window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1" ? "development" : "production"}</dd><dt>{t("settings.backendEnvironment")}</dt><dd>FastAPI / Linux</dd><dt>{t("settings.technologies")}</dt><dd>React · TypeScript · FastAPI · lucide-react</dd><dt>{t("settings.license")}</dt><dd>{t("settings.licenseInfo")}</dd></dl><a className="settings-repository" href="https://github.com/chmajster/Algen-server-web-explorer-panel" target="_blank" rel="noreferrer">{t("settings.repository")}</a></Card></div>;
  }

  return <section className="settings-app">
    <aside className="settings-sidebar"><div className="settings-profile"><Settings /><span><strong>{t("app.settings")}</strong><small>{settings.username}</small></span></div><div className="settings-search"><Search /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("settings.search")} aria-label={t("settings.search")} />{query && <button type="button" aria-label={t("action.clear")} onClick={() => setQuery("")}><X /></button>}</div><nav aria-label={t("settings.categories")}>{categories.map((item) => <button key={item} type="button" className={category === item ? "active" : ""} aria-current={category === item ? "page" : undefined} onClick={() => choose(item)}>{categoryIcons[item]}<span>{t(`settings.category.${item}`)}</span></button>)}</nav></aside>
    <main className="settings-main"><header className="settings-header"><div className="settings-title-wrap">{category === "personalization" && personalizationPage === "wallpaper" && !normalizedQuery && <button className="settings-back" type="button" title={t("action.back")} aria-label={t("action.back")} onClick={() => setPersonalizationPage("overview")}><ChevronLeft /></button>}<div><small>{category === "personalization" && personalizationPage === "wallpaper" ? `${t("app.settings")} · ${t("settings.category.personalization")}` : t("app.settings")}</small><h2>{normalizedQuery ? t("settings.searchResults") : category === "personalization" && personalizationPage === "wallpaper" ? t("settings.wallpaper") : t(`settings.category.${category}`)}</h2></div></div><div className={`settings-save-state ${saveState}`} role="status" aria-live="polite">{saveState === "saving" ? t("settings.saving") : saveState === "saved" ? t("settings.saved") : saveState === "error" ? `${t("settings.saveError")}: ${saveError}` : ""}</div><Select label={t("settings.categories")} value={category} onChange={(value) => choose(value as SettingsCategory)}>{categories.map((item) => <option key={item} value={item}>{t(`settings.category.${item}`)}</option>)}</Select></header><div className={`settings-content ${category === "policies" && !normalizedQuery ? "policy-content" : ""} ${category === "identity" && !normalizedQuery ? "identity-content" : ""} ${category === "personalization" && personalizationPage === "wallpaper" ? "wallpaper-content" : ""}`}>{!normalizedQuery && category === "system" && <HostInformationSection language={settings.language} t={t} />}{normalizedQuery ? <div className="settings-search-results">{searchResults.length ? searchResults.map((result) => <button key={`${result.category}:${result.key}`} type="button" onClick={() => result.category === "personalization" && result.key === "wallpaper" ? openWallpaper() : choose(result.category)}>{categoryIcons[result.category]}<span><strong>{result.label}</strong><small>{t(`settings.category.${result.category}`)}</small></span></button>) : <div className="empty-state">{t("settings.noSearchResults")}</div>}</div> : content()}</div></main>
  </section>;
}
