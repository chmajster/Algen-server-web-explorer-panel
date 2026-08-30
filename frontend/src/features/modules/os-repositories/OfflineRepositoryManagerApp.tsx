import { Archive, CheckCircle2, Download, HardDrive, RefreshCw, ShieldAlert, Snowflake, Trash2, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type HostsManagerGroup, type ModuleStatus, type OsRepository, type OsRepositoryJob, type OsRepositorySnapshot } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import type {
  OfflineHostGroupCompatibility,
  OfflineRepositoryBundle,
  OfflineRepositoryDiagnostic,
  OfflineRepositorySettings,
  OfflineRepositoryTarget,
} from "../../../modules/os-repositories/api/client";
import { useRefreshOnConnectionRestored } from "../../connection/ConnectionStatusMonitor";
import { ModuleAppShell, ModuleHealthCard, type ModuleSection } from "../common/ModuleAppShell";
import "./offline-repository-manager.css";

const sections: ModuleSection[] = ["overview", "repositories", "packages", "assignments", "synchronizations", "snapshots", "jobs", "builder", "diagnostics", "settings"];
const sectionLabels: Partial<Record<ModuleSection, string>> = {
  overview: "Dashboard",
  repositories: "Targets",
  packages: "Bundles",
  assignments: "Host Groups",
  synchronizations: "Import",
  snapshots: "Delta & Freeze",
  jobs: "Jobs",
  builder: "Storage",
  diagnostics: "Diagnostics",
  settings: "Settings",
};
const fallbackStatus: ModuleStatus = { installed: true, package_version: "", update_available: false, service_state: "unknown", service_enabled: false, services: {}, health: "unknown", health_message: "", last_action: "", last_action_status: "", last_error: "", metrics: {} };
const emptySettings: OfflineRepositorySettings = { air_gapped_mode: false, keep_last: 5, delete_after_days: 90, keep_production: true, keep_signed: true };

type StagedBundle = { id: string; filename: string; size_bytes: number; modified_at: number };
type Diagnostics = { checks: OfflineRepositoryDiagnostic[]; tools: Record<string, string>; active_offline_jobs: number; storage: Record<string, number>; air_gapped_mode: boolean };

function bytes(value: number | undefined): string {
  const size = Number(value || 0);
  if (!size) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
  return `${(size / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function packageList(value: string): string[] {
  return value.split(/[\n,]+/).map((item) => item.trim()).filter(Boolean);
}

function errorText(error: unknown, t: Translate): string {
  return error instanceof Error ? error.message : t("error.generic");
}

export function OfflineRepositoryManagerApp({ permissions, t, toast }: { permissions: string[]; t: Translate; toast: ToastFn }) {
  const [section, setSection] = useState<ModuleSection>("overview");
  const [status, setStatus] = useState<ModuleStatus>(fallbackStatus);
  const [dashboard, setDashboard] = useState<{ repositories: number; targets: number; packages: number; snapshots: number; bundles: number; air_gapped_mode: boolean; storage: Record<string, number> } | null>(null);
  const [settings, setSettings] = useState<OfflineRepositorySettings>(emptySettings);
  const [repositories, setRepositories] = useState<OsRepository[]>([]);
  const [snapshots, setSnapshots] = useState<OsRepositorySnapshot[]>([]);
  const [targets, setTargets] = useState<OfflineRepositoryTarget[]>([]);
  const [bundles, setBundles] = useState<OfflineRepositoryBundle[]>([]);
  const [staged, setStaged] = useState<StagedBundle[]>([]);
  const [jobs, setJobs] = useState<OsRepositoryJob[]>([]);
  const [groups, setGroups] = useState<HostsManagerGroup[]>([]);
  const [storage, setStorage] = useState<Record<string, number>>({});
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [loading, setLoading] = useState(true);
  const [jobDetails, setJobDetails] = useState<Awaited<ReturnType<typeof api.offlineRepositoryJob>> | null>(null);

  const canTargets = permissions.includes("os-repositories.offline.targets.manage");
  const canExport = permissions.includes("os-repositories.offline.export");
  const canImport = permissions.includes("os-repositories.offline.import");
  const canVerify = permissions.includes("os-repositories.offline.verify");
  const canDelete = permissions.includes("os-repositories.offline.delete");
  const canDelta = permissions.includes("os-repositories.offline.delta");
  const canFreeze = permissions.includes("os-repositories.offline.freeze");
  const canConfigure = permissions.includes("os-repositories.offline.configure");
  const canAirGap = permissions.includes("os-repositories.offline.airgap.manage");
  const canViewHosts = permissions.includes("hosts-manager.hosts.view");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [moduleData, dashboardData, settingsData, repositoryPage, snapshotPage, targetData, bundlePage, stagedData, jobPage, storageData, diagnosticData, groupData] = await Promise.all([
        api.module("os-repositories"),
        api.offlineRepositoryDashboard(),
        api.offlineRepositorySettings(),
        api.osRepositories(),
        api.osRepositorySnapshots(),
        api.offlineRepositoryTargets(),
        api.offlineRepositoryBundles(),
        api.stagedOfflineRepositoryBundles(),
        api.offlineRepositoryJobs(),
        api.offlineRepositoryStorage(),
        api.offlineRepositoryDiagnostics(),
        canViewHosts ? api.hostsManagerGroups() : Promise.resolve([]),
      ]);
      setStatus(moduleData.module_status);
      setDashboard(dashboardData);
      setSettings(settingsData);
      setRepositories(repositoryPage.items);
      setSnapshots(snapshotPage.items);
      setTargets(targetData);
      setBundles(bundlePage.items);
      setStaged(stagedData.items);
      setJobs(jobPage.items);
      setStorage(storageData);
      setDiagnostics(diagnosticData);
      setGroups(groupData);
    } catch (error) {
      toast(errorText(error, t), "error", "admin", "os-repositories");
    } finally {
      setLoading(false);
    }
  }, [canViewHosts, t, toast]);

  useEffect(() => { void refresh(); }, [refresh]);
  useRefreshOnConnectionRestored(() => { void refresh(); });

  const activeJob = jobs.find((job) => ["queued", "running"].includes(job.status));
  let content: React.ReactNode;
  if (section === "overview") content = <Overview dashboard={dashboard} diagnostics={diagnostics} />;
  else if (section === "repositories") content = <TargetsPanel repositories={repositories} targets={targets} canManage={canTargets} t={t} toast={toast} onChanged={refresh} />;
  else if (section === "packages") content = <BundlesPanel repositories={repositories} snapshots={snapshots} bundles={bundles} canExport={canExport} canDelete={canDelete} canConfigure={canConfigure} canDelta={canDelta} t={t} toast={toast} onChanged={refresh} />;
  else if (section === "assignments") content = <HostGroupsPanel repositories={repositories} groups={groups} enabled={canTargets && canViewHosts} t={t} toast={toast} onChanged={refresh} />;
  else if (section === "synchronizations") content = <ImportPanel repositories={repositories} staged={staged} canImport={canImport} canVerify={canVerify} t={t} toast={toast} onChanged={refresh} />;
  else if (section === "snapshots") content = <DeltaPanel snapshots={snapshots} repositories={repositories} canDelta={canDelta} canFreeze={canFreeze} t={t} toast={toast} onChanged={refresh} />;
  else if (section === "jobs") content = <JobsPanel jobs={jobs} canManage={canConfigure} t={t} toast={toast} onOpen={async (id) => setJobDetails(await api.offlineRepositoryJob(id))} onChanged={refresh} />;
  else if (section === "builder") content = <StoragePanel storage={storage} />;
  else if (section === "diagnostics") content = <DiagnosticsPanel diagnostics={diagnostics} />;
  else content = <SettingsPanel value={settings} canSave={canConfigure} canAirGap={canAirGap} t={t} toast={toast} onSaved={refresh} />;

  return <>
    <ModuleAppShell
      className="offline-repository-manager-app"
      name="Offline Repository Manager"
      status={status}
      healthMessage={dashboard?.air_gapped_mode ? "Air-Gapped Mode is enabled. Outbound repository synchronization is blocked by the backend." : "Portable APT/RPM bundles for disconnected Linux environments."}
      activeJob={activeJob ? { operation: activeJob.operation, progress: activeJob.progress } : null}
      section={section}
      sections={sections}
      sectionLabels={sectionLabels}
      t={t}
      onSection={setSection}
      actions={<button onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button>}
    >
      {loading && !dashboard ? <div className="module-loading"><RefreshCw className="spin" />{t("common.loading")}</div> : content}
    </ModuleAppShell>
    {jobDetails && <div className="orm-job-drawer"><div className="orm-panel"><header><div><strong>{jobDetails.operation}</strong><small>{jobDetails.id}</small></div><button onClick={() => setJobDetails(null)}>×</button></header><p>Status: <strong>{jobDetails.status}</strong> · {jobDetails.stage} · {jobDetails.progress}%</p>{jobDetails.error && <div className="orm-alert danger">{jobDetails.error}</div>}<pre>{jobDetails.logs.map((line) => `[${line.stream}] ${line.line}`).join("\n") || "No logs"}</pre></div></div>}
  </>;
}

function Overview({ dashboard, diagnostics }: { dashboard: { repositories: number; targets: number; packages: number; snapshots: number; bundles: number; air_gapped_mode: boolean; storage: Record<string, number> } | null; diagnostics: Diagnostics | null }) {
  if (!dashboard) return null;
  const errorCount = diagnostics?.checks.filter((item) => item.status === "error").length || 0;
  return <>
    {dashboard.air_gapped_mode && <div className="orm-alert warning"><ShieldAlert />Air-Gapped Mode active: mirror synchronization and outbound repository refreshes are blocked.</div>}
    <div className="module-health-grid">
      <ModuleHealthCard title="Repositories" value={dashboard.repositories} />
      <ModuleHealthCard title="Targets" value={dashboard.targets} />
      <ModuleHealthCard title="Bundles" value={dashboard.bundles} />
      <ModuleHealthCard title="Snapshots" value={dashboard.snapshots} />
      <ModuleHealthCard title="Packages" value={dashboard.packages} />
      <ModuleHealthCard title="Bundle storage" value={bytes(dashboard.storage.bundle_bytes)} />
      <ModuleHealthCard title="Air gap" value={dashboard.air_gapped_mode ? "Enabled" : "Disabled"} tone={dashboard.air_gapped_mode ? "warning" : "success"} />
      <ModuleHealthCard title="Diagnostic errors" value={errorCount} tone={errorCount ? "danger" : "success"} />
    </div>
    <section className="orm-panel"><h3>Workflow</h3><div className="orm-flow"><span>Online mirror</span><b>→</b><span>Snapshot</span><b>→</b><span>Bundle</span><b>→</b><span>Controlled transfer</span><b>→</b><span>Verify</span><b>→</b><span>Import</span><b>→</b><span>Testing / Production</span></div></section>
  </>;
}

function TargetsPanel({ repositories, targets, canManage, t, toast, onChanged }: { repositories: OsRepository[]; targets: OfflineRepositoryTarget[]; canManage: boolean; t: Translate; toast: ToastFn; onChanged: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [repositoryId, setRepositoryId] = useState("");
  const [channel, setChannel] = useState("testing");
  const [architecture, setArchitecture] = useState("amd64");
  const [packages, setPackages] = useState("");
  const selected = repositories.find((item) => item.id === repositoryId);
  async function save() {
    if (!selected || !name.trim()) return;
    try {
      await api.saveOfflineRepositoryTarget({ name: name.trim(), repository_id: selected.id, channel, distribution: selected.distribution, distribution_version: selected.distribution_version, architecture, package_names: packageList(packages), include_dependencies: true, signing_key_id: selected.signing_key_id || null, host_group_id: null });
      setName(""); setPackages(""); await onChanged();
      toast("Offline target saved", "ok", "admin", "os-repositories");
    } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); }
  }
  return <div className="orm-stack">
    {canManage && <section className="orm-panel"><h3>Create reusable target</h3><div className="orm-form-grid"><label>Name<input value={name} onChange={(event) => setName(event.target.value)} /></label><label>Repository<select value={repositoryId} onChange={(event) => { const value = event.target.value; setRepositoryId(value); const repo = repositories.find((item) => item.id === value); if (repo?.architectures[0]) setArchitecture(repo.architectures[0]); }}><option value="">Select…</option>{repositories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Channel<select value={channel} onChange={(event) => setChannel(event.target.value)}><option value="testing">Testing</option><option value="production">Production</option></select></label><label>Architecture<select value={architecture} onChange={(event) => setArchitecture(event.target.value)}>{(selected?.architectures || ["amd64"]).map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label className="wide">Packages (comma/newline; empty = complete snapshot)<textarea value={packages} onChange={(event) => setPackages(event.target.value)} /></label></div><button className="button-primary" onClick={() => void save()} disabled={!selected || !name.trim()}>Save target</button></section>}
    <section className="orm-panel"><h3>Targets</h3><SimpleTable heads={["Name", "Repository", "Scope", "Architecture", "Packages", "Host group", "Actions"]} rows={targets.map((item) => [item.name, repositories.find((repo) => repo.id === item.repository_id)?.name || item.repository_id.slice(0, 8), item.snapshot_id ? `snapshot ${item.snapshot_id.slice(0, 8)}` : item.channel || "—", item.architecture, item.package_names.length || "all", item.host_group_id?.slice(0, 8) || "—", canManage ? <button className="danger" onClick={() => void api.deleteOfflineRepositoryTarget(item.id).then(onChanged)}><Trash2 />Delete</button> : "—"])} /></section>
  </div>;
}

function BundlesPanel({ repositories, snapshots, bundles, canExport, canDelete, canConfigure, canDelta, t, toast, onChanged }: { repositories: OsRepository[]; snapshots: OsRepositorySnapshot[]; bundles: OfflineRepositoryBundle[]; canExport: boolean; canDelete: boolean; canConfigure: boolean; canDelta: boolean; t: Translate; toast: ToastFn; onChanged: () => Promise<void> }) {
  const [repositoryId, setRepositoryId] = useState("");
  const [snapshotId, setSnapshotId] = useState("");
  const [architecture, setArchitecture] = useState("amd64");
  const [bundleType, setBundleType] = useState<"full" | "selected" | "delta">("full");
  const [packages, setPackages] = useState("");
  const [baseSnapshotId, setBaseSnapshotId] = useState("");
  const [signManifest, setSignManifest] = useState(true);
  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  const selectedRepository = repositories.find((item) => item.id === repositoryId);
  const repositorySnapshots = snapshots.filter((item) => !repositoryId || item.repository_id === repositoryId);
  const payload = useMemo(() => ({ repository_id: repositoryId, snapshot_id: snapshotId, architecture, bundle_type: bundleType, package_names: packageList(packages), include_dependencies: true, base_snapshot_id: bundleType === "delta" ? baseSnapshotId : null, sign_manifest: signManifest }), [architecture, baseSnapshotId, bundleType, packages, repositoryId, signManifest, snapshotId]);
  async function planExport() { try { setPlan(await api.planOfflineRepositoryExport(payload)); } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); } }
  async function exportBundle() { try { await api.createOfflineRepositoryExport(payload); toast("Offline export queued", "ok", "admin", "os-repositories"); await onChanged(); } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); } }
  async function remove(item: OfflineRepositoryBundle) {
    let force = false; let confirmation = "";
    if (item.pinned) { confirmation = window.prompt("Pinned bundle. Type DELETE to remove it.") || ""; if (confirmation !== "DELETE") return; force = true; }
    if (!item.pinned && !window.confirm(`Delete bundle ${item.filename}?`)) return;
    try { await api.deleteOfflineRepositoryBundle(item.id, force, confirmation); await onChanged(); } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); }
  }
  return <div className="orm-stack">
    {canExport && <section className="orm-panel"><h3>Create bundle</h3><div className="orm-form-grid"><label>Repository<select value={repositoryId} onChange={(event) => { const value = event.target.value; setRepositoryId(value); setSnapshotId(""); const repo = repositories.find((item) => item.id === value); if (repo?.architectures[0]) setArchitecture(repo.architectures[0]); }}><option value="">Select…</option>{repositories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Snapshot<select value={snapshotId} onChange={(event) => setSnapshotId(event.target.value)}><option value="">Select…</option>{repositorySnapshots.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Architecture<select value={architecture} onChange={(event) => setArchitecture(event.target.value)}>{(selectedRepository?.architectures || ["amd64"]).map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label>Bundle type<select value={bundleType} onChange={(event) => setBundleType(event.target.value as "full" | "selected" | "delta")}><option value="full">Full</option><option value="selected">Selected packages</option>{canDelta && <option value="delta">Delta</option>}</select></label>{bundleType === "delta" && <label>Base snapshot<select value={baseSnapshotId} onChange={(event) => setBaseSnapshotId(event.target.value)}><option value="">Select…</option>{repositorySnapshots.filter((item) => item.id !== snapshotId).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}<label className="wide">Selected packages<textarea disabled={bundleType === "full"} value={packages} onChange={(event) => setPackages(event.target.value)} /></label><label className="orm-check"><input type="checkbox" checked={signManifest} onChange={(event) => setSignManifest(event.target.checked)} /> Sign manifest when a repository key is configured</label></div><div className="orm-actions"><button onClick={() => void planExport()} disabled={!repositoryId || !snapshotId}>Plan export</button><button className="button-primary" onClick={() => void exportBundle()} disabled={!repositoryId || !snapshotId || (bundleType === "selected" && !packageList(packages).length) || (bundleType === "delta" && !baseSnapshotId)}>Create bundle</button></div>{plan && <JsonPreview value={plan} />}</section>}
    <section className="orm-panel"><h3>Bundles</h3><SimpleTable heads={["Created", "Type", "Repository", "Arch", "Packages", "Size", "Signature", "Status", "Actions"]} rows={bundles.filter((item) => item.status !== "deleted").map((item) => [new Date(item.created_at * 1000).toLocaleString(), item.bundle_type, repositories.find((repo) => repo.id === item.repository_id)?.name || item.repository_id.slice(0, 8), item.architecture, item.package_count, bytes(item.size_bytes), item.signed ? item.signature_status : "unsigned", item.status, <div className="orm-actions"><a className="button" href={api.offlineRepositoryBundleDownloadPath(item.id)}><Download />Download</a>{canConfigure && <button onClick={() => void api.pinOfflineRepositoryBundle(item.id, !item.pinned).then(onChanged)}>{item.pinned ? "Unpin" : "Pin"}</button>}{canDelete && <button className="danger" onClick={() => void remove(item)}><Trash2 />Delete</button>}</div>])} /></section>
  </div>;
}

function HostGroupsPanel({ repositories, groups, enabled, t, toast, onChanged }: { repositories: OsRepository[]; groups: HostsManagerGroup[]; enabled: boolean; t: Translate; toast: ToastFn; onChanged: () => Promise<void> }) {
  const [groupId, setGroupId] = useState("");
  const [repositoryIds, setRepositoryIds] = useState<string[]>([]);
  const [packages, setPackages] = useState("");
  const [channel, setChannel] = useState("testing");
  const [compatibility, setCompatibility] = useState<OfflineHostGroupCompatibility | null>(null);
  function toggleRepository(id: string) { setRepositoryIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]); }
  async function check() { try { setCompatibility(await api.offlineRepositoryHostGroupCompatibility(groupId, repositoryIds)); } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); } }
  async function generate() { try { const result = await api.createOfflineRepositoryTargetsFromHostGroup({ host_group_id: groupId, repository_ids: repositoryIds, channel, package_names: packageList(packages), include_dependencies: true, name_prefix: "Hosts" }); setCompatibility(result.compatibility); toast(`${result.targets.length} target(s) generated`, "ok", "admin", "os-repositories"); await onChanged(); } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); } }
  if (!enabled) return <section className="orm-panel"><div className="orm-alert">Hosts Manager integration requires `hosts-manager.hosts.view` and `os-repositories.offline.targets.manage`.</div></section>;
  return <div className="orm-stack"><section className="orm-panel"><h3>Generate targets from Hosts Manager group</h3><div className="orm-form-grid"><label>Host group<select value={groupId} onChange={(event) => setGroupId(event.target.value)}><option value="">Select…</option>{groups.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.host_ids.length})</option>)}</select></label><label>Channel<select value={channel} onChange={(event) => setChannel(event.target.value)}><option value="testing">Testing</option><option value="production">Production</option></select></label><fieldset className="wide"><legend>Candidate repositories</legend><div className="orm-checkbox-grid">{repositories.map((item) => <label key={item.id} className="orm-check"><input type="checkbox" checked={repositoryIds.includes(item.id)} onChange={() => toggleRepository(item.id)} />{item.name} · {item.distribution} {item.distribution_version} · {item.architectures.join(", ")}</label>)}</div></fieldset><label className="wide">Packages<textarea value={packages} onChange={(event) => setPackages(event.target.value)} /></label></div><div className="orm-actions"><button onClick={() => void check()} disabled={!groupId || !repositoryIds.length}>Compatibility</button><button className="button-primary" onClick={() => void generate()} disabled={!groupId || !repositoryIds.length}>Generate targets</button></div></section>{compatibility && <section className="orm-panel"><h3>Compatibility result</h3><div className="module-health-grid"><ModuleHealthCard title="Hosts" value={compatibility.total_hosts} /><ModuleHealthCard title="Compatible" value={compatibility.compatible_hosts} tone="success" /><ModuleHealthCard title="Incompatible" value={compatibility.incompatible_hosts} tone={compatibility.incompatible_hosts ? "warning" : "success"} /></div><SimpleTable heads={["OS / version / architecture", "Hosts"]} rows={compatibility.signatures.map((item) => [item.signature, item.count])} />{compatibility.incompatible.length > 0 && <JsonPreview value={compatibility.incompatible} />}</section>}</div>;
}

function ImportPanel({ repositories, staged, canImport, canVerify, t, toast, onChanged }: { repositories: OsRepository[]; staged: StagedBundle[]; canImport: boolean; canVerify: boolean; t: Translate; toast: ToastFn; onChanged: () => Promise<void> }) {
  const [repositoryId, setRepositoryId] = useState("");
  const [publishChannel, setPublishChannel] = useState("");
  const [inspection, setInspection] = useState<Record<string, unknown> | null>(null);
  async function upload(file: File) { try { await api.uploadOfflineRepositoryBundle(file); toast("Bundle staged", "ok", "admin", "os-repositories"); await onChanged(); } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); } }
  async function inspect(id: string) { try { setInspection(await api.inspectOfflineRepositoryBundle(id)); } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); } }
  async function verify(id: string) { try { await api.verifyOfflineRepositoryBundle(id, repositoryId); toast("Verification job queued", "ok", "admin", "os-repositories"); await onChanged(); } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); } }
  async function importBundle(id: string) { try { await api.importOfflineRepositoryBundle(id, { repository_id: repositoryId, publish_channel: publishChannel || null, confirmation_text: publishChannel === "production" ? "Production" : "" }); toast("Import job queued", "ok", "admin", "os-repositories"); await onChanged(); } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); } }
  return <div className="orm-stack"><section className="orm-panel"><h3>Controlled staging</h3><div className="orm-form-grid"><label>Destination repository<select value={repositoryId} onChange={(event) => setRepositoryId(event.target.value)}><option value="">Select…</option>{repositories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Publish after import<select value={publishChannel} onChange={(event) => setPublishChannel(event.target.value)}><option value="">Do not publish</option><option value="testing">Testing</option><option value="production">Production</option></select></label>{canImport && <label className="orm-upload"><Upload />Upload bundle<input type="file" accept=".tar.gz,.tgz,.tar.zst,.tzst" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); }} /></label>}</div></section><section className="orm-panel"><h3>Staged bundles</h3><SimpleTable heads={["File", "Size", "Modified", "Actions"]} rows={staged.map((item) => [item.filename, bytes(item.size_bytes), new Date(item.modified_at * 1000).toLocaleString(), <div className="orm-actions"><button onClick={() => void inspect(item.id)}>Inspect</button>{canVerify && <button onClick={() => void verify(item.id)} disabled={!repositoryId}><CheckCircle2 />Verify</button>}{canImport && <button className="button-primary" onClick={() => void importBundle(item.id)} disabled={!repositoryId}>Import</button>}</div>])} /></section>{inspection && <section className="orm-panel"><h3>Bundle inspection</h3><JsonPreview value={inspection} /></section>}</div>;
}

function DeltaPanel({ snapshots, repositories, canDelta, canFreeze, t, toast, onChanged }: { snapshots: OsRepositorySnapshot[]; repositories: OsRepository[]; canDelta: boolean; canFreeze: boolean; t: Translate; toast: ToastFn; onChanged: () => Promise<void> }) {
  const [baseId, setBaseId] = useState(""); const [targetId, setTargetId] = useState(""); const [architecture, setArchitecture] = useState("amd64"); const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  const target = snapshots.find((item) => item.id === targetId); const repo = repositories.find((item) => item.id === target?.repository_id);
  async function calculate() { try { setPlan(await api.offlineRepositoryDeltaPlan(baseId, targetId, architecture)); } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); } }
  async function freeze() { try { await api.freezeOfflineRepositorySnapshot(targetId); toast("Snapshot frozen", "ok", "admin", "os-repositories"); await onChanged(); } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); } }
  return <section className="orm-panel"><h3>Delta planning and snapshot freeze</h3><div className="orm-form-grid"><label>Base snapshot<select value={baseId} onChange={(event) => setBaseId(event.target.value)}><option value="">Select…</option>{snapshots.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Target snapshot<select value={targetId} onChange={(event) => { setTargetId(event.target.value); const selected = snapshots.find((item) => item.id === event.target.value); const repository = repositories.find((item) => item.id === selected?.repository_id); if (repository?.architectures[0]) setArchitecture(repository.architectures[0]); }}><option value="">Select…</option>{snapshots.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Architecture<select value={architecture} onChange={(event) => setArchitecture(event.target.value)}>{(repo?.architectures || ["amd64"]).map((item) => <option key={item} value={item}>{item}</option>)}</select></label></div><div className="orm-actions">{canDelta && <button onClick={() => void calculate()} disabled={!baseId || !targetId}>Calculate delta</button>}{canFreeze && <button onClick={() => void freeze()} disabled={!targetId}><Snowflake />Freeze target snapshot</button>}</div>{plan && <JsonPreview value={plan} />}</section>;
}

function JobsPanel({ jobs, canManage, t, toast, onOpen, onChanged }: { jobs: OsRepositoryJob[]; canManage: boolean; t: Translate; toast: ToastFn; onOpen: (id: string) => void; onChanged: () => Promise<void> }) {
  async function action(id: string, operation: "cancel" | "retry") { try { if (operation === "cancel") await api.cancelOfflineRepositoryJob(id); else await api.retryOfflineRepositoryJob(id); await onChanged(); } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); } }
  return <section className="orm-panel"><h3>Durable offline jobs</h3><SimpleTable heads={["Operation", "Status", "Stage", "Progress", "Current item", "Error", "Actions"]} rows={jobs.map((item) => [item.operation, item.status, item.stage, `${item.progress}%`, item.current_item || "—", item.error || "—", <div className="orm-actions"><button onClick={() => onOpen(item.id)}>Logs</button>{canManage && ["queued", "running"].includes(item.status) && <button onClick={() => void action(item.id, "cancel")}>Cancel</button>}{canManage && ["failed", "cancelled"].includes(item.status) && <button onClick={() => void action(item.id, "retry")}>Retry</button>}</div>])} /></section>;
}

function StoragePanel({ storage }: { storage: Record<string, number> }) {
  const entries = Object.entries(storage);
  return <section className="orm-panel"><h3><HardDrive /> Storage and deduplication</h3><div className="module-health-grid">{entries.map(([key, value]) => <ModuleHealthCard key={key} title={key.replace(/_/g, " ")} value={key.includes("bytes") || key.includes("space") ? bytes(value) : value} />)}</div></section>;
}

function DiagnosticsPanel({ diagnostics }: { diagnostics: Diagnostics | null }) {
  if (!diagnostics) return null;
  return <div className="orm-stack"><section className="orm-panel"><h3>Offline checks</h3><div className="orm-check-list">{diagnostics.checks.map((item) => <div key={item.id} className={`orm-diagnostic ${item.status}`}><span>{item.id.replace(/_/g, " ")}</span><strong>{item.status}</strong><small>{item.message}</small></div>)}</div></section><section className="orm-panel"><h3>Tools</h3><SimpleTable heads={["Tool", "Path"]} rows={Object.entries(diagnostics.tools).map(([name, path]) => [name, path || "not installed"])} /></section></div>;
}

function SettingsPanel({ value, canSave, canAirGap, t, toast, onSaved }: { value: OfflineRepositorySettings; canSave: boolean; canAirGap: boolean; t: Translate; toast: ToastFn; onSaved: () => Promise<void> }) {
  const [settings, setSettings] = useState(value);
  useEffect(() => setSettings(value), [value]);
  async function save() { try { await api.saveOfflineRepositorySettings(settings); toast("Offline repository settings saved", "ok", "admin", "os-repositories"); await onSaved(); } catch (error) { toast(errorText(error, t), "error", "admin", "os-repositories"); } }
  return <div className="orm-stack"><section className="orm-panel"><h3>Air-Gapped Mode</h3><div className={`orm-alert ${settings.air_gapped_mode ? "warning" : ""}`}><ShieldAlert />This control is enforced in the backend. Enabling it blocks new mirror synchronization and aborts queued sync before DNS/HTTP access.</div><label className="orm-check"><input type="checkbox" checked={settings.air_gapped_mode} disabled={!canSave || !canAirGap} onChange={(event) => setSettings((current) => ({ ...current, air_gapped_mode: event.target.checked }))} /> Enable Air-Gapped Mode</label>{!canAirGap && <small>Changing this switch requires `os-repositories.offline.airgap.manage`.</small>}</section><section className="orm-panel"><h3>Retention</h3><div className="orm-form-grid"><label>Keep latest bundles<input type="number" min={1} max={100} value={settings.keep_last} disabled={!canSave} onChange={(event) => setSettings((current) => ({ ...current, keep_last: Number(event.target.value) }))} /></label><label>Delete after days<input type="number" min={1} max={3650} value={settings.delete_after_days} disabled={!canSave} onChange={(event) => setSettings((current) => ({ ...current, delete_after_days: Number(event.target.value) }))} /></label><label className="orm-check"><input type="checkbox" checked={settings.keep_production} disabled={!canSave} onChange={(event) => setSettings((current) => ({ ...current, keep_production: event.target.checked }))} /> Keep Production bundles</label><label className="orm-check"><input type="checkbox" checked={settings.keep_signed} disabled={!canSave} onChange={(event) => setSettings((current) => ({ ...current, keep_signed: event.target.checked }))} /> Keep signed bundles</label></div>{canSave && <button className="button-primary" onClick={() => void save()}>Save settings</button>}</section></div>;
}

function SimpleTable({ heads, rows }: { heads: string[]; rows: React.ReactNode[][] }) {
  return <div className="module-table-wrap"><table className="module-table"><thead><tr>{heads.map((head) => <th key={head}>{head}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table>{!rows.length && <div className="empty-state"><Archive />No items</div>}</div>;
}

function JsonPreview({ value }: { value: unknown }) {
  return <pre className="orm-json">{JSON.stringify(value, null, 2)}</pre>;
}
