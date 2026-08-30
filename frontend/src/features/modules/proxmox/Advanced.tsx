import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Play,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ProxmoxConnection } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { request } from "../../../core/api/transport";

export type ProxmoxAdvancedFeature = {
  id: number;
  slug: string;
  name: string;
  scope: string;
};

type Catalog = { features: ProxmoxAdvancedFeature[]; total: number };
type JsonObject = Record<string, unknown>;

type AdvancedProps = {
  connections: ProxmoxConnection[];
  permissions: string[];
  t: Translate;
  toast: ToastFn;
};

const REPORT_BASE = "/api/modules/proxmox-manager/advanced";
const MANAGE_PERMISSION = "hosts-manager.hosts.manage";

function asRecord(value: unknown): JsonObject {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : {};
}

function countArray(report: JsonObject, keys: string[]): number | null {
  for (const key of keys) {
    const value = report[key];
    if (Array.isArray(value)) return value.length;
  }
  return null;
}

function featureMetric(feature: string, report: JsonObject): { value: string; label: string } | null {
  const direct: Record<string, [string, string]> = {
    "capacity-planner": ["estimated_vm_capacity", "Estimated VM capacity"],
    "backup-analyzer": ["coverage_percent", "Backup coverage %"],
    "snapshot-retention": ["count", "Cleanup candidates"],
    "drift-manager": ["drifted", "Drifted VMs"],
  };
  const entry = direct[feature];
  if (entry && typeof report[entry[0]] === "number") return { value: String(report[entry[0]]), label: entry[1] };
  const count = countArray(report, ["vms", "nodes", "storage", "jobs", "resources", "interfaces", "zones", "templates", "isos", "orphans", "snapshots"]);
  return count === null ? null : { value: String(count), label: "Items" };
}

function PrettyJson({ value }: { value: unknown }) {
  return <pre className="proxmox-advanced-json">{JSON.stringify(value, null, 2)}</pre>;
}

function AsyncButton({ running, children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { running?: boolean }) {
  return <button type="button" {...props} disabled={Boolean(running || props.disabled)}>{running ? <Loader2 className="spin" /> : null}{children}</button>;
}

function CloudInitForm({ connectionId, onSaved, toast }: { connectionId: string; onSaved: () => void | Promise<void>; toast: ToastFn }) {
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [ipconfig, setIpconfig] = useState("ip=dhcp");
  const [nameserver, setNameserver] = useState("");
  const [searchdomain, setSearchdomain] = useState("");
  const [packages, setPackages] = useState("");
  const [cicustom, setCicustom] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await request(`${REPORT_BASE}/cloud-init-profiles`, {
        method: "POST",
        body: JSON.stringify({
          connection_id: connectionId,
          name: name.trim(),
          username: username.trim(),
          ssh_keys: [],
          ipconfig: ipconfig.trim() || "ip=dhcp",
          nameserver: nameserver.trim(),
          searchdomain: searchdomain.trim(),
          packages: packages.split(/[\n,]/).map((item) => item.trim()).filter(Boolean),
          cicustom: cicustom.trim(),
          notes: notes.trim(),
        }),
      });
      toast("Cloud-Init profile saved.", "ok", "admin", "proxmox-manager");
      await onSaved();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Failed to save Cloud-Init profile.", "error", "admin", "proxmox-manager");
    } finally {
      setSaving(false);
    }
  };

  return <section className="module-panel">
    <h3>Reusable Cloud-Init profile</h3>
    <div className="form-grid">
      <label>Name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="ubuntu-server" /></label>
      <label>User<input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="admin" /></label>
      <label>IP config<input value={ipconfig} onChange={(event) => setIpconfig(event.target.value)} /></label>
      <label>Nameserver<input value={nameserver} onChange={(event) => setNameserver(event.target.value)} placeholder="1.1.1.1" /></label>
      <label>Search domain<input value={searchdomain} onChange={(event) => setSearchdomain(event.target.value)} placeholder="lab.example" /></label>
      <label>Packages<input value={packages} onChange={(event) => setPackages(event.target.value)} placeholder="qemu-guest-agent,curl" /></label>
      <label className="span-2">CI custom<input value={cicustom} onChange={(event) => setCicustom(event.target.value)} placeholder="user=local:snippets/user.yaml" /></label>
      <label className="span-2">Notes<textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} /></label>
    </div>
    <AsyncButton running={saving} onClick={() => void save()} disabled={!name.trim()}><Save />Save profile</AsyncButton>
  </section>;
}

function VmPolicyForm({ connectionId, onSaved, toast }: { connectionId: string; onSaved: () => void | Promise<void>; toast: ToastFn }) {
  const [name, setName] = useState("");
  const [namingRegex, setNamingRegex] = useState("");
  const [requiredTags, setRequiredTags] = useState("");
  const [maxCpu, setMaxCpu] = useState(0);
  const [maxMemoryMb, setMaxMemoryMb] = useState(0);
  const [requireBackup, setRequireBackup] = useState(false);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      await request(`${REPORT_BASE}/vm-policies`, {
        method: "POST",
        body: JSON.stringify({
          connection_id: connectionId,
          name: name.trim(),
          naming_regex: namingRegex.trim(),
          required_tags: requiredTags.split(/[;,\s]+/).map((item) => item.trim()).filter(Boolean),
          max_cpu: maxCpu,
          max_memory_mb: maxMemoryMb,
          require_backup: requireBackup,
        }),
      });
      toast("VM policy saved.", "ok", "admin", "proxmox-manager");
      await onSaved();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Failed to save VM policy.", "error", "admin", "proxmox-manager");
    } finally {
      setSaving(false);
    }
  };

  return <section className="module-panel">
    <h3>VM policy</h3>
    <div className="form-grid">
      <label>Name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="production" /></label>
      <label>Naming regex<input value={namingRegex} onChange={(event) => setNamingRegex(event.target.value)} placeholder="^prd-[a-z0-9-]+$" /></label>
      <label>Required tags<input value={requiredTags} onChange={(event) => setRequiredTags(event.target.value)} placeholder="backup,production" /></label>
      <label>Max vCPU<input type="number" min={0} value={maxCpu} onChange={(event) => setMaxCpu(Number(event.target.value))} /></label>
      <label>Max RAM MB<input type="number" min={0} value={maxMemoryMb} onChange={(event) => setMaxMemoryMb(Number(event.target.value))} /></label>
      <label className="checkbox-row"><input type="checkbox" checked={requireBackup} onChange={(event) => setRequireBackup(event.target.checked)} />Backup required</label>
    </div>
    <AsyncButton running={saving} onClick={() => void save()} disabled={!name.trim()}><Save />Save policy</AsyncButton>
  </section>;
}

function DriftForm({ connectionId, onSaved, toast }: { connectionId: string; onSaved: () => void | Promise<void>; toast: ToastFn }) {
  const [vmid, setVmid] = useState(100);
  const [expected, setExpected] = useState('{\n  "cores": 2,\n  "memory_mb": 2048\n}');
  const [saving, setSaving] = useState(false);

  const save = async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(expected);
    } catch {
      toast("Expected configuration must be valid JSON.", "error", "admin", "proxmox-manager");
      return;
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      toast("Expected configuration must be a JSON object.", "error", "admin", "proxmox-manager");
      return;
    }
    setSaving(true);
    try {
      await request(`${REPORT_BASE}/drift-baselines`, {
        method: "POST",
        body: JSON.stringify({ connection_id: connectionId, vmid, expected: parsed }),
      });
      toast("Drift baseline saved.", "ok", "admin", "proxmox-manager");
      await onSaved();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Failed to save drift baseline.", "error", "admin", "proxmox-manager");
    } finally {
      setSaving(false);
    }
  };

  return <section className="module-panel">
    <h3>Expected VM baseline</h3>
    <div className="form-grid">
      <label>VMID<input type="number" min={1} value={vmid} onChange={(event) => setVmid(Number(event.target.value))} /></label>
      <label className="span-2">Expected configuration JSON<textarea value={expected} onChange={(event) => setExpected(event.target.value)} rows={8} spellCheck={false} /></label>
    </div>
    <AsyncButton running={saving} onClick={() => void save()}><Save />Save baseline</AsyncButton>
  </section>;
}

function SnapshotRetentionApply({ connectionId, maxAgeDays, onChanged, toast }: { connectionId: string; maxAgeDays: number; onChanged: () => void | Promise<void>; toast: ToastFn }) {
  const [confirmation, setConfirmation] = useState("");
  const [running, setRunning] = useState(false);
  const expected = "DELETE OLD SNAPSHOTS";

  const apply = async () => {
    setRunning(true);
    try {
      const result = await request<{ accepted: number; failed: number }>(`${REPORT_BASE}/snapshot-retention/apply`, {
        method: "POST",
        body: JSON.stringify({ connection_id: connectionId, max_age_days: maxAgeDays, vmids: [], confirmation_text: confirmation }),
      });
      toast(`Snapshot retention: ${result.accepted} queued/accepted, ${result.failed} failed.`, result.failed ? "error" : "ok", "admin", "proxmox-manager");
      setConfirmation("");
      await onChanged();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Snapshot retention failed.", "error", "admin", "proxmox-manager");
    } finally {
      setRunning(false);
    }
  };

  return <section className="module-panel danger-panel">
    <h3><Trash2 />Apply snapshot retention</h3>
    <p>Queues deletion of every non-current snapshot older than {maxAgeDays} days in the selected Proxmox connection.</p>
    <label>Type <code>{expected}</code> to confirm<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
    <AsyncButton running={running} className="danger" disabled={confirmation !== expected} onClick={() => void apply()}><Trash2 />Delete old snapshots</AsyncButton>
  </section>;
}

function BulkForm({ connectionId, toast, onChanged }: { connectionId: string; toast: ToastFn; onChanged: () => void | Promise<void> }) {
  const [action, setAction] = useState("shutdown");
  const [vmids, setVmids] = useState("");
  const [targetNode, setTargetNode] = useState("");
  const [snapshotName, setSnapshotName] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [running, setRunning] = useState(false);
  const expected = `BULK ${action.toUpperCase()}`;
  const parsedVmids = useMemo(() => vmids.split(/[;,\s]+/).map(Number).filter((value) => Number.isInteger(value) && value > 0), [vmids]);

  useEffect(() => setConfirmation(""), [action]);

  const run = async () => {
    setRunning(true);
    try {
      const result = await request<{ accepted: number; failed: number }>(`${REPORT_BASE}/bulk`, {
        method: "POST",
        body: JSON.stringify({
          connection_id: connectionId,
          action,
          vmids: parsedVmids,
          target_node: targetNode.trim(),
          snapshot_name: snapshotName.trim(),
          confirmation_text: confirmation,
        }),
      });
      toast(`Bulk ${action}: ${result.accepted} queued/accepted, ${result.failed} failed.`, result.failed ? "error" : "ok", "admin", "proxmox-manager");
      await onChanged();
    } catch (error) {
      toast(error instanceof Error ? error.message : `Bulk ${action} failed.`, "error", "admin", "proxmox-manager");
    } finally {
      setRunning(false);
    }
  };

  return <section className="module-panel danger-panel">
    <h3><Activity />Bulk operation</h3>
    <div className="form-grid">
      <label>Action<select value={action} onChange={(event) => setAction(event.target.value)}>
        <option value="start">Start</option>
        <option value="shutdown">Shutdown</option>
        <option value="reboot">Reboot</option>
        <option value="stop">Force stop</option>
        <option value="snapshot">Snapshot</option>
        <option value="migrate">Migrate</option>
      </select></label>
      <label>VMIDs<input value={vmids} onChange={(event) => setVmids(event.target.value)} placeholder="100,101,102" /></label>
      {action === "migrate" && <label>Target node<input value={targetNode} onChange={(event) => setTargetNode(event.target.value)} /></label>}
      {action === "snapshot" && <label>Snapshot name<input value={snapshotName} onChange={(event) => setSnapshotName(event.target.value)} placeholder="pre-maintenance" /></label>}
      <label className="span-2">Type <code>{expected}</code> to confirm<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
    </div>
    <AsyncButton running={running} className={action === "stop" ? "danger" : undefined} disabled={!parsedVmids.length || confirmation !== expected || (action === "migrate" && !targetNode.trim())} onClick={() => void run()}><Play />Run on {parsedVmids.length} VM(s)</AsyncButton>
  </section>;
}

export function ProxmoxAdvanced({ connections, permissions, t, toast }: AdvancedProps) {
  const activeConnections = useMemo(() => connections.filter((item) => item.active), [connections]);
  const [connectionId, setConnectionId] = useState("");
  const [features, setFeatures] = useState<ProxmoxAdvancedFeature[]>([]);
  const [feature, setFeature] = useState("cluster-health");
  const [report, setReport] = useState<JsonObject>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [cpuCores, setCpuCores] = useState(2);
  const [memoryMb, setMemoryMb] = useState(2048);
  const [diskGb, setDiskGb] = useState(32);
  const [maxAgeDays, setMaxAgeDays] = useState(30);
  const canManage = permissions.includes(MANAGE_PERMISSION) || permissions.includes("hosts-manager.manage") || permissions.includes("modules.manage");

  useEffect(() => {
    if (!connectionId && activeConnections.length) setConnectionId(activeConnections[0].id);
  }, [activeConnections, connectionId]);

  useEffect(() => {
    request<Catalog>(`${REPORT_BASE}/catalog`)
      .then((value) => setFeatures(value.features))
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Failed to load Proxmox Advanced catalog."));
  }, []);

  const load = useCallback(async () => {
    if (!connectionId) {
      setReport({});
      return;
    }
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        connection_id: connectionId,
        cpu_cores: String(Math.max(1, cpuCores)),
        memory_mb: String(Math.max(128, memoryMb)),
        disk_gb: String(Math.max(1, diskGb)),
        max_age_days: String(Math.max(1, maxAgeDays)),
      });
      const value = await request<JsonObject>(`${REPORT_BASE}/reports/${encodeURIComponent(feature)}?${params.toString()}`);
      setReport(asRecord(value));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Failed to load Proxmox Advanced report.");
      setReport({});
    } finally {
      setLoading(false);
    }
  }, [connectionId, cpuCores, diskGb, feature, maxAgeDays, memoryMb]);

  useEffect(() => { void load(); }, [load]);

  const selected = features.find((item) => item.slug === feature);
  const metric = featureMetric(feature, report);
  const reportErrors = Array.isArray(report.errors) ? report.errors.length : 0;

  return <div className="proxmox-advanced">
    <header className="module-panel">
      <div className="module-toolbar">
        <div>
          <h3>Proxmox Advanced 361–380</h3>
          <p>Capacity, placement, storage, backup/PBS, HA, migration, SDN, lifecycle, policy, drift and bulk operations.</p>
        </div>
        <button type="button" onClick={() => void load()} disabled={loading || !connectionId}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button>
      </div>
      <div className="form-grid compact">
        <label>Connection<select value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>
          {!activeConnections.length && <option value="">No active connection</option>}
          {activeConnections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select></label>
        <label>VM vCPU<input type="number" min={1} value={cpuCores} onChange={(event) => setCpuCores(Number(event.target.value))} /></label>
        <label>VM RAM MB<input type="number" min={128} value={memoryMb} onChange={(event) => setMemoryMb(Number(event.target.value))} /></label>
        <label>VM disk GB<input type="number" min={1} value={diskGb} onChange={(event) => setDiskGb(Number(event.target.value))} /></label>
        <label>Retention age days<input type="number" min={1} value={maxAgeDays} onChange={(event) => setMaxAgeDays(Number(event.target.value))} /></label>
      </div>
    </header>

    <div className="proxmox-advanced-layout">
      <nav className="proxmox-advanced-catalog" aria-label="Proxmox Advanced features">
        {features.map((item) => <button key={item.id} type="button" className={feature === item.slug ? "active" : ""} onClick={() => setFeature(item.slug)}>
          <strong>#{item.id}</strong><span>{item.name.replace(/^Proxmox\s+/, "")}</span><small>{item.scope}</small>
        </button>)}
      </nav>

      <div className="proxmox-advanced-report">
        <section className="module-panel">
          <div className="module-toolbar">
            <div><h3>{selected ? `#${selected.id} ${selected.name}` : feature}</h3><p>{selected?.scope}</p></div>
            {reportErrors ? <span className="status-chip danger"><AlertTriangle />{reportErrors} error(s)</span> : Object.keys(report).length ? <span className="status-chip success"><CheckCircle2 />Loaded</span> : null}
          </div>
          {metric && <div className="module-health-grid"><article className="module-health-card"><span>{metric.label}</span><strong>{metric.value}</strong></article></div>}
          {error && <div className="inline-error"><AlertTriangle />{error}</div>}
          {loading ? <div className="loading-state"><Loader2 className="spin" />Loading…</div> : <PrettyJson value={report} />}
        </section>

        {canManage && feature === "cloud-init-profiles" && <CloudInitForm connectionId={connectionId} toast={toast} onSaved={load} />}
        {canManage && feature === "vm-policy-manager" && <VmPolicyForm connectionId={connectionId} toast={toast} onSaved={load} />}
        {canManage && feature === "drift-manager" && <DriftForm connectionId={connectionId} toast={toast} onSaved={load} />}
        {canManage && feature === "snapshot-retention" && <SnapshotRetentionApply connectionId={connectionId} maxAgeDays={maxAgeDays} toast={toast} onChanged={load} />}
        {canManage && feature === "bulk-operations" && <BulkForm connectionId={connectionId} toast={toast} onChanged={load} />}
        {!canManage && ["cloud-init-profiles", "vm-policy-manager", "drift-manager", "snapshot-retention", "bulk-operations"].includes(feature) && <section className="module-panel"><p>Read-only mode: management permission is required for changes.</p></section>}
      </div>
    </div>
  </div>;
}