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
type ConnectionAuthMode = "saved" | "username_password";

type EndpointFields = {
  address: string;
  port: string;
};

function bytes(value: number): string {
  if (!value) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function percent(value: number): string {
  return `${Math.max(0, value * 100).toFixed(1)}%`;
}

function splitEndpoint(value: string): EndpointFields {
  try {
    const parsed = new URL(value);
    const defaultPort = parsed.protocol === "http:" ? "80" : parsed.protocol === "https:" ? "443" : "8006";
    return {
      address: `${parsed.protocol}//${parsed.hostname}`,
      port: parsed.port || defaultPort,
    };
  } catch {
    const match = value.trim().match(/^(https?:\/\/[^/:]+)(?::(\d+))?\/?$/i);
    return {
      address: match?.[1] || value,
      port: match?.[2] || "8006",
    };
  }
}

function buildEndpoint(address: string, port: string): string {
  const parsed = new URL(address.trim());
  if (!(["http:", "https:"] as string[]).includes(parsed.protocol)) throw new Error("invalid protocol");
  if (!parsed.hostname || parsed.username || parsed.password || parsed.search || parsed.hash) throw new Error("invalid address");
  if (parsed.pathname !== "/" && parsed.pathname !== "") throw new Error("invalid path");
  if (parsed.port) throw new Error("port must be separate");

  const numericPort = Number(port);
  if (!Number.isInteger(numericPort) || numericPort < 1 || numericPort > 65535) throw new RangeError("invalid port");

  parsed.port = String(numericPort);
  parsed.pathname = "";
  return parsed.origin;
}

function powerActionLabel(t: Translate, action: PowerAction): string {
  if (action === "start") return t("proxmox.power.start");
  if (action === "shutdown") return t("proxmox.power.shutdown");
  if (action === "reboot") return t("proxmox.power.reboot");
  return t("proxmox.power.stop");
}

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
  const canManageCredentials = permissions.includes("hosts-manager.credentials.manage");
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
      setCredentials(credentialItems.filter((item) => ["proxmox_api", "username_password"].includes(item.type) && (item.shared_with || []).includes("proxmox-manager")));
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally {
      setLoading(false);
    }
  }, [t, toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);
  useRefreshOnConnectionRestored(() => {
    void refresh();
  });

  const status = useMemo<ModuleStatus>(() => ({
    ...initialStatus,
    health: errors.length ? "degraded" : connections.some((item) => item.active) ? "healthy" : "unknown",
    health_message: errors.length
      ? `${errors.length} ${t("proxmox.health.connectionErrors").toLocaleLowerCase()}.`
      : connections.some((item) => item.active)
        ? t("proxmox.health.providerActive")
        : t("proxmox.health.configure"),
    metrics: { connections: connections.length, vms: vms.length, synced: vms.filter((item) => item.host_id).length },
  }), [connections, errors.length, t, vms]);

  async function sync(item: ProxmoxConnection) {
    setBusyConnection(item.id);
    try {
      const result = await api.syncProxmoxConnection(item.id);
      toast(
        `Proxmox: ${result.created} ${t("proxmox.sync.created")}, ${result.updated} ${t("proxmox.sync.updated")}, ${result.disabled} ${t("proxmox.sync.disabled")}, ${result.tagged} ${t("proxmox.sync.tagsUpdated")}, ${result.tag_errors.length} ${t("proxmox.sync.tagErrors")}, ${result.skipped.length} ${t("proxmox.sync.skipped")}.`,
        result.tag_errors.length ? "error" : "ok",
        "admin",
        "proxmox-manager",
      );
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally {
      setBusyConnection("");
    }
  }

  async function test(item: ProxmoxConnection) {
    setBusyConnection(item.id);
    try {
      await api.testProxmoxConnection(item.id);
      toast(`${item.name}: ${t("proxmox.toast.connectionAvailable")}.`, "ok", "admin", "proxmox-manager");
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally {
      setBusyConnection("");
    }
  }

  async function remove(item: ProxmoxConnection) {
    if (!window.confirm(`${t("proxmox.confirm.disablePrefix")} "${item.name}"? ${t("proxmox.confirm.disableSuffix")}`)) return;
    try {
      await api.deleteProxmoxConnection(item.id, item.name);
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    }
  }

  async function power(vm: ProxmoxVm, action: PowerAction, confirmationText: string) {
    setBusyVm(`${vm.connection_id}:${vm.vmid}`);
    try {
      await api.proxmoxVmPower(vm.connection_id, vm.vmid, action, confirmationText);
      toast(`${vm.name}: ${powerActionLabel(t, action)} — ${t("proxmox.toast.requestSent")}.`, "ok", "admin", "proxmox-manager");
      setPowerDialog(null);
      await refresh();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally {
      setBusyVm("");
    }
  }

  const content = section === "overview"
    ? <Overview connections={connections} vms={vms} errors={errors} t={t} />
    : section === "hosts"
      ? <VmTable vms={vms} canStart={canStart} canShutdown={canShutdown} canReboot={canReboot} busyVm={busyVm} onPower={(vm, action) => setPowerDialog({ vm, action })} t={t} />
      : <ConnectionsPanel connections={connections} canConfigure={canConfigure} canManageHosts={canManageHosts} busyConnection={busyConnection} onAdd={() => setConnectionDialog(null)} onEdit={setConnectionDialog} onTest={(item) => void test(item)} onSync={(item) => void sync(item)} onRemove={(item) => void remove(item)} t={t} />;

  return <>
    <ModuleAppShell className="proxmox-manager-app" name="Proxmox Manager" status={status} section={section} sections={sections} t={t} onSection={setSection} actions={<button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button>}>
      {loading && !connections.length && !vms.length ? <div className="loading-state">{t("common.loading")}</div> : content}
    </ModuleAppShell>
    {connectionDialog !== undefined && <ConnectionDialog value={connectionDialog} credentials={credentials} canManageCredentials={canManageCredentials} t={t} toast={toast} onClose={() => setConnectionDialog(undefined)} onSaved={async () => { setConnectionDialog(undefined); await refresh(); }} />}
    {powerDialog && <PowerDialog vm={powerDialog.vm} action={powerDialog.action} busy={busyVm === `${powerDialog.vm.connection_id}:${powerDialog.vm.vmid}`} t={t} onClose={() => setPowerDialog(null)} onConfirm={(text) => void power(powerDialog.vm, powerDialog.action, text)} />}
  </>;
}

function Overview({ connections, vms, errors, t }: { connections: ProxmoxConnection[]; vms: ProxmoxVm[]; errors: Array<{ connection_id: string; connection_name: string; error: string }>; t: Translate }) {
  const running = vms.filter((item) => item.status === "running").length;
  const synced = vms.filter((item) => item.host_id).length;
  return <>
    <div className="module-health-grid">
      <ModuleHealthCard title={t("proxmox.health.connections")} value={connections.filter((item) => item.active).length} detail={`${connections.length} ${t("proxmox.health.configured")}`} />
      <ModuleHealthCard title={t("proxmox.health.vms")} value={vms.length} detail={`${running} ${t("proxmox.health.running")}`} />
      <ModuleHealthCard title={t("proxmox.health.registry")} value={synced} detail={`${Math.max(0, vms.length - synced)} ${t("proxmox.health.notSynchronized")}`} tone={synced === vms.length && vms.length ? "success" : "neutral"} />
      <ModuleHealthCard title={t("proxmox.health.apiErrors")} value={errors.length} tone={errors.length ? "danger" : "success"} />
    </div>
    <section className="module-info">
      <h3>{t("proxmox.shared.title")}</h3>
      <p>{t("proxmox.shared.description")}</p>
      <dl>
        <dt>{t("proxmox.shared.identity")}</dt><dd>{t("proxmox.shared.identityValue")}</dd>
        <dt>{t("proxmox.shared.secrets")}</dt><dd>{t("proxmox.shared.secretsValue")}</dd>
        <dt>{t("proxmox.shared.remote")}</dt><dd>{t("proxmox.shared.remoteValue")}</dd>
      </dl>
    </section>
    {errors.length > 0 && <section className="module-info"><h3>{t("proxmox.health.connectionErrors")}</h3>{errors.map((item) => <p key={item.connection_id}><strong>{item.connection_name}</strong>: {item.error}</p>)}</section>}
  </>;
}

function VmTable({ vms, canStart, canShutdown, canReboot, busyVm, onPower, t }: { vms: ProxmoxVm[]; canStart: boolean; canShutdown: boolean; canReboot: boolean; busyVm: string; onPower: (vm: ProxmoxVm, action: PowerAction) => void; t: Translate }) {
  return <section className="module-info">
    <header className="module-section-toolbar"><div><h3>{t("proxmox.vm.title")}</h3><p>{t("proxmox.vm.description")}</p></div></header>
    <div className="module-table-wrap"><table className="module-table"><thead><tr><th>{t("proxmox.vm.name")}</th><th>VMID</th><th>{t("proxmox.vm.node")}</th><th>{t("proxmox.vm.type")}</th><th>{t("proxmox.vm.status")}</th><th>{t("proxmox.vm.resources")}</th><th>{t("proxmox.vm.tags")}</th><th>{t("proxmox.vm.sharedHost")}</th><th>{t("proxmox.vm.actions")}</th></tr></thead><tbody>{vms.map((vm) => {
      const busy = busyVm === `${vm.connection_id}:${vm.vmid}`;
      return <tr key={`${vm.connection_id}:${vm.vmid}`}>
        <td><strong>{vm.name}</strong><br /><small>{vm.connection_name}</small></td>
        <td><code>{vm.vmid}</code></td>
        <td>{vm.node}</td>
        <td>{vm.type === "qemu" ? "VM" : "LXC"}</td>
        <td><span className={`status-badge ${vm.status === "running" ? "ok" : "neutral"}`}>{vm.status}</span></td>
        <td>{vm.maxcpu || "—"} CPU · {bytes(vm.maxmem)} RAM<br /><small>{percent(vm.cpu)} CPU · {bytes(vm.mem)} {t("proxmox.vm.used")}</small></td>
        <td>{vm.tags.length ? <small>{vm.tags.join(" · ")}</small> : <span>—</span>}</td>
        <td>{vm.host_id ? <><code>{vm.host_id}</code><br /><small>{vm.host_address || t("proxmox.vm.addressPending")}</small></> : <span>{t("proxmox.vm.notSynchronized")}</span>}</td>
        <td><div className="module-row-actions">
          {canStart && vm.status !== "running" && <button type="button" title={t("proxmox.power.start")} disabled={busy} onClick={() => onPower(vm, "start")}><Play /></button>}
          {canShutdown && vm.status === "running" && <button type="button" title={t("proxmox.power.shutdown")} disabled={busy} onClick={() => onPower(vm, "shutdown")}><Power /></button>}
          {canReboot && vm.status === "running" && <button type="button" title={t("proxmox.power.reboot")} disabled={busy} onClick={() => onPower(vm, "reboot")}><RotateCcw /></button>}
          {canShutdown && vm.status === "running" && <button type="button" className="danger" title={t("proxmox.power.stop")} disabled={busy} onClick={() => onPower(vm, "stop")}><Square /></button>}
        </div></td>
      </tr>;
    })}</tbody></table>{!vms.length && <div className="empty-state"><Server /><strong>{t("proxmox.vm.none")}</strong></div>}</div>
  </section>;
}

function ConnectionsPanel({ connections, canConfigure, canManageHosts, busyConnection, onAdd, onEdit, onTest, onSync, onRemove, t }: { connections: ProxmoxConnection[]; canConfigure: boolean; canManageHosts: boolean; busyConnection: string; onAdd: () => void; onEdit: (item: ProxmoxConnection) => void; onTest: (item: ProxmoxConnection) => void; onSync: (item: ProxmoxConnection) => void; onRemove: (item: ProxmoxConnection) => void; t: Translate }) {
  return <section className="module-info">
    <header className="module-section-toolbar">
      <div><h3>{t("proxmox.connections.title")}</h3><p>{t("proxmox.connections.description")}</p></div>
      {canConfigure && <button className="button-primary" type="button" onClick={onAdd}><Plus />{t("proxmox.connections.add")}</button>}
    </header>
    <div className="module-table-wrap"><table className="module-table"><thead><tr><th>{t("proxmox.vm.name")}</th><th>{t("proxmox.connections.endpoint")}</th><th>{t("proxmox.connections.credential")}</th><th>TLS</th><th>{t("proxmox.connections.lastSync")}</th><th>{t("proxmox.connections.status")}</th><th>{t("proxmox.vm.actions")}</th></tr></thead><tbody>{connections.map((item) => {
      const busy = busyConnection === item.id;
      return <tr key={item.id}>
        <td><strong>{item.name}</strong><br /><small>{item.project || t("proxmox.connections.noProject")} · {item.environment || t("proxmox.connections.noEnvironment")}</small></td>
        <td><code>{item.endpoint}</code></td>
        <td>{item.credential ? <><strong>{item.credential.name}</strong><br /><small>{item.credential.username}</small></> : <span>{t("proxmox.connections.missingCredential")}</span>}</td>
        <td>{item.verify_tls ? t("proxmox.connections.tlsVerified") : t("proxmox.connections.tlsDisabled")}</td>
        <td>{item.last_sync_at ? new Date(item.last_sync_at * 1000).toLocaleString() : t("proxmox.connections.never")}</td>
        <td>{item.active ? item.last_sync_status || t("proxmox.connections.active") : t("proxmox.connections.disabled")}{item.last_error ? <><br /><small>{item.last_error}</small></> : null}</td>
        <td><div className="module-row-actions">
          {canConfigure && <button type="button" title={t("proxmox.connections.edit")} disabled={busy} onClick={() => onEdit(item)}><Wrench /></button>}
          {canConfigure && <button type="button" title={t("proxmox.connections.test")} disabled={busy || !item.active} onClick={() => onTest(item)}><Link2 /></button>}
          {canManageHosts && <button type="button" title={t("proxmox.connections.sync")} disabled={busy || !item.active} onClick={() => onSync(item)}><RefreshCw className={busy ? "spin" : ""} /></button>}
          {canConfigure && <button type="button" className="danger" title={t("proxmox.connections.disable")} disabled={busy || !item.active} onClick={() => onRemove(item)}><Trash2 /></button>}
        </div></td>
      </tr>;
    })}</tbody></table>{!connections.length && <div className="empty-state"><Boxes /><strong>{t("proxmox.connections.none")}</strong></div>}</div>
  </section>;
}

function ConnectionDialog({ value, credentials, canManageCredentials, t, toast, onClose, onSaved }: { value: ProxmoxConnection | null; credentials: HostsManagerCredential[]; canManageCredentials: boolean; t: Translate; toast: ToastFn; onClose: () => void; onSaved: () => Promise<void> }) {
  const endpointFields = splitEndpoint(value?.endpoint || "https://pve.example:8006");
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<ProxmoxConnectionInput>({
    name: value?.name || "",
    endpoint: endpointFields.address,
    credential_id: value?.credential_id || credentials[0]?.id || "",
    verify_tls: value?.verify_tls ?? true,
    ca_certificate: value?.ca_certificate || "",
    default_ssh_user: value?.default_ssh_user || "algen-ansible",
    project: value?.project || "",
    environment: value?.environment || "",
    location: value?.location || "",
    tags: value?.tags?.length ? value.tags : ["proxmox"],
    sync_proxmox_tags: value?.sync_proxmox_tags ?? true,
    sync_lxc: value?.sync_lxc ?? true,
    sync_templates: value?.sync_templates ?? false,
    active: value?.active ?? true,
    auto_sync: value?.auto_sync ?? false,
  });
  const [endpointPort, setEndpointPort] = useState(endpointFields.port);
  const [authMode, setAuthMode] = useState<ConnectionAuthMode>(value || credentials.length || !canManageCredentials ? "saved" : "username_password");
  const [credentialName, setCredentialName] = useState(value ? `${value.name} Proxmox login` : "Proxmox login");
  const [loginUsername, setLoginUsername] = useState(value?.credential?.type === "username_password" ? value.credential.username : "root@pam");
  const [loginPassword, setLoginPassword] = useState("");
  const inlineLogin = authMode === "username_password";
  const saveDisabled = saving || !endpointPort || (inlineLogin
    ? !canManageCredentials || !credentialName.trim() || !loginUsername.trim() || !loginPassword
    : !form.credential_id);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!inlineLogin && !form.credential_id) {
      toast(t("proxmox.error.selectCredential"), "error", "admin", "proxmox-manager");
      return;
    }
    if (inlineLogin && !canManageCredentials) {
      toast(t("proxmox.error.manageCredentials"), "error", "admin", "proxmox-manager");
      return;
    }
    if (inlineLogin && !loginUsername.includes("@")) {
      toast(t("proxmox.error.realm"), "error", "admin", "proxmox-manager");
      return;
    }
    if (inlineLogin && (!credentialName.trim() || !loginPassword)) {
      toast(t("proxmox.error.credentialRequired"), "error", "admin", "proxmox-manager");
      return;
    }

    let endpoint = "";
    try {
      endpoint = buildEndpoint(form.endpoint, endpointPort);
    } catch (error) {
      toast(error instanceof RangeError ? t("proxmox.error.port") : t("proxmox.error.address"), "error", "admin", "proxmox-manager");
      return;
    }

    setSaving(true);
    let createdCredentialId = "";
    let connectionSaved = false;
    try {
      let credentialId = form.credential_id;
      if (inlineLogin) {
        const created = await api.saveHostsManagerCredential({
          name: credentialName.trim(),
          type: "username_password",
          username: loginUsername.trim(),
          environment_id: null,
          secret: loginPassword,
          passphrase: "",
          description: `Proxmox login for ${form.name.trim() || endpoint}`,
          shared_with: ["proxmox-manager"],
          confirm: true,
        }) as HostsManagerCredential;
        credentialId = created.id;
        createdCredentialId = created.id;
      }
      await api.saveProxmoxConnection({ ...form, endpoint, credential_id: credentialId }, value?.id || "");
      connectionSaved = true;
      setLoginPassword("");
      await onSaved();
    } catch (error) {
      if (createdCredentialId && !connectionSaved) await api.deleteHostsManagerCredential(createdCredentialId).catch(() => undefined);
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally {
      setSaving(false);
    }
  }

  return <Modal
    title={value ? `${t("proxmox.dialog.editTitle")} ${value.name}` : t("proxmox.dialog.addTitle")}
    onClose={onClose}
    wide
    footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button className="button-primary" type="submit" form="proxmox-connection-form" disabled={saveDisabled}>{saving ? t("proxmox.dialog.saving") : t("action.save")}</button></>}
  >
    <form id="proxmox-connection-form" onSubmit={submit}>
      <p>{t("proxmox.dialog.description")}</p>
      <label className="field-label">{t("proxmox.dialog.name")}<input autoFocus required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
      <label className="field-label">{t("proxmox.dialog.address")}<input required type="url" value={form.endpoint} placeholder="http://10.0.0.10" onChange={(event) => setForm({ ...form, endpoint: event.target.value })} /><small>{t("proxmox.dialog.addressHint")}</small></label>
      <label className="field-label">{t("proxmox.dialog.port")}<input required type="number" min={1} max={65535} step={1} value={endpointPort} onChange={(event) => setEndpointPort(event.target.value)} /><small>{t("proxmox.dialog.portHint")}</small></label>
      <label className="field-label">{t("proxmox.dialog.authentication")}<select value={authMode} onChange={(event) => setAuthMode(event.target.value as ConnectionAuthMode)}><option value="saved">{t("proxmox.dialog.savedCredential")}</option><option value="username_password" disabled={!canManageCredentials}>{t("proxmox.dialog.loginPassword")}</option></select>{!canManageCredentials && <small>{t("proxmox.dialog.permissionCredential")}</small>}</label>
      {inlineLogin ? <>
        <label className="field-label">{t("proxmox.dialog.credentialName")}<input required value={credentialName} onChange={(event) => setCredentialName(event.target.value)} placeholder="Proxmox production login" /><small>{t("proxmox.dialog.credentialNameHint")}</small></label>
        <label className="field-label">{t("proxmox.dialog.login")}<input required value={loginUsername} onChange={(event) => setLoginUsername(event.target.value)} placeholder="root@pam" autoComplete="username" /></label>
        <label className="field-label">{t("proxmox.dialog.password")}<input required type="password" value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} autoComplete="current-password" /><small>{t("proxmox.dialog.passwordHint")}</small></label>
      </> : <label className="field-label">{t("proxmox.dialog.centralCredential")}<select required value={form.credential_id} onChange={(event) => setForm({ ...form, credential_id: event.target.value })}><option value="">{t("proxmox.dialog.selectCredential")}</option>{credentials.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.type} · {item.username}</option>)}</select>{!credentials.length && <small>{t("proxmox.dialog.noCredential")}</small>}</label>}
      <label className="field-label">{t("proxmox.dialog.sshUser")}<input required value={form.default_ssh_user} onChange={(event) => setForm({ ...form, default_ssh_user: event.target.value })} /></label>
      <label className="field-label">{t("proxmox.dialog.project")}<input value={form.project} onChange={(event) => setForm({ ...form, project: event.target.value })} /><small>{t("proxmox.dialog.projectHint")}</small></label>
      <label className="field-label">{t("proxmox.dialog.environment")}<input value={form.environment} onChange={(event) => setForm({ ...form, environment: event.target.value })} /></label>
      <label className="field-label">{t("proxmox.dialog.location")}<input value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} /></label>
      <label className="field-label">{t("proxmox.dialog.tags")}<input value={form.tags.join(",")} onChange={(event) => setForm({ ...form, tags: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /><small>{t("proxmox.dialog.tagsHint")}</small></label>
      <label><input type="checkbox" checked={form.sync_proxmox_tags} onChange={(event) => setForm({ ...form, sync_proxmox_tags: event.target.checked })} /> {t("proxmox.dialog.syncTags")}</label><br />
      <label className="field-label">{t("proxmox.dialog.caCertificate")}<textarea rows={5} value={form.ca_certificate} placeholder="-----BEGIN CERTIFICATE-----" onChange={(event) => setForm({ ...form, ca_certificate: event.target.value })} /></label>
      <label><input type="checkbox" checked={form.verify_tls} onChange={(event) => setForm({ ...form, verify_tls: event.target.checked })} /> {t("proxmox.dialog.verifyTls")}</label><br />
      <label><input type="checkbox" checked={form.sync_lxc} onChange={(event) => setForm({ ...form, sync_lxc: event.target.checked })} /> {t("proxmox.dialog.includeLxc")}</label><br />
      <label><input type="checkbox" checked={form.sync_templates} onChange={(event) => setForm({ ...form, sync_templates: event.target.checked })} /> {t("proxmox.dialog.includeTemplates")}</label><br />
      <label><input type="checkbox" checked={form.active} onChange={(event) => setForm({ ...form, active: event.target.checked })} /> {t("proxmox.dialog.active")}</label>
    </form>
  </Modal>;
}

function PowerDialog({ vm, action, busy, t, onClose, onConfirm }: { vm: ProxmoxVm; action: PowerAction; busy: boolean; t: Translate; onClose: () => void; onConfirm: (text: string) => void }) {
  const dangerous = action !== "start";
  const [confirmation, setConfirmation] = useState("");
  const actionLabel = powerActionLabel(t, action);
  return <Modal
    title={`${actionLabel}: ${vm.name}`}
    onClose={onClose}
    footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button className={dangerous ? "button-danger" : "button-primary"} type="button" disabled={busy || (dangerous && confirmation !== vm.name)} onClick={() => onConfirm(dangerous ? confirmation : "")}>{busy ? t("proxmox.power.working") : actionLabel}</button></>}
  >
    <p>{t("proxmox.power.target")}: <strong>{vm.name}</strong> · VMID {vm.vmid} · {vm.node}</p>
    {dangerous && <label className="field-label">{t("proxmox.power.confirmName")}<input autoFocus value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder={vm.name} /></label>}
  </Modal>;
}
