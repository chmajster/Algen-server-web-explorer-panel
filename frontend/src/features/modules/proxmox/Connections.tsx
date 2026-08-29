import { Link2, Plus, RefreshCw, Trash2, Wrench } from "lucide-react";
import { useState } from "react";
import { api, type HostsManagerCredential, type ProxmoxConnection, type ProxmoxConnectionInput } from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { Modal } from "../../../components/Modal";
import { buildEndpoint, splitEndpoint } from "./utils";

type ConnectionAuthMode = "saved" | "username_password";

export function ProxmoxConnections({ connections, credentials, permissions, t, toast, onChanged }: { connections: ProxmoxConnection[]; credentials: HostsManagerCredential[]; permissions: string[]; t: Translate; toast: ToastFn; onChanged: () => Promise<void> }) {
  const [dialog, setDialog] = useState<ProxmoxConnection | null | undefined>(undefined);
  const [busy, setBusy] = useState("");
  const canConfigure = permissions.includes("hosts-manager.configure");
  const canManageCredentials = permissions.includes("hosts-manager.credentials.manage");
  const canManageHosts = permissions.includes("hosts-manager.hosts.manage");

  async function sync(item: ProxmoxConnection) {
    setBusy(item.id);
    try {
      await api.syncProxmoxConnection(item.id);
      await onChanged();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally { setBusy(""); }
  }

  async function test(item: ProxmoxConnection) {
    setBusy(item.id);
    try {
      await api.testProxmoxConnection(item.id);
      await onChanged();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    } finally { setBusy(""); }
  }

  async function remove(item: ProxmoxConnection) {
    const confirmation = window.prompt(`Type the exact connection name to disable it: ${item.name}`);
    if (confirmation !== item.name) return;
    try {
      await api.deleteProxmoxConnection(item.id, item.name);
      await onChanged();
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin", "proxmox-manager");
    }
  }

  return <>
    <section className="module-info">
      <header className="module-section-toolbar"><div><h3>Connections</h3><p>Connection metadata is local; credentials and secrets remain in the central Host Registry credential store.</p></div>{canConfigure && <button className="button-primary" type="button" onClick={() => setDialog(null)}><Plus />Add connection</button>}</header>
      <div className="module-table-wrap"><table className="module-table"><thead><tr><th>Name</th><th>Endpoint</th><th>Credential</th><th>TLS</th><th>Auto sync</th><th>Last / next sync</th><th>Status</th><th>Actions</th></tr></thead><tbody>{connections.map((item) => {
        const working = busy === item.id;
        return <tr key={item.id}><td><strong>{item.name}</strong><br /><small>{item.project || "no project"} · {item.environment || "no environment"}</small></td><td><code>{item.endpoint}</code></td>
          <td>{item.credential ? <><strong>{item.credential.name}</strong><br /><small>{item.credential.username}</small></> : "missing credential"}</td><td>{item.verify_tls ? "verified" : "disabled"}</td>
          <td>{item.auto_sync ? `every ${item.sync_interval_seconds || 300}s` : "disabled"}{item.consecutive_sync_failures ? <><br /><small>{item.consecutive_sync_failures} consecutive failure(s)</small></> : null}</td>
          <td>{item.last_sync_at ? new Date(item.last_sync_at * 1000).toLocaleString() : "never"}<br /><small>{item.next_sync_at ? new Date(item.next_sync_at * 1000).toLocaleString() : "—"}</small></td>
          <td>{item.active ? item.last_sync_status || "active" : "disabled"}{item.last_error ? <><br /><small>{item.last_error}</small></> : null}</td>
          <td><div className="module-row-actions">{canConfigure && <button type="button" title="Edit" disabled={working} onClick={() => setDialog(item)}><Wrench /></button>}{canConfigure && <button type="button" title="Test" disabled={working || !item.active} onClick={() => void test(item)}><Link2 /></button>}{canManageHosts && <button type="button" title="Sync" disabled={working || !item.active} onClick={() => void sync(item)}><RefreshCw className={working ? "spin" : ""} /></button>}{canConfigure && <button className="danger" type="button" title="Disable" disabled={working || !item.active} onClick={() => void remove(item)}><Trash2 /></button>}</div></td>
        </tr>;
      })}</tbody></table>{!connections.length && <div className="empty-state"><strong>No Proxmox connections configured.</strong></div>}</div>
    </section>
    {dialog !== undefined && <ConnectionDialog value={dialog} credentials={credentials} canManageCredentials={canManageCredentials} t={t} toast={toast} onClose={() => setDialog(undefined)} onSaved={async () => { setDialog(undefined); await onChanged(); }} />}
  </>;
}

function ConnectionDialog({ value, credentials, canManageCredentials, t, toast, onClose, onSaved }: { value: ProxmoxConnection | null; credentials: HostsManagerCredential[]; canManageCredentials: boolean; t: Translate; toast: ToastFn; onClose: () => void; onSaved: () => Promise<void> }) {
  const endpointFields = splitEndpoint(value?.endpoint || "pve.example:8006");
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<ProxmoxConnectionInput>({
    name: value?.name || "", endpoint: endpointFields.address, credential_id: value?.credential_id || credentials[0]?.id || "",
    verify_tls: value?.verify_tls ?? true, ca_certificate: value?.ca_certificate || "", default_ssh_user: value?.default_ssh_user || "algen-ansible",
    project: value?.project || "", environment: value?.environment || "", location: value?.location || "", tags: value?.tags?.length ? value.tags : ["proxmox"],
    sync_proxmox_tags: value?.sync_proxmox_tags ?? true, sync_lxc: value?.sync_lxc ?? true, sync_templates: value?.sync_templates ?? false,
    active: value?.active ?? true, auto_sync: value?.auto_sync ?? false, sync_interval_seconds: value?.sync_interval_seconds || 300,
  });
  const [endpointPort, setEndpointPort] = useState(endpointFields.port);
  const [authMode, setAuthMode] = useState<ConnectionAuthMode>(value || credentials.length || !canManageCredentials ? "saved" : "username_password");
  const [credentialName, setCredentialName] = useState(value ? `${value.name} Proxmox login` : "Proxmox login");
  const [loginUsername, setLoginUsername] = useState(value?.credential?.type === "username_password" ? value.credential.username : "root@pam");
  const [loginPassword, setLoginPassword] = useState("");
  const inlineLogin = authMode === "username_password";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (inlineLogin && (!canManageCredentials || !credentialName.trim() || !loginUsername.includes("@") || !loginPassword)) return;
    if (!inlineLogin && !form.credential_id) return;
    let endpoint: string;
    try { endpoint = buildEndpoint(form.endpoint, endpointPort); }
    catch (error) { toast(error instanceof RangeError ? "Invalid port" : "Invalid endpoint", "error", "admin", "proxmox-manager"); return; }

    setSaving(true);
    let createdCredentialId = "";
    let connectionSaved = false;
    try {
      let credentialId = form.credential_id;
      if (inlineLogin) {
        const created = await api.saveHostsManagerCredential({
          name: credentialName.trim(), type: "username_password", username: loginUsername.trim(), environment_id: null,
          secret: loginPassword, passphrase: "", description: `Proxmox login for ${form.name.trim() || endpoint}`,
          shared_with: ["proxmox-manager"], confirm: true,
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
    } finally { setSaving(false); }
  }

  return <Modal title={value ? `Edit connection: ${value.name}` : "Add Proxmox connection"} onClose={onClose} wide footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button className="button-primary" type="submit" form="proxmox-connection-form" disabled={saving}>{saving ? "Saving…" : t("action.save")}</button></>}>
    <form id="proxmox-connection-form" onSubmit={submit}>
      <label className="field-label">Name<input autoFocus required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
      <label className="field-label">Address<input required value={form.endpoint} onChange={(event) => setForm({ ...form, endpoint: event.target.value })} placeholder="10.0.0.10" /></label>
      <label className="field-label">Port<input required type="number" min={1} max={65535} value={endpointPort} onChange={(event) => setEndpointPort(event.target.value)} /></label>
      <label className="field-label">Authentication<select value={authMode} onChange={(event) => setAuthMode(event.target.value as ConnectionAuthMode)}><option value="saved">Saved central credential</option><option value="username_password" disabled={!canManageCredentials}>Username / password</option></select></label>
      {inlineLogin ? <><label className="field-label">Credential name<input value={credentialName} onChange={(event) => setCredentialName(event.target.value)} /></label><label className="field-label">Login<input value={loginUsername} onChange={(event) => setLoginUsername(event.target.value)} placeholder="root@pam" autoComplete="username" /></label><label className="field-label">Password<input type="password" value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} autoComplete="current-password" /><small>The password is sent only to the central credential store; Proxmox Manager keeps credential_id only.</small></label></> : <label className="field-label">Credential<select required value={form.credential_id} onChange={(event) => setForm({ ...form, credential_id: event.target.value })}><option value="">Select credential</option>{credentials.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.type} · {item.username}</option>)}</select></label>}
      <label className="field-label">Default SSH user<input required value={form.default_ssh_user} onChange={(event) => setForm({ ...form, default_ssh_user: event.target.value })} /></label>
      <label className="field-label">Project<input value={form.project} onChange={(event) => setForm({ ...form, project: event.target.value })} /></label><label className="field-label">Environment<input value={form.environment} onChange={(event) => setForm({ ...form, environment: event.target.value })} /></label><label className="field-label">Location<input value={form.location} onChange={(event) => setForm({ ...form, location: event.target.value })} /></label>
      <label className="field-label">Tags<input value={form.tags.join(",")} onChange={(event) => setForm({ ...form, tags: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></label>
      <label className="field-label">Custom CA certificate<textarea rows={5} value={form.ca_certificate} onChange={(event) => setForm({ ...form, ca_certificate: event.target.value })} placeholder="-----BEGIN CERTIFICATE-----" /></label>
      <label><input type="checkbox" checked={form.verify_tls} onChange={(event) => setForm({ ...form, verify_tls: event.target.checked })} /> Verify TLS certificate</label><br />
      <label><input type="checkbox" checked={form.sync_lxc} onChange={(event) => setForm({ ...form, sync_lxc: event.target.checked })} /> Include LXC in Host Registry sync</label><br />
      <label><input type="checkbox" checked={form.sync_templates} onChange={(event) => setForm({ ...form, sync_templates: event.target.checked })} /> Include templates in Host Registry sync</label><br />
      <label><input type="checkbox" checked={form.sync_proxmox_tags} onChange={(event) => setForm({ ...form, sync_proxmox_tags: event.target.checked })} /> Synchronize Algen tags to Proxmox</label><br />
      <label><input type="checkbox" checked={form.auto_sync} onChange={(event) => setForm({ ...form, auto_sync: event.target.checked })} /> Automatic full inventory synchronization</label>
      {form.auto_sync && <label className="field-label">Sync interval (seconds)<input type="number" min={60} max={86400} value={form.sync_interval_seconds || 300} onChange={(event) => setForm({ ...form, sync_interval_seconds: Number(event.target.value) })} /><small>Allowed range: 60–86400 seconds. Failed syncs use exponential backoff.</small></label>}
      <br /><label><input type="checkbox" checked={form.active} onChange={(event) => setForm({ ...form, active: event.target.checked })} /> Active</label>
    </form>
  </Modal>;
}
