import { Copy, Download, FileCheck2, FileText, FolderOpen, Play, Plus, RefreshCw, RotateCcw, Save, Square, Stethoscope, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type ModuleBackup, type ModuleConfig, type ModuleDiagnostic, type ModuleJob, type ModuleStatus, type ModuleSummary, type SambaConfig, type SambaModuleUser, type SambaSession, type SambaShare, type SambaShareAccess } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { AdminActionDialog } from "../../admin/AdminActionDialog";
import { PackageActionDialog } from "../../package-center/PackageActionDialog";
import { PackageJobDialog } from "../../package-center/PackageJobDialog";
import { ModuleApplyPlanDialog } from "../common/ModuleApplyPlanDialog";
import { ModuleAppShell, ModuleHealthCard, translateModuleOperation, translateServiceState, type ModuleSection } from "../common/ModuleAppShell";
import { ModuleBackups, ModuleDangerZone, ModuleDiagnostics, ModuleJobProgress, ModuleLogs, ModuleServiceControls } from "../common/ModuleComponents";
import { ModuleUninstallDialog } from "../common/ModuleUninstallDialog";
import { SambaShareEditor } from "./SambaShareEditor";

const emptyStatus: ModuleStatus = { installed: false, update_available: false, service_state: "unknown", service_enabled: false, services: {}, health: "unknown", health_message: "", last_action: "", last_action_status: "", last_error: "", metrics: {} };
type Dialog = { type: "service"; action: "start" | "stop" | "restart" | "reload" | "enable" | "disable" } | { type: "diagnostics" } | { type: "backup" } | { type: "restore"; backup: ModuleBackup } | { type: "deleteBackup"; backup: ModuleBackup } | { type: "user"; action: "add" | "password" | "enable" | "disable" | "remove"; user: SambaModuleUser } | { type: "firewall" } | null;

export function SambaModuleApp({ initialSharePath, readOnly = false, canReinstall = false, t, toast, onOpenFolder, onDirtyChange }: { initialSharePath?: string; readOnly?: boolean; canReinstall?: boolean; t: Translate; toast: ToastFn; onOpenFolder: (path: string) => void; onDirtyChange: (dirty: boolean) => void }) {
  const [summary, setSummary] = useState<ModuleSummary | null>(null);
  const [status, setStatus] = useState(emptyStatus);
  const [config, setConfig] = useState<SambaConfig>({ shares: [], global_options: {} });
  const [savedConfig, setSavedConfig] = useState<SambaConfig>({ shares: [], global_options: {} });
  const [section, setSection] = useState<ModuleSection>("overview");
  const [loading, setLoading] = useState(true);
  const [job, setJob] = useState<ModuleJob | null>(null);
  const [liveJob, setLiveJob] = useState<ModuleJob | null>(null);
  const [diagnostics, setDiagnostics] = useState<ModuleDiagnostic[]>([]);
  const [backups, setBackups] = useState<ModuleBackup[]>([]);
  const [users, setUsers] = useState<SambaModuleUser[]>([]);
  const [sessions, setSessions] = useState<SambaSession[]>([]);
  const [shareAccess, setShareAccess] = useState<Record<string, SambaShareAccess>>({});
  const [firewall, setFirewall] = useState<{ adapter: string; ports: string[]; can_manage: boolean; plan: string[][] }>({ adapter: "unsupported", ports: [], can_manage: false, plan: [] });
  const [dialog, setDialog] = useState<Dialog>(null);
  const [reinstallOpen, setReinstallOpen] = useState(false);
  const [uninstallOpen, setUninstallOpen] = useState(false);
  const [editing, setEditing] = useState<SambaShare | "new" | null>(null);
  const [validation, setValidation] = useState<Awaited<ReturnType<typeof api.validateModuleConfig>> | null>(null);
  const initialShareHandled = useRef(false);
  const dirty = useMemo(() => JSON.stringify(config) !== JSON.stringify(savedConfig), [config, savedConfig]);
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);
  useEffect(() => { const beforeUnload = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); }; window.addEventListener("beforeunload", beforeUnload); return () => window.removeEventListener("beforeunload", beforeUnload); }, [dirty]);

  const refresh = useCallback(async (quiet = false) => { if (!quiet) setLoading(true); try { const [nextStatus, nextConfig, nextFirewall, nextSummary] = await Promise.all([api.moduleStatus("samba"), api.moduleConfig("samba"), api.sambaFirewall(), api.module("samba")]); const samba = nextConfig as unknown as SambaConfig; setStatus(nextStatus); setFirewall(nextFirewall); setSummary(nextSummary); if (!dirty) { setConfig(samba); setSavedConfig(samba); } if (initialSharePath && !initialShareHandled.current) { initialShareHandled.current = true; setSection("shares"); setEditing(samba.shares.find((item) => item.path === initialSharePath) || { ...samba.shares[0], name: "", path: initialSharePath, comment: "", enabled: true, browseable: true, read_only: true, guest_ok: false, valid_users: [], valid_groups: [], write_list: [], read_list: [], admin_users: [], force_user: null, force_group: null, force_create_mode: "", force_directory_mode: "", inherit_permissions: false, veto_files: "", recycle_bin: false, recycle_versions: true, create_directory: false, directory_owner: "", directory_group: "", directory_mode: "", advanced_options: {}, create_mask: "0664", directory_mask: "0775" }); } const active = await api.appJobs("", "samba"); setJob(active.find((item) => ["queued", "running"].includes(item.status)) || active[0] || null); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin"); } finally { if (!quiet) setLoading(false); } }, [dirty, initialSharePath, t, toast]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { const timer = window.setInterval(() => { if (!document.hidden) void refresh(true); }, 5000); return () => window.clearInterval(timer); }, [refresh]);
  useEffect(() => { if (job && !["queued", "running", "waiting_for_confirmation"].includes(job.status)) setJob(null); }, [job]);
  useEffect(() => { if (!job || !["queued", "running"].includes(job.status) || typeof EventSource === "undefined") return; const source = new EventSource(`/api/modules/samba/jobs/${encodeURIComponent(job.id)}/events`); source.onmessage = (event) => { const next = JSON.parse(event.data) as ModuleJob; setJob(next); if (next.status === "completed") { if (next.action === "apply" || next.action === "restore") { setSavedConfig(config); } void refresh(true); if (next.result?.diagnostics) setDiagnostics(next.result.diagnostics as ModuleDiagnostic[]); } if (next.status === "failed") toast(next.error || t("module.jobFailed"), "error", "admin"); }; source.onerror = () => source.close(); return () => source.close(); }, [config, job, refresh, t, toast]);
  useEffect(() => { if (section === "users") void api.sambaModuleUsers().then(setUsers).catch((error: unknown) => toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin")); if (section === "sessions") void api.sambaSessions().then(setSessions).catch((error: unknown) => toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin")); if (section === "shares") void Promise.all(config.shares.map((share) => api.testSambaShare(share.name))).then((items) => setShareAccess(Object.fromEntries(items.map((item) => [item.share, item])))).catch(() => undefined); if (section === "diagnostics") void api.moduleDiagnostics("samba").then((data) => setDiagnostics(data.diagnostics)); if (section === "backups") void api.moduleBackups("samba").then(setBackups); }, [config.shares, section, t, toast]);

  async function validateAndPlan() { const result = await api.validateModuleConfig("samba", config as unknown as ModuleConfig); setValidation(result); }
  function trackJob(next: ModuleJob) { setJob(next); setLiveJob(next); }
  async function apply(confirmations: string[]) { const result = await api.applyModuleConfig("samba", config as unknown as ModuleConfig, confirmations); trackJob(result.job); toast(t("module.jobQueued"), "ok", "admin"); }
  async function submit(values: Record<string, string>) { if (!dialog) return; if (dialog.type === "service") trackJob((await api.moduleService("samba", dialog.action)).job); else if (dialog.type === "diagnostics") trackJob((await api.runModuleDiagnostics("samba")).job); else if (dialog.type === "backup") { await api.createModuleBackup("samba", values.description); setBackups(await api.moduleBackups("samba")); } else if (dialog.type === "restore") trackJob((await api.restoreModuleBackup("samba", dialog.backup.id)).job); else if (dialog.type === "deleteBackup") { await api.deleteModuleBackup("samba", dialog.backup.id); setBackups(await api.moduleBackups("samba")); } else if (dialog.type === "user") { await api.sambaModuleUserAction(dialog.user.username, dialog.action, values.password); setUsers(await api.sambaModuleUsers()); } else if (dialog.type === "firewall") { await api.openSambaFirewall(); setFirewall(await api.sambaFirewall()); } toast(t("admin.actionCompleted"), "ok", "admin"); }
  function saveShare(next: SambaShare) { setConfig((current) => ({ ...current, shares: [...current.shares.filter((item) => item.name !== (editing === "new" ? "" : editing?.name)), next] })); setEditing(null); }
  function duplicate(share: SambaShare) { setEditing({ ...share, name: `${share.name}-copy`, enabled: false }); }
  function removeShare(share: SambaShare) { setConfig((current) => ({ ...current, shares: current.shares.filter((item) => item.name !== share.name) })); }
  function toggleShare(share: SambaShare) { setConfig((current) => ({ ...current, shares: current.shares.map((item) => item.name === share.name ? { ...item, enabled: !item.enabled } : item) })); }

  const sections: ModuleSection[] = ["overview", "shares", "users", "sessions", "configuration", "service", "logs", "diagnostics", "backups", "info"];
  const metrics = status.metrics as { shares?: number; sessions?: number; users?: number; ports?: Record<string, boolean>; uptime_seconds?: number | null; last_restart?: number | null };
  const uptimeText = metrics.uptime_seconds == null ? t("module.notAvailable") : t("module.samba.uptimeValue").replace("{days}", String(Math.floor(metrics.uptime_seconds / 86400))).replace("{hours}", String(Math.floor(metrics.uptime_seconds % 86400 / 3600))).replace("{minutes}", String(Math.floor(metrics.uptime_seconds % 3600 / 60)));
  const busy = Boolean(job && ["queued", "running", "waiting_for_confirmation"].includes(job.status));
  const serviceActive = status.service_state === "active";
  const healthMessage = sambaHealthMessage(status, t);
  let content: React.ReactNode;
  if (loading) content = <div className="module-skeleton">{Array.from({ length: 6 }, (_, index) => <span key={index} />)}</div>;
  else if (section === "overview") content = <>
    <div className="module-health-grid samba-overview-grid">
      <ModuleHealthCard title={t("module.packageState")} value={status.installed ? t("common.enabled") : t("common.disabled")} tone={status.installed ? "success" : "warning"} />
      <ModuleHealthCard title="smbd" value={translateServiceState(status.services.smbd?.state || "unknown", t)} tone={serviceTone(status.services.smbd?.state)} />
      <ModuleHealthCard title="nmbd" value={translateServiceState(status.services.nmbd?.state || "unknown", t)} tone={serviceTone(status.services.nmbd?.state)} />
      <ModuleHealthCard title="winbind" value={translateServiceState(status.services.winbind?.state || "unknown", t)} tone={serviceTone(status.services.winbind?.state)} />
      <ModuleHealthCard title={t("module.samba.autostart")} value={status.service_enabled ? t("common.yes") : t("common.no")} tone={status.service_enabled ? "success" : "warning"} />
      <ModuleHealthCard title={t("module.configurationValid")} value={status.configuration_valid == null ? t("module.notAvailable") : status.configuration_valid ? t("common.yes") : t("common.no")} tone={status.configuration_valid == null ? "warning" : status.configuration_valid ? "success" : "danger"} />
      <ModuleHealthCard title={t("module.samba.uptime")} value={uptimeText} />
      <ModuleHealthCard title={t("module.samba.lastRestart")} value={metrics.last_restart ? new Date(metrics.last_restart * 1000).toLocaleString() : t("module.notAvailable")} />
      <ModuleHealthCard title={t("module.samba.sharesCount")} value={metrics.shares || 0} />
      <ModuleHealthCard title={t("module.samba.sessionsCount")} value={metrics.sessions || 0} />
      <ModuleHealthCard title={t("module.samba.usersCount")} value={metrics.users || 0} />
      <ModuleHealthCard title={t("module.samba.lastAction")} value={status.last_action ? translateModuleOperation(status.last_action, t) : t("module.notAvailable")} detail={status.last_action_time ? new Date(status.last_action_time * 1000).toLocaleString() : undefined} />
      <ModuleHealthCard title={t("module.lastError")} value={status.last_error || t("common.none")} tone={status.last_error ? "danger" : "success"} />
      <ModuleHealthCard title={t("module.samba.firewall")} value={firewall.adapter === "unsupported" ? t("module.notAvailable") : firewall.adapter.toUpperCase()} detail={firewall.ports.join(", ")} tone={firewall.can_manage ? "neutral" : "warning"} />
    </div>
    {firewall.can_manage && <div className="module-section-toolbar"><button type="button" onClick={() => setDialog({ type: "firewall" })}>{t("module.samba.openFirewall")}</button></div>}
    {busy && job && <ModuleJobProgress job={job} t={t} />}
  </>;
  else if (section === "shares") content = <section className="samba-shares"><header><div><h3>{t("module.section.shares")}</h3><p>{t("module.samba.sharesHint")}</p></div><button type="button" onClick={() => setEditing("new")}><Plus />{t("samba.addShare")}</button></header><div className="module-table-wrap"><table><thead><tr><th>{t("samba.shareName")}</th><th>{t("files.fullPath")}</th><th>{t("samba.comment")}</th><th>{t("common.enabled")}</th><th>{t("files.readOnly")}</th><th>{t("module.samba.guestAccess")}</th><th>{t("module.samba.browseable")}</th><th>{t("module.samba.allowedAccounts")}</th><th>{t("module.samba.masks")}</th><th>{t("module.samba.pathStatus")}</th><th>{t("module.warnings")}</th><th>{t("column.actions")}</th></tr></thead><tbody>{config.shares.map((share) => { const access = shareAccess[share.name]; return <tr key={share.name}><td><strong>{share.name}</strong></td><td><code>{share.path}</code></td><td>{share.comment || "—"}</td><td>{share.enabled ? t("common.yes") : t("common.no")}</td><td>{share.read_only ? t("common.yes") : t("common.no")}</td><td>{share.guest_ok ? t("common.yes") : t("common.no")}</td><td>{share.browseable ? t("common.yes") : t("common.no")}</td><td>{[...share.valid_users, ...(share.valid_groups || []).map((item) => `@${item}`)].join(", ") || "—"}</td><td><code>{share.create_mask} / {share.directory_mask}</code></td><td><span className={`module-path-state ${access?.ok ? "ok" : access ? "error" : "unknown"}`}>{access ? access.ok ? t("module.samba.pathAvailable") : t("module.samba.pathUnavailable") : t("module.samba.notTested")}</span></td><td>{access ? [...access.warnings, ...access.errors].join("; ") || t("common.none") : "—"}</td><td><div className="module-row-actions"><button title={t("action.edit")} onClick={() => setEditing(share)}>{t("action.edit")}</button><button title={t("module.samba.testAccess")} onClick={() => void api.testSambaShare(share.name).then((result) => setShareAccess((current) => ({ ...current, [share.name]: result })))}>{t("module.samba.testAccess")}</button><button title={t("module.samba.duplicate")} onClick={() => duplicate(share)}><Copy /></button><button title={share.enabled ? t("common.disabled") : t("common.enabled")} onClick={() => toggleShare(share)}>{share.enabled ? <Square /> : <Play />}</button><button title={t("files.openNewWindow")} onClick={() => onOpenFolder(share.path)}><FolderOpen /></button><button className="danger" title={t("action.delete")} onClick={() => removeShare(share)}><Trash2 /></button></div></td></tr>; })}</tbody></table></div></section>;
  else if (section === "configuration") content = <SambaGlobalConfiguration config={config} t={t} onChange={setConfig} onImport={(next) => { setConfig(next); toast(t("module.importValidated")); }} />;
  else if (section === "service") content = <><ModuleServiceControls status={status} disabled={Boolean(job && ["queued", "running"].includes(job.status))} t={t} onAction={(action) => setDialog({ type: "service", action })} /><div className="module-service-list">{Object.entries(status.services).map(([name, service]) => <article key={name}><strong>{name}</strong><span>{service.state}</span><span>{service.enabled ? t("module.enabledAtBoot") : t("module.disabledAtBoot")}</span><small>{service.required ? t("module.required") : t("module.optional")}</small></article>)}</div></>;
  else if (section === "logs") content = <ModuleLogs moduleId="samba" t={t} toast={toast} />;
  else if (section === "diagnostics") content = <><div className="module-section-toolbar"><button onClick={() => setDialog({ type: "diagnostics" })}><Stethoscope />{t("module.runDiagnostics")}</button></div><ModuleDiagnostics diagnostics={diagnostics} t={t} /></>;
  else if (section === "backups") content = <ModuleBackups backups={backups} t={t} onCreate={() => setDialog({ type: "backup" })} onRestore={(backup) => setDialog({ type: "restore", backup })} onDelete={(backup) => setDialog({ type: "deleteBackup", backup })} />;
  else if (section === "users") content = <SambaUsers users={users} t={t} onAction={(action, user) => setDialog({ type: "user", action, user })} />;
  else if (section === "sessions") content = <SambaSessions sessions={sessions} t={t} onRefresh={() => void api.sambaSessions().then(setSessions)} />;
  else content = <><section className="module-info"><h3>{t("module.information")}</h3><dl><dt>{t("module.version")}</dt><dd>{status.package_version || "—"}</dd><dt>{t("module.homepage")}</dt><dd><a href="https://www.samba.org" target="_blank" rel="noreferrer">samba.org</a></dd><dt>{t("module.license")}</dt><dd>GPL-3.0-or-later</dd></dl></section><ModuleDangerZone name="Samba" t={t} onUninstall={() => setUninstallOpen(true)} /></>;

  return <>
    <ModuleAppShell
      name="Samba"
      status={status}
      healthMessage={healthMessage}
      activeJob={busy && job ? { operation: job.operation || job.action, progress: job.progress } : null}
      section={section}
      sections={sections}
      t={t}
      onSection={setSection}
      actions={<>
        {!readOnly && <>
          <button className={!serviceActive ? "button-primary" : ""} type="button" disabled={busy || serviceActive} onClick={() => setDialog({ type: "service", action: "start" })}><Play />{t("module.start")}</button>
          <button type="button" disabled={busy || !serviceActive} onClick={() => setDialog({ type: "service", action: "stop" })}><Square />{t("module.stop")}</button>
          <button type="button" disabled={busy || !status.installed} onClick={() => setDialog({ type: "service", action: "restart" })}><RotateCcw />{t("module.restart")}</button>
          <button type="button" disabled={busy || !status.installed} onClick={() => setDialog({ type: "service", action: "reload" })}><RefreshCw />{t("module.reload")}</button>
          <button type="button" disabled={busy || !status.installed} onClick={() => void validateAndPlan()}><FileCheck2 />{t("module.checkConfiguration")}</button>
        </>}
        <button type="button" onClick={() => setSection("logs")}><FileText />{t("module.section.logs")}</button>
      </>}
    >
      <fieldset className="module-readonly" disabled={readOnly}>{content}</fieldset>
      {section === "configuration" && canReinstall && summary?.state.installed && summary.capabilities.update && <section className="module-info"><h3>{t("module.packageMaintenance")}</h3><p>{t("module.reinstallHint")}</p><div className="module-section-toolbar"><button type="button" disabled={busy} onClick={() => setReinstallOpen(true)}><RefreshCw />{t("store.reinstall")}</button></div></section>}
    </ModuleAppShell>
    {!readOnly && dirty && <div className="module-save-bar" role="status"><span><i />{t("module.unsavedChanges")}</span><button type="button" onClick={() => setConfig(savedConfig)}>{t("action.cancel")}</button><button className="button-primary" type="button" onClick={() => void validateAndPlan()}><Save />{t("module.reviewAndApply")}</button></div>}
    {!readOnly && editing && <SambaShareEditor share={editing === "new" ? undefined : editing} t={t} onClose={() => setEditing(null)} onSave={saveShare} />}
    {!readOnly && validation && <ModuleApplyPlanDialog validation={validation} t={t} onClose={() => setValidation(null)} onApply={apply} />}
    {canReinstall && reinstallOpen && summary && <PackageActionDialog item={summary} action="reinstall" t={t} toast={toast} onClose={() => setReinstallOpen(false)} onStarted={(started) => { trackJob(started); void refresh(true); }} />}
    {!readOnly && uninstallOpen && summary && <ModuleUninstallDialog item={summary} activeShares={config.shares.filter((item) => item.enabled).length} activeSessions={sessions.length || Number(metrics.sessions || 0)} t={t} toast={toast} onClose={() => setUninstallOpen(false)} onStarted={(started) => { trackJob(started); void refresh(true); }} />}
    {liveJob && <PackageJobDialog initialJob={liveJob} moduleName="Samba" t={t} onClose={() => setLiveJob(null)} />}
    {!readOnly && dialog && <AdminActionDialog title={dialog.type === "service" ? t(`module.${dialog.action}`) : dialog.type === "diagnostics" ? t("module.runDiagnostics") : dialog.type === "backup" ? t("module.createBackup") : dialog.type === "restore" ? t("module.restore") : dialog.type === "deleteBackup" ? t("module.deleteBackup") : dialog.type === "firewall" ? t("module.samba.openFirewall") : t(`module.samba.userAction.${dialog.action}`)} description={dialog.type === "firewall" ? <div className="module-firewall-plan"><strong>{t("module.changePlan")}</strong><p>{t("module.samba.firewallPlanHint")}</p><pre>{firewall.plan.map((command) => command.join(" ")).join("\n")}</pre></div> : undefined} fields={[...(dialog.type === "backup" ? [{ name: "description", label: t("module.backupDescription") }] : []), ...(dialog.type === "user" && ["add", "password"].includes(dialog.action) ? [{ name: "password", label: t("auth.password"), type: "password" as const, required: true }] : [])]} danger={dialog.type === "deleteBackup" || dialog.type === "restore" || dialog.type === "firewall" || dialog.type === "service" && ["stop", "restart"].includes(dialog.action)} t={t} onClose={() => setDialog(null)} onSubmit={submit} />}
  </>;
}

function serviceTone(state?: string): "neutral" | "success" | "warning" | "danger" {
  if (state === "active") return "success";
  if (state === "failed" || state === "error") return "danger";
  if (!state || ["unknown", "unavailable"].includes(state)) return "warning";
  return "neutral";
}

function sambaHealthMessage(status: ModuleStatus, t: Translate): string {
  if (!status.installed) return t("module.samba.healthNotInstalled");
  if (status.health === "healthy") return t("module.samba.healthHealthy");
  if (status.configuration_valid === false) return t("module.samba.healthInvalidConfiguration");
  return t("module.samba.healthServiceInactive");
}

function SambaGlobalConfiguration({ config, t, onChange, onImport }: { config: SambaConfig; t: Translate; onChange: (config: SambaConfig) => void; onImport: (config: SambaConfig) => void }) {
  const options = config.global_options || {}; const [advanced, setAdvanced] = useState(false); const [preview, setPreview] = useState("");
  function set(key: string, value: string) { onChange({ ...config, global_options: { ...options, [key]: value } }); }
  async function showPreview() { const data = await api.validateModuleConfig("samba", config as unknown as ModuleConfig); setPreview(data.generated_config); setAdvanced(true); }
  async function importFile(files: FileList | null) { const file = files?.[0]; if (!file || file.size > 1_000_000) return; const result = await api.validateSambaImport(await file.text()); if (result.validation.ok) onImport(result.config); }
  return <section className="samba-global-config"><header><div><h3>{t("module.samba.globalConfiguration")}</h3><p>{t("module.samba.globalConfigHint")}</p></div><button type="button" onClick={() => void showPreview()}>{t("module.advancedPreview")}</button></header><div className="module-form-grid"><label>workgroup<input value={options.workgroup || "WORKGROUP"} onChange={(event) => set("workgroup", event.target.value)} /></label><label>server string<input value={options["server string"] || "WebNAS Samba Server"} onChange={(event) => set("server string", event.target.value)} /></label><label>netbios name<input value={options["netbios name"] || ""} onChange={(event) => set("netbios name", event.target.value)} /></label><label>security<select value={options.security || "user"} onChange={(event) => set("security", event.target.value)}><option value="user">user</option></select></label><label>map to guest<select value={options["map to guest"] || "Never"} onChange={(event) => set("map to guest", event.target.value)}><option>Never</option><option>Bad User</option></select></label><label>server min protocol<select value={options["server min protocol"] || "SMB2"} onChange={(event) => set("server min protocol", event.target.value)}><option>SMB2</option><option>SMB3</option><option value="NT1">NT1 (SMB1)</option></select><small>{t("module.samba.smb1Warning")}</small></label><label>server max protocol<select value={options["server max protocol"] || "SMB3"} onChange={(event) => set("server max protocol", event.target.value)}><option>SMB3</option><option>SMB2</option></select></label><label>interfaces<input value={options.interfaces || ""} onChange={(event) => set("interfaces", event.target.value)} /></label><label>printing<select value={options.printing || "cups"} onChange={(event) => set("printing", event.target.value)}><option value="cups">CUPS</option><option value="bsd">BSD</option></select></label>{["bind interfaces only", "load printers", "disable spoolss", "unix extensions", "wide links", "follow symlinks"].map((key) => <label className="check" key={key}><input type="checkbox" checked={(options[key] || "no") === "yes"} onChange={(event) => set(key, event.target.checked ? "yes" : "no")} />{key}</label>)}<label>log level<input type="number" min="0" max="10" value={options["log level"] || "1"} onChange={(event) => set("log level", event.target.value)} /></label><label>max log size<input type="number" min="50" max="100000" value={options["max log size"] || "5000"} onChange={(event) => set("max log size", event.target.value)} /></label><label>deadtime<input type="number" min="0" max="1440" value={options.deadtime || "15"} onChange={(event) => set("deadtime", event.target.value)} /></label></div>{advanced && <div className="samba-config-preview"><header><strong>{t("module.generatedConfig")}</strong><div className="header-actions"><button type="button" onClick={() => { const url = URL.createObjectURL(new Blob([preview], { type: "text/plain;charset=utf-8" })); const link = document.createElement("a"); link.href = url; link.download = "webnas-samba.conf"; link.click(); URL.revokeObjectURL(url); }}><Download />{t("module.downloadConfig")}</button><label>{t("module.importConfig")}<input type="file" accept=".conf,text/plain" onChange={(event) => void importFile(event.target.files)} /></label></div></header><pre>{preview}</pre></div>}</section>;
}

function SambaUsers({ users, t, onAction }: { users: SambaModuleUser[]; t: Translate; onAction: (action: "add" | "password" | "enable" | "disable" | "remove", user: SambaModuleUser) => void }) { return <section className="module-table-wrap"><table><thead><tr><th>{t("settings.username")}</th><th>UID</th><th>{t("module.samba.smbDatabase")}</th><th>{t("module.status")}</th><th>{t("settings.groups")}</th><th>{t("column.actions")}</th></tr></thead><tbody>{users.map((user) => <tr key={user.username}><td><strong>{user.username}</strong></td><td>{user.uid}</td><td>{user.samba_enabled ? t("common.yes") : t("common.no")}</td><td>{user.status}</td><td>{user.groups.join(", ") || "—"}</td><td><div className="module-row-actions">{!user.samba_enabled ? <button onClick={() => onAction("add", user)}>{t("module.samba.addSmbUser")}</button> : <><button onClick={() => onAction("password", user)}>{t("users.password")}</button><button onClick={() => onAction("disable", user)}>{t("common.disabled")}</button><button onClick={() => onAction("enable", user)}>{t("common.enabled")}</button><button className="danger" onClick={() => onAction("remove", user)}>{t("module.samba.removeFromSmb")}</button></>}</div></td></tr>)}</tbody></table></section>; }
function SambaSessions({ sessions, t, onRefresh }: { sessions: SambaSession[]; t: Translate; onRefresh: () => void }) { return <section className="samba-sessions"><header><div><h3>{t("module.section.sessions")}</h3><p>{t("module.samba.sessionsHint")}</p></div><button onClick={onRefresh}><RefreshCw />{t("action.refresh")}</button></header>{sessions.length ? <div className="module-table-wrap"><table><thead><tr><th>{t("settings.username")}</th><th>{t("module.samba.client")}</th><th>IP</th><th>{t("module.samba.protocol")}</th><th>{t("module.samba.openShare")}</th><th>{t("module.samba.openFiles")}</th><th>{t("module.samba.connectedAt")}</th><th>PID</th></tr></thead><tbody>{sessions.map((session) => <tr key={session.id}><td>{session.username}</td><td>{session.client}</td><td>{session.ip}</td><td>{session.protocol}</td><td>{session.share || "—"}</td><td>{session.open_files}</td><td>{session.connected_at ? new Date(typeof session.connected_at === "number" && session.connected_at < 1_000_000_000_000 ? session.connected_at * 1000 : session.connected_at).toLocaleString() : "—"}</td><td>{session.pid || "—"}</td></tr>)}</tbody></table></div> : <div className="empty-state">{t("module.samba.noSessions")}</div>}</section>; }
