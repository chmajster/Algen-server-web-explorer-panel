import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, CircleOff, Cloud, Copy, Database, FilePenLine, FileText,
  HardDrive, LoaderCircle, MoreHorizontal, Network, Plus, RefreshCw, RotateCcw, Search, Server,
  TestTube2, Trash2, Unplug,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type NetworkMount, type NetworkMountPayload } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { Modal } from "../../components/Modal";
import { AdminActionDialog } from "../admin/AdminActionDialog";
import { notifyNetworkMountsChanged, stopWatchingNetworkMountChanges, watchNetworkMountChanges } from "./useNetworkMounts";

type Protocol = NetworkMountPayload["type"];
type MountAction = "mount" | "unmount" | "remount" | "test" | "delete" | "migrate";
type StatusFilter = "all" | "mounted" | "unmounted" | "attention" | "busy";
type ProtocolFilter = "all" | Protocol;
type SortOrder = "name-asc" | "name-desc" | "status" | "last-operation";
type FormState = {
  name: string; type: Protocol; host: string; share: string; export_path: string; remote_path: string;
  username: string; password: string; domain: string; smb_version: string; nfs_version: string;
  ssh_port: string; ssh_auth: "key"; read_only: boolean; persistent: boolean; automount: boolean;
  uid: string; gid: string; file_mode: string; dir_mode: string; noexec: boolean;
  advanced_options: string; allowed_users: string; allowed_groups: string; remove_secret: boolean;
};

const ATTENTION_STATUSES = new Set(["error", "missing_packages", "host_unavailable", "migration_required", "manual_intervention_required"]);
const BUSY_STATUSES = new Set(["mounting", "unmounting", "remounting", "testing", "migrating"]);
const emptyForm = (): FormState => ({
  name: "", type: "smb", host: "", share: "", export_path: "", remote_path: "", username: "", password: "", domain: "",
  smb_version: "auto", nfs_version: "auto", ssh_port: "22", ssh_auth: "key", read_only: false, persistent: false,
  automount: false, uid: "", gid: "", file_mode: "0644", dir_mode: "0755", noexec: true, advanced_options: "",
  allowed_users: "", allowed_groups: "", remove_secret: false,
});
const list = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);
const isBusy = (mount: NetworkMount) => BUSY_STATUSES.has(mount.status) || mount.jobs.some((job) => ["queued", "running"].includes(job.status));
const needsAttention = (mount: NetworkMount) => ATTENTION_STATUSES.has(mount.status) || mount.manual_intervention;

function configString(mount: NetworkMount, key: string, fallback = "") {
  const value = mount.config[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : fallback;
}

function ProtocolIcon({ protocol }: { protocol: Protocol }) {
  if (protocol === "smb") return <Server aria-hidden="true" />;
  if (protocol === "nfs") return <Database aria-hidden="true" />;
  if (protocol === "sshfs") return <HardDrive aria-hidden="true" />;
  return <Cloud aria-hidden="true" />;
}

function MountStatusBadge({ mount, t }: { mount: NetworkMount; t: Translate }) {
  const status = mount.status;
  const Icon = isBusy(mount) ? LoaderCircle : mount.actual_mounted ? CheckCircle2 : needsAttention(mount) ? AlertTriangle : CircleOff;
  return <span className={`mount-status-badge status-${status}`}><Icon className={isBusy(mount) ? "spin" : ""} aria-hidden="true" /><span>{t(`mounts.status.${status}`)}</span></span>;
}

function NetworkMountsHeader({ loading, t, onRefresh, onCreate }: { loading: boolean; t: Translate; onRefresh: () => void; onCreate: () => void }) {
  return <header className="network-mounts-page-header">
    <div className="network-mounts-title"><span><Network aria-hidden="true" /></span><div><h3>{t("settings.networkResources")}</h3><p>{t("mounts.settingsSubtitle")}</p></div></div>
    <div className="network-mounts-header-actions">
      <button type="button" disabled={loading} aria-busy={loading} onClick={onRefresh}><RefreshCw className={loading ? "spin" : ""} aria-hidden="true" />{t("action.refresh")}</button>
      <button type="button" className="button-primary" onClick={onCreate}><Plus aria-hidden="true" />{t("mounts.new")}</button>
    </div>
  </header>;
}

function NetworkMountsSummary({ mounts, t }: { mounts: NetworkMount[]; t: Translate }) {
  const mounted = mounts.filter((mount) => mount.actual_mounted).length;
  const unmounted = mounts.filter((mount) => !mount.actual_mounted).length;
  const attention = mounts.filter(needsAttention).length;
  const items = [
    { key: "total", value: mounts.length, icon: Network, tone: "neutral" },
    { key: "mounted", value: mounted, icon: CheckCircle2, tone: "success" },
    { key: "unmounted", value: unmounted, icon: Unplug, tone: "muted" },
    { key: "attention", value: attention, icon: AlertTriangle, tone: "warning" },
  ];
  return <section className="network-mounts-summary" aria-label={t("mounts.summary")}>{items.map(({ key, value, icon: Icon, tone }) => <article className={tone} key={key}><Icon aria-hidden="true" /><div><strong>{value}</strong><span>{t(`mounts.summary.${key}`)}</span></div></article>)}</section>;
}

function NetworkMountsToolbar({ query, status, protocol, sort, count, t, onQuery, onStatus, onProtocol, onSort }: {
  query: string; status: StatusFilter; protocol: ProtocolFilter; sort: SortOrder; count: number; t: Translate;
  onQuery: (value: string) => void; onStatus: (value: StatusFilter) => void; onProtocol: (value: ProtocolFilter) => void; onSort: (value: SortOrder) => void;
}) {
  return <section className="network-mounts-toolbar" aria-label={t("mounts.filters")}>
    <label className="network-mounts-search"><span>{t("mounts.search")}</span><span><Search aria-hidden="true" /><input value={query} onChange={(event) => onQuery(event.target.value)} placeholder={t("mounts.searchPlaceholder")} /></span></label>
    <label><span>{t("mounts.filter.status")}</span><select value={status} onChange={(event) => onStatus(event.target.value as StatusFilter)}><option value="all">{t("mounts.filter.all")}</option><option value="mounted">{t("mounts.filter.mounted")}</option><option value="unmounted">{t("mounts.filter.unmounted")}</option><option value="attention">{t("mounts.filter.attention")}</option><option value="busy">{t("mounts.filter.busy")}</option></select></label>
    <label><span>{t("mounts.filter.protocol")}</span><select value={protocol} onChange={(event) => onProtocol(event.target.value as ProtocolFilter)}><option value="all">{t("mounts.filter.all")}</option><option value="smb">SMB</option><option value="nfs">NFS</option><option value="sshfs">SSHFS</option><option value="webdav">WebDAV</option></select></label>
    <label><span>{t("mounts.sort")}</span><select value={sort} onChange={(event) => onSort(event.target.value as SortOrder)}><option value="name-asc">{t("mounts.sort.nameAsc")}</option><option value="name-desc">{t("mounts.sort.nameDesc")}</option><option value="status">{t("mounts.sort.status")}</option><option value="last-operation">{t("mounts.sort.lastOperation")}</option></select></label>
    <p aria-live="polite">{t("mounts.resultsCount").replace("{count}", String(count))}</p>
  </section>;
}

function MountPathField({ value, label, copyLabel, t, toast }: { value: string; label: string; copyLabel: string; t: Translate; toast: ToastFn }) {
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      toast(t("mounts.pathCopied"), "ok");
    } catch {
      toast(t("mounts.copyFailed"), "error");
    }
  }
  return <div className="mount-path-row"><dt>{label}</dt><dd><code>{value}</code><button type="button" aria-label={copyLabel} title={copyLabel} onClick={() => void copy()}><Copy aria-hidden="true" /></button></dd></div>;
}

function MountStorageMeter({ mount, t }: { mount: NetworkMount; t: Translate }) {
  const fs = mount.fs;
  if (!fs) return null;
  const total = Number.isFinite(fs.total) && fs.total > 0 ? fs.total : 0;
  const used = Number.isFinite(fs.used) && fs.used > 0 ? fs.used : 0;
  const free = Number.isFinite(fs.free) && fs.free > 0 ? fs.free : 0;
  const percent = total ? Math.max(0, Math.min(100, Math.round((used / total) * 100))) : 0;
  return <section className="mount-storage">
    <div><span>{t("mounts.space")}</span><strong>{percent}%</strong></div>
    <div className="mount-storage-track" role="progressbar" aria-label={t("mounts.storageUsage")} aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${percent}%` }} /></div>
    <small>{(free / 1073741824).toFixed(1)} GiB {t("mounts.free")} · {fs.fs_type || t("common.none")}</small>
  </section>;
}

function MountAlert({ mount, t }: { mount: NetworkMount; t: Translate }) {
  let message = "";
  if (mount.status === "missing_packages" && mount.missing_packages.length) message = `${t("mounts.missingPackages")}: ${mount.missing_packages.join(", ")}`;
  else if (mount.status === "host_unavailable") message = mount.last_error || t("mounts.hostUnavailable");
  else if (mount.status === "migration_required") message = t("mounts.migrationRequired");
  else if (mount.status === "manual_intervention_required" || mount.manual_intervention) message = mount.last_error || t("mounts.manualInterventionRequired");
  else if (mount.last_error) message = mount.last_error;
  if (!message) return null;
  return <p className={`mount-inline-alert ${needsAttention(mount) ? "warning" : "error"}`} role="status"><AlertTriangle aria-hidden="true" /><span>{message}</span></p>;
}

function MountActionsMenu({ mount, busy, t, onAction, onLogs }: { mount: NetworkMount; busy: boolean; t: Translate; onAction: (action: MountAction) => void; onLogs: () => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    function closeOutside(event: PointerEvent) { if (!root.current?.contains(event.target as Node)) setOpen(false); }
    function keyboard(event: KeyboardEvent) {
      if (event.key === "Escape") { setOpen(false); root.current?.querySelector<HTMLButtonElement>(".mount-more-trigger")?.focus(); return; }
      if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
      const buttons = [...(root.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') || [])];
      if (!buttons.length) return;
      event.preventDefault();
      const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : event.key === "ArrowDown" ? (current + 1) % buttons.length : (current - 1 + buttons.length) % buttons.length;
      buttons[next].focus();
    }
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", keyboard);
    return () => { document.removeEventListener("pointerdown", closeOutside); document.removeEventListener("keydown", keyboard); };
  }, [open]);
  function select(action: MountAction | "logs") { setOpen(false); if (action === "logs") onLogs(); else onAction(action); }
  return <div className="mount-actions-menu" ref={root}>
    <button className="mount-more-trigger" type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((value) => !value)}><MoreHorizontal aria-hidden="true" />{t("mounts.moreActions")}<ChevronDown aria-hidden="true" /></button>
    {open && <div role="menu" className="mount-actions-popover">
      <button role="menuitem" disabled={busy || !mount.actual_mounted} onClick={() => select("remount")}><RotateCcw aria-hidden="true" />{t("mounts.remount")}</button>
      <button role="menuitem" onClick={() => select("logs")}><FileText aria-hidden="true" />{t("mounts.logs")}</button>
      {mount.migration_status !== "ready" && <button role="menuitem" disabled={busy} onClick={() => select("migrate")}><HardDrive aria-hidden="true" />{t("mounts.migrate")}</button>}
      <button role="menuitem" className="danger" disabled={busy} onClick={() => select("delete")}><Trash2 aria-hidden="true" />{t("action.delete")}</button>
    </div>}
  </div>;
}

function NetworkMountCard({ mount, t, toast, onEdit, onAction, onLogs }: { mount: NetworkMount; t: Translate; toast: ToastFn; onEdit: () => void; onAction: (action: MountAction) => void; onLogs: () => void }) {
  const [collapsed, setCollapsed] = useState(false);
  const busy = isBusy(mount);
  const activeJob = mount.jobs.find((job) => ["queued", "running"].includes(job.status));
  const operation = BUSY_STATUSES.has(mount.status) ? mount.status : activeJob?.action;
  return <article className={`network-mount-card ${collapsed ? "is-collapsed" : ""} ${mount.actual_mounted ? "is-mounted" : "is-unmounted"} ${needsAttention(mount) ? "needs-attention" : ""}`} aria-busy={busy}>
    <header>
      <button type="button" className="mount-card-collapse-toggle" aria-expanded={!collapsed} aria-label={`${t(collapsed ? "mounts.expandResource" : "mounts.collapseResource")}: ${mount.name}`} onClick={() => setCollapsed((value) => !value)}>
        {collapsed ? <ChevronRight aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
        <div className="mount-card-identity">
          {!collapsed && <span><ProtocolIcon protocol={mount.type} /></span>}
          <div><div><h4>{mount.name}</h4>{!collapsed && <b>{mount.type.toUpperCase()}</b>}</div>{!collapsed && <small>{mount.host}</small>}</div>
        </div>
        {!collapsed && <MountStatusBadge mount={mount} t={t} />}
      </button>
    </header>
    {!collapsed && <>
      {busy && <p className="mount-operation-state" role="status"><LoaderCircle className="spin" aria-hidden="true" />{t(`mounts.operation.${operation || "running"}`)}</p>}
      <dl className="mount-card-details">
        <MountPathField value={mount.remote} label={t("mounts.remote")} copyLabel={t("mounts.copyRemote")} t={t} toast={toast} />
        <MountPathField value={mount.mount_point} label={t("mounts.mountPoint")} copyLabel={t("mounts.copyMountPoint")} t={t} toast={toast} />
        <div><dt>{t("mounts.owner")}</dt><dd>{mount.owner}</dd></div>
        <div><dt>{t("mounts.access")}</dt><dd>{[...mount.allowed_users, ...mount.allowed_groups.map((group) => `@${group}`)].join(", ") || t("mounts.allAuthenticated")}</dd></div>
        <div><dt>{t("mounts.mode")}</dt><dd>{mount.read_only ? t("mounts.readOnly") : t("mounts.readWrite")}</dd></div>
        <div><dt>{t("mounts.persistence")}</dt><dd>{mount.persistent ? t("mounts.persistent") : t("mounts.temporary")}</dd></div>
        <div><dt>{t("mounts.lastOperation")}</dt><dd>{mount.last_operation || t("common.none")}{mount.last_operation_at ? <small>{new Date(mount.last_operation_at * 1000).toLocaleString()}</small> : null}</dd></div>
      </dl>
      <MountStorageMeter mount={mount} t={t} />
      <MountAlert mount={mount} t={t} />
      <footer>
        <button type="button" className="button-primary mount-primary-action" disabled={busy} onClick={() => onAction(mount.actual_mounted ? "unmount" : "mount")}>{mount.actual_mounted ? <Unplug aria-hidden="true" /> : <Network aria-hidden="true" />}{t(mount.actual_mounted ? "mounts.unmount" : "mounts.mount")}</button>
        <button type="button" disabled={busy} onClick={() => onAction("test")}><TestTube2 aria-hidden="true" />{t("mounts.test")}</button>
        <button type="button" disabled={busy} onClick={onEdit}><FilePenLine aria-hidden="true" />{t("action.edit")}</button>
        <MountActionsMenu mount={mount} busy={busy} t={t} onAction={onAction} onLogs={onLogs} />
      </footer>
    </>}
  </article>;
}

function NetworkMountEmptyState({ filtered, t, onCreate, onReset }: { filtered: boolean; t: Translate; onCreate: () => void; onReset: () => void }) {
  return <section className="network-mounts-empty"><span>{filtered ? <Search aria-hidden="true" /> : <Network aria-hidden="true" />}</span><h4>{t(filtered ? "mounts.noFilterResults" : "mounts.empty")}</h4><p>{t(filtered ? "mounts.noFilterResultsHint" : "mounts.emptyHint")}</p><button type="button" className={filtered ? "" : "button-primary"} onClick={filtered ? onReset : onCreate}>{t(filtered ? "mounts.clearFilters" : "mounts.addFirst")}</button></section>;
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
      await onSaved(); notifyNetworkMountsChanged(); onClose();
    } catch (reason) {
      if (reason instanceof ApiError && reason.field && reason.field in form) setFieldErrors((current) => ({ ...current, [reason.field!]: reason.message }));
      else setError(reason instanceof Error ? reason.message : t("error.generic"));
    } finally { setSaving(false); }
  }
  const field = (name: keyof FormState, label: string, options?: { type?: string; required?: boolean; placeholder?: string; readOnly?: boolean }) => <label className="field-label">{label}<input type={options?.type || "text"} required={options?.required} readOnly={options?.readOnly} placeholder={options?.placeholder} value={String(form[name])} onChange={(event) => set(name, event.target.value as FormState[typeof name])} />{fieldErrors[name] && <small className="field-error">{fieldErrors[name]}</small>}</label>;
  const check = (name: keyof FormState, label: string, disabled = false) => <label className="mount-check"><input type="checkbox" disabled={disabled} checked={Boolean(form[name])} onChange={(event) => set(name, event.target.checked as FormState[typeof name])} />{label}</label>;
  return <Modal wide title={mount ? t("mounts.edit") : t("mounts.new")} closeLabel={t("action.close")} onClose={onClose} footer={<><button type="button" onClick={onClose}>{t("action.cancel")}</button><button className="button-primary" type="submit" form={formId} disabled={saving}>{saving ? t("status.loading") : t("action.apply")}</button></>}>
    <form id={formId} className="mount-form" onSubmit={(event) => void submit(event)}>
      <fieldset><legend>{t("mounts.form.basic")}</legend><div className="mount-form-grid">{field("name", t("mounts.name"), { required: true })}<label className="field-label">{t("mounts.type")}<select value={form.type} onChange={(event) => set("type", event.target.value as Protocol)}><option value="smb">SMB/CIFS</option><option value="nfs">NFS</option><option value="sshfs">SSHFS</option><option value="webdav">WebDAV</option></select></label><label className="field-label">{t("mounts.mountPoint")}<input readOnly value={mountPoint} /><small>{t("mounts.mountPointManaged")}</small></label></div></fieldset>
      <fieldset><legend>{t("mounts.form.connection")}</legend><div className="mount-form-grid">{field("host", t("mounts.host"), { required: true })}
        {form.type === "smb" && <>{field("share", t("mounts.share"), { required: true })}{field("username", t("settings.username"))}{field("password", t("auth.password"), { type: "password", placeholder: mount?.config.has_secret ? t("mounts.keepSecret") : "" })}{field("domain", t("mounts.domain"))}<label className="field-label">{t("mounts.smbVersion")}<select value={form.smb_version} onChange={(event) => set("smb_version", event.target.value)}>{["auto", "2.1", "3.0", "3.1.1"].map((value) => <option key={value}>{value}</option>)}</select></label></>}
        {form.type === "nfs" && <>{field("export_path", t("mounts.exportPath"), { required: true })}<label className="field-label">{t("mounts.nfsVersion")}<select value={form.nfs_version} onChange={(event) => set("nfs_version", event.target.value)}>{["auto", "3", "4", "4.1", "4.2"].map((value) => <option key={value}>{value}</option>)}</select></label></>}
        {form.type === "sshfs" && <>{field("username", t("mounts.sshUser"), { required: true })}{field("remote_path", t("mounts.remotePath"), { required: true })}{field("ssh_port", t("mounts.port"), { type: "number", required: true })}<label className="field-label">{t("mounts.authentication")}<select value="key" disabled><option value="key">{t("mounts.sshKeyOnly")}</option></select><small>{t("mounts.sshPasswordDisabled")}</small></label></>}
        {form.type === "webdav" && <>{field("remote_path", t("mounts.webdavUrl"), { required: true })}{field("username", t("settings.username"))}{field("password", t("auth.password"), { type: "password", placeholder: mount?.config.has_secret ? t("mounts.keepSecret") : "" })}{form.remote_path.startsWith("http://") && <p className="warning-note">{t("mounts.httpWarning")}</p>}</>}
      </div></fieldset>
      <fieldset><legend>{t("mounts.form.permissions")}</legend><div className="mount-form-grid">{field("allowed_users", t("mounts.allowedUsers"))}{field("allowed_groups", t("mounts.allowedGroups"))}</div></fieldset>
      <fieldset><legend>{t("mounts.form.mounting")}</legend><div className="mount-form-checks">{check("read_only", t("mounts.readOnly"))}{check("persistent", t("mounts.persistent"))}{check("automount", t("mounts.automount"), !form.persistent)}{check("noexec", t("mounts.noexec"))}</div></fieldset>
      <details className="mount-form-advanced"><summary>{t("mounts.form.advanced")}</summary><div className="mount-form-grid">{field("uid", "UID")}{field("gid", "GID")}{field("file_mode", t("mounts.fileMode"))}{field("dir_mode", t("mounts.dirMode"))}{field("advanced_options", t("mounts.advancedOptions"))}</div>{mount?.config.has_secret && <div className="mount-form-checks">{check("remove_secret", t("mounts.removeSecret"))}</div>}</details>
      {!form.read_only && <p className="credential-note">{t("mounts.writeAccessHint")}</p>}
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
  const [actionDialog, setActionDialog] = useState<{ mount: NetworkMount; action: MountAction } | null>(null);
  const [logs, setLogs] = useState<{ name: string; lines: string[] } | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [protocolFilter, setProtocolFilter] = useState<ProtocolFilter>("all");
  const [sort, setSort] = useState<SortOrder>("name-asc");
  const trackedJobs = useRef(new Set<string>());
  const refresh = useCallback(async () => {
    if (!isAdmin) return;
    setLoading(true); setError("");
    try { setMounts(await api.mounts()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("error.generic")); }
    finally { setLoading(false); }
  }, [isAdmin, t]);
  useEffect(() => { void refresh(); }, [refresh]);
  const activeKey = useMemo(() => mounts.flatMap((mount) => mount.jobs).filter((job) => ["queued", "running"].includes(job.status)).map((job) => job.id).join("|"), [mounts]);
  useEffect(() => { if (!activeKey) return; const timer = window.setInterval(() => void refresh(), 1200); return () => window.clearInterval(timer); }, [activeKey, refresh]);
  useEffect(() => {
    const finished = mounts.flatMap((mount) => mount.jobs).filter((job) => trackedJobs.current.has(job.id) && ["completed", "failed"].includes(job.status));
    finished.forEach((job) => { trackedJobs.current.delete(job.id); toast(job.status === "completed" ? t("admin.actionCompleted") : `${t("mounts.operationFailed")}: ${job.error}`, job.status === "failed" ? "error" : "ok", "admin"); notifyNetworkMountsChanged(); });
    if (finished.length > 0 && trackedJobs.current.size === 0) stopWatchingNetworkMountChanges();
  }, [mounts, t, toast]);
  const visibleMounts = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const filtered = mounts.filter((mount) => {
      const matchesQuery = !needle || [mount.name, mount.host, mount.remote, mount.mount_point].some((value) => value.toLocaleLowerCase().includes(needle));
      const matchesStatus = statusFilter === "all" || statusFilter === "mounted" && mount.actual_mounted || statusFilter === "unmounted" && !mount.actual_mounted || statusFilter === "attention" && needsAttention(mount) || statusFilter === "busy" && isBusy(mount);
      return matchesQuery && matchesStatus && (protocolFilter === "all" || mount.type === protocolFilter);
    });
    return filtered.sort((left, right) => sort === "name-asc" ? left.name.localeCompare(right.name) : sort === "name-desc" ? right.name.localeCompare(left.name) : sort === "status" ? left.status.localeCompare(right.status) || left.name.localeCompare(right.name) : (right.last_operation_at || 0) - (left.last_operation_at || 0));
  }, [mounts, protocolFilter, query, sort, statusFilter]);
  if (!isAdmin) return null;
  async function runAction() {
    if (!actionDialog) return;
    const { mount, action } = actionDialog;
    try {
      if (action === "delete") await api.deleteMount(mount.id);
      else {
        const result = await api.mountAction(mount.id, action);
        if (result.job) { trackedJobs.current.add(result.job.id); if (action !== "test") watchNetworkMountChanges(); }
      }
    } finally { await refresh(); }
    setActionDialog(null);
    if (action === "delete") notifyNetworkMountsChanged();
  }
  function showLogs(mount: NetworkMount) { void api.mountLogs(mount.id).then((value) => setLogs({ name: mount.name, lines: value.lines })).catch((reason: unknown) => toast(reason instanceof Error ? reason.message : t("error.generic"), "error", "admin")); }
  function resetFilters() { setQuery(""); setStatusFilter("all"); setProtocolFilter("all"); setSort("name-asc"); }
  const filtered = Boolean(query || statusFilter !== "all" || protocolFilter !== "all");
  return <section className="network-mounts-settings" aria-label={t("settings.networkResources")} aria-busy={loading}>
    <NetworkMountsHeader loading={loading} t={t} onRefresh={() => void refresh()} onCreate={() => setEditing("new")} />
    <NetworkMountsSummary mounts={mounts} t={t} />
    <NetworkMountsToolbar query={query} status={statusFilter} protocol={protocolFilter} sort={sort} count={visibleMounts.length} t={t} onQuery={setQuery} onStatus={setStatusFilter} onProtocol={setProtocolFilter} onSort={setSort} />
    <div className="network-mounts-live" aria-live="polite">{loading ? t("mounts.refreshing") : t("mounts.resultsCount").replace("{count}", String(visibleMounts.length))}</div>
    {error && <p className="error-state" role="alert">{error}</p>}
    {!loading && mounts.length === 0 ? <NetworkMountEmptyState filtered={false} t={t} onCreate={() => setEditing("new")} onReset={resetFilters} /> : !loading && visibleMounts.length === 0 ? <NetworkMountEmptyState filtered={filtered} t={t} onCreate={() => setEditing("new")} onReset={resetFilters} /> : <div className="mount-card-grid">{visibleMounts.map((mount) => <NetworkMountCard key={mount.id} mount={mount} t={t} toast={toast} onEdit={() => setEditing(mount)} onAction={(action) => setActionDialog({ mount, action })} onLogs={() => showLogs(mount)} />)}</div>}
    {editing && <MountForm mount={editing === "new" ? undefined : editing} t={t} onClose={() => setEditing(null)} onSaved={refresh} />}
    {actionDialog && <AdminActionDialog title={`${t(`mounts.${actionDialog.action}`)}: ${actionDialog.mount.name}`} fields={[]} danger={["delete", "unmount", "remount", "migrate"].includes(actionDialog.action)} t={t} onClose={() => setActionDialog(null)} onSubmit={runAction} />}
    {logs && <Modal wide title={`${t("mounts.logs")}: ${logs.name}`} closeLabel={t("action.close")} onClose={() => setLogs(null)} footer={<button onClick={() => setLogs(null)}>{t("action.close")}</button>}><pre className="log-view">{logs.lines.join("\n") || t("mounts.noLogs")}</pre></Modal>}
  </section>;
}
