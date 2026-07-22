import { Archive, Boxes, CircleAlert, CircleCheckBig, Database, Download, ExternalLink, FileText, Gauge, Link, PackageCheck, Pencil, Play, Plus, Power, RefreshCw, RotateCcw, Save, Shield, Square, Stethoscope, Trash2, Wrench } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type ModuleBackup, type ModuleDiagnostic, type ModuleJob, type ModuleResource, type ModuleStatus, type ModuleSummary } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { AdminActionDialog, type AdminField } from "../admin/AdminActionDialog";
import { PackageJobDialog } from "../package-center/PackageJobDialog";
import { ModuleHeader, ModuleHealthCard, translateServiceState } from "./common/ModuleAppShell";
import { ModuleBackups, ModuleDiagnostics, ModuleJobProgress, ModuleLogs } from "./common/ModuleComponents";

const EMPTY: ModuleStatus = { installed: false, update_available: false, service_state: "unknown", service_enabled: false, services: {}, health: "unknown", health_message: "", last_action: "", last_action_status: "", last_error: "", metrics: {} };
type ActionDialog = { kind: "action"; action: string; fields?: AdminField[]; payload?: Record<string, unknown>; danger?: boolean } | { kind: "connection"; connection?: { base_url: string; username: string } } | { kind: "compose"; project?: string; content?: string } | { kind: "backup" } | { kind: "restore" | "delete"; backup: ModuleBackup } | { kind: "diagnostics" } | { kind: "service"; action: "start" | "stop" | "restart" | "reload" };

const RESOURCE_LABELS: Record<string, string> = {
  packages: "managed.packages", security: "managed.securityUpdates", repositories: "managed.repositories", history: "managed.history", reboot: "managed.restart",
  apps: "managed.apps", containers: "managed.containers", images: "managed.images", networks: "managed.networks", volumes: "managed.volumes", stats: "managed.statistics", compose: "managed.compose",
  statistics: "managed.statistics", domains: "managed.domains", clients: "managed.clients", lists: "managed.filterLists", updates: "managed.updates",
  filters: "managed.filters", upstreams: "managed.upstreams", querylog: "managed.queryLog", databases: "managed.databases", users: "managed.users",
  connections: "managed.connections", permissions: "managed.permissions", replication: "managed.replication", memory: "managed.memory", persistence: "managed.persistence",
  limits: "managed.limits", security_config: "managed.security", container: "managed.container", panel: "managed.panel", logs: "managed.logs",
};

const ACTIONS: Record<string, string[]> = {
  "linux-updates": ["refresh", "upgrade_security", "upgrade_all"],
  pihole: ["install_container", "container_start", "container_stop", "container_restart", "update_container", "remove_container", "blocking_enable", "blocking_disable"],
  "adguard-home": ["install_container", "container_start", "container_stop", "container_restart", "update_container", "remove_container", "protection_enable", "protection_disable", "refresh_filters", "set_rules", "set_upstreams", "update_application"],
  redis: ["configure_memory", "configure_persistence"],
  "home-assistant": ["install_container", "container_start", "container_stop", "container_restart", "update_container", "remove_container"],
};

export function ManagedModuleApp({ moduleId, permissions, t, toast }: { moduleId: string; permissions: string[]; t: Translate; toast: ToastFn }) {
  const [summary, setSummary] = useState<ModuleSummary | null>(null); const [status, setStatus] = useState(EMPTY); const [section, setSection] = useState("overview"); const [resource, setResource] = useState<ModuleResource | null>(null); const [resourceLoading, setResourceLoading] = useState(false); const [resourceError, setResourceError] = useState(""); const [job, setJob] = useState<ModuleJob | null>(null); const [liveJob, setLiveJob] = useState<ModuleJob | null>(null); const [diagnostics, setDiagnostics] = useState<ModuleDiagnostic[]>([]); const [backups, setBackups] = useState<ModuleBackup[]>([]); const [dialog, setDialog] = useState<ActionDialog | null>(null); const [search, setSearch] = useState("");
  const resourceRequest = useRef(0);
  const canOperate = useMemo(() => moduleId === "linux-updates" ? permissions.includes("updates.apply") : moduleId === "docker" ? permissions.includes("docker.manage_containers") : ["pihole", "adguard-home"].includes(moduleId) ? permissions.includes("dns.configure") : moduleId === "home-assistant" ? permissions.includes("homeassistant.operate") : permissions.includes("modules.configure") || permissions.includes("databases.backup"), [moduleId, permissions]);
  const canConfigure = moduleId === "docker" ? permissions.includes("docker.manage_compose") : canOperate;
  const requestedResource = section === "security_config" ? "security" : section;
  const summaryReady = summary !== null;
  const requestedResourceSupported = summary?.capabilities.resources.includes(requestedResource) ?? false;
  const refresh = useCallback(async () => { try { const data = await api.module(moduleId); setSummary(data); setStatus(data.module_status); setJob(data.active_job || null); } catch (error) { toast(message(error, t), "error", "admin"); } }, [moduleId, t, toast]);
  const loadResource = useCallback(async (name: string, query = "") => {
    const request = ++resourceRequest.current;
    setResourceLoading(true); setResourceError(""); setResource(null);
    try {
      const next = await api.moduleResource(moduleId, name, 300, query);
      if (request === resourceRequest.current) setResource(next);
    } catch (error) {
      if (request !== resourceRequest.current) return;
      const detail = message(error, t); setResourceError(detail); toast(detail, "error", "admin");
    } finally {
      if (request === resourceRequest.current) setResourceLoading(false);
    }
  }, [moduleId, t, toast]);
  useEffect(() => { void refresh(); const timer = window.setInterval(() => { if (!document.hidden) void refresh(); }, 4000); return () => window.clearInterval(timer); }, [refresh]);
  useEffect(() => {
    if (!summaryReady) return;
    if (moduleId === "docker" && requestedResource === "logs" && !search) { setResource({ resource: "logs", items: [], total: 0 }); setResourceLoading(false); setResourceError(""); return; }
    if (requestedResourceSupported) {
      const timer = window.setTimeout(() => void loadResource(requestedResource, search), search ? 300 : 0);
      return () => window.clearTimeout(timer);
    }
    if (section === "diagnostics") void api.moduleDiagnostics(moduleId).then((data) => setDiagnostics(data.diagnostics));
    else if (section === "backups") void api.moduleBackups(moduleId).then(setBackups);
  }, [loadResource, moduleId, requestedResource, requestedResourceSupported, search, section, summaryReady]);
  if (!summary) return <div className="loading-state">{t("status.loading")}</div>;
  const resourceNames = summary.capabilities.resources.map((name) => name === "security" && moduleId === "redis" ? "security_config" : name);
  const sections = ["overview", ...resourceNames, ...(summary.capabilities.service_control ? ["service"] : []), ...(summary.capabilities.logs ? ["journal"] : []), ...(summary.capabilities.diagnostics ? ["diagnostics"] : []), ...(summary.capabilities.backups ? ["backups"] : []), ...(["pihole", "adguard-home", "home-assistant"].includes(moduleId) ? ["connection"] : [])];
  const selectedResource = section === "security_config" ? "security" : section;
  const updateJobActive = Boolean(job && ["queued", "running", "waiting_for_confirmation"].includes(job.status));
  const screenUnavailable = moduleId === "linux-updates" && status.metrics.screen_available === false;
  const canOperateResource = moduleId !== "docker" ? canOperate : section === "images" ? permissions.includes("docker.manage_images") : section === "compose" ? permissions.includes("docker.manage_compose") : permissions.includes("docker.manage_containers");
  const selectedResourceEmpty = resource?.resource === selectedResource && resource.total === 0;
  const healthMessage = moduleId === "linux-updates" ? linuxUpdateHealthMessage(status, t) : status.health_message;
  const stateLabel = moduleId === "linux-updates" ? t("managed.field.package_manager") : t("module.serviceState");
  const stateValue = moduleId === "linux-updates" ? String(status.metrics.package_manager || t("module.notAvailable")) : translateServiceState(status.service_state, t);

  function trackJob(next: ModuleJob) { setJob(next); setLiveJob(next); }
  async function reloadVisible() { await refresh(); if (resourceNames.includes(section)) await loadResource(selectedResource, search); }
  async function submit(values: Record<string, string>) {
    if (!dialog) return;
    if (dialog.kind === "action") {
      const appId = String(dialog.payload?.app_id || moduleId);
      if (["install_container", "app_install"].includes(dialog.action) && appId === "pihole") {
        await api.saveModuleConnection("pihole", { base_url: "http://127.0.0.1:8080", username: "", secret: values.web_password });
      }
      const payload = actionPayload(dialog.action, values, dialog.payload);
      trackJob((await api.moduleAction(moduleId, dialog.action, payload)).job);
    } else if (dialog.kind === "connection") await api.saveModuleConnection(moduleId, { base_url: values.base_url, username: values.username, secret: values.secret });
    else if (dialog.kind === "compose") await api.saveDockerCompose(values.project, values.content);
    else if (dialog.kind === "backup") { await api.createModuleBackup(moduleId, values.description); setBackups(await api.moduleBackups(moduleId)); }
    else if (dialog.kind === "restore") trackJob((await api.restoreModuleBackup(moduleId, dialog.backup.id)).job);
    else if (dialog.kind === "delete") { await api.deleteModuleBackup(moduleId, dialog.backup.id); setBackups(await api.moduleBackups(moduleId)); }
    else if (dialog.kind === "diagnostics") trackJob((await api.runModuleDiagnostics(moduleId)).job);
    else if (dialog.kind === "service") trackJob((await api.moduleService(moduleId, dialog.action)).job);
    toast(t("admin.actionCompleted"), "ok", "admin"); await refresh(); if (summary?.capabilities.resources.includes(selectedResource)) await loadResource(selectedResource);
  }
  async function editCompose(project: string) { try { const data = await api.dockerCompose(project); setDialog({ kind: "compose", project, content: data.content }); } catch (error) { toast(message(error, t), "error", "admin"); } }
  function openAction(action: string, payload: Record<string, unknown> = {}) { setDialog({ kind: "action", action, payload, fields: fieldsFor(action, t, payload, moduleId, String(status.metrics.package_manager || "")), danger: ["upgrade_all", "container_stop", "compose_down", "update_container", "app_remove", "remove_container", "repository_delete"].includes(action) }); }
  function openResource(name: string, query = "") { setSearch(query); setSection(name); }

  let content: React.ReactNode;
  if (section === "overview") content = <><div className="module-health-grid"><ModuleHealthCard title={t("module.health")} value={t(`module.health.${status.health}`)} /><ModuleHealthCard title={stateLabel} value={stateValue} /><ModuleHealthCard title={t("module.version")} value={status.package_version || "—"} /><ModuleHealthCard title={t("managed.updateAvailable")} value={status.update_available ? t("common.yes") : t("common.no")} /></div>{status.health === "failed" && <p className="module-health-message error">{healthMessage}</p>}<Metrics value={status.metrics} t={t} />{job && <ModuleJobProgress job={job} t={t} />}{canOperate && <div className="managed-actions">{(ACTIONS[moduleId] || []).filter((action) => moduleActionVisible(action, status)).map((action) => <button className={["upgrade_all", "remove_container"].includes(action) ? "danger" : ""} key={action} onClick={() => openAction(action)}><Wrench />{t(`managed.action.${action}`)}</button>)}</div>}</>;
  else if (resourceNames.includes(section)) content = <><div className="module-section-toolbar"><input aria-label={t("action.search")} placeholder={t("action.search")} value={search} onChange={(event) => setSearch(event.target.value)} /><button disabled={resourceLoading} onClick={() => void loadResource(selectedResource, search)}><RefreshCw className={resourceLoading ? "spin" : ""} />{t("managed.reloadList")}</button>{moduleId === "linux-updates" && section === "repositories" && canOperate && <button className="button-primary" disabled={updateJobActive} onClick={() => openAction("repository_add", { enabled: true, gpgcheck: true })}><Plus />{t("managed.addRepository")}</button>}{moduleId === "linux-updates" && ["packages", "security"].includes(section) && canOperate && <button disabled={updateJobActive} onClick={() => openAction("refresh")}><RefreshCw />{t("managed.refreshMetadata")}</button>}{moduleId === "linux-updates" && ["packages", "security"].includes(section) && canOperate && <button className="button-primary" disabled={updateJobActive || screenUnavailable || selectedResourceEmpty || resourceLoading || Boolean(resourceError)} title={screenUnavailable ? t("managed.screenRequired") : selectedResourceEmpty ? t(section === "security" ? "managed.noSecurityUpdates" : "managed.noPackageUpdates") : undefined} onClick={() => openAction(section === "security" ? "upgrade_security" : "upgrade_all")}><Download />{t("managed.updateNow")}</button>}{moduleId === "docker" && section === "compose" && canConfigure && <button onClick={() => setDialog({ kind: "compose" })}><Save />{t("managed.newCompose")}</button>}</div>{moduleId === "linux-updates" && ["packages", "security"].includes(section) && <p className="detached-update-hint"><Shield />{t(screenUnavailable ? "managed.screenRequired" : "managed.detachedUpdateHint")}</p>}{job && moduleId === "linux-updates" && <ModuleJobProgress job={job} t={t} />}{moduleId === "linux-updates" && section === "repositories" ? <RepositoryCatalog resource={resource} loading={resourceLoading} error={resourceError} canOperate={canOperateResource} t={t} onRetry={() => void loadResource(selectedResource, search)} onAction={openAction} /> : moduleId === "docker" && section === "apps" ? <DockerAppCatalog resource={resource} loading={resourceLoading} error={resourceError} canOperate={canOperateResource} t={t} onRetry={() => void loadResource(selectedResource, search)} onAction={openAction} /> : <ResourceTable resource={resource} loading={resourceLoading} error={resourceError} moduleId={moduleId} section={section} onRetry={() => void loadResource(selectedResource, search)} t={t} actions={(item) => resourceActions(moduleId, section, item, canOperateResource, canConfigure, t, openAction, openResource, editCompose)} />}</>;
  else if (section === "service") content = <div className="managed-actions"><button disabled={!canOperate || status.service_state === "active"} onClick={() => setDialog({ kind: "service", action: "start" })}><Play />{t("module.start")}</button><button disabled={!canOperate || status.service_state !== "active"} onClick={() => setDialog({ kind: "service", action: "stop" })}><Square />{t("module.stop")}</button><button disabled={!canOperate} onClick={() => setDialog({ kind: "service", action: "restart" })}><RotateCcw />{t("module.restart")}</button></div>;
  else if (section === "journal") content = <ModuleLogs moduleId={moduleId} t={t} toast={toast} />;
  else if (section === "diagnostics") content = <><div className="module-section-toolbar">{canOperate && <button onClick={() => setDialog({ kind: "diagnostics" })}><Stethoscope />{t("module.runDiagnostics")}</button>}</div><ModuleDiagnostics diagnostics={diagnostics} t={t} /></>;
  else if (section === "backups") content = canOperate ? <ModuleBackups backups={backups} t={t} onCreate={() => setDialog({ kind: "backup" })} onRestore={(backup) => setDialog({ kind: "restore", backup })} onDelete={(backup) => setDialog({ kind: "delete", backup })} /> : <ResourceTable resource={{ resource: "backups", items: backups as unknown as Array<Record<string, unknown>>, total: backups.length }} t={t} />;
  else content = <ConnectionPanel moduleId={moduleId} canConfigure={canConfigure} t={t} onEdit={(connection) => setDialog({ kind: "connection", connection })} />;

  const packageActionDialog = dialog?.kind === "action" && moduleId === "linux-updates" && ["refresh", "upgrade_security", "upgrade_all"].includes(dialog.action);
  return <><section className="module-app managed-module"><ModuleHeader name={moduleId === "linux-updates" ? t("managed.linuxUpdatesName") : summary.manifest.name} status={status} healthMessage={healthMessage} stateLabel={stateLabel} stateValue={stateValue} activeJob={job ? { operation: job.operation || job.action, progress: job.progress } : null} t={t} actions={<button onClick={() => void reloadVisible()}><RefreshCw />{t("action.refresh")}</button>} /><div className="module-layout"><nav className="module-navigation" aria-label={t("module.sections")}>{sections.map((name) => <button key={name} className={section === name ? "active" : ""} onClick={() => setSection(name)}>{navIcon(name)}<span>{t(RESOURCE_LABELS[name] || `managed.${name}`)}</span></button>)}</nav><main className="module-content">{content}</main></div></section>{liveJob && <PackageJobDialog initialJob={liveJob} moduleName={moduleId === "linux-updates" ? t("managed.linuxUpdatesName") : summary.manifest.name} t={t} onClose={() => { setLiveJob(null); void reloadVisible(); }} />}{dialog && <AdminActionDialog title={dialogTitle(dialog, t)} fields={dialogFields(dialog, t)} description={packageActionDialog && dialog.kind === "action" ? <LinuxUpdateConfirmation action={dialog.action} status={status} resource={resource} t={t} /> : undefined} submitLabel={packageActionDialog && dialog.kind === "action" ? linuxUpdateSubmitLabel(dialog.action, t) : undefined} danger={"danger" in dialog ? dialog.danger : dialog.kind === "restore" || dialog.kind === "delete"} t={t} onClose={() => setDialog(null)} onSubmit={submit} />}</>;
}

function LinuxUpdateConfirmation({ action, status, resource, t }: { action: string; status: ModuleStatus; resource: ModuleResource | null; t: Translate }) {
  const refreshOnly = action === "refresh";
  const securityOnly = action === "upgrade_security";
  const count = resource?.total ?? Number(securityOnly ? status.metrics.security_updates || 0 : status.metrics.updates || 0);
  return <section className="linux-update-confirmation">
    <div className={`linux-update-confirmation-intro ${refreshOnly ? "refresh" : "install"}`}>{refreshOnly ? <RefreshCw /> : securityOnly ? <Shield /> : <Download />}<div><strong>{t(refreshOnly ? "managed.confirm.refreshTitle" : securityOnly ? "managed.confirm.securityTitle" : "managed.confirm.allTitle")}</strong><p>{t(refreshOnly ? "managed.confirm.refreshIntro" : securityOnly ? "managed.confirm.securityIntro" : "managed.confirm.allIntro")}</p></div></div>
    <dl><div><dt>{t("managed.confirm.scope")}</dt><dd>{t(refreshOnly ? "managed.confirm.scopeMetadata" : securityOnly ? "managed.confirm.scopeSecurity" : "managed.confirm.scopeAll")}</dd></div>{!refreshOnly && <div><dt>{t("managed.confirm.packageCount")}</dt><dd>{count}</dd></div>}<div><dt>{t("managed.field.package_manager")}</dt><dd>{String(status.metrics.package_manager || t("module.notAvailable"))}</dd></div><div><dt>{t("managed.confirm.execution")}</dt><dd>{t(refreshOnly ? "managed.confirm.foreground" : "managed.confirm.background")}</dd></div></dl>
    <p className="linux-update-confirmation-note"><CircleAlert />{t(refreshOnly ? "managed.confirm.refreshNote" : "managed.confirm.restartWarning")}</p>
  </section>;
}

function linuxUpdateSubmitLabel(action: string, t: Translate): string {
  if (action === "refresh") return t("managed.confirm.checkRepositories");
  if (action === "upgrade_security") return t("managed.confirm.installSecurity");
  return t("managed.confirm.installAll");
}

function moduleActionVisible(action: string, status: ModuleStatus): boolean {
  if (action === "install_container") return !status.installed;
  if (action === "container_start") return status.installed && status.service_state !== "active";
  if (action === "container_stop") return status.installed && status.service_state === "active";
  if (["container_restart", "update_container", "remove_container"].includes(action)) return status.installed;
  return status.installed || !["blocking_enable", "blocking_disable", "protection_enable", "protection_disable", "refresh_filters", "set_rules", "set_upstreams", "update_application"].includes(action);
}

function RepositoryCatalog({ resource, loading, error, canOperate, t, onRetry, onAction }: { resource: ModuleResource | null; loading: boolean; error: string; canOperate: boolean; t: Translate; onRetry: () => void; onAction: (action: string, payload?: Record<string, unknown>) => void }) {
  if (loading) return <div className="loading-state" role="status">{t("status.loading")}</div>;
  if (error) return <div className="error-state" role="alert"><CircleAlert /><strong>{t("managed.resourceLoadFailed")}</strong><span>{error}</span><button onClick={onRetry}><RefreshCw />{t("action.retry")}</button></div>;
  if (!resource?.items.length) { const paths = Array.isArray(resource?.scanned_paths) ? resource.scanned_paths.map(String) : []; return <div className="empty-state"><Database /><strong>{t("managed.noRepositories")}</strong><span>{t("managed.noRepositoriesHint")}</span>{paths.length > 0 && <code>{paths.join(" · ")}</code>}</div>; }
  return <div className="repository-list">{resource.items.map((item) => {
    const id = String(item.id || ""); const enabled = item.enabled === true; const components = Array.isArray(item.components) ? item.components.join(" ") : String(item.components || "");
    const payload = { ...item, repository_id: id, components };
    return <article className="repository-card" key={id}><span className={`repository-state ${enabled ? "enabled" : "disabled"}`}><Database /></span><div className="repository-main"><header><strong>{String(item.name || item.repository_id || t("managed.repository"))}</strong><span className={`status-badge ${enabled ? "completed" : "cancelled"}`}>{t(enabled ? "common.enabled" : "common.disabled")}</span>{item.managed === true && <span className="repository-managed">WebNAS</span>}</header><code>{String(item.uri || "—")}</code><small>{[String(item.type || ""), String(item.suite || ""), components].filter(Boolean).join(" · ") || String(item.format || "")}</small><small title={String(item.file || "")}>{String(item.file || "—")}</small></div>{canOperate && <div className="repository-actions"><button title={t("action.edit")} onClick={() => onAction("repository_update", payload)}><Pencil /></button><button title={t(enabled ? "managed.disableRepository" : "managed.enableRepository")} onClick={() => onAction(enabled ? "repository_disable" : "repository_enable", { repository_id: id, name: item.name })}><Power /></button><button className="danger" title={t("action.delete")} onClick={() => onAction("repository_delete", { repository_id: id, name: item.name })}><Trash2 /></button></div>}</article>;
  })}</div>;
}

function DockerAppCatalog({ resource, loading, error, canOperate, t, onRetry, onAction }: { resource: ModuleResource | null; loading: boolean; error: string; canOperate: boolean; t: Translate; onRetry: () => void; onAction: (action: string, payload?: Record<string, unknown>) => void }) {
  if (loading) return <div className="loading-state" role="status">{t("status.loading")}</div>;
  if (error) return <div className="error-state" role="alert"><CircleAlert /><strong>{t("managed.resourceLoadFailed")}</strong><span>{error}</span><button onClick={onRetry}><RefreshCw />{t("action.retry")}</button></div>;
  if (!resource?.items.length) return <div className="empty-state"><strong>{t("managed.noApps")}</strong></div>;
  return <div className="docker-app-grid">{resource.items.map((item) => {
    const id = String(item.id || ""); const installed = item.installed === true; const running = item.running === true; const managed = item.managed === true;
    const panelUrl = dockerAppPanelUrl(Number(item.panel_port || 0));
    return <article className="docker-app-card" key={id}><header><span className="package-icon"><Boxes /></span><div><strong>{String(item.name || id)}</strong><small>{t(`package.category.${String(item.category || "containers")}`)}</small></div><span className={`package-status ui-status-${running ? "running" : installed ? "stopped" : "not_installed"}`}>{t(`package.status.${running ? "running" : installed ? "stopped" : "not_installed"}`)}</span></header><p>{String(item.description || "")}</p><dl><dt>{t("managed.field.image")}</dt><dd>{String(item.image || "—")}</dd><dt>{t("managed.field.ports")}</dt><dd>{Array.isArray(item.ports) ? item.ports.join(", ") : "—"}</dd></dl>{installed && !managed && <p className="module-health-message error">{t("managed.unmanagedContainer")}</p>}<footer>{running && panelUrl && <a className="button" href={panelUrl} target="_blank" rel="noreferrer"><ExternalLink />{t("managed.openPanel")}</a>}{canOperate && !installed && <button className="button-primary" onClick={() => onAction("app_install", { app_id: id })}><Download />{t("store.install")}</button>}{canOperate && installed && managed && <>{running ? <button onClick={() => onAction("app_stop", { app_id: id })}><Square />{t("module.stop")}</button> : <button className="button-primary" onClick={() => onAction("app_start", { app_id: id })}><Play />{t("module.start")}</button>}<button onClick={() => onAction("app_update", { app_id: id })}><RefreshCw />{t("store.update")}</button><button className="button-danger" onClick={() => onAction("app_remove", { app_id: id })}><Trash2 />{t("managed.removeContainer")}</button></>}</footer></article>;
  })}</div>;
}

function dockerAppPanelUrl(port: number): string {
  if (!port || typeof window === "undefined") return "";
  const hostname = window.location.hostname.replace(/^\[|\]$/g, "");
  const host = hostname.includes(":") ? `[${hostname}]` : hostname;
  return `http://${host}:${port}`;
}

function ResourceTable({ resource, loading = false, error = "", moduleId = "", section = "", onRetry, t, actions }: { resource: ModuleResource | null; loading?: boolean; error?: string; moduleId?: string; section?: string; onRetry?: () => void; t: Translate; actions?: (item: Record<string, unknown>) => React.ReactNode }) {
  if (loading) return <div className="loading-state" role="status">{t("status.loading")}</div>;
  if (error) return <div className="error-state" role="alert"><CircleAlert /><strong>{t("managed.resourceLoadFailed")}</strong><span>{error}</span>{onRetry && <button onClick={onRetry}><RefreshCw />{t("action.retry")}</button>}</div>;
  if (!resource) return <div className="loading-state" role="status">{t("status.loading")}</div>;
  if (!resource.items.length) {
    const linuxEmptyKey = section === "security" ? "managed.noSecurityUpdates" : section === "packages" ? "managed.noPackageUpdates" : section === "history" ? "managed.noUpdateHistory" : "";
    return <div className="empty-state">{moduleId === "linux-updates" ? section === "security" ? <CircleCheckBig /> : <PackageCheck /> : null}<strong>{t(linuxEmptyKey || "managed.noData")}</strong>{moduleId === "linux-updates" && ["packages", "security"].includes(section) && <span>{t("managed.refreshMetadataHint")}</span>}</div>;
  }
  const keys = Array.from(new Set(resource.items.flatMap((item) => Object.keys(item)))).filter((key) => !["content", "secret", "password"].includes(key.toLowerCase())).slice(0, 8);
  return <div className="managed-table-wrap"><table className="managed-table"><thead><tr>{keys.map((key) => <th key={key}>{columnLabel(key, t)}</th>)}{actions && <th>{t("managed.actions")}</th>}</tr></thead><tbody>{resource.items.map((item, index) => <tr key={String(item.id || item.ID || item.name || index)}>{keys.map((key) => <td key={key}>{format(item[key], t)}</td>)}{actions && <td><div className="data-actions">{actions(item)}</div></td>}</tr>)}</tbody></table></div>;
}
function resourceActions(moduleId: string, section: string, item: Record<string, unknown>, canOperate: boolean, canConfigure: boolean, t: Translate, action: (name: string, payload?: Record<string, unknown>) => void, openResource: (name: string, search?: string) => void, editCompose: (project: string) => Promise<void>) {
  if (!canOperate) return null;
  if (moduleId === "docker" && section === "containers") { const target = String(item.ID || item.Names || item.Name || ""); return <><button title={t("module.start")} onClick={() => action("container_start", { target })}><Play /></button><button title={t("module.stop")} onClick={() => action("container_stop", { target })}><Square /></button><button title={t("module.restart")} onClick={() => action("container_restart", { target })}><RotateCcw /></button><button title={t("managed.logs")} onClick={() => openResource("logs", target)}><FileText /></button></>; }
  if (moduleId === "docker" && section === "images") { const target = [item.Repository, item.Tag].filter(Boolean).join(":") || String(item.ID || ""); return <button onClick={() => action("image_update", { target })}><RefreshCw />{t("managed.action.image_update")}</button>; }
  if (moduleId === "docker" && section === "compose") { const project = String(item.name || ""); return <>{canConfigure && <button title={t("action.edit")} onClick={() => void editCompose(project)}><Save />{t("action.edit")}</button>}<button title={t("managed.action.compose_up")} onClick={() => action("compose_up", { project })}><Play /></button><button title={t("managed.action.compose_down")} onClick={() => action("compose_down", { project })}><Square /></button><button title={t("managed.action.compose_pull")} onClick={() => action("compose_pull", { project })}><RefreshCw /></button><button title={t("managed.action.compose_restart")} onClick={() => action("compose_restart", { project })}><RotateCcw /></button></>; }
  return null;
}

function fieldsFor(action: string, t: Translate, payload: Record<string, unknown> = {}, moduleId = "", packageManager = ""): AdminField[] {
  if (action === "set_rules") return [{ name: "rules", label: t("managed.rules"), type: "textarea", required: true }];
  if (action === "set_upstreams") return [{ name: "upstreams", label: t("managed.upstreams"), type: "textarea", required: true }];
  if (action === "configure_memory") return [{ name: "maxmemory", label: t("managed.maxMemory"), type: "number", value: "0", required: true }, { name: "policy", label: t("managed.evictionPolicy"), type: "select", value: "noeviction", options: ["noeviction", "allkeys-lru", "allkeys-lfu", "volatile-lru", "volatile-lfu", "allkeys-random", "volatile-random", "volatile-ttl"].map((value) => ({ value, label: value })) }];
  if (action === "configure_persistence") return [{ name: "appendonly", label: t("managed.appendOnly"), type: "select", value: "true", options: [{ value: "true", label: t("common.enabled") }, { value: "false", label: t("common.disabled") }] }];
  if (["install_container", "update_container", "app_install", "app_update"].includes(action)) {
    const appId = String(payload.app_id || moduleId);
    const fields: AdminField[] = [{ name: "timezone", label: t("managed.timezone"), value: "Europe/Warsaw", required: true }];
    if (["install_container", "app_install"].includes(action) && appId === "pihole") fields.push({ name: "web_password", label: t("managed.piholePassword"), type: "password", required: true });
    return fields;
  }
  if (["repository_add", "repository_update"].includes(action)) {
    const adding = action === "repository_add";
    if (["dnf", "yum"].includes(packageManager)) return [
      { name: "name", label: t("managed.repositoryName"), value: String(payload.name || ""), required: true },
      { name: "uri", label: t("managed.repositoryUrl"), value: String(payload.uri || ""), required: true },
      { name: "enabled", label: t("managed.repositoryState"), type: "select", value: String(payload.enabled ?? true), options: booleanOptions(t) },
      { name: "gpgcheck", label: t("managed.repositoryGpgCheck"), type: "select", value: String(payload.gpgcheck ?? true), options: booleanOptions(t) },
      { name: "gpgkey", label: t("managed.repositoryGpgKey"), value: String(payload.gpgkey || "") },
    ];
    return [
      ...(adding ? [{ name: "name", label: t("managed.repositoryName"), value: "", required: true } satisfies AdminField] : []),
      { name: "type", label: t("managed.repositoryType"), type: "select", value: String(payload.type || "deb"), options: [{ value: "deb", label: "deb" }, { value: "deb-src", label: "deb-src" }] },
      { name: "uri", label: t("managed.repositoryUrl"), value: String(payload.uri || ""), required: true },
      { name: "suite", label: t("managed.repositorySuite"), value: String(payload.suite || ""), required: true },
      { name: "components", label: t("managed.repositoryComponents"), value: Array.isArray(payload.components) ? payload.components.join(" ") : String(payload.components || "") },
      { name: "options", label: t("managed.repositoryOptions"), value: String(payload.options || "") },
      { name: "enabled", label: t("managed.repositoryState"), type: "select", value: String(payload.enabled ?? true), options: booleanOptions(t) },
    ];
  }
  return [];
}
function booleanOptions(t: Translate) { return [{ value: "true", label: t("common.enabled") }, { value: "false", label: t("common.disabled") }]; }
function actionPayload(action: string, values: Record<string, string>, initial: Record<string, unknown> = {}) {
  if (action === "set_rules") return { ...initial, rules: values.rules.split("\n").map((value) => value.trim()).filter(Boolean) };
  if (action === "set_upstreams") return { ...initial, upstream_dns: values.upstreams.split("\n").map((value) => value.trim()).filter(Boolean) };
  if (action === "configure_memory") return { ...initial, maxmemory: Number(values.maxmemory), policy: values.policy };
  if (action === "configure_persistence") return { ...initial, appendonly: values.appendonly === "true" };
  if (["install_container", "update_container", "app_install", "app_update"].includes(action)) return { ...initial, timezone: values.timezone };
  if (["repository_add", "repository_update"].includes(action)) {
    const result: Record<string, unknown> = { name: values.name || initial.name, uri: values.uri, enabled: values.enabled === "true" };
    if (initial.repository_id) result.repository_id = initial.repository_id;
    if (values.type !== undefined) Object.assign(result, { type: values.type, suite: values.suite, components: values.components, options: values.options });
    if (values.gpgcheck !== undefined) Object.assign(result, { gpgcheck: values.gpgcheck === "true", gpgkey: values.gpgkey });
    return result;
  }
  return initial;
}
function dialogFields(dialog: ActionDialog, t: Translate): AdminField[] { if (dialog.kind === "action") return dialog.fields || []; if (dialog.kind === "connection") return [{ name: "base_url", label: t("managed.apiUrl"), value: dialog.connection?.base_url || "http://127.0.0.1", required: true }, { name: "username", label: t("settings.username"), value: dialog.connection?.username || "" }, { name: "secret", label: t("managed.apiSecret"), type: "password" }]; if (dialog.kind === "compose") return [{ name: "project", label: t("managed.project"), value: dialog.project || "", required: true }, { name: "content", label: t("managed.composeYaml"), type: "textarea", value: dialog.content || "services:\n  app:\n    image: nginx:stable\n    restart: unless-stopped\n", required: true }]; if (dialog.kind === "backup") return [{ name: "description", label: t("module.backupDescription") }]; return []; }
function dialogTitle(dialog: ActionDialog, t: Translate) { if (dialog.kind === "action") return t(`managed.action.${dialog.action}`); if (dialog.kind === "connection") return t("managed.connection"); if (dialog.kind === "compose") return t("managed.compose"); if (dialog.kind === "backup") return t("module.createBackup"); if (dialog.kind === "restore") return t("module.restore"); if (dialog.kind === "delete") return t("module.deleteBackup"); if (dialog.kind === "diagnostics") return t("module.runDiagnostics"); return dialog.kind === "service" ? t(`module.${dialog.action}`) : t("admin.actionCompleted"); }
function ConnectionPanel({ moduleId, canConfigure, t, onEdit }: { moduleId: string; canConfigure: boolean; t: Translate; onEdit: (connection?: { base_url: string; username: string }) => void }) { const [connection, setConnection] = useState<{ base_url: string; username: string; secret_configured: boolean } | null>(null); useEffect(() => { void api.moduleConnection(moduleId).then(setConnection); }, [moduleId]); return <section className="module-info"><dl><dt>{t("managed.apiUrl")}</dt><dd>{connection?.base_url || "—"}</dd><dt>{t("settings.username")}</dt><dd>{connection?.username || "—"}</dd><dt>{t("managed.apiSecret")}</dt><dd>{connection?.secret_configured ? t("managed.configured") : t("managed.notConfigured")}</dd></dl>{canConfigure && <button onClick={() => onEdit(connection ? { base_url: connection.base_url, username: connection.username } : undefined)}><Link />{t("action.edit")}</button>}</section>; }
function Metrics({ value, t }: { value: Record<string, unknown>; t: Translate }) { return <div className="managed-metrics">{Object.entries(value).filter(([, item]) => item !== "").slice(0, 8).map(([key, item]) => <article key={key}><span>{columnLabel(key, t)}</span><strong>{format(item, t)}</strong></article>)}</div>; }
function columnLabel(key: string, t: Translate): string { const translated = t(`managed.field.${key}`); return translated === `managed.field.${key}` ? key.replace(/_/g, " ") : translated; }
function format(value: unknown, t: Translate): string { if (value == null || value === "") return "—"; if (typeof value === "boolean") return value ? t("common.yes") : t("common.no"); if (typeof value === "object") { const text = JSON.stringify(value); return text.length > 180 ? `${text.slice(0, 177)}…` : text; } return String(value); }
function linuxUpdateHealthMessage(status: ModuleStatus, t: Translate): string {
  const error = String(status.metrics.package_query_error || "");
  if (error) return t("managed.updateReadError").replace("{error}", error);
  if (!status.metrics.package_manager) return t("managed.packageManagerUnavailable");
  if (status.metrics.screen_available === false) return t("managed.screenRequired");
  return t("managed.updateSummary").replace("{updates}", String(status.metrics.updates || 0)).replace("{security}", String(status.metrics.security_updates || 0));
}
function navIcon(name: string) { if (["apps", "containers", "images", "networks", "volumes", "compose"].includes(name)) return <Boxes />; if (["databases", "users", "connections", "permissions", "replication", "repositories"].includes(name)) return <Database />; if (["security", "security_config", "filters", "domains"].includes(name)) return <Shield />; if (name === "diagnostics") return <Stethoscope />; if (name === "backups") return <Archive />; return <Gauge />; }
function message(error: unknown, t: Translate) { return error instanceof Error ? error.message : t("error.generic"); }
