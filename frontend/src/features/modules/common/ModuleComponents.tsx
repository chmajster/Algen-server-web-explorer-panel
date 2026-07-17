import { ArchiveRestore, Copy, Download, Play, RefreshCw, RotateCcw, Square, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, type ModuleBackup, type ModuleDiagnostic, type ModuleJob, type ModuleLogSource, type ModuleStatus } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { translateModuleOperation } from "./ModuleAppShell";

export function ModuleServiceControls({ status, disabled, t, onAction }: { status: ModuleStatus; disabled?: boolean; t: Translate; onAction: (action: "start" | "stop" | "restart" | "reload" | "enable" | "disable") => void }) {
  const active = status.service_state === "active";
  return <div className="module-service-controls"><button type="button" disabled={disabled || active} onClick={() => onAction("start")}><Play />{t("module.start")}</button><button type="button" disabled={disabled || !active} onClick={() => onAction("stop")}><Square />{t("module.stop")}</button><button type="button" disabled={disabled || !status.installed} onClick={() => onAction("restart")}><RotateCcw />{t("module.restart")}</button><button type="button" disabled={disabled || !status.installed} onClick={() => onAction("reload")}><RefreshCw />{t("module.reload")}</button></div>;
}

export function ModuleJobProgress({ job, t }: { job: ModuleJob; t: Translate }) {
  const step = job.stage || job.current_step || "";
  const normalizedStep = step.trim().toLowerCase();
  const translatedStep = ["queued", "running", "completed", "failed", "cancelled"].includes(normalizedStep) ? t(`task.${normalizedStep}`) : step;
  return <section className={`module-job-progress ${job.status}`} aria-live="polite"><header><strong>{translateModuleOperation(job.operation || job.action, t)}</strong><span>{t(`task.${job.status}`)} · {job.progress}%</span></header><div className="progress-track"><span style={{ width: `${job.progress}%` }} /></div>{translatedStep && <p>{translatedStep}</p>}{job.error && <pre>{job.error}</pre>}</section>;
}

export function ModuleDiagnostics({ diagnostics, t }: { diagnostics: ModuleDiagnostic[]; t: Translate }) {
  if (!diagnostics.length) return <div className="empty-state">{t("module.noDiagnostics")}</div>;
  return <div className="module-diagnostics">{diagnostics.map((item, index) => <article className={item.severity} key={`${item.title}-${index}`}><header><span>{t(`module.diagnostic.${item.severity}`)}</span><strong>{item.title}</strong></header><p>{item.description}</p>{item.details && <pre>{item.details}</pre>}{item.recommended_action && <small><b>{t("module.recommendedAction")}:</b> {item.recommended_action}</small>}</article>)}</div>;
}

export function ModuleLogs({ moduleId, t, toast }: { moduleId: string; t: Translate; toast: ToastFn }) {
  const [sources, setSources] = useState<ModuleLogSource[]>([]); const [source, setSource] = useState(""); const [lines, setLines] = useState<string[]>([]); const [lineLimit, setLineLimit] = useState(300); const [search, setSearch] = useState(""); const [level, setLevel] = useState(""); const [paused, setPaused] = useState(false); const [loading, setLoading] = useState(false);
  const refresh = useCallback(async () => { setLoading(true); try { const data = await api.moduleLogs(moduleId, source, lineLimit, search, level); setSources(data.sources); setSource(data.source); setLines(data.lines); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin"); } finally { setLoading(false); } }, [level, lineLimit, moduleId, search, source, t, toast]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { if (paused) return; const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 4000); return () => window.clearInterval(timer); }, [paused, refresh]);
  return <section className="module-logs"><header><select aria-label={t("module.logSource")} value={source} onChange={(event) => setSource(event.target.value)}>{sources.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select><select aria-label={t("module.logLines")} value={lineLimit} onChange={(event) => setLineLimit(Number(event.target.value))}>{[100, 300, 500, 1000].map((value) => <option key={value} value={value}>{value}</option>)}</select><select aria-label={t("module.logLevel")} value={level} onChange={(event) => setLevel(event.target.value)}><option value="">{t("module.logLevelAll")}</option><option value="error">error</option><option value="warning">warning</option><option value="info">info</option></select><input aria-label={t("action.search")} placeholder={t("action.search")} value={search} onChange={(event) => setSearch(event.target.value)} /><button type="button" onClick={() => setPaused((value) => !value)}>{paused ? t("module.resumeRefresh") : t("module.pauseRefresh")}</button><button type="button" onClick={() => void refresh()}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button><button type="button" onClick={() => { const selected = window.getSelection()?.toString(); void navigator.clipboard?.writeText(selected || lines.join("\n")); }}><Copy />{t("action.copy")}</button><button type="button" onClick={() => { const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" })); const link = document.createElement("a"); link.href = url; link.download = `${moduleId}-${source.replace(/[^a-z0-9_.-]+/gi, "-") || "log"}.log`; link.click(); URL.revokeObjectURL(url); }}><Download />{t("action.download")}</button></header><pre>{lines.join("\n") || t("module.noLogs")}</pre></section>;
}

export function ModuleBackups({ backups, t, onCreate, onRestore, onDelete }: { backups: ModuleBackup[]; t: Translate; onCreate: () => void; onRestore: (backup: ModuleBackup) => void; onDelete: (backup: ModuleBackup) => void }) {
  return <section className="module-backups"><header><div><h3>{t("module.backups")}</h3><p>{t("module.backupsHint")}</p></div><button type="button" onClick={onCreate}>{t("module.createBackup")}</button></header>{backups.length ? <div>{backups.map((backup) => <article key={backup.id}><div><strong>{backup.description || t("module.configurationBackup")}</strong><small>{new Date(backup.created_at * 1000).toLocaleString()} · {backup.created_by} · {Math.ceil(backup.size / 1024)} KiB</small><code>{backup.checksum.slice(0, 16)}…</code></div><span>{backup.automatic ? t("module.automatic") : t("module.manual")}</span><button type="button" onClick={() => onRestore(backup)}><ArchiveRestore />{t("module.restore")}</button><button className="danger" type="button" onClick={() => onDelete(backup)}><Trash2 />{t("action.delete")}</button></article>)}</div> : <div className="empty-state">{t("module.noBackups")}</div>}</section>;
}

export function ModuleDangerZone({ name, t, onUninstall }: { name: string; t: Translate; onUninstall: () => void }) {
  return <section className="module-danger-zone"><h3>{t("module.dangerZone")}</h3><p>{t("module.uninstallWarning").replace("{name}", name)}</p><button className="button-danger" type="button" onClick={onUninstall}>{t("store.uninstall")}</button></section>;
}
