import { FilePenLine, FileText, Plus, RefreshCw, RotateCcw, TestTube2, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type NetworkMount, type NetworkMountPayload } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { notifyNetworkMountsChanged, stopWatchingNetworkMountChanges, watchNetworkMountChanges } from "./useNetworkMounts";

type Protocol = NetworkMountPayload["type"];
type FormState = {
  name: string; type: Protocol; host: string; share: string; export_path: string; remote_path: string;
  username: string; password: string; domain: string; smb_version: string; nfs_version: string;
  ssh_port: string; ssh_auth: "key"; read_only: boolean; persistent: boolean; automount: boolean;
  uid: string; gid: string; file_mode: string; dir_mode: string; noexec: boolean;
  advanced_options: string; allowed_users: string; allowed_groups: string; remove_secret: boolean;
};

const emptyForm = (): FormState => ({
  name: "", type: "smb", host: "", share: "", export_path: "", remote_path: "", username: "", password: "", domain: "",
  smb_version: "auto", nfs_version: "auto", ssh_port: "22", ssh_auth: "key", read_only: false, persistent: false,
  automount: false, uid: "", gid: "", file_mode: "0644", dir_mode: "0755", noexec: true, advanced_options: "",
  allowed_users: "", allowed_groups: "", remove_secret: false,
});

const list = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);
const busyStatuses = new Set(["mounting", "unmounting", "remounting", "testing", "migrating"]);

function configString(mount: NetworkMount, key: string, fallback = "") {
  const value = mount.config[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : fallback;
}

function MountForm({ mount, t, onClose, onSaved }: { mount?: NetworkMount; t: Translate; onClose: () => void; onSaved: () => Promise<void> }) {
  const [form, setForm] = useState<FormState>(() => mount ? {
    ...emptyForm(), name: mount.name, type: mount.type, host: mount.host,
    share: mount.type === "smb" ? mount.remote.replace(/^\/\/[^/]+\//, "") : "",
    export_path: mount.type === "nfs" ? mount.remote.slice(mount.remote.indexOf(":") + 1) : "",
    remote_path: ["sshfs", "webdav"].includes(mount.type) ? (mount.type === "sshfs" ? mount.remote.slice(mount.remote.indexOf(":") + 1) : mount.remote) : "",
    username: configString(mount, "username"), domain: configString(mount, "domain"), smb_version: configString(mount, "smb_version", "auto"),
    nfs_version: configString(mount, "nfs_version", "auto"), ssh_port: configString(mount, "ssh_port", "22"), read_only: mount.read_only,
    persistent: mount.persistent, automount: Boolean(mount.config.automount), uid: configString(mount, "uid"), gid: configString(mount, "gid"),
    file_mode: configString(mount, "file_mode", "0644"), dir_mode: configString(mount, "dir_mode", "0755"), noexec: mount.config.noexec !== false,
    advanced_options: Array.isArray(mount.config.advanced_options) ? mount.config.advanced_options.join(", ") : "",
    allowed_users: mount.allowed_users.join(", "), allowed_groups: mount.allowed_groups.join(", "),
  } : emptyForm());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const formId = `network-mount-${mount?.id || "new"}`;
  const mountPoint = `/mnt/webnas/mnt/${form.name || t("mounts.namePlaceholder")}`;
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((current) => ({ ...current, [key]: value }));

  function validate() {
    const errors: Record<string, string> = {};
    if (!/^[\p{L}\p{N}][\p{L}\p{N}_.-]{0,62}$/u.test(form.name) || form.name.includes("..") || form.name.endsWith(".")) errors.name = t("mounts.invalidName");
    if (!form.host.trim()) errors.host = t("mounts.required");
    if (form.type === "smb" && !form.share.trim()) errors.share = t("mounts.required");
    if (form.type === "nfs" && !form.export_path.startsWith("/")) errors.export_path = t("mounts.pathMustBeAbsolute");
    if (form.type === "sshfs" && !form.remote_path.startsWith("/")) errors.remote_path = t("mounts.pathMustBeAbsolute");
    if (form.type === "sshfs" && !form.username.trim()) errors.username = t("mounts.required");
    if (form.type === "webdav" && !/^https?:\/\//.test(form.remote_path)) errors.remote_path = t("mounts.invalidUrl");
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!validate()) return;
    setSaving(true); setError("");
    const payload: NetworkMountPayload = {
      name: form.name, type: form.type, host: form.host,
      share: form.type === "smb" ? form.share : undefined, export_path: form.type === "nfs" ? form.export_path : undefined,
      remote_path: ["sshfs", "webdav"].includes(form.type) ? form.remote_path : undefined,
      username: ["smb", "sshfs", "webdav"].includes(form.type) ? form.username || undefined : undefined,
      password: form.password || undefined, domain: form.type === "smb" ? form.domain || undefined : undefined,
      smb_version: form.smb_version, nfs_version: form.nfs_version, ssh_port: Number(form.ssh_port), ssh_auth: "key",
      read_only: form.read_only, persistent: form.persistent, automount: form.persistent && form.automount,
      uid: form.uid || undefined, gid: form.gid || undefined, file_mode: form.file_mode, dir_mode: form.dir_mode, noexec: form.noexec,
      advanced_options: list(form.advanced_options), allowed_users: list(form.allowed_users), allowed_groups: list(form.allowed_groups), remove_secret: form.remove_secret,
    };
    try {
      if (mount) await api.updateMount(mount.id, payload); else await api.createMount(payload);
      await onSaved();
      notifyNetworkMountsChanged();
      onClose();
    } catch (reason) {
      if (reason instanceof ApiError && reason.field && reason.field in form) {
        setFieldErrors((current) => ({ ...current, [reason.field!]: reason.message }));
      } else {
        setError(reason instanceof Error ? reason.message : t("error.generic"));
      }
    } finally { setSaving(false); }
  }

  const field = (name: keyof FormState, label: string, options?: { type?: string; required?: boolean; placeholder?: string }) => <label className="field-label">{label}<input type={options?.type || "text"} required={options?.required} placeholder={options?.placeholder} value={String(form[name])} onChange={(event) => set(name, event.target.value as FormState[typeof name])} />{fieldErrors[name] && <small className="field-error">{fieldErrors[name]}</small>}</label>;
  const check = (name: keyof FormState, label: string, disabled = false) => <label className="mount-check"><input type="checkbox" disabled={disabled} checked={Boolean(form[name])} onChange={(event) => set(name, event.target.checked as FormState[typeof name])} />{label}</label>;

  return <Modal wide title={mount ? t("mounts.edit") : t("mounts.new")} closeLabel={t("action.close")} onClose={onClose} footer={<><button onClick={onClose}>{t("action.cancel")}</button><button className="button-primary" type="submit" form={formId} disabled={saving}>{saving ? t("status.loading") : t("action.apply")}</button></>}>
    <form id={formId} className="mount-form" onSubmit={(event) => void submit(event)}>
      <div className="mount-form-grid">{field("name", t("mounts.name"), { required: true })}<label className="field-label">{t("mounts.type")}<select value={form.type} onChange={(event) => set("type", event.target.value as Protocol)}><option value="smb">SMB/CIFS</option><option value="nfs">NFS</option><option value="sshfs">SSHFS</option><option value="webdav">WebDAV</option></select></label>{field("host", t("mounts.host"), { required: true })}<label className="field-label">{t("mounts.mountPoint")}<input readOnly value={mountPoint} /><small>{t("mounts.mountPointManaged")}</small></label>
        {form.type === "smb" && <>{field("share", t("mounts.share"), { required: true })}{field("username", t("settings.username"))}{field("password", t("auth.password"), { type: "password", placeholder: mount?.config.has_secret ? t("mounts.keepSecret") : "" })}{field("domain", t("mounts.domain"))}<label className="field-label">{t("mounts.smbVersion")}<select value={form.smb_version} onChange={(event) => set("smb_version", event.target.value)}>{["auto", "2.1", "3.0", "3.1.1"].map((value) => <option key={value}>{value}</option>)}</select></label></>}
        {form.type === "nfs" && <>{field("export_path", t("mounts.exportPath"), { required: true })}<label className="field-label">{t("mounts.nfsVersion")}<select value={form.nfs_version} onChange={(event) => set("nfs_version", event.target.value)}>{["auto", "3", "4", "4.1", "4.2"].map((value) => <option key={value}>{value}</option>)}</select></label></>}
        {form.type === "sshfs" && <>{field("username", t("mounts.sshUser"), { required: true })}{field("remote_path", t("mounts.remotePath"), { required: true })}{field("ssh_port", t("mounts.port"), { type: "number", required: true })}<label className="field-label">{t("mounts.authentication")}<select value="key" disabled><option value="key">{t("mounts.sshKeyOnly")}</option></select><small>{t("mounts.sshPasswordDisabled")}</small></label></>}
        {form.type === "webdav" && <>{field("remote_path", t("mounts.webdavUrl"), { required: true })}{field("username", t("settings.username"))}{field("password", t("auth.password"), { type: "password", placeholder: mount?.config.has_secret ? t("mounts.keepSecret") : "" })}{form.remote_path.startsWith("http://") && <p className="warning-note">{t("mounts.httpWarning")}</p>}</>}
        {field("uid", "UID")}{field("gid", "GID")}{field("file_mode", t("mounts.fileMode"))}{field("dir_mode", t("mounts.dirMode"))}{field("advanced_options", t("mounts.advancedOptions"))}{field("allowed_users", t("mounts.allowedUsers"))}{field("allowed_groups", t("mounts.allowedGroups"))}
      </div>
      <div className="mount-form-checks">{check("read_only", t("mounts.readOnly"))}{check("persistent", t("mounts.persistent"))}{check("automount", t("mounts.automount"), !form.persistent)}{check("noexec", t("mounts.noexec"))}{mount?.config.has_secret && check("remove_secret", t("mounts.removeSecret"))}</div>
      {mount?.config.has_secret && !form.remove_secret && <p className="credential-note">{t("mounts.secretPreserved")}</p>}
      {error && <p className="error-state compact-error" role="alert">{error}</p>}
    </form>
  </Modal>;
}

export function NetworkMountsSettingsSection({ isAdmin, t, toast }: { isAdmin: boolean; t: Translate; toast: ToastFn }) {
  const [mounts, setMounts] = useState<NetworkMount[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<NetworkMount | "new" | null>(null);
  const [actionDialog, setActionDialog] = useState<{ mount: NetworkMount; action: "mount" | "unmount" | "remount" | "test" | "delete" | "migrate" } | null>(null);
  const [logs, setLogs] = useState<{ name: string; lines: string[] } | null>(null);
  const trackedJobs = useRef(new Set<string>());

  const refresh = useCallback(async () => {
    if (!isAdmin) return;
    setLoading(true); setError("");
    try { setMounts(await api.mounts()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Error"); }
    finally { setLoading(false); }
  }, [isAdmin]);
  useEffect(() => { void refresh(); }, [refresh]);
  const activeKey = useMemo(() => mounts.flatMap((mount) => mount.jobs).filter((job) => ["queued", "running"].includes(job.status)).map((job) => job.id).join("|"), [mounts]);
  useEffect(() => {
    if (!activeKey) return;
    const timer = window.setInterval(() => void refresh(), 1200);
    return () => window.clearInterval(timer);
  }, [activeKey, refresh]);
  useEffect(() => {
    const finished = mounts.flatMap((mount) => mount.jobs).filter((job) => trackedJobs.current.has(job.id) && ["completed", "failed"].includes(job.status));
    finished.forEach((job) => {
      trackedJobs.current.delete(job.id);
      toast(job.status === "completed" ? t("admin.actionCompleted") : `${t("mounts.operationFailed")}: ${job.error}`, job.status === "failed" ? "error" : "ok", "admin");
      notifyNetworkMountsChanged();
    });
    if (finished.length > 0 && trackedJobs.current.size === 0) stopWatchingNetworkMountChanges();
  }, [mounts, t, toast]);

  if (!isAdmin) return null;
  async function runAction() {
    if (!actionDialog) return;
    const { mount, action } = actionDialog;
    try {
      if (action === "delete") {
        await api.deleteMount(mount.id);
      } else {
        const result = await api.mountAction(mount.id, action);
        if (result.job) {
          trackedJobs.current.add(result.job.id);
          if (action !== "test") watchNetworkMountChanges();
        }
      }
    } finally {
      await refresh();
    }
    setActionDialog(null);
    if (action === "delete") notifyNetworkMountsChanged();
  }

  return <section className="network-mounts-settings" aria-label={t("settings.networkResources")}>
    <header className="feature-header"><div><h3>{t("settings.networkResources")}</h3><p>{t("mounts.settingsSubtitle")}</p></div><div className="header-actions"><button onClick={() => void refresh()}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button><button onClick={() => setEditing("new")}><Plus />{t("mounts.new")}</button></div></header>
    {error && <p className="error-state" role="alert">{error}</p>}
    {!loading && mounts.length === 0 && <div className="empty-state">{t("mounts.empty")}</div>}
    <div className="mount-card-grid">{mounts.map((mount) => { const busy = busyStatuses.has(mount.status) || mount.jobs.some((job) => ["queued", "running"].includes(job.status)); const fs = mount.fs; return <article className="mount-card" key={mount.id}>
      <header><div><strong>{mount.name}</strong><small>{mount.type.toUpperCase()} · {mount.host}</small></div><span className={`status-badge ${mount.status}`}>{t(`mounts.status.${mount.status}`)}</span></header>
      <dl><div><dt>{t("mounts.remote")}</dt><dd>{mount.remote}</dd></div><div><dt>{t("mounts.mountPoint")}</dt><dd><code>{mount.mount_point}</code></dd></div><div><dt>{t("mounts.owner")}</dt><dd>{mount.owner}</dd></div><div><dt>{t("mounts.access")}</dt><dd>{[...mount.allowed_users, ...mount.allowed_groups.map((group) => `@${group}`)].join(", ") || t("mounts.allAuthenticated")}</dd></div><div><dt>{t("mounts.mode")}</dt><dd>{mount.read_only ? t("mounts.readOnly") : t("mounts.readWrite")} · {mount.persistent ? t("mounts.persistent") : t("mounts.temporary")}</dd></div>{fs && <div><dt>{t("mounts.space")}</dt><dd>{Math.round(fs.used / Math.max(fs.total, 1) * 100)}% · {(fs.free / 1073741824).toFixed(1)} GiB {t("mounts.free")} · {fs.fs_type}</dd></div>}</dl>
      {mount.missing_packages.length > 0 && <p className="warning-note">{t("mounts.missingPackages")}: {mount.missing_packages.join(", ")}</p>}
      {mount.last_error && !(mount.status === "missing_packages" && mount.missing_packages.length > 0) && <p className="error-note">{mount.last_error}</p>}
      {mount.last_operation && <small>{t("mounts.lastOperation")}: {mount.last_operation}{mount.last_operation_at ? ` · ${new Date(mount.last_operation_at * 1000).toLocaleString()}` : ""}</small>}
      <div className="data-actions"><button disabled={busy || mount.status === "mounted"} onClick={() => setActionDialog({ mount, action: "mount" })}>{t("mounts.mount")}</button><button disabled={busy || !mount.actual_mounted} onClick={() => setActionDialog({ mount, action: "unmount" })}>{t("mounts.unmount")}</button><button disabled={busy || !mount.actual_mounted} onClick={() => setActionDialog({ mount, action: "remount" })}><RotateCcw />{t("mounts.remount")}</button><button disabled={busy} onClick={() => setActionDialog({ mount, action: "test" })}><TestTube2 />{t("mounts.test")}</button><button disabled={busy} onClick={() => setEditing(mount)}><FilePenLine />{t("action.edit")}</button><button onClick={() => api.mountLogs(mount.id).then((value) => setLogs({ name: mount.name, lines: value.lines })).catch((reason: unknown) => toast(reason instanceof Error ? reason.message : t("error.generic"), "error", "admin"))}><FileText />{t("mounts.logs")}</button>{mount.migration_status !== "ready" && <button disabled={busy} onClick={() => setActionDialog({ mount, action: "migrate" })}>{t("mounts.migrate")}</button>}<button className="danger" disabled={busy} onClick={() => setActionDialog({ mount, action: "delete" })}><Trash2 />{t("action.delete")}</button></div>
    </article>; })}</div>
    {editing && <MountForm mount={editing === "new" ? undefined : editing} t={t} onClose={() => setEditing(null)} onSaved={refresh} />}
    {actionDialog && <AdminActionDialog title={`${t(`mounts.${actionDialog.action}`)}: ${actionDialog.mount.name}`} fields={[]} danger={["delete", "unmount", "remount", "migrate"].includes(actionDialog.action)} t={t} onClose={() => setActionDialog(null)} onSubmit={runAction} />}
    {logs && <Modal wide title={`${t("mounts.logs")}: ${logs.name}`} closeLabel={t("action.close")} onClose={() => setLogs(null)} footer={<button onClick={() => setLogs(null)}>{t("action.close")}</button>}><pre className="log-view">{logs.lines.join("\n") || t("mounts.noLogs")}</pre></Modal>}
  </section>;
}
