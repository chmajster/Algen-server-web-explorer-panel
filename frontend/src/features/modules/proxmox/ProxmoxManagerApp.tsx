import { Boxes, Link2, Play, Plus, Power, RefreshCw, RotateCcw, Server, Square, Trash2, Wrench } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type HostsManagerCredential,
  type ModuleStatus,
  type ProxmoxConnection,
  type ProxmoxConnectionInput,
  type ProxmoxVm,
} from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { Modal } from "../../../components/Modal";
import { useRefreshOnConnectionRestored } from "../../connection/ConnectionStatusMonitor";
import { ModuleAppShell, ModuleHealthCard, type ModuleSection } from "../common/ModuleAppShell";

const sections: ModuleSection[] = ["overview", "hosts", "settings"];
const initialStatus: ModuleStatus = {
  installed: true,
  package_version: "1.0.0",
  update_available: false,
  service_state: "not_applicable",
  service_enabled: false,
  services: {},
  health: "unknown",
  health_message: "",
  last_action: "",
  last_action_status: "",
  last_error: "",
  metrics: {},
};
type PowerAction = "start" | "stop" | "shutdown" | "reboot";

function bytes(value: number): string {
  if (!value) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}
function percent(value: number): string { return `${Math.max(0, value * 100).toFixed(1)}%`; }

export function ProxmoxManagerApp({ permissions, t, toast }: { permissions: string[]; t: Translate; toast: ToastFn }) {
  const [section, setSection] = useState<ModuleSection>("overview");
  const [connections, setConnections] = useState<ProxmoxConnection[]>([]);
  const [vms, setVms] = useState<ProxmoxVm[]>([]);
  const [errors, setErrors] = useState<Array<{ connection_id: string; connection_name: string; error: string }>>([]);
  const [credentials, setCredentials] = useState<HostsManagerCredential[]>([]);
  const [loading, setLoading] = useState(true);
  const [connectionDialog, setConnectionDialog] = useState<ProxmoxConnection | null | undefined>(undefined);
  const [powerDialog, setPowerDialog] = useState<{ vm: ProxmoxVm; action: PowerAction } | null>(null);
  const [busyConnection, setBusyConnection] = useState("");
  const [busyVm, setBusyVm] = useState("");

  const canConfigure = permissions.includes("hosts-manager.configure");
  const canManageHosts = permissions.includes("hosts-manager.hosts.manage");
  const canStart = permissions.includes("hosts-manager.power.on");
  const canShutdown = permissions.includes("hosts-manager.power.shutdown");
  const canReboot = permissions.includes("hosts-manager.power.reboot");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [connectionItems, vmResult, credentialItems] = await Promise.all([
        api.proxmoxConnections(),
        api.proxmoxVms(),
        api.hostsManagerCredentials().catch(() => [] as HostsManagerCredential[]),
      ]);
      setConnections(connectionItems);
      setVms(vmResult.vms);
      setErrors(vmResult.errors);
      setCredentials(credentialItems.filter((item) => item.type === "proxmox_api"));
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally { setLoading(false); }
  }, [t, toast]);

  useEffect(() => { void refresh(); }, [refresh]);
  useRefreshOnConnectionRestored(() => { void refresh(); });

  const status = useMemo<ModuleStatus>(() => ({
    ...initialStatus,
    health: errors.length ? "degraded" : connections.some((item) => item.active) ? "healthy" : "unknown",
    health_message: errors.length
      ? `${errors.length} Proxmox connection(s) returned an error.`
      : connections.some((item) => item.active) ? "Shared Proxmox host provider is active." : "Configure a Proxmox connection.",
    metrics: { connections: connections.length, vms: vms.length, synced: vms.filter((item) => item.host_id).length },
  }), [connections, errors.length, vms]);

  async function sync(item: ProxmoxConnection) {
    setBusyConnection(item.id);
    try {
      const result = await api.syncProxmoxConnection(item.id);
      toast(`Proxmox sync: ${result.created} created, ${result.updated} updated, ${result.disabled} disabled, ${result.skipped.length} skipped.`, "ok", "admin", "proxmox-manager");
      await refresh();
    } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager"); }
    finally { setBusyConnection(""); }
  }

  async function test(item: ProxmoxConnection) {
    setBusyConnection(item.id);
    try {
      await api.testProxmoxConnection(item.id);
      toast(`Connection ${item.name} is available.`, "ok", "admin", "proxmox-manager");
      await refresh();
    } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager"); }
    finally { setBusyConnection(""); }
  }

  async function remove(item: ProxmoxConnection) {
    if (!window.confirm(`Disable Proxmox connection "${item.name}"? Existing shared hosts will be preserved.`)) return;
    try { await api.deleteProxmoxConnection(item.id, item.name); await refresh(); }
    catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager"); }
  }

  async function power(vm: ProxmoxVm, action: PowerAction, confirmationText: string) {
    setBusyVm(`${vm.connection_id}:${vm.vmid}`);
    try {
      await api.proxmoxVmPower(vm.connection_id, vm.vmid, action, confirmationText);
      toast(`${vm.name}: ${action} request sent.`, "ok", "admin", "proxmox-manager");
      setPowerDialog(null);
      await refresh();
    } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager"); }
    finally { setBusyVm(""); }
  }

  const content = section === "overview"
    ? <Overview connections={connections} vms={vms} errors={errors} />
    : section === "hosts"
      ? <VmTable vms={vms} canStart={canStart} canShutdown={canShutdown} canReboot={canReboot} busyVm={busyVm} onPower={(vm, action) => setPowerDialog({ vm, action })} />
      : <ConnectionsPanel connections={connections} canConfigure={canConfigure} canManageHosts={canManageHosts} busyConnection={busyConnection} onAdd={() => setConnectionDialog(null)} onEdit={setConnectionDialog} onTest={(item) => void test(item)} onSync={(item) => void sync(item)} onRemove={(item) => void remove(item)} />;

  return <>
    <ModuleAppShell className="proxmox-manager-app" name="Proxmox Manager" status={status} section={section} sections={sections} t={t} onSection={setSection} actions={<button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button>}>
      {loading && !connections.length && !vms.length ? <div className="loading-state">{t("common.loading")}</div> : content}
    </ModuleAppShell>
    {connectionDialog !== undefined && <ConnectionDialog value={connectionDialog} credentials={credentials} t={t} toast={toast} onClose={() => setConnectionDialog(undefined)} onSaved={async () => { setConnectionDialog(undefined); await refresh(); }} />}
    {powerDialog && <PowerDialog vm={powerDialog.vm} action={powerDialog.action} busy={busyVm === `${powerDialog.vm.connection_id}:${powerDialog.vm.vmid}`} t={t} onClose={() => setPowerDialog(null)} onConfirm={(text) => void power(powerDialog.vm, powerDialog.action, text)} />}
  </>;
}

function Overview({ connections, vms, errors }: { connections: ProxmoxConnection[]; vms: ProxmoxVm[]; errors: Array<{ connection_id: string; connection_name: string; error: string }> }) {
  const running = vms.filter((item) => item.status === "running").length;
  const synced = vms.filter((item) => item.host_id).length;
  return <>
    <div className="module-health-grid">
      <ModuleHealthCard title="Proxmox connections" value={connections.filter((item) => item.active).length} detail={`${connections.length} configured`} />
      <ModuleHealthCard title="Virtual machines / containers" value={vms.length} detail={`${running} running`} />
      <ModuleHealthCard title="Shared Host Registry" value={synced} detail={`${Math.max(0, vms.length - synced)} not synchronized`} tone={synced === vms.length && vms.length ? "success" : "neutral"} />
      <ModuleHealthCard title="API errors" value={errors.length} tone={errors.length ? "danger" : "success"} />
    </div>
    <section className="module-info"><h3>Shared host model</h3><p>Proxmox Manager discovers infrastructure. Hosts Manager owns the canonical host record. Ansible Automation Controller consumes that same host ID and connection data.</p><dl><dt>Stable identity</dt><dd>Proxmox connection ID + VMID</dd><dt>Secrets</dt><dd>Central Hosts Manager credential store</dd><dt>Remote management</dt><dd>Hosts Manager capabilities and Ansible inventory use the same host record</dd></dl></section>
    {errors.length > 0 && <section className="module-info"><h3>Connection errors</h3>{errors.map((item) => <p key={item.connection_id}><strong>{item.connection_name}</strong>: {item.error}</p>)}</section>}
  </>;
}

function VmTable({ vms, canStart, canShutdown, canReboot, busyVm, onPower }: { vms: ProxmoxVm[]; canStart: boolean; canShutdown: boolean; canReboot: boolean; busyVm: string; onPower: (vm: ProxmoxVm, action: PowerAction) => void }) {
  return <section className="module-info"><header className="module-section-toolbar"><div><h3>Proxmox virtual machines</h3><p>Synced rows point to the same host record used by Hosts Manager and Ansible.</p></div></header><div className="module-table-wrap"><table className="module-table"><thead><tr><th>Name</th><th>VMID</th><th>Node</th><th>Type</th><th>Status</th><th>Resources</th><th>Shared host</th><th>Actions</th></tr></thead><tbody>{vms.map((vm) => {
    const busy = busyVm === `${vm.connection_id}:${vm.vmid}`;
    return <tr key={`${vm.connection_id}:${vm.vmid}`}><td><strong>{vm.name}</strong><br /><small>{vm.connection_name}</small></td><td><code>{vm.vmid}</code></td><td>{vm.node}</td><td>{vm.type === "qemu" ? "VM" : "LXC"}</td><td><span className={`status-badge ${vm.status === "running" ? "ok" : "neutral"}`}>{vm.status}</span></td><td>{vm.maxcpu || "—"} CPU · {bytes(vm.maxmem)} RAM<br /><small>{percent(vm.cpu)} CPU · {bytes(vm.mem)} used</small></td><td>{vm.host_id ? <><code>{vm.host_id}</code><br /><small>{vm.host_address || "address pending"}</small></> : <span>Not synchronized</span>}</td><td><div className="module-row-actions">{canStart && vm.status !== "running" && <button type="button" title="Start" disabled={busy} onClick={() => onPower(vm, "start")}><Play /></button>}{canShutdown && vm.status === "running" && <button type="button" title="Graceful shutdown" disabled={busy} onClick={() => onPower(vm, "shutdown")}><Power /></button>}{canReboot && vm.status === "running" && <button type="button" title="Reboot" disabled={busy} onClick={() => onPower(vm, "reboot")}><RotateCcw /></button>}{canShutdown && vm.status === "running" && <button type="button" className="danger" title="Stop immediately" disabled={busy} onClick={() => onPower(vm, "stop")}><Square /></button>}</div></td></tr>;
  })}</tbody></table>{!vms.length && <div className="empty-state"><Server /><strong>No Proxmox virtual machines found.</strong></div>}</div></section>;
}

function ConnectionsPanel({ connections, canConfigure, canManageHosts, busyConnection, onAdd, onEdit, onTest, onSync, onRemove }: { connections: ProxmoxConnection[]; canConfigure: boolean; canManageHosts: boolean; busyConnection: string; onAdd: () => void; onEdit: (item: ProxmoxConnection) => void; onTest: (item: ProxmoxConnection) => void; onSync: (item: ProxmoxConnection) => void; onRemove: (item: ProxmoxConnection) => void }) {
  return <section className="module-info"><header className="module-section-toolbar"><div><h3>Proxmox API connections</h3><p>API tokens are referenced from Hosts Manager credentials and are never copied into this module.</p></div>{canConfigure && <button className="button-primary" type="button" onClick={onAdd}><Plus />Add connection</button>}</header><div className="module-table-wrap"><table className="module-table"><thead><tr><th>Name</th><th>Endpoint</th><th>Credential</th><th>TLS</th><th>Last sync</th><th>Status</th><th>Actions</th></tr></thead><tbody>{connections.map((item) => {
    const busy = busyConnection === item.id;
    return <tr key={item.id}><td><strong>{item.name}</strong><br /><small>{item.environment || "no environment"}</small></td><td><code>{item.endpoint}</code></td><td>{item.credential ? <><strong>{item.credential.name}</strong><br /><small>{item.credential.username}</small></> : <span>Missing credential</span>}</td><td>{item.verify_tls ? "Verified" : "Verification disabled"}</td><td>{item.last_sync_at ? new Date(item.last_sync_at * 1000).toLocaleString() : "Never"}</td><td>{item.active ? item.last_sync_status || "active" : "disabled"}{item.last_error ? <><br /><small>{item.last_error}</small></> : null}</td><td><div className="module-row-actions">{canConfigure && <button type="button" title="Edit" disabled={busy} onClick={() => onEdit(item)}><Wrench /></button>}{canConfigure && <button type="button" title="Test API" disabled={busy || !item.active} onClick={() => onTest(item)}><Link2 /></button>}{canManageHosts && <button type="button" title="Synchronize hosts" disabled={busy || !item.active} onClick={() => onSync(item)}><RefreshCw className={busy ? "spin" : ""} /></button>}{canConfigure && <button type="button" className="danger" title="Disable connection" disabled={busy || !item.active} onClick={() => onRemove(item)}><Trash2 /></button>}</div></td></tr>;
  })}</tbody></table>{!connections.length && <div className="empty-state"><Boxes /><strong>No Proxmox API connections configured.</strong></div>}</div></section>;
}

function ConnectionDialog({ value, credentials, t, toast, onClose, onSaved }: { value: ProxmoxConnection | null; credentials: HostsManagerCredential[]; t: Translate; toast: ToastFn; onClose: () => void; onSaved: () => Promise<void> }) {
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<ProxmoxConnectionInput>({ name: value?.name || "", endpoint: value?.endpoint || "https://pve.example:8006", credential_id: value?.credential_id || credentials[0]?.id || "", verify_tls: value?.verify_tls ?? true, ca_certificate: value?.ca_certificate || "", default_ssh_user: value?.default_ssh_user || "algen-ansible", environment: value?.environment || "", location: value?.location || "", tags: value?.tags?.length ? value.tags : ["proxmox"], sync_lxc: value?.sync_lxc ?? true, sync_templates: value?.sync_templates ?? false, active: value?.active ?? true, auto_sync: false });
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!form.credential_id) { toast("Create a Hosts Manager credential of type proxmox_api first.", "error", "admin", "proxmox-manager"); return; }
    setSaving(true);
    try { await api.saveProxmoxConnection(form, value?.id || ""); await onSaved(); }
    catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager"); }
    finally { setSaving(false); }
  }
  return <Modal title={value ? `Edit ${value.name}` : "Add Proxmox connection"} onClose={onClose} wide footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button className="button-primary" type="submit" form="proxmox-connection-form" disabled={saving || !form.credential_id}>{saving ? "Saving…" : t("action.save")}</button></>}><form id="proxmox-connection-form" onSubmit={submit}><p>Store the API token in Hosts Manager → Credentials as type <code>proxmox_api</code>. Set username to <code>user@realm!tokenid</code> and secret to the token secret.</p><label className="field-label">Name<input autoFocus required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label className="field-label">Proxmox API endpoint<input required type="url" value={form.endpoint} onChange={(event) => setForm({ ...form, endpoint: event.target.value })} /><small>HTTPS origin, normally https://host:8006</small></label><label className="field-label">Central credential<select required value={form.credential_id} onChange={(event) => setForm({ ...form, credential_id: event.target.value })}><option value="">Select proxmox_api credential</option>{credentials.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.username}</option>)}</select></label><label className="field-label">Default SSH user for synchronized hosts<input required value={form.default_ssh_user} onChange={(event) => setForm({ ...form, default_ssh_user: event.target.value })} /></label><label className="field-label">Environment<input value={form.environment} onChange={(event) => setForm({ ...form, environment: event.target.value })} /></label><label className="field-label">Location<input value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} /></label><label className="field-label">Tags<input value={form.tags.join(",")} onChange={(event) => setForm({ ...form, tags: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></label><label className="field-label">Custom CA certificate<textarea rows={5} value={form.ca_certificate} placeholder="-----BEGIN CERTIFICATE-----" onChange={(event) => setForm({ ...form, ca_certificate: event.target.value })} /></label><label><input type="checkbox" checked={form.verify_tls} onChange={(event) => setForm({ ...form, verify_tls: event.target.checked })} /> Verify TLS certificate</label><br /><label><input type="checkbox" checked={form.sync_lxc} onChange={(event) => setForm({ ...form, sync_lxc: event.target.checked })} /> Include LXC containers</label><br /><label><input type="checkbox" checked={form.sync_templates} onChange={(event) => setForm({ ...form, sync_templates: event.target.checked })} /> Include templates</label><br /><label><input type="checkbox" checked={form.active} onChange={(event) => setForm({ ...form, active: event.target.checked })} /> Connection active</label></form></Modal>;
}

function PowerDialog({ vm, action, busy, t, onClose, onConfirm }: { vm: ProxmoxVm; action: PowerAction; busy: boolean; t: Translate; onClose: () => void; onConfirm: (text: string) => void }) {
  const dangerous = action !== "start";
  const [confirmation, setConfirmation] = useState("");
  return <Modal title={`${action} ${vm.name}`} onClose={onClose} footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button className={dangerous ? "button-danger" : "button-primary"} type="button" disabled={busy || (dangerous && confirmation !== vm.name)} onClick={() => onConfirm(dangerous ? confirmation : "")}>{busy ? "Working…" : action}</button></>}><p>Target: <strong>{vm.name}</strong> · VMID {vm.vmid} · {vm.node}</p>{dangerous && <label className="field-label">Type the exact VM name to confirm<input autoFocus value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder={vm.name} /></label>}</Modal>;
}
