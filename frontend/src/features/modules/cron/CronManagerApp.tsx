import { CalendarClock, ChevronDown, Copy, FileClock, Pencil, Play, Plus, RefreshCw, Search, Square, Stethoscope, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api, type AppJob, type CronDiagnostic, type CronJob, type CronJobInput, type CronLogEntry, type CronManagerStatus, type CronValidation } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { Modal } from "../../../components/Modal";
import "./cron-manager.css";

type Section = "jobs" | "diagnostics" | "logs";
type Action = { kind: "enable" | "disable" | "duplicate" | "delete"; job: CronJob };
const presets = [
  ["minute", "* * * * *"], ["5minutes", "*/5 * * * *"], ["10minutes", "*/10 * * * *"],
  ["15minutes", "*/15 * * * *"], ["30minutes", "*/30 * * * *"], ["hourly", "0 * * * *"],
  ["daily", "0 0 * * *"], ["weekly", "0 0 * * 0"], ["monthly", "0 0 1 * *"], ["reboot", "@reboot"],
] as const;
const emptyJob: CronJobInput = { name: "", description: "", user: "root", schedule: "*/5 * * * *", command: "", working_directory: null, environment: [], timeout_seconds: null, enabled: true };

export function CronManagerApp({ permissions, t, toast }: { permissions: string[]; t: Translate; toast: ToastFn }) {
  const [section, setSection] = useState<Section>("jobs");
  const [status, setStatus] = useState<CronManagerStatus | null>(null);
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [diagnostics, setDiagnostics] = useState<CronDiagnostic[]>([]);
  const [logs, setLogs] = useState<CronLogEntry[]>([]);
  const [logSources, setLogSources] = useState<Array<{ id: string; label: string }>>([]);
  const [logSource, setLogSource] = useState("");
  const [logSearch, setLogSearch] = useState("");
  const [logUser, setLogUser] = useState("");
  const [logJob, setLogJob] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [userFilter, setUserFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [editing, setEditing] = useState<CronJob | "new" | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [details, setDetails] = useState<CronJob | null>(null);
  const [history, setHistory] = useState<{ available: boolean; reason: string; entries: Array<{ id: number; action: string; actor: string; created_at: number }> } | null>(null);
  const [activeJob, setActiveJob] = useState<AppJob | null>(null);
  const can = (permission: string) => permissions.includes(permission) || permissions.includes("cron.admin");
  const canViewLogs = can("cron.logs");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [nextStatus, nextJobs] = await Promise.all([api.cronStatus(), api.cronJobs()]);
      setStatus(nextStatus); setJobs(nextJobs.items);
    } catch (reason) { setError(message(reason, t)); }
    finally { setLoading(false); }
  }, [t]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (section === "diagnostics") void api.cronDiagnostics().then((value) => setDiagnostics(value.items)).catch((reason: unknown) => setError(message(reason, t)));
  }, [section, t]);
  const loadLogs = useCallback(async () => {
    try {
      const value = await api.cronLogs({ source: logSource, search: logSearch, username: logUser, job_id: logJob, limit: 300 });
      setLogs(value.entries); setLogSources(value.sources); if (!logSource && value.source) setLogSource(value.source);
    } catch (reason) { setError(message(reason, t)); }
  }, [logJob, logSearch, logSource, logUser, t]);
  useEffect(() => { if (section === "logs" && canViewLogs) void loadLogs(); }, [canViewLogs, section, loadLogs]);

  const users = useMemo(() => [...new Set(jobs.map((job) => job.user).filter(Boolean))].sort(), [jobs]);
  const visible = useMemo(() => jobs.filter((job) => {
    const needle = search.toLocaleLowerCase();
    return (!needle || `${job.name} ${job.command} ${job.schedule} ${job.user}`.toLocaleLowerCase().includes(needle))
      && (!userFilter || job.user === userFilter) && (!statusFilter || job.status === statusFilter);
  }), [jobs, search, statusFilter, userFilter]);

  function watch(job: AppJob) {
    setActiveJob(job);
    let attempts = 0;
    const poll = async () => {
      try {
        const current = await api.appJob(job.id); setActiveJob(current);
        if (["completed", "failed", "cancelled"].includes(current.status)) { await load(); return; }
      } catch { return; }
      if (++attempts < 100) window.setTimeout(() => void poll(), 500);
    };
    window.setTimeout(() => void poll(), 200);
  }

  async function openDetails(job: CronJob) {
    setDetails(job); setHistory(null);
    if (canViewLogs) {
      try { setHistory(await api.cronHistory(job.id)); } catch { setHistory(null); }
    }
  }

  const dashboard = status?.dashboard;
  return <section className="cron-manager system-app">
    <header className="cron-header"><div><span className="cron-title-icon"><CalendarClock /></span><div><h2>{t("cron.name")}</h2><p>{t("cron.subtitle")}</p></div></div><div className="header-actions">{activeJob && <span className={`cron-job-state ${activeJob.status}`}>{t(`task.${activeJob.status}`)} · {Math.round(activeJob.progress)}%</span>}<button onClick={() => void load()}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button></div></header>
    {status?.blocked_by_proxmox && <div className="cron-warning" role="status">{t("cron.proxmoxBlocked")}</div>}
    <div className="cron-stats"><Stat label={t("cron.stats.active")} value={dashboard?.active ?? 0} /><Stat label={t("cron.stats.inactive")} value={dashboard?.inactive ?? 0} /><Stat label={t("cron.stats.errors")} value={dashboard?.errors ?? 0} danger={Boolean(dashboard?.errors)} /><Stat label={t("cron.stats.recent")} value={dashboard?.recently_run ?? 0} /></div>
    <nav className="cron-tabs" aria-label={t("module.sections")}><button className={section === "jobs" ? "active" : ""} onClick={() => setSection("jobs")}><FileClock />{t("cron.jobs")}</button><button className={section === "diagnostics" ? "active" : ""} onClick={() => setSection("diagnostics")}><Stethoscope />{t("cron.diagnostics")}</button>{can("cron.logs") && <button className={section === "logs" ? "active" : ""} onClick={() => setSection("logs")}><Search />{t("cron.logs")}</button>}</nav>
    {error && <div className="cron-error" role="alert"><span>{error}</span><button onClick={() => void load()}>{t("action.retry")}</button></div>}
    {section === "jobs" && <main className="cron-content">
      <div className="cron-toolbar"><label className="cron-search"><Search /><span className="visually-hidden">{t("action.search")}</span><input aria-label={t("action.search")} placeholder={t("action.search")} value={search} onChange={(event) => setSearch(event.target.value)} /></label><label><span>{t("cron.user")}</span><select aria-label={t("cron.userFilter")} value={userFilter} onChange={(event) => setUserFilter(event.target.value)}><option value="">{t("common.all")}</option>{users.map((value) => <option key={value}>{value}</option>)}</select></label><label><span>{t("cron.status")}</span><select aria-label={t("cron.statusFilter")} value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="">{t("common.all")}</option>{["enabled", "disabled", "external", "invalid"].map((value) => <option key={value} value={value}>{t(`cron.status.${value}`)}</option>)}</select></label>{can("cron.create") && <button className="button-primary" disabled={Boolean(status?.blocked_by_proxmox)} onClick={() => setEditing("new")}><Plus />{t("cron.new")}</button>}</div>
      {loading ? <div className="loading-state">{t("status.loading")}</div> : visible.length ? <JobTable jobs={visible} canEdit={can("cron.edit")} canEnable={can("cron.enable")} canCreate={can("cron.create")} canDelete={can("cron.delete")} t={t} onEdit={setEditing} onAction={setAction} onDetails={(job) => void openDetails(job)} onLogs={(job) => { setLogJob(job.id); setSection("logs"); }} /> : <div className="cron-empty"><CalendarClock /><h3>{search || userFilter || statusFilter ? t("cron.empty.filtered") : t("cron.empty.title")}</h3><p>{t("cron.empty.hint")}</p>{can("cron.create") && !search && !userFilter && !statusFilter && <button className="button-primary" onClick={() => setEditing("new")}><Plus />{t("cron.empty.action")}</button>}</div>}
    </main>}
    {section === "diagnostics" && <main className="cron-content"><div className="cron-section-toolbar"><div><h3>{t("cron.diagnostics")}</h3><p>{t("cron.diagnosticsHint")}</p></div><button onClick={() => void api.cronDiagnostics().then((value) => setDiagnostics(value.items))}><RefreshCw />{t("action.refresh")}</button></div><div className="cron-diagnostics">{diagnostics.map((item) => <article key={item.code} className={item.status}><span aria-hidden="true" /><div><strong>{item.title}</strong><p>{item.detail}</p>{item.recommendation && <small>{item.recommendation}</small>}</div></article>)}</div></main>}
    {section === "logs" && <main className="cron-content"><div className="cron-log-toolbar"><select aria-label={t("cron.logSource")} value={logSource} onChange={(event) => setLogSource(event.target.value)}>{logSources.map((source) => <option key={source.id} value={source.id}>{source.label}</option>)}</select><input aria-label={t("action.search")} placeholder={t("action.search")} value={logSearch} onChange={(event) => setLogSearch(event.target.value)} /><select aria-label={t("cron.userFilter")} value={logUser} onChange={(event) => setLogUser(event.target.value)}><option value="">{t("common.all")}</option>{users.map((value) => <option key={value}>{value}</option>)}</select><select aria-label={t("cron.jobFilter")} value={logJob} onChange={(event) => setLogJob(event.target.value)}><option value="">{t("common.all")}</option>{jobs.map((job) => <option key={job.id} value={job.id}>{job.name}</option>)}</select><button onClick={() => void loadLogs()}><RefreshCw />{t("action.refresh")}</button></div><div className="cron-log-view" aria-live="polite">{logs.length ? logs.map((entry, index) => <code key={`${entry.source}-${index}`}>{entry.message}</code>) : <div className="empty-state">{t("cron.logsEmpty")}</div>}</div></main>}
    {editing && <JobEditor job={editing === "new" ? undefined : editing} t={t} onClose={() => setEditing(null)} onSubmit={async (job, confirmation) => { const response = editing === "new" ? await api.createCronJob(job, confirmation) : await api.updateCronJob(editing.id, job, confirmation); watch(response.job); setEditing(null); toast(t("cron.operationQueued"), "ok", "admin", "cron"); }} />}
    {action && <ActionDialog value={action} t={t} onClose={() => setAction(null)} onSubmit={async (confirmation) => { const response = action.kind === "delete" ? await api.deleteCronJob(action.job.id, confirmation) : action.kind === "duplicate" ? await api.duplicateCronJob(action.job.id, confirmation) : await api.setCronJobEnabled(action.job.id, action.kind === "enable", confirmation); watch(response.job); setAction(null); toast(t("cron.operationQueued"), "ok", "admin", "cron"); }} />}
    {details && <Details job={details} history={history} t={t} onClose={() => setDetails(null)} />}
  </section>;
}

function Stat({ label, value, danger = false }: { label: string; value: number; danger?: boolean }) { return <article className={danger ? "danger" : ""}><span>{label}</span><strong>{value}</strong></article>; }

function JobTable({ jobs, canEdit, canEnable, canCreate, canDelete, t, onEdit, onAction, onDetails, onLogs }: { jobs: CronJob[]; canEdit: boolean; canEnable: boolean; canCreate: boolean; canDelete: boolean; t: Translate; onEdit: (job: CronJob) => void; onAction: (action: Action) => void; onDetails: (job: CronJob) => void; onLogs: (job: CronJob) => void }) {
  return <div className="cron-table-wrap"><table><thead><tr>{["name", "schedule", "user", "command", "status", "source", "lastRun", "nextRun", "actions"].map((key) => <th key={key}>{t(`cron.column.${key}`)}</th>)}</tr></thead><tbody>{jobs.map((job) => <tr key={job.id}><td data-label={t("cron.column.name")}><button className="cron-name" onClick={() => onDetails(job)}>{job.name}</button></td><td data-label={t("cron.column.schedule")}><code>{job.schedule}</code></td><td data-label={t("cron.column.user")}>{job.user}</td><td data-label={t("cron.column.command")}><code title={job.command}>{job.command}</code></td><td data-label={t("cron.column.status")}><span className={`cron-status ${job.status}`}>{t(`cron.status.${job.status}`)}</span></td><td data-label={t("cron.column.source")}><span title={job.source_label}>{job.source === "webnas" ? "WebNAS" : t("cron.external")}</span></td><td data-label={t("cron.column.lastRun")}>{time(job.last_run_at, t)}</td><td data-label={t("cron.column.nextRun")}>{time(job.next_run_at, t)}</td><td data-label={t("cron.column.actions")}><div className="cron-row-actions">{!job.read_only && canEdit && <button aria-label={`${t("action.edit")}: ${job.name}`} title={t("action.edit")} onClick={() => onEdit(job)}><Pencil /></button>}{!job.read_only && canEnable && <button aria-label={`${t(job.enabled ? "cron.disable" : "cron.enable")}: ${job.name}`} title={t(job.enabled ? "cron.disable" : "cron.enable")} onClick={() => onAction({ kind: job.enabled ? "disable" : "enable", job })}>{job.enabled ? <Square /> : <Play />}</button>}{!job.read_only && canCreate && <button aria-label={`${t("cron.duplicate")}: ${job.name}`} title={t("cron.duplicate")} onClick={() => onAction({ kind: "duplicate", job })}><Copy /></button>}<button aria-label={`${t("cron.details")}: ${job.name}`} title={t("cron.details")} onClick={() => onDetails(job)}><ChevronDown /></button><button aria-label={`${t("cron.logs")}: ${job.name}`} title={t("cron.logs")} onClick={() => onLogs(job)}><FileClock /></button>{!job.read_only && canDelete && <button className="danger" aria-label={`${t("action.delete")}: ${job.name}`} title={t("action.delete")} onClick={() => onAction({ kind: "delete", job })}><Trash2 /></button>}</div></td></tr>)}</tbody></table></div>;
}

function JobEditor({ job, t, onClose, onSubmit }: { job?: CronJob; t: Translate; onClose: () => void; onSubmit: (job: CronJobInput, confirmation: { confirmation: string; pam_password: string }) => Promise<void> }) {
  const [value, setValue] = useState<CronJobInput>(job ? { name: job.name, description: job.description, user: job.user, schedule: job.schedule, command: job.command, working_directory: job.working_directory, environment: job.environment, timeout_seconds: job.timeout_seconds, enabled: job.enabled } : emptyJob);
  const [mode, setMode] = useState<"simple" | "advanced">(presets.some(([, schedule]) => schedule === value.schedule) ? "simple" : "advanced");
  const [environment, setEnvironment] = useState(value.environment.map((item) => `${item.name}=${item.value}`).join("\n"));
  const [confirmation, setConfirmation] = useState(""); const [password, setPassword] = useState(""); const [validation, setValidation] = useState<CronValidation | null>(null); const [validationError, setValidationError] = useState(""); const [saving, setSaving] = useState(false); const [error, setError] = useState("");
  const expected = job?.id || "cron:create";
  const fields = value.schedule === "@reboot" ? ["0", "0", "*", "*", "*"] : value.schedule.split(" ").length === 5 ? value.schedule.split(" ") : ["*", "*", "*", "*", "*"];
  const envValues = () => parseEnvironment(environment, t);
  useEffect(() => {
    setValidation(null); setValidationError("");
    const timer = window.setTimeout(() => {
      try {
        const next = { schedule: value.schedule, user: value.user, command: value.command, working_directory: value.working_directory, timeout_seconds: value.timeout_seconds, environment: parseEnvironment(environment, t) };
        if (!next.schedule || !next.command || !next.user) return;
        void api.validateCronJob(next).then(setValidation).catch((reason: unknown) => setValidationError(message(reason, t)));
      } catch (reason) { setValidationError(message(reason, t)); }
    }, 350);
    return () => window.clearTimeout(timer);
  }, [value.schedule, value.user, value.command, value.working_directory, value.timeout_seconds, environment, t]);
  function updateField(index: number, next: string) { const values = [...fields]; values[index] = next || "*"; setValue((current) => ({ ...current, schedule: values.join(" ") })); }
  async function submit(event: React.FormEvent) { event.preventDefault(); setSaving(true); setError(""); try { await onSubmit({ ...value, environment: envValues() }, { confirmation, pam_password: password }); } catch (reason) { setError(message(reason, t)); setSaving(false); } }
  return <Modal title={t(job ? "cron.edit" : "cron.new")} closeLabel={t("action.close")} onClose={onClose} wide footer={<><button onClick={onClose}>{t("action.cancel")}</button><button className="button-primary" type="submit" form="cron-job-form" disabled={saving || !validation?.valid}>{saving ? t("status.loading") : t("action.save")}</button></>}>
    <form id="cron-job-form" className="cron-form" onSubmit={submit}><fieldset><legend>{t("cron.basic")}</legend><label>{t("common.name")}<input autoFocus required value={value.name} onChange={(event) => setValue({ ...value, name: event.target.value })} /></label><label className="span-2">{t("common.description")}<textarea value={value.description} onChange={(event) => setValue({ ...value, description: event.target.value })} /></label><label>{t("cron.user")}<input required value={value.user} onChange={(event) => setValue({ ...value, user: event.target.value })} /></label><label className="cron-checkbox"><input type="checkbox" checked={value.enabled} onChange={(event) => setValue({ ...value, enabled: event.target.checked })} />{t("cron.enabled")}</label></fieldset>
      <fieldset><legend>{t("cron.schedule")}</legend><div className="cron-mode" role="group" aria-label={t("cron.scheduleMode")}><button type="button" className={mode === "simple" ? "active" : ""} onClick={() => setMode("simple")}>{t("cron.simple")}</button><button type="button" className={mode === "advanced" ? "active" : ""} onClick={() => setMode("advanced")}>{t("cron.advanced")}</button></div>{mode === "simple" ? <><label className="span-2">{t("cron.preset")}<select value={presets.find(([, schedule]) => schedule === value.schedule)?.[1] || "custom"} onChange={(event) => event.target.value !== "custom" && setValue({ ...value, schedule: event.target.value })}><option value="custom">{t("cron.custom")}</option>{presets.map(([name, schedule]) => <option key={name} value={schedule}>{t(`cron.preset.${name}`)}</option>)}</select></label>{value.schedule !== "@reboot" && <div className="cron-fields span-2">{["minute", "hour", "day", "month", "weekday"].map((name, index) => <label key={name}>{t(`cron.field.${name}`)}<input value={fields[index]} onChange={(event) => updateField(index, event.target.value)} /></label>)}</div>}</> : <label className="span-2">{t("cron.expression")}<input required className="cron-expression" value={value.schedule} onChange={(event) => setValue({ ...value, schedule: event.target.value })} placeholder="*/5 * * * *" /></label>}<div className={`cron-preview span-2 ${validationError ? "invalid" : ""}`} aria-live="polite"><code>{value.schedule}</code><p>{validationError || validation?.explanation || t("cron.validating")}</p>{validation?.next_run_at && <small>{t("cron.nextRun")}: {time(validation.next_run_at, t)}</small>}</div></fieldset>
      <fieldset><legend>{t("cron.command")}</legend><label className="span-2">{t("cron.command")}<textarea className="cron-command" required value={value.command} onChange={(event) => setValue({ ...value, command: event.target.value })} placeholder="/usr/local/bin/backup.sh" /></label><label>{t("cron.workingDirectory")}<input value={value.working_directory || ""} onChange={(event) => setValue({ ...value, working_directory: event.target.value || null })} placeholder="/srv/backups" /></label><label>{t("cron.timeout")}<input type="number" min="1" max="604800" value={value.timeout_seconds || ""} onChange={(event) => setValue({ ...value, timeout_seconds: event.target.value ? Number(event.target.value) : null })} /></label><label className="span-2">{t("cron.environment")}<textarea value={environment} onChange={(event) => setEnvironment(event.target.value)} placeholder="LANG=pl_PL.UTF-8" /><small>{t("cron.environmentHint")}</small></label>{validation?.generated_entry && <label className="span-2">{t("cron.generatedEntry")}<pre>{validation.generated_entry}</pre></label>}{validation?.warnings.map((warning) => <p className="cron-form-warning span-2" key={warning}>{warning}</p>)}</fieldset>
      <fieldset><legend>{t("cron.confirmation")}</legend><p className="span-2">{t("cron.confirmationHint").replace("{value}", expected)}</p><label>{t("cron.confirmationValue")}<input required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label><label>{t("cron.currentPassword")}<input required type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label></fieldset>{error && <div className="cron-error span-2" role="alert">{error}</div>}
    </form>
  </Modal>;
}

function ActionDialog({ value, t, onClose, onSubmit }: { value: Action; t: Translate; onClose: () => void; onSubmit: (confirmation: { confirmation: string; pam_password: string }) => Promise<void> }) {
  const expected = value.kind === "delete" ? value.job.name : value.job.id; const [confirmation, setConfirmation] = useState(""); const [password, setPassword] = useState(""); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent) { event.preventDefault(); setBusy(true); try { await onSubmit({ confirmation, pam_password: password }); } catch (reason) { setError(message(reason, t)); setBusy(false); } }
  return <Modal title={t(`cron.action.${value.kind}`)} closeLabel={t("action.close")} onClose={onClose} footer={<><button onClick={onClose}>{t("action.cancel")}</button><button type="submit" form="cron-action-form" className={value.kind === "delete" ? "button-danger" : "button-primary"} disabled={busy}>{t("action.confirm")}</button></>}><form id="cron-action-form" className="cron-action-form" onSubmit={submit}><p>{value.kind === "delete" ? t("cron.deleteHint").replace("{name}", value.job.name) : t("cron.actionHint").replace("{name}", value.job.name)}</p><label>{t("cron.confirmationHint").replace("{value}", expected)}<input autoFocus required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label><label>{t("cron.currentPassword")}<input required type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>{error && <div className="cron-error" role="alert">{error}</div>}</form></Modal>;
}

function Details({ job, history, t, onClose }: { job: CronJob; history: { available: boolean; reason: string; entries: Array<{ id: number; action: string; actor: string; created_at: number }> } | null; t: Translate; onClose: () => void }) {
  return <Modal title={job.name} closeLabel={t("action.close")} onClose={onClose} wide footer={<button onClick={onClose}>{t("action.close")}</button>}><div className="cron-details"><dl><dt>{t("cron.schedule")}</dt><dd><code>{job.schedule}</code></dd><dt>{t("cron.user")}</dt><dd>{job.user}</dd><dt>{t("cron.command")}</dt><dd><code>{job.command}</code></dd><dt>{t("cron.workingDirectory")}</dt><dd>{job.working_directory || t("cron.noData")}</dd><dt>{t("cron.timeout")}</dt><dd>{job.timeout_seconds || t("cron.noData")}</dd><dt>{t("cron.column.source")}</dt><dd>{job.source_label}</dd><dt>{t("cron.nextRun")}</dt><dd>{time(job.next_run_at, t)}</dd></dl><section><h3>{t("cron.history")}</h3>{history?.entries.length ? history.entries.map((entry) => <article key={entry.id}><strong>{entry.action}</strong><span>{entry.actor}</span><time>{time(entry.created_at, t)}</time></article>) : <p>{history?.reason || t("status.loading")}</p>}</section></div></Modal>;
}

function time(value: number | null, t: Translate) { return value ? new Date(value * 1000).toLocaleString() : t("cron.noData"); }
function parseEnvironment(value: string, t: Translate) { return value.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => { const index = line.indexOf("="); if (index < 1) throw new Error(t("cron.environmentInvalid")); return { name: line.slice(0, index).trim(), value: line.slice(index + 1) }; }); }
function message(error: unknown, t: Translate) { if (error instanceof ApiError && error.code) { const key = `cron.error.${error.code}`; const translated = t(key); if (translated !== key) return translated; } return error instanceof Error ? error.message : t("error.generic"); }
