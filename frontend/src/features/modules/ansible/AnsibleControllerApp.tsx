import { AlertTriangle, CheckCircle2, ChevronRight, Copy, Cpu, Download, Eye, EyeOff, FileCode2, KeyRound, LockKeyhole, Maximize2, MemoryStick, Network, Play, Plus, Radar, RefreshCw, Save, Search, Server, ShieldCheck, Square, Terminal, Trash2, Upload, UserRoundCheck, XCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api, type AnsibleCredential, type AnsibleDashboard, type AnsibleExecution, type AnsibleGroup, type AnsibleHost,
  type AnsiblePlaybook, type AnsibleProject, type AnsibleScan, type AnsibleSchedule, type AnsibleTemplate,
  type AnsibleValidation, type ModuleBackup, type ModuleDiagnostic, type ModuleStatus,
} from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { ModuleAppShell, ModuleHealthCard, type ModuleSection } from "../common/ModuleAppShell";
import { ModuleBackups, ModuleDiagnostics } from "../common/ModuleComponents";

const emptyStatus: ModuleStatus = { installed: false, update_available: false, service_state: "unknown", service_enabled: false, services: {}, health: "unknown", health_message: "", last_action: "", last_action_status: "", last_error: "", metrics: {} };
const sections: ModuleSection[] = ["overview", "hosts", "inventory", "discovery", "credentials", "automation-account", "projects", "playbooks", "templates", "jobs", "schedules", "facts", "configuration", "diagnostics", "backups"];

type Props = { permissions: string[]; t: Translate; toast: ToastFn };
type HostForm = { name: string; address: string; port: string; ssh_user: string; credential_id: string };
const blankHost: HostForm = { name: "", address: "", port: "22", ssh_user: "root", credential_id: "" };

export function AnsibleControllerApp({ permissions, t, toast }: Props) {
  const [section, setSection] = useState<ModuleSection>("overview");
  const [status, setStatus] = useState<ModuleStatus>(emptyStatus);
  const [dashboard, setDashboard] = useState<AnsibleDashboard | null>(null);
  const [hosts, setHosts] = useState<AnsibleHost[]>([]); const [groups, setGroups] = useState<AnsibleGroup[]>([]);
  const [credentials, setCredentials] = useState<AnsibleCredential[]>([]); const [projects, setProjects] = useState<AnsibleProject[]>([]);
  const [playbooks, setPlaybooks] = useState<AnsiblePlaybook[]>([]); const [templates, setTemplates] = useState<AnsibleTemplate[]>([]);
  const [jobs, setJobs] = useState<AnsibleExecution[]>([]); const [schedules, setSchedules] = useState<AnsibleSchedule[]>([]);
  const [scans, setScans] = useState<AnsibleScan[]>([]); const [diagnostics, setDiagnostics] = useState<ModuleDiagnostic[]>([]); const [backups, setBackups] = useState<ModuleBackup[]>([]);
  const [inventory, setInventory] = useState(""); const [config, setConfig] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const can = useCallback((permission: string) => permissions.includes(permission), [permissions]);

  const refresh = useCallback(async () => {
    if (!can("ansible-controller.view")) { setLoading(false); return; }
    setLoading(true); setError("");
    try {
      const [summary, nextDashboard] = await Promise.all([api.module("ansible-controller"), api.ansibleDashboard()]);
      setStatus(summary.module_status); setDashboard(nextDashboard);
      const loaders: Array<Promise<void>> = [];
      if (["hosts", "inventory", "facts", "templates"].includes(section)) loaders.push(api.ansibleHosts().then(setHosts), api.ansibleGroups().then(setGroups));
      if (section === "inventory") loaders.push(api.ansibleInventory().then((value) => setInventory(value.content)));
      if (["credentials", "hosts", "automation-account", "projects", "templates", "configuration"].includes(section)) loaders.push(api.ansibleCredentials().then(setCredentials));
      if (["projects", "playbooks", "templates"].includes(section)) loaders.push(api.ansibleProjects().then(setProjects));
      if (section === "automation-account") loaders.push(api.ansibleHosts().then(setHosts));
      if (["playbooks", "templates"].includes(section)) loaders.push(api.ansiblePlaybooks().then(setPlaybooks));
      if (["templates", "schedules"].includes(section)) loaders.push(api.ansibleTemplates().then(setTemplates));
      if (section === "jobs") loaders.push(api.ansibleJobs().then(setJobs));
      if (section === "schedules") loaders.push(api.ansibleSchedules().then(setSchedules));
      if (section === "discovery") loaders.push(api.ansibleScans().then(setScans));
      if (section === "diagnostics") loaders.push(api.ansibleDiagnostics().then((value) => setDiagnostics(value.diagnostics)));
      if (section === "backups") loaders.push(api.ansibleBackups().then(setBackups));
      if (["configuration", "automation-account", "hosts"].includes(section)) loaders.push(api.ansibleConfig().then(setConfig));
      await Promise.all(loaders);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : t("error.generic"); setError(message); toast(message, "error", "admin", "ansible-controller");
    } finally { setLoading(false); }
  }, [can, section, t, toast]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { const timer = window.setInterval(() => { if (!document.hidden && ["overview", "jobs", "discovery"].includes(section)) void refresh(); }, 8000); return () => window.clearInterval(timer); }, [refresh, section]);

  if (!can("ansible-controller.view")) return <div className="permission-state" role="alert"><XCircle />{t("ansible.permissionRequired")}</div>;
  const actions = <button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button>;
  const selectableCredentials = credentials.filter((item) => !item.description.startsWith("managed-host:"));
  let content: React.ReactNode;
  if (error) content = <div className="error-state" role="alert"><AlertTriangle />{error}<button onClick={() => void refresh()}>{t("action.retry")}</button></div>;
  else if (section === "overview") content = <Dashboard dashboard={dashboard} status={status} t={t} />;
  else if (section === "hosts") content = <><EnrollmentCommand t={t} toast={toast} credentials={selectableCredentials} canManage={can("ansible-controller.hosts.manage")} defaultSshUser={String(config.managed_username || "algen-ansible")} /><Hosts hosts={hosts} credentials={selectableCredentials} config={config} canManage={can("ansible-controller.hosts.manage")} t={t} toast={toast} refresh={refresh} /></>;
  else if (section === "inventory") content = <Inventory content={inventory} canManage={can("ansible-controller.hosts.manage")} t={t} toast={toast} refresh={refresh} />;
  else if (section === "discovery") content = <Discovery scans={scans} canManage={can("ansible-controller.discovery")} t={t} toast={toast} refresh={refresh} />;
  else if (section === "credentials") content = <Credentials items={credentials} canManage={can("ansible-controller.credentials.manage")} t={t} toast={toast} refresh={refresh} />;
  else if (section === "automation-account") content = <AutomationAccount value={config} hosts={hosts} credentials={credentials} canManage={can("ansible-controller.configure")} t={t} toast={toast} refresh={refresh} />;
  else if (section === "projects") content = <Projects items={projects} credentials={credentials} canManage={can("ansible-controller.projects.manage")} t={t} toast={toast} refresh={refresh} />;
  else if (section === "playbooks") content = <Playbooks items={playbooks} projects={projects} canManage={can("ansible-controller.playbooks.manage")} t={t} toast={toast} refresh={refresh} />;
  else if (section === "templates") content = <Templates items={templates} hosts={hosts} groups={groups} projects={projects} playbooks={playbooks} canManage={can("ansible-controller.playbooks.manage")} canLaunch={can("ansible-controller.jobs.launch")} t={t} toast={toast} refresh={refresh} />;
  else if (section === "jobs") content = <Jobs items={jobs} canCancel={can("ansible-controller.jobs.cancel")} canLaunch={can("ansible-controller.jobs.launch")} t={t} toast={toast} refresh={refresh} />;
  else if (section === "schedules") content = <Schedules items={schedules} templates={templates} canManage={can("ansible-controller.schedules.manage")} t={t} toast={toast} refresh={refresh} />;
  else if (section === "facts") content = <Facts hosts={hosts} t={t} />;
  else if (section === "configuration") content = <Configuration value={config} canManage={can("ansible-controller.configure")} t={t} toast={toast} refresh={refresh} />;
  else if (section === "diagnostics") content = <ModuleDiagnostics diagnostics={diagnostics} t={t} />;
  else content = <Backups items={backups} canManage={can("ansible-controller.backup")} t={t} toast={toast} refresh={refresh} />;

  return <ModuleAppShell name={t("ansible.name")} status={status} section={section} sections={sections} t={t} onSection={setSection} actions={actions}>{loading && !dashboard ? <div className="loading-state">{t("status.loading")}</div> : content}</ModuleAppShell>;
}

function Dashboard({ dashboard, status, t }: { dashboard: AnsibleDashboard | null; status: ModuleStatus; t: Translate }) {
  if (!dashboard) return <div className="empty-state">{t("ansible.dashboard.empty")}</div>;
  const cards: Array<[string, React.ReactNode, "neutral" | "success" | "warning" | "danger"]> = [
    ["hosts", dashboard.hosts, "neutral"], ["online", dashboard.hosts_online, "success"], ["unreachable", dashboard.hosts_unreachable, dashboard.hosts_unreachable ? "danger" : "success"],
    ["keyErrors", dashboard.host_key_errors, dashboard.host_key_errors ? "danger" : "success"], ["groups", dashboard.groups, "neutral"], ["projects", dashboard.projects, "neutral"],
    ["playbooks", dashboard.playbooks, "neutral"], ["templates", dashboard.templates, "neutral"], ["activeJobs", dashboard.active_jobs, dashboard.active_jobs ? "warning" : "neutral"],
    ["failedJobs", dashboard.failed_jobs, dashboard.failed_jobs ? "danger" : "success"], ["scheduled", dashboard.scheduled, "neutral"], ["version", dashboard.ansible_version || t("common.none"), "neutral"],
  ];
  return <><div className="module-health-grid ansible-dashboard">{cards.map(([key, value, tone]) => <ModuleHealthCard key={key} title={t(`ansible.dashboard.${key}`)} value={value} tone={tone} />)}</div><section className="ansible-controller-state"><Status state={status.health} t={t} /><span>{status.health_message}</span></section></>;
}

function Status({ state, t }: { state: string; t: Translate }) { const Icon = ["healthy", "completed", "online", "ok", "accepted", "safe"].includes(state) ? CheckCircle2 : ["failed", "unreachable", "changed", "error", "blocked"].includes(state) ? XCircle : AlertTriangle; return <span className={`ansible-status ${state}`}><Icon aria-hidden="true" />{t(`ansible.status.${state}`)}</span>; }

function EnrollmentCommand({ canManage, credentials, defaultSshUser, t, toast }: { canManage: boolean; credentials: AnsibleCredential[]; defaultSshUser: string; t: Translate; toast: ToastFn }) {
  const [hostnamePattern, setHostnamePattern] = useState("node-*");
  const [sshUser, setSshUser] = useState(defaultSshUser);
  const [port, setPort] = useState("22");
  const [credentialId, setCredentialId] = useState("");
  const [environment, setEnvironment] = useState("");
  const [location, setLocation] = useState("");
  const [tags, setTags] = useState("");
  const [expiresMinutes, setExpiresMinutes] = useState("15");
  const [command, setCommand] = useState("");
  const [expiresAt, setExpiresAt] = useState(0);
  const [busy, setBusy] = useState(false);

  async function generate(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setCommand("");
    try {
      const value = await api.createAnsibleEnrollmentToken({
        hostname_pattern: hostnamePattern,
        ssh_user: sshUser,
        port: Number(port),
        credential_id: credentialId || null,
        environment,
        location,
        tags: tags.split(",").map((item) => item.trim()).filter(Boolean),
        expires_minutes: Number(expiresMinutes),
      });
      const endpoint = new URL("/api/modules/ansible-controller/enroll", window.location.origin).toString();
      setExpiresAt(value.expires_at);
      setCommand(`set -eu
DETECTED_HOST_NAME="$(hostname -f 2>/dev/null || hostname)"
DETECTED_HOST_ADDRESS="$(hostname -I 2>/dev/null | awk '{print $1}')"
HOST_NAME="\${ANSIBLE_ENROLL_HOSTNAME:-$DETECTED_HOST_NAME}"
HOST_ADDRESS="\${ANSIBLE_ENROLL_ADDRESS:-$DETECTED_HOST_ADDRESS}"
[ -n "$HOST_ADDRESS" ] || HOST_ADDRESS="$HOST_NAME"
PAYLOAD="$(printf '{"hostname":"%s","address":"%s"}' "$HOST_NAME" "$HOST_ADDRESS")"
curl --fail --silent --show-error --max-time 30 \\
  -X POST '${endpoint}' \\
  -H 'Authorization: Bearer ${value.token}' \\
  -H 'Content-Type: application/json' \\
  --data "$PAYLOAD"
echo`);
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "ansible-controller");
    } finally { setBusy(false); }
  }

  async function copyCommand() {
    try {
      await navigator.clipboard.writeText(command);
      toast(t("ansible.enrollment.copied"), "ok");
    } catch {
      toast(t("ansible.enrollment.copyFailed"), "error");
    }
  }

  if (!canManage) return null;
  return <details className="ansible-enrollment">
    <summary><Terminal /><span><strong>{t("ansible.enrollment.title")}</strong><small>{t("ansible.enrollment.hint")}</small></span><ChevronRight /></summary>
    <form className="module-form-grid" onSubmit={(event) => void generate(event)}>
      <label>{t("ansible.enrollment.hostnamePattern")}<input list="ansible-hostname-patterns" required maxLength={128} pattern="[A-Za-z0-9*?.-]+" value={hostnamePattern} onChange={(event) => setHostnamePattern(event.target.value)} /><datalist id="ansible-hostname-patterns"><option value="node-*" /><option value="web-*" /><option value="db-*" /><option value="worker-*" /><option value="*.example.com" /></datalist><small>{t("ansible.enrollment.hostnamePatternHint")}</small></label>
      <label>{t("ansible.host.sshUser")}<input required value={sshUser} onChange={(event) => setSshUser(event.target.value)} /></label>
      <label>{t("ansible.host.port")}<input type="number" min="1" max="65535" value={port} onChange={(event) => setPort(event.target.value)} /></label>
      <label>{t("ansible.credential.title")}<select value={credentialId} onChange={(event) => setCredentialId(event.target.value)}><option value="">{t("common.none")}</option>{credentials.filter((item) => ["ssh_private_key", "ssh_password"].includes(item.type)).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>{t("ansible.enrollment.expiration")}<select value={expiresMinutes} onChange={(event) => setExpiresMinutes(event.target.value)}><option value="5">5 min</option><option value="15">15 min</option><option value="30">30 min</option><option value="60">60 min</option></select></label>
      <label>{t("ansible.host.environment")}<input value={environment} onChange={(event) => setEnvironment(event.target.value)} /></label>
      <label>{t("ansible.host.location")}<input value={location} onChange={(event) => setLocation(event.target.value)} /></label>
      <label className="wide">{t("ansible.enrollment.tags")}<input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="linux, production" /></label>
      <button className="button-primary" type="submit" disabled={busy}><Terminal />{t(busy ? "status.loading" : "ansible.enrollment.generateCommand")}</button>
    </form>
    {command && <section className="ansible-enrollment-command"><header><div><strong>{t("ansible.enrollment.commandTitle")}</strong><small>{t("ansible.enrollment.validUntil")}: {new Date(expiresAt * 1000).toLocaleString()}</small></div><button type="button" onClick={() => void copyCommand()}><Copy />{t("action.copy")}</button></header><pre>{command}</pre><p><AlertTriangle />{t("ansible.enrollment.securityHint")}</p></section>}
  </details>;
}

function Hosts({ hosts, credentials, config, canManage, t, toast, refresh }: { hosts: AnsibleHost[]; credentials: AnsibleCredential[]; config: Record<string, unknown>; canManage: boolean; t: Translate; toast: ToastFn; refresh: () => Promise<void> }) {
  const [form, setForm] = useState(blankHost); const [open, setOpen] = useState(false); const [search, setSearch] = useState(""); const [selected, setSelected] = useState<AnsibleHost | null>(null); const [key, setKey] = useState<{ public_key: string; fingerprint: string; changed: boolean } | null>(null);
  const visible = hosts.filter((host) => `${host.name} ${host.address} ${host.tags.join(" ")}`.toLowerCase().includes(search.toLowerCase())).slice(0, 100);
  async function save(event: React.FormEvent) { event.preventDefault(); try { await api.saveAnsibleHost({ ...form, port: Number(form.port), credential_id: form.credential_id || null, python_interpreter: "auto_silent", connection_type: "ssh", environment: "", location: "", tags: [], variables: {}, active: true }); setForm(blankHost); setOpen(false); await refresh(); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin"); } }
  async function scanKey(host: AnsibleHost) { const value = await api.scanAnsibleHostKey(host.id); const first = value.keys[0]; if (first) setKey({ public_key: `${first.key_type} ${first.public_key}`, fingerprint: first.fingerprint, changed: value.changed }); setSelected(host); }
  async function accept() { if (!selected || !key || !window.confirm(t(key.changed ? "ansible.host.confirmKeyChange" : "ansible.host.confirmKey"))) return; await api.acceptAnsibleHostKey(selected.id, key, key.changed); setKey(null); await refresh(); }
  async function onboard(host: AnsibleHost) { if (!window.confirm(t("ansible.host.confirmOnboarding"))) return; const sudoProfile = config.managed_sudo_profile === "nopasswd" ? "nopasswd" : "none"; const confirmHostName = sudoProfile === "nopasswd" ? window.prompt(t("ansible.host.typeAddressForSudo"), "") || "" : ""; if (sudoProfile === "nopasswd" && confirmHostName !== host.address) return; await api.onboardAnsibleHost({ host: { name: host.name, address: host.address, port: host.port, ssh_user: host.ssh_user, credential_id: host.credential_id, python_interpreter: host.python_interpreter, connection_type: host.connection_type, environment: host.environment, location: host.location, tags: host.tags, variables: host.variables, active: host.active }, initial_username: host.ssh_user, credential_id: host.credential_id, create_managed_user: true, managed_username: String(config.managed_username || "algen-ansible"), sudo_profile: sudoProfile, sudoers_policy: "", confirm_host_name: confirmHostName }); toast(t("ansible.jobQueued"), "ok", "admin", "ansible-controller"); }
  return <section className="ansible-panel"><header><div><h3>{t("ansible.hosts.title")}</h3><p>{t("ansible.hosts.hint")}</p></div><div className="header-actions"><label className="ansible-search"><Search /><input aria-label={t("action.search")} value={search} onChange={(event) => setSearch(event.target.value)} /></label>{canManage && <button onClick={() => setOpen((value) => !value)}><Plus />{t("ansible.host.add")}</button>}</div></header>{open && <form className="module-form-grid" onSubmit={save}><label>{t("common.name")}<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label>{t("ansible.host.address")}<input required value={form.address} onChange={(event) => setForm({ ...form, address: event.target.value })} /></label><label>{t("ansible.host.port")}<input type="number" min="1" max="65535" value={form.port} onChange={(event) => setForm({ ...form, port: event.target.value })} /></label><label>{t("ansible.host.sshUser")}<input value={form.ssh_user} onChange={(event) => setForm({ ...form, ssh_user: event.target.value })} /></label><label>{t("ansible.credential.title")}<select value={form.credential_id} onChange={(event) => setForm({ ...form, credential_id: event.target.value })}><option value="">{t("common.none")}</option>{credentials.filter((item) => item.type === "ssh_private_key").map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button className="button-primary" type="submit"><Save />{t("action.save")}</button></form>}{key && <div className="ansible-key-confirm" role="alert"><AlertTriangle /><div><strong>{t(key.changed ? "ansible.host.keyChanged" : "ansible.host.newKey")}</strong><code>{key.fingerprint}</code><p>{t("ansible.host.verifyFingerprint")}</p></div><button className="button-primary" onClick={() => void accept()}>{t("action.confirm")}</button><button onClick={() => setKey(null)}>{t("action.cancel")}</button></div>}<Table headers={[t("common.name"), t("ansible.host.address"), t("ansible.host.user"), t("ansible.host.fingerprint"), t("ansible.host.lastTest"), t("column.actions")]} rows={visible.map((host) => [<button className="link-button" onClick={() => setSelected(host)}>{host.name}</button>, `${host.address}:${host.port}`, host.ssh_user, <Status state={host.fingerprint_status} t={t} />, host.last_test_at ? new Date(host.last_test_at * 1000).toLocaleString() : t("common.none"), canManage && <div className="module-row-actions"><button onClick={() => void scanKey(host)}>{t("ansible.host.scanKey")}</button><button disabled={host.fingerprint_status !== "accepted"} onClick={() => void api.testAnsibleHost(host.id).then(() => toast(t("ansible.jobQueued"), "ok"))}>{t("ansible.host.test")}</button><button disabled={host.fingerprint_status !== "accepted" || !host.credential_id} onClick={() => void onboard(host)}>{t("ansible.host.onboard")}</button><button disabled={host.fingerprint_status !== "accepted"} onClick={() => void api.gatherAnsibleFacts(host.id).then(() => toast(t("ansible.jobQueued"), "ok"))}>{t("ansible.host.facts")}</button><button className="danger" onClick={() => { if (window.confirm(t("ansible.host.confirmDelete"))) void api.deleteAnsibleHost(host.id).then(refresh); }}>{t("action.delete")}</button></div>])} empty={t("ansible.hosts.empty")} />{selected && <HostDetails host={selected} t={t} onClose={() => setSelected(null)} />}</section>;
}

function HostDetails({ host, t, onClose }: { host: AnsibleHost; t: Translate; onClose: () => void }) {
  const facts = host.facts || {};
  const python = facts.ansible_python as Record<string, unknown> | undefined;
  useEffect(() => { const close = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); }; window.addEventListener("keydown", close); return () => window.removeEventListener("keydown", close); }, [onClose]);
  return <div className="ansible-details-backdrop" onMouseDown={onClose}>
    <aside className="ansible-details" role="dialog" aria-modal="true" aria-label={t("ansible.host.details")} onMouseDown={(event) => event.stopPropagation()}>
      <header><span className="ansible-details-host-icon"><Server /></span><div><small>{t("ansible.host.details")}</small><h3>{host.name}</h3><p>{host.address}:{host.port}</p></div><Status state={host.fingerprint_status} t={t} /><button aria-label={t("action.close")} onClick={onClose}><XCircle /></button></header>
      <div className="ansible-details-content">
        <section className="ansible-host-summary"><article><Network /><span>{t("ansible.host.connection")}</span><strong>{host.connection_type.toUpperCase()} · {host.port}</strong></article><article><UserRoundCheck /><span>{t("ansible.host.user")}</span><strong>{host.ssh_user}</strong></article><article><KeyRound /><span>{t("ansible.host.fingerprint")}</span><strong>{t(`ansible.status.${host.fingerprint_status}`)}</strong></article><article><ShieldCheck /><span>{t("ansible.host.managedAccount")}</span><strong>{host.managed_user_created ? t("common.yes") : t("common.no")}</strong></article></section>
        <section className="ansible-details-section"><header><Server /><div><strong>{t("ansible.host.systemSection")}</strong><span>{t("ansible.host.systemSectionHint")}</span></div></header><div className="ansible-host-property-grid"><article><span>{t("ansible.host.os")}</span><strong>{String(facts.ansible_distribution || t("common.none"))}</strong></article><article><span>{t("ansible.host.kernel")}</span><strong>{String(facts.ansible_kernel || t("common.none"))}</strong></article><article><span>{t("ansible.host.architecture")}</span><strong>{String(facts.ansible_architecture || t("common.none"))}</strong></article><article><span>{t("ansible.host.python")}</span><strong>{String(python?.version || host.python_interpreter)}</strong></article><article><span><Cpu />{t("ansible.host.cpu")}</span><strong>{String(facts.ansible_processor_vcpus || t("common.none"))}</strong></article><article><span><MemoryStick />{t("ansible.host.ram")}</span><strong>{facts.ansible_memtotal_mb ? `${String(facts.ansible_memtotal_mb)} MiB` : t("common.none")}</strong></article></div></section>
        <section className="ansible-details-section"><header><Terminal /><div><strong>{t("ansible.host.activitySection")}</strong><span>{t("ansible.host.activitySectionHint")}</span></div></header><dl className="ansible-host-activity"><div><dt>{t("ansible.host.lastTest")}</dt><dd>{host.last_test_at ? new Date(host.last_test_at * 1000).toLocaleString() : t("common.none")}</dd></div><div><dt>{t("ansible.host.lastFacts")}</dt><dd>{host.last_facts_at ? new Date(host.last_facts_at * 1000).toLocaleString() : t("common.none")}</dd></div><div><dt>{t("ansible.host.location")}</dt><dd>{host.location || t("common.none")}</dd></div><div><dt>{t("ansible.host.environment")}</dt><dd>{host.environment || t("common.none")}</dd></div></dl></section>
        {host.last_error && <div className="ansible-host-error" role="alert"><AlertTriangle /><div><strong>{t("ansible.host.lastError")}</strong><span>{host.last_error}</span></div></div>}
      </div>
      <footer><span>{t("ansible.host.updated")}: {new Date(host.updated_at * 1000).toLocaleString()}</span><button type="button" onClick={onClose}>{t("action.close")}</button></footer>
    </aside>
  </div>;
}

function Inventory({ content, canManage, t, toast, refresh }: { content: string; canManage: boolean; t: Translate; toast: ToastFn; refresh: () => Promise<void> }) { const [value, setValue] = useState(content); const [format, setFormat] = useState<"yaml" | "ini">("yaml"); useEffect(() => setValue(content), [content]); async function importValue() { try { const preview = await api.importAnsibleInventory(value, format, false); if (window.confirm(`${t("ansible.inventory.confirmImport")} (${String((preview.validation as Record<string, unknown>)?.host_count || 0)})`)) { await api.importAnsibleInventory(value, format, true); await refresh(); } } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error"); } } return <section className="ansible-panel"><header><div><h3>{t("ansible.inventory.title")}</h3><p>{t("ansible.inventory.hint")}</p></div><select aria-label={t("ansible.inventory.format")} value={format} onChange={(event) => setFormat(event.target.value as "yaml" | "ini")}><option value="yaml">YAML</option><option value="ini">INI</option></select></header><textarea className="ansible-code" aria-label={t("ansible.inventory.content")} value={value} onChange={(event) => setValue(event.target.value)} readOnly={!canManage} />{canManage && <button className="button-primary" onClick={() => void importValue()}><Upload />{t("ansible.inventory.validateImport")}</button>}</section>; }

function Discovery({ scans, canManage, t, toast, refresh }: { scans: AnsibleScan[]; canManage: boolean; t: Translate; toast: ToastFn; refresh: () => Promise<void> }) { const [cidr, setCidr] = useState("192.168.1.0/24"); const [port, setPort] = useState("22"); const [selectedScan, setSelectedScan] = useState<AnsibleScan | null>(null); const [selected, setSelected] = useState<string[]>([]); async function start(event: React.FormEvent) { event.preventDefault(); if (!window.confirm(t("ansible.discovery.confirmScan"))) return; try { const value = await api.startAnsibleScan({ cidr, port: Number(port), timeout_seconds: 2, concurrency: 32, group_name: "", method: "nmap", reverse_dns: true }); setSelectedScan(value.scan); toast(t("ansible.discovery.started"), "ok"); await refresh(); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error"); } } async function importHosts() { if (!selectedScan || !selected.length) return; await api.importAnsibleScan(selectedScan.id, selected); setSelected([]); await refresh(); } const detail = selectedScan || scans[0]; return <section className="ansible-panel"><header><div><h3>{t("ansible.discovery.title")}</h3><p>{t("ansible.discovery.hint")}</p></div></header>{canManage && <form className="module-form-grid" onSubmit={start}><label>{t("ansible.discovery.cidr")}<input required value={cidr} onChange={(event) => setCidr(event.target.value)} /></label><label>{t("ansible.host.port")}<input type="number" min="1" max="65535" value={port} onChange={(event) => setPort(event.target.value)} /></label><button className="button-primary"><Search />{t("ansible.discovery.start")}</button></form>}<div className="ansible-scan-list" aria-label={t("ansible.discovery.scanHistory")}>{scans.map((scan) => <button className={detail?.id === scan.id ? "selected" : ""} key={scan.id} aria-pressed={detail?.id === scan.id} onClick={() => void api.ansibleScan(scan.id).then(setSelectedScan)}><span className={`ansible-scan-icon ${scan.status}`}><Radar /></span><span className="ansible-scan-copy"><span><Status state={scan.status} t={t} /><small>{new Date(scan.created_at * 1000).toLocaleString()}</small></span><code>{String(scan.request.cidr || t("common.none"))}</code></span><span className="ansible-scan-count"><strong>{scan.discovered}</strong><small>{t("ansible.discovery.hostsFound")}</small></span><ChevronRight className="ansible-scan-arrow" /></button>)}</div>{detail?.hosts && <><Table headers={[t("common.select"), t("ansible.host.address"), t("ansible.host.hostname"), t("ansible.host.port"), t("ansible.host.latency"), t("ansible.discovery.ssh")]} rows={detail.hosts.map((host) => [<input aria-label={`${t("common.select")} ${host.address}`} type="checkbox" checked={selected.includes(host.id)} onChange={(event) => setSelected((items) => event.target.checked ? [...items, host.id] : items.filter((id) => id !== host.id))} />, host.address, host.hostname || t("common.none"), host.port, host.latency_ms ?? t("common.none"), <Status state={host.ssh_status} t={t} />])} empty={t("ansible.discovery.empty")} />{canManage && <button className="button-primary" disabled={!selected.length} onClick={() => void importHosts()}>{t("ansible.discovery.importSelected")}</button>}</>}</section>; }

function AutomationAccount({ value, hosts, credentials, canManage, t, toast, refresh }: { value: Record<string, unknown>; hosts: AnsibleHost[]; credentials: AnsibleCredential[]; canManage: boolean; t: Translate; toast: ToastFn; refresh: () => Promise<void> }) {
  const [username, setUsername] = useState("algen-ansible");
  const [sudoProfile, setSudoProfile] = useState<"none" | "nopasswd">("none");
  const [shell, setShell] = useState<"/bin/bash" | "/bin/sh">("/bin/bash");
  const [comment, setComment] = useState("Algen Ansible automation");
  const keysMode = "exclusive" as const;
  const [rotationDays, setRotationDays] = useState(90);
  const [rotating, setRotating] = useState("");
  const [saving, setSaving] = useState(false);
  const [renderedAt] = useState(() => Date.now());
  useEffect(() => {
    setUsername(String(value.managed_username || "algen-ansible"));
    setSudoProfile(value.managed_sudo_profile === "nopasswd" ? "nopasswd" : "none");
    setShell(value.managed_shell === "/bin/sh" ? "/bin/sh" : "/bin/bash");
    setComment(typeof value.managed_comment === "string" ? value.managed_comment : "Algen Ansible automation");
    setRotationDays(typeof value.managed_key_rotation_days === "number" ? value.managed_key_rotation_days : 90);
  }, [value]);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!window.confirm(t("ansible.managedAccount.confirmSave"))) return;
    setSaving(true);
    try {
      await api.saveAnsibleManagedAccount({ username: username.trim(), sudo_profile: sudoProfile, shell, comment: comment.trim(), authorized_keys_mode: keysMode, key_rotation_days: rotationDays });
      toast(t("ansible.managedAccount.saved"), "ok", "admin", "ansible-controller");
      await refresh();
    } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "ansible-controller"); }
    finally { setSaving(false); }
  }
  async function rotate(host: AnsibleHost) { if (!window.confirm(t("ansible.managedAccount.confirmRotate"))) return; setRotating(host.id); try { await api.rotateAnsibleHostKey(host.id); toast(t("ansible.managedAccount.rotationQueued"), "ok", "admin", "ansible-controller"); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error"); } finally { setRotating(""); } }
  const managedHosts = hosts.filter((host) => host.active && host.managed_user_created);
  const text = (key: string, fallback: string) => { const translated = t(key); return translated === key ? fallback : translated; };
  return <section className="ansible-panel automation-account-page">
    <header><div><h3>{t("ansible.managedAccount.pageTitle")}</h3><p>{t("ansible.managedAccount.pageHint")}</p></div><span className="automation-account-ready"><CheckCircle2 />{t("ansible.managedAccount.policyActive")}</span></header>
    <div className="automation-account-hero"><span><UserRoundCheck /></span><div><small>{t("ansible.managedAccount.eyebrow")}</small><h4>{username || "algen-ansible"}</h4><p>{t("ansible.managedAccount.hint")}</p></div><dl><div><dt>{t("ansible.managedAccount.authentication")}</dt><dd><KeyRound />SSH Ed25519</dd></div><div><dt>{t("ansible.managedAccount.password")}</dt><dd><LockKeyhole />{t("ansible.managedAccount.passwordLocked")}</dd></div></dl></div>
    <form className="automation-account-form" onSubmit={save}>
      <fieldset><legend><UserRoundCheck />{t("ansible.managedAccount.identitySection")}</legend><p>{t("ansible.managedAccount.identityHint")}</p><div className="automation-account-fields">
        <label>{t("ansible.managedAccount.username")}<input aria-label={t("ansible.managedAccount.username")} required minLength={2} maxLength={32} pattern="[a-z_][a-z0-9_-]{0,30}[a-z0-9_$]" value={username} disabled={!canManage || saving} onChange={(event) => setUsername(event.target.value.toLowerCase())} /><small>{t("ansible.managedAccount.usernameHint")}</small></label>
        <label>{t("ansible.managedAccount.comment")}<input aria-label={t("ansible.managedAccount.comment")} maxLength={100} value={comment} disabled={!canManage || saving} onChange={(event) => setComment(event.target.value.replace(/[:\r\n]/g, ""))} /><small>{t("ansible.managedAccount.commentHint")}</small></label>
        <label>{t("ansible.managedAccount.shell")}<select aria-label={t("ansible.managedAccount.shell")} value={shell} disabled={!canManage || saving} onChange={(event) => setShell(event.target.value as "/bin/bash" | "/bin/sh")}><option value="/bin/bash">/bin/bash</option><option value="/bin/sh">/bin/sh</option></select><small>{t("ansible.managedAccount.shellHint")}</small></label>
      </div></fieldset>
      <fieldset><legend><ShieldCheck />{t("ansible.managedAccount.accessSection")}</legend><p>{t("ansible.managedAccount.accessHint")}</p><div className="automation-account-fields">
        <label>{t("ansible.managedAccount.sudoProfile")}<select aria-label={t("ansible.managedAccount.sudoProfile")} value={sudoProfile} disabled={!canManage || saving} onChange={(event) => setSudoProfile(event.target.value as "none" | "nopasswd")}><option value="none">{t("ansible.managedAccount.sudo.none")}</option><option value="nopasswd">{t("ansible.managedAccount.sudo.nopasswd")}</option></select><small>{t("ansible.managedAccount.sudoHint")}</small></label>
        <label>{t("ansible.managedAccount.keysMode")}<select aria-label={t("ansible.managedAccount.keysMode")} value={keysMode} disabled><option value="exclusive">{t("ansible.managedAccount.keys.perHostRequired")}</option></select><small>{t("ansible.managedAccount.keysHint")}</small></label>
        <label>{t("ansible.managedAccount.rotationInterval")}<select aria-label={t("ansible.managedAccount.rotationInterval")} value={rotationDays} disabled={!canManage || saving} onChange={(event) => setRotationDays(Number(event.target.value))}><option value={0}>{t("ansible.managedAccount.rotation.manual")}</option>{[30, 60, 90, 180, 365].map((days) => <option value={days} key={days}>{days} {t("ansible.managedAccount.days")}</option>)}</select><small>{t("ansible.managedAccount.rotationHint")}</small></label>
      </div>{sudoProfile === "nopasswd" && <div className="automation-account-warning"><AlertTriangle /><span>{t("ansible.managedAccount.sudoWarning")}</span></div>}</fieldset>
      <div className="automation-account-policies"><article><KeyRound /><div><strong>{t("ansible.managedAccount.keyPolicy")}</strong><span>{t("ansible.managedAccount.keyHint")}</span></div></article><article><LockKeyhole /><div><strong>{t("ansible.managedAccount.lockPolicy")}</strong><span>{t("ansible.managedAccount.lockHint")}</span></div></article><article><Terminal /><div><strong>{t("ansible.managedAccount.applyPolicy")}</strong><span>{t("ansible.managedAccount.applyHint")}</span></div></article></div>
      <section className="ansible-panel managed-key-inventory"><header><div><KeyRound /><span><strong>{text("ansible.managedAccount.hostKeys", "Klucze SSH serwerów")}</strong><small>{text("ansible.managedAccount.hostKeysHint", "Każdy zarządzany serwer używa oddzielnego klucza SSH.")}</small></span></div><b>{managedHosts.length}</b></header><div>{managedHosts.map((host) => { const credential = credentials.find((item) => item.id === host.credential_id); const unique = credential?.description.startsWith(`managed-host:${host.id}`); const ageDays = credential ? Math.max(0, Math.floor((renderedAt / 1000 - credential.updated_at) / 86400)) : null; const due = rotationDays > 0 && ageDays != null && ageDays >= rotationDays; return <article key={host.id}><span className={`managed-key-state ${unique ? due ? "due" : "unique" : "legacy"}`}><KeyRound /></span><div><strong>{host.name}</strong><code>{host.address}:{host.port}</code></div><span><small>{unique ? text("ansible.managedAccount.uniqueKey", "Unikalny klucz Ed25519") : text("ansible.managedAccount.legacyKey", "Współdzielony klucz — wymaga rotacji")}</small><b>{credential ? `${text("ansible.managedAccount.keyAge", "Wiek klucza")}: ${ageDays} ${text("ansible.managedAccount.days", "dni")}` : t("common.none")}</b></span>{canManage && <button type="button" disabled={!host.credential_id || rotating === host.id} onClick={() => void rotate(host)}><RefreshCw className={rotating === host.id ? "spin" : ""} />{text("ansible.managedAccount.rotateNow", "Rotuj teraz")}</button>}</article>; })}{!managedHosts.length && <div className="empty-state managed-key-empty"><KeyRound /><strong>{text("ansible.managedAccount.noManagedHosts", "Brak przygotowanych hostów")}</strong><span>{text("ansible.managedAccount.hostKeysHint", "Po przygotowaniu serwera jego unikalny klucz pojawi się tutaj.")}</span></div>}</div></section>
      {canManage && <footer><span>{t("ansible.managedAccount.saveHint")}</span><button className="button-primary" type="submit" disabled={saving || !username.trim()}><Save />{saving ? t("status.saving") : t("ansible.managedAccount.save")}</button></footer>}
    </form>
  </section>;
}

function Credentials({ items, canManage, t, toast, refresh }: { items: AnsibleCredential[]; canManage: boolean; t: Translate; toast: ToastFn; refresh: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [name, setName] = useState("");
  const [type, setType] = useState<AnsibleCredential["type"]>("ssh_private_key");
  const [username, setUsername] = useState("");
  const [secret, setSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [description, setDescription] = useState("");
  const [revealSecret, setRevealSecret] = useState(false);
  const privateKey = type === "ssh_private_key" || type === "git_private_key";
  const usernameVisible = ["ssh_private_key", "ssh_password", "become_password", "git_private_key"].includes(type);
  const usernameRequired = type === "ssh_password";

  function changeType(next: AnsibleCredential["type"]) {
    setType(next);
    setUsername(next === "git_private_key" ? "git" : "");
    setSecret("");
    setPassphrase("");
    setRevealSecret(false);
  }

  function resetForm() {
    setName(""); setType("ssh_private_key"); setUsername(""); setSecret(""); setPassphrase(""); setDescription(""); setRevealSecret(false);
  }

  function beginCreate() { resetForm(); setOpen(true); }
  function cancelCreate() { resetForm(); setOpen(false); }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!window.confirm(t("ansible.credential.confirmSave"))) return;
    try {
      await api.saveAnsibleCredential({ name, type, username: usernameVisible ? username : "", secret, description, passphrase: privateKey ? passphrase : "", confirm: true });
      resetForm(); setOpen(false);
      await refresh();
    } catch (error) {
      setSecret(""); setPassphrase("");
      toast(error instanceof Error ? error.message : t("error.generic"), "error");
    }
  }

  const secretLabel = t(`ansible.credential.secret.${type}`);
  const userItems = items.filter((item) => !item.description.startsWith("managed-host:"));
  const visible = userItems.filter((item) => `${item.name} ${item.type} ${item.username || ""}`.toLowerCase().includes(search.trim().toLowerCase()));
  const types: AnsibleCredential["type"][] = ["ssh_private_key", "ssh_password", "become_password", "git_private_key", "awx_token", "vault_secret"];
  return <section className="ansible-panel ansible-credentials">
    <header><div><h3>{t("ansible.credentials.title")}</h3><p>{t("ansible.credentials.hint")}</p></div>{canManage && <button type="button" onClick={beginCreate}><Plus />{t("ansible.credential.add")}</button>}</header>
    <div className="credential-workspace">
      <aside className="credential-vault">
        <header><div><span className="credential-vault-icon"><LockKeyhole /></span><span><strong>{t("ansible.credentials.vaultTitle")}</strong><small>{userItems.length} · {t("ansible.credentials.stored")}</small></span></div>{userItems.length > 0 && <label className="credential-search"><Search /><input aria-label={t("action.search")} placeholder={t("ansible.credentials.search")} value={search} onChange={(event) => setSearch(event.target.value)} /></label>}</header>
        <div className="credential-list">{visible.map((item) => <article key={item.id}>
          <span className="credential-item-icon"><KeyRound /></span>
          <div><strong>{item.name}</strong><small>{t(`ansible.credential.type.${item.type}`)}</small><span>{item.username || t("ansible.credentials.noUser")}</span></div>
          <span className={`credential-secret-state ${item.secret_configured ? "configured" : ""}`} title={t("ansible.credential.configured")}><ShieldCheck /></span>
          {canManage && <button className="credential-delete" type="button" aria-label={`${t("action.delete")} ${item.name}`} onClick={() => { if (window.confirm(t("ansible.credential.confirmDelete"))) void api.deleteAnsibleCredential(item.id).then(refresh); }}><Trash2 /></button>}
        </article>)}{!visible.length && <div className="credential-empty"><KeyRound /><strong>{search ? t("ansible.credentials.noSearchResults") : t("ansible.credentials.empty")}</strong><span>{search ? t("ansible.credentials.changeSearch") : t("ansible.credentials.emptyHint")}</span>{canManage && !search && <button type="button" onClick={beginCreate}><Plus />{t("ansible.credentials.createFirst")}</button>}</div>}</div>
      </aside>
      {open ? <form className="credential-editor" onSubmit={save}>
        <header><div><small>{t("ansible.credentials.creator")}</small><h4>{t("ansible.credentials.newTitle")}</h4><p>{t("ansible.credentials.newHint")}</p></div><button type="button" aria-label={t("action.close")} onClick={cancelCreate}><XCircle /></button></header>
        <div className="credential-security-notice"><ShieldCheck /><div><strong>{t("ansible.credentials.securityTitle")}</strong><span>{t("ansible.credentials.securityHint")}</span></div></div>
        <fieldset><legend>{t("ansible.credentials.basicInformation")}</legend><div className="credential-field-grid">
          <label>{t("common.name")}<input required value={name} autoComplete="off" placeholder={t("ansible.credentials.namePlaceholder")} onChange={(event) => setName(event.target.value)} /></label>
          <label>{t("ansible.credential.type")}<select value={type} onChange={(event) => changeType(event.target.value as AnsibleCredential["type"])}>{types.map((value) => <option key={value} value={value}>{t(`ansible.credential.type.${value}`)}</option>)}</select></label>
          <label className="wide">{t("ansible.credential.description")}<input value={description} maxLength={500} placeholder={t("ansible.credentials.descriptionPlaceholder")} onChange={(event) => setDescription(event.target.value)} /></label>
        </div></fieldset>
        <div className="ansible-credential-type-hint"><span className="credential-type-icon"><KeyRound /></span><div><strong>{t(`ansible.credential.type.${type}`)}</strong><span>{t(`ansible.credential.hint.${type}`)}</span></div></div>
        <fieldset><legend>{t("ansible.credentials.authenticationData")}</legend><p>{t("ansible.credentials.authenticationHint")}</p><div className="credential-field-grid">
          {usernameVisible && <label>{t(type === "ssh_password" ? "ansible.credential.localUsername" : "ansible.host.user")}<input required={usernameRequired} value={username} autoComplete="username" placeholder={type === "git_private_key" ? "git" : "root"} onChange={(event) => setUsername(event.target.value)} /></label>}
          {privateKey ? <label className="wide">{secretLabel}<textarea required autoComplete="off" spellCheck={false} placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" value={secret} onChange={(event) => setSecret(event.target.value)} /></label> : <label className="wide">{secretLabel}<span className="credential-secret-input"><input aria-label={secretLabel} required type={revealSecret ? "text" : "password"} autoComplete={type === "ssh_password" ? "current-password" : "off"} value={secret} onChange={(event) => setSecret(event.target.value)} /><button type="button" aria-label={t(revealSecret ? "ansible.credentials.hideSecret" : "ansible.credentials.showSecret")} onClick={() => setRevealSecret((value) => !value)}>{revealSecret ? <EyeOff /> : <Eye />}</button></span></label>}
          {privateKey && <label>{t("ansible.credential.passphrase")}<input type="password" autoComplete="off" value={passphrase} onChange={(event) => setPassphrase(event.target.value)} /></label>}
        </div></fieldset>
        <footer><button type="button" onClick={cancelCreate}>{t("action.cancel")}</button><button className="button-primary" type="submit" disabled={!name.trim() || !secret.trim() || (usernameRequired && !username.trim())}><Save />{t("ansible.credentials.saveEncrypted")}</button></footer>
      </form> : <div className="credential-welcome"><span><ShieldCheck /></span><h4>{t("ansible.credentials.welcomeTitle")}</h4><p>{t("ansible.credentials.welcomeHint")}</p>{canManage && <button className="button-primary" type="button" onClick={beginCreate}><Plus />{t("ansible.credentials.openCreator")}</button>}</div>}
    </div>
  </section>;
}

function Projects({ items, credentials, canManage, t, toast, refresh }: { items: AnsibleProject[]; credentials: AnsibleCredential[]; canManage: boolean; t: Translate; toast: ToastFn; refresh: () => Promise<void> }) { const [open, setOpen] = useState(false); const [name, setName] = useState(""); const [url, setUrl] = useState(""); const [revision, setRevision] = useState("main"); const [credentialId, setCredentialId] = useState(""); async function save(event: React.FormEvent) { event.preventDefault(); try { await api.saveAnsibleProject({ name, source_type: url ? "git" : "editor", repository_url: url || null, revision, credential_id: credentialId || null, sync_before_run: false, allow_submodules: false, active: true }); setOpen(false); await refresh(); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error"); } } return <section className="ansible-panel"><header><div><h3>{t("ansible.projects.title")}</h3><p>{t("ansible.projects.hint")}</p></div>{canManage && <button onClick={() => setOpen((value) => !value)}><Plus />{t("ansible.project.add")}</button>}</header>{open && <form className="module-form-grid" onSubmit={save}><label>{t("common.name")}<input required value={name} onChange={(event) => setName(event.target.value)} /></label><label>{t("ansible.project.url")}<input type="text" inputMode="url" value={url} onChange={(event) => setUrl(event.target.value)} /></label><label>{t("ansible.project.revision")}<input value={revision} onChange={(event) => setRevision(event.target.value)} /></label><label>{t("ansible.credential.title")}<select value={credentialId} onChange={(event) => setCredentialId(event.target.value)}><option value="">{t("common.none")}</option>{credentials.filter((item) => item.type === "git_private_key").map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button className="button-primary"><Save />{t("action.save")}</button></form>}<Table headers={[t("common.name"), t("ansible.project.source"), t("ansible.project.revision"), t("ansible.project.commit"), t("ansible.project.lastSync"), t("column.actions")]} rows={items.map((item) => [item.name, item.source_type, item.revision, item.last_commit || t("common.none"), item.last_sync_at ? new Date(item.last_sync_at * 1000).toLocaleString() : t("common.none"), canManage && item.source_type === "git" && <button onClick={() => void api.syncAnsibleProject(item.id).then(() => toast(t("ansible.jobQueued"), "ok"))}>{t("ansible.project.sync")}</button>])} empty={t("ansible.projects.empty")} /></section>; }

const blankPlaybook = "---\n- name: Managed play\n  hosts: all\n  gather_facts: false\n  tasks:\n    - name: Connectivity\n      ansible.builtin.ping:\n";

function Playbooks({ items, projects, canManage, t, toast, refresh }: { items: AnsiblePlaybook[]; projects: AnsibleProject[]; canManage: boolean; t: Translate; toast: ToastFn; refresh: () => Promise<void> }) {
  const [editing, setEditing] = useState<AnsiblePlaybook | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [name, setName] = useState(""); const [filename, setFilename] = useState("playbook.yml"); const [projectId, setProjectId] = useState("");
  const [content, setContent] = useState(blankPlaybook); const [comment, setComment] = useState(""); const [search, setSearch] = useState("");
  const [validation, setValidation] = useState<AnsibleValidation | null>(null); const [fullscreen, setFullscreen] = useState(false); const [saving, setSaving] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);
  const visible = items.filter((item) => `${item.name} ${item.filename} ${projects.find((project) => project.id === item.project_id)?.name || ""}`.toLowerCase().includes(search.trim().toLowerCase()));
  const lines = useMemo(() => content.split("\n").map((_, index) => index + 1).join("\n"), [content]);
  const payload = { project_id: projectId, name: name.trim(), filename: normalizePlaybookFilename(filename || name), content, comment: comment.trim(), active: true };

  function select(item: AnsiblePlaybook) { setEditing(item); setEditorOpen(true); setName(item.name); setFilename(item.filename); setProjectId(item.project_id); setContent(item.content); setComment(""); setValidation(null); }
  function create() { setEditing(null); setEditorOpen(true); setName(""); setFilename("playbook.yml"); setProjectId(projects[0]?.id || ""); setContent(blankPlaybook); setComment(""); setValidation(null); }
  async function importFile(file?: File) {
    if (!file) return;
    if (!/\.ya?ml$/i.test(file.name) || file.size > 2_000_000) { toast(t("ansible.playbook.invalidFile"), "error"); return; }
    try { const text = await file.text(); setEditing(null); setEditorOpen(true); setName(file.name.replace(/\.ya?ml$/i, "").replace(/[-_]+/g, " ")); setFilename(normalizePlaybookFilename(file.name)); setProjectId(projects[0]?.id || ""); setContent(text); setComment(t("ansible.playbook.importComment")); setValidation(null); }
    catch { toast(t("ansible.playbook.readError"), "error"); }
    finally { if (uploadRef.current) uploadRef.current.value = ""; }
  }
  async function validate() { try { setValidation(await api.validateAnsiblePlaybook(payload)); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error"); } }
  async function save() {
    setSaving(true);
    try {
      const result = await api.validateAnsiblePlaybook(payload); setValidation(result); if (!result.ok) return;
      const saved = await api.saveAnsiblePlaybook(payload, editing?.id); setEditing(saved); setFilename(saved.filename); setComment(""); toast(t(editing ? "ansible.playbook.updated" : "ansible.playbook.created"), "ok"); await refresh();
    } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error"); }
    finally { setSaving(false); }
  }
  async function remove(item: AnsiblePlaybook) { if (!window.confirm(t("ansible.playbook.confirmDelete"))) return; try { await api.deleteAnsiblePlaybook(item.id); if (editing?.id === item.id) { setEditing(null); setEditorOpen(false); } toast(t("ansible.playbook.deleted"), "ok"); await refresh(); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error"); } }
  function download() { const blob = new Blob([content], { type: "application/yaml;charset=utf-8" }); const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = normalizePlaybookFilename(filename || name); anchor.click(); URL.revokeObjectURL(url); }

  return <section className={`ansible-panel ansible-playbooks ${fullscreen ? "fullscreen" : ""}`}>
    <header><div><h3>{t("ansible.playbooks.title")}</h3><p>{t("ansible.playbooks.libraryHint")}</p></div>{canManage && <div className="header-actions"><input ref={uploadRef} className="playbook-file-input" type="file" accept=".yml,.yaml,application/yaml,text/yaml" onChange={(event) => void importFile(event.target.files?.[0])} /><button type="button" onClick={() => uploadRef.current?.click()}><Upload />{t("ansible.playbook.import")}</button><button className="button-primary" type="button" onClick={create}><Plus />{t("ansible.playbook.add")}</button></div>}</header>
    {!projects.length && <div className="playbook-project-warning" role="alert"><AlertTriangle /><div><strong>{t("ansible.playbook.projectRequired")}</strong><span>{t("ansible.playbook.projectRequiredHint")}</span></div></div>}
    <div className="playbook-workspace">
      <aside className="playbook-library"><header><div><FileCode2 /><span><strong>{t("ansible.playbook.library")}</strong><small>{items.length} {t("ansible.playbook.items")}</small></span></div><label><Search /><input aria-label={t("action.search")} value={search} placeholder={t("ansible.playbook.search")} onChange={(event) => setSearch(event.target.value)} /></label></header><div className="playbook-list">{visible.map((item) => <article className={editing?.id === item.id ? "selected" : ""} key={item.id}><button className="playbook-open" type="button" onClick={() => select(item)}><span className="playbook-file-icon"><FileCode2 /></span><span className="playbook-list-copy"><strong>{item.name}</strong><code>{item.filename}</code><small>{projects.find((project) => project.id === item.project_id)?.name || t("common.none")} · v{item.current_version} · {new Date(item.updated_at * 1000).toLocaleString()}</small></span><Status state={item.risk_status} t={t} /><ChevronRight /></button>{canManage && <button className="playbook-delete" type="button" aria-label={`${t("action.delete")} ${item.name}`} onClick={() => void remove(item)}><Trash2 /></button>}</article>)}{!visible.length && <div className="playbook-empty"><FileCode2 /><strong>{search ? t("ansible.playbook.noResults") : t("ansible.playbook.empty")}</strong><span>{search ? t("ansible.playbook.changeSearch") : t("ansible.playbook.emptyHint")}</span>{canManage && !search && <button type="button" onClick={create}><Plus />{t("ansible.playbook.createFirst")}</button>}</div>}</div></aside>
      {editorOpen ? <div className="ansible-editor playbook-editor"><header><div><small>{editing ? t("ansible.playbook.editing") : t("ansible.playbook.new")}</small><h4>{name || t("ansible.playbook.untitled")}</h4></div><div><button type="button" onClick={download} aria-label={t("ansible.playbook.download")}><Download /></button><button type="button" onClick={() => { setEditorOpen(false); setFullscreen(false); }} aria-label={t("action.close")}><XCircle /></button></div></header><div className="playbook-editor-fields"><label>{t("common.name")}<input value={name} maxLength={100} onChange={(event) => { setName(event.target.value); if (!editing) setFilename(normalizePlaybookFilename(event.target.value)); }} disabled={!canManage} /></label><label>{t("ansible.playbook.filename")}<input value={filename} maxLength={200} pattern="[A-Za-z0-9][A-Za-z0-9_.-]*\.ya?ml" onChange={(event) => setFilename(event.target.value)} disabled={!canManage} /></label><label>{t("ansible.project.title")}<select value={projectId} onChange={(event) => setProjectId(event.target.value)} disabled={!canManage}><option value="">{t("common.select")}</option>{projects.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label>{t("ansible.playbook.versionComment")}<input value={comment} maxLength={500} placeholder={t("ansible.playbook.versionCommentHint")} onChange={(event) => setComment(event.target.value)} disabled={!canManage} /></label></div><div className="ansible-code-editor"><pre aria-hidden="true">{lines}</pre><textarea aria-label={t("ansible.playbook.content")} value={content} onChange={(event) => { setContent(event.target.value); setValidation(null); }} readOnly={!canManage} spellCheck={false} /></div><div className="playbook-editor-actions"><button type="button" onClick={() => setFullscreen((value) => !value)}><Maximize2 />{t("ansible.playbook.fullscreen")}</button><button type="button" onClick={() => void validate()}>{t("ansible.playbook.validate")}</button>{canManage && <button className="button-primary" type="button" disabled={saving || !name.trim() || !projectId || !content.trim()} onClick={() => void save()}><Save />{saving ? t("status.saving") : t("action.save")}</button>}</div>{validation && <RiskReport validation={validation} t={t} />}</div> : <div className="playbook-welcome"><FileCode2 /><h4>{t("ansible.playbook.selectTitle")}</h4><p>{t("ansible.playbook.selectHint")}</p>{canManage && <div><button type="button" onClick={() => uploadRef.current?.click()}><Upload />{t("ansible.playbook.import")}</button><button className="button-primary" type="button" onClick={create}><Plus />{t("ansible.playbook.add")}</button></div>}</div>}
    </div>
  </section>;
}

function normalizePlaybookFilename(value: string) { const extension = /\.yaml$/i.test(value.trim()) ? ".yaml" : ".yml"; const stem = value.trim().replace(/\.ya?ml$/i, "").toLowerCase().replace(/[^a-z0-9_.-]+/g, "-").replace(/^[^a-z0-9]+/, "").slice(0, 190) || "playbook"; return `${stem}${extension}`; }

function riskLabel(item: { code: string; message: string }, t: Translate) { const key = `ansible.risk.${item.code}`; const translated = t(key); return translated === key ? item.message : translated; }

function RiskReport({ validation, t }: { validation: AnsibleValidation; t: Translate }) { return <div className="ansible-risk" role="status"><header><Status state={validation.ok ? "ok" : "failed"} t={t} /><span>{t("ansible.playbook.tasks")}: {validation.task_count}</span></header>{validation.errors.map((item, index) => <p className="blocked" key={`e-${index}`}><XCircle />{riskLabel(item, t)} <code>{item.path || item.line}</code></p>)}{validation.blocked.map((item, index) => <p className="blocked" key={`b-${index}`}><XCircle />{riskLabel(item, t)} <code>{item.path}</code></p>)}{validation.warnings.map((item, index) => <p key={`w-${index}`}><AlertTriangle />{riskLabel(item, t)} <code>{item.path}</code></p>)}</div>; }

function Templates({ items, hosts, groups, projects, playbooks, canManage, canLaunch, t, toast, refresh }: { items: AnsibleTemplate[]; hosts: AnsibleHost[]; groups: AnsibleGroup[]; projects: AnsibleProject[]; playbooks: AnsiblePlaybook[]; canManage: boolean; canLaunch: boolean; t: Translate; toast: ToastFn; refresh: () => Promise<void> }) { const [open, setOpen] = useState(false); const [name, setName] = useState(""); const [projectId, setProjectId] = useState(""); const [playbookId, setPlaybookId] = useState(""); const [hostId, setHostId] = useState(""); const [plan, setPlan] = useState<Record<string, unknown> | null>(null); const [launchId, setLaunchId] = useState(""); async function save(event: React.FormEvent) { event.preventDefault(); await api.saveAnsibleTemplate({ name, description: "", project_id: projectId, playbook_id: playbookId, host_ids: hostId ? [hostId] : [], group_ids: [], ssh_credential_id: null, become_credential_id: null, vault_credential_id: null, limit: "", tags: [], skip_tags: [], check_mode: false, diff_mode: false, verbosity: 0, forks: 10, timeout_seconds: 3600, extra_vars: "{}", concurrency_policy: "same_hosts", sync_before_run: false, confirmation_required: true, active: true }); setOpen(false); await refresh(); } async function review(id: string) { setLaunchId(id); setPlan(await api.ansibleLaunchPlan(id)); } async function launch() { if (!launchId || !window.confirm(t("ansible.template.confirmLaunch"))) return; await api.launchAnsibleTemplate(launchId); setPlan(null); toast(t("ansible.jobQueued"), "ok", "admin", "ansible-controller"); } return <section className="ansible-panel"><header><div><h3>{t("ansible.templates.title")}</h3><p>{t("ansible.templates.hint")}</p></div>{canManage && <button onClick={() => setOpen((value) => !value)}><Plus />{t("ansible.template.add")}</button>}</header>{open && <form className="module-form-grid" onSubmit={save}><label>{t("common.name")}<input required value={name} onChange={(event) => setName(event.target.value)} /></label><label>{t("ansible.project.title")}<select required value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">{t("common.select")}</option>{projects.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label>{t("ansible.playbook.title")}<select required value={playbookId} onChange={(event) => setPlaybookId(event.target.value)}><option value="">{t("common.select")}</option>{playbooks.filter((item) => !projectId || item.project_id === projectId).map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label>{t("ansible.host.title")}<select required value={hostId} onChange={(event) => setHostId(event.target.value)}><option value="">{t("common.select")}</option>{hosts.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><button className="button-primary"><Save />{t("action.save")}</button></form>}<Table headers={[t("common.name"), t("ansible.playbook.title"), t("ansible.template.targets"), t("ansible.template.policy"), t("column.actions")]} rows={items.map((item) => [item.name, playbooks.find((playbook) => playbook.id === item.playbook_id)?.name || t("common.none"), item.host_ids.length + item.group_ids.length, t(`ansible.policy.${item.concurrency_policy}`), canLaunch && <button onClick={() => void review(item.id)}><Play />{t("ansible.template.review")}</button>])} empty={t("ansible.templates.empty")} />{plan && <div className="ansible-plan" role="dialog" aria-modal="true"><h3>{t("ansible.template.plan")}</h3><dl><dt>{t("ansible.template.hostCount")}</dt><dd>{String(plan.host_count)}</dd><dt>{t("ansible.template.checkMode")}</dt><dd>{String(plan.check_mode)}</dd><dt>{t("ansible.template.diffMode")}</dt><dd>{String(plan.diff_mode)}</dd></dl><pre>{JSON.stringify(plan.warnings || [], null, 2)}</pre><button className="button-primary" onClick={() => void launch()}>{t("ansible.template.confirmLaunch")}</button><button onClick={() => setPlan(null)}>{t("action.cancel")}</button></div>}</section>; }

function Jobs({ items, canCancel, canLaunch, t, toast, refresh }: { items: AnsibleExecution[]; canCancel: boolean; canLaunch: boolean; t: Translate; toast: ToastFn; refresh: () => Promise<void> }) { const [selected, setSelected] = useState<AnsibleExecution | null>(null); useEffect(() => { if (!selected || !["queued", "running"].includes(selected.status)) return; const source = new EventSource(`/api/modules/ansible-controller/jobs/${encodeURIComponent(selected.id)}/events`, { withCredentials: true }); const update = (event: MessageEvent) => { try { const value = JSON.parse(event.data) as { execution?: AnsibleExecution }; if (value.execution) setSelected(value.execution); } catch { /* malformed server event is ignored */ } }; source.addEventListener("progress", update as EventListener); source.addEventListener("done", update as EventListener); source.onerror = () => source.close(); return () => source.close(); }, [selected?.id, selected?.status]); async function cancel(item: AnsibleExecution) { if (!window.confirm(t("ansible.job.confirmCancel"))) return; await api.cancelAnsibleJob(item.id); await refresh(); } async function retry(item: AnsibleExecution) { await api.retryAnsibleJob(item.id); toast(t("ansible.jobQueued"), "ok"); await refresh(); } return <section className="ansible-panel"><header><div><h3>{t("ansible.jobs.title")}</h3><p>{t("ansible.jobs.hint")}</p></div></header><Table headers={[t("ansible.job.id"), t("common.status"), t("ansible.job.stage"), t("ansible.job.actor"), t("ansible.job.started"), t("column.actions")]} rows={items.map((item) => [<button className="link-button" onClick={() => void api.ansibleJob(item.id).then(setSelected)}>{item.id.slice(0, 12)}</button>, <Status state={item.status} t={t} />, item.stage, item.requested_by, new Date(item.created_at * 1000).toLocaleString(), <div className="module-row-actions">{canCancel && ["queued", "running"].includes(item.status) && <button onClick={() => void cancel(item)}><Square />{t("action.cancel")}</button>}{canLaunch && ["failed", "cancelled", "completed"].includes(item.status) && <button onClick={() => void retry(item)}><RefreshCw />{t("action.retry")}</button>}</div>])} empty={t("ansible.jobs.empty")} />{selected && <div className="ansible-live-log"><header><Status state={selected.status} t={t} /><strong>{selected.stage}</strong><button aria-label={t("action.close")} onClick={() => setSelected(null)}><XCircle /></button></header><div className="ansible-recap">{Object.entries(selected.summary || {}).map(([key, value]) => <span key={key}>{t(`ansible.recap.${key}`)}: <strong>{value}</strong></span>)}</div><pre aria-live="polite">{selected.stdout || selected.stderr || t("ansible.job.waitingLog")}</pre>{selected.host_results?.length ? <Table headers={[t("ansible.host.title"), t("ansible.recap.ok"), t("ansible.recap.changed"), t("ansible.recap.failed"), t("ansible.recap.unreachable"), t("common.status")]} rows={selected.host_results.map((result) => [result.host_name, result.ok_count, result.changed_count, result.failed_count, result.unreachable_count, <Status state={result.status} t={t} />])} empty="" /> : null}</div>}</section>; }

function Schedules({ items, templates, canManage, t, toast, refresh }: { items: AnsibleSchedule[]; templates: AnsibleTemplate[]; canManage: boolean; t: Translate; toast: ToastFn; refresh: () => Promise<void> }) { const [open, setOpen] = useState(false); const [name, setName] = useState(""); const [templateId, setTemplateId] = useState(""); const [kind, setKind] = useState<AnsibleSchedule["kind"]>("daily"); const [expression, setExpression] = useState("1"); async function save(event: React.FormEvent) { event.preventDefault(); try { await api.saveAnsibleSchedule({ name, template_id: templateId, kind, expression, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC", missed_policy: "skip", active: true }); setOpen(false); await refresh(); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error"); } } return <section className="ansible-panel"><header><div><h3>{t("ansible.schedules.title")}</h3><p>{t("ansible.schedules.hint")}</p></div>{canManage && <button onClick={() => setOpen((value) => !value)}><Plus />{t("ansible.schedule.add")}</button>}</header>{open && <form className="module-form-grid" onSubmit={save}><label>{t("common.name")}<input required value={name} onChange={(event) => setName(event.target.value)} /></label><label>{t("ansible.template.title")}<select required value={templateId} onChange={(event) => setTemplateId(event.target.value)}><option value="">{t("common.select")}</option>{templates.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>{t("ansible.schedule.kind")}<select value={kind} onChange={(event) => setKind(event.target.value as AnsibleSchedule["kind"])}>{["once", "hourly", "daily", "weekly", "monthly", "cron"].map((value) => <option key={value} value={value}>{t(`ansible.schedule.kind.${value}`)}</option>)}</select></label><label>{t("ansible.schedule.expression")}<input value={expression} onChange={(event) => setExpression(event.target.value)} /></label><button className="button-primary"><Save />{t("action.save")}</button></form>}<Table headers={[t("common.name"), t("ansible.template.title"), t("ansible.schedule.kind"), t("ansible.schedule.nextRun"), t("ansible.schedule.lastRun"), t("common.status")]} rows={items.map((item) => [item.name, templates.find((template) => template.id === item.template_id)?.name || t("common.none"), t(`ansible.schedule.kind.${item.kind}`), item.next_run_at ? new Date(item.next_run_at * 1000).toLocaleString() : t("common.none"), item.last_run_at ? new Date(item.last_run_at * 1000).toLocaleString() : t("common.none"), item.active ? t("common.enabled") : t("common.disabled")])} empty={t("ansible.schedules.empty")} /></section>; }

function Facts({ hosts, t }: { hosts: AnsibleHost[]; t: Translate }) { const [selected, setSelected] = useState(hosts[0]?.id || ""); const host = hosts.find((item) => item.id === selected); useEffect(() => { if (!selected && hosts[0]) setSelected(hosts[0].id); }, [hosts, selected]); return <section className="ansible-panel"><header><div><h3>{t("ansible.facts.title")}</h3><p>{t("ansible.facts.hint")}</p></div><select aria-label={t("ansible.host.title")} value={selected} onChange={(event) => setSelected(event.target.value)}>{hosts.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></header>{host ? <pre className="ansible-facts">{JSON.stringify(host.facts || {}, null, 2)}</pre> : <div className="empty-state">{t("ansible.facts.empty")}</div>}</section>; }

function Configuration({ value, canManage, t, toast, refresh }: { value: Record<string, unknown>; canManage: boolean; t: Translate; toast: ToastFn; refresh: () => Promise<void> }) { const [networks, setNetworks] = useState(""); const [awxUrl, setAwxUrl] = useState(""); const [awxCredential, setAwxCredential] = useState(""); const [verifyTls, setVerifyTls] = useState(true); useEffect(() => { setNetworks(Array.isArray(value.allowed_networks) ? value.allowed_networks.join("\n") : ""); const awx = (value.awx || {}) as Record<string, unknown>; setAwxUrl(String(awx.url || "")); setAwxCredential(String(awx.credential_id || "")); setVerifyTls(awx.verify_tls !== false); }, [value]); async function save() { try { await api.saveAnsibleConfig({ allowed_networks: networks.split(/\s+/).filter(Boolean), max_scan_addresses: 4096, default_concurrency_policy: "same_hosts", managed_username: String(value.managed_username || "algen-ansible"), managed_sudo_profile: value.managed_sudo_profile === "nopasswd" ? "nopasswd" : "none", managed_shell: value.managed_shell === "/bin/sh" ? "/bin/sh" : "/bin/bash", managed_comment: typeof value.managed_comment === "string" ? value.managed_comment : "Algen Ansible automation", managed_authorized_keys_mode: value.managed_authorized_keys_mode === "append" ? "append" : "exclusive", awx: awxUrl ? { url: awxUrl, credential_id: awxCredential || null, verify_tls: verifyTls, ca_certificate: "", timeout_seconds: 15 } : null }); toast(t("ansible.configuration.queued"), "ok"); await refresh(); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error"); } } return <section className="ansible-panel"><header><div><h3>{t("ansible.configuration.title")}</h3><p>{t("ansible.configuration.hint")}</p></div></header><div className="module-form-grid"><label className="wide">{t("ansible.configuration.allowedNetworks")}<textarea value={networks} onChange={(event) => setNetworks(event.target.value)} readOnly={!canManage} /><small>{t("ansible.configuration.networkSafety")}</small></label><label>{t("ansible.configuration.awxUrl")}<input type="url" value={awxUrl} onChange={(event) => setAwxUrl(event.target.value)} readOnly={!canManage} /></label><label>{t("ansible.configuration.awxCredential")}<input value={awxCredential} onChange={(event) => setAwxCredential(event.target.value)} readOnly={!canManage} /></label><label className="check"><input type="checkbox" checked={verifyTls} onChange={(event) => setVerifyTls(event.target.checked)} disabled={!canManage} />{t("ansible.configuration.verifyTls")}</label></div>{canManage && <button className="button-primary" onClick={() => void save()}><Save />{t("action.save")}</button>}</section>; }

function Backups({ items, canManage, t, toast, refresh }: { items: ModuleBackup[]; canManage: boolean; t: Translate; toast: ToastFn; refresh: () => Promise<void> }) { async function create() { try { await api.createAnsibleBackup(t("ansible.backup.description"), false); toast(t("ansible.jobQueued"), "ok"); await refresh(); } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error"); } } async function restore(item: ModuleBackup) { if (!window.confirm(t("ansible.backup.confirmRestore"))) return; await api.restoreAnsibleBackup(item.id, item.checksum); toast(t("ansible.jobQueued"), "ok"); } async function remove(item: ModuleBackup) { if (!window.confirm(t("ansible.backup.confirmDelete"))) return; await api.deleteAnsibleBackup(item.id); await refresh(); } return <section className="ansible-panel">{canManage && <div className="module-section-toolbar"><button className="button-primary" onClick={() => void create()}><Plus />{t("module.createBackup")}</button></div>}<ModuleBackups backups={items} t={t} onCreate={() => void create()} onRestore={(item) => void restore(item)} onDelete={(item) => void remove(item)} /></section>; }

function Table({ headers, rows, empty }: { headers: string[]; rows: React.ReactNode[][]; empty: string }) { if (!rows.length) return <div className="empty-state">{empty}</div>; return <div className="module-table-wrap"><table><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, index) => <td key={index}>{cell}</td>)}</tr>)}</tbody></table></div>; }
