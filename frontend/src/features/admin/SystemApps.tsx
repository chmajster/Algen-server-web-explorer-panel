import { Lock, PackagePlus, Play, Plus, Power, RefreshCw, RotateCcw, Square, Trash2, Unlock } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type AdminGroup, type AdminUser, type SambaConfig, type SambaShare, type SambaStatus, type StoreApp, type SystemdService } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { NetworkMountsSettingsSection } from "../mounts/NetworkMountsSettingsSection";
import { AdminActionDialog, type AdminField } from "./AdminActionDialog";

type Dialog = { title: string; fields: AdminField[]; danger?: boolean; submit: (values: Record<string, string>) => Promise<void> } | null;

function Shell({ title, subtitle, loading, t, onRefresh, actions, children }: { title: string; subtitle: string; loading: boolean; t: Translate; onRefresh: () => void; actions?: React.ReactNode; children: React.ReactNode }) {
  return <section className="system-app"><header className="feature-header"><div><h2>{title}</h2><p>{subtitle}</p></div><div className="header-actions">{actions}<button onClick={onRefresh}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button></div></header>{children}</section>;
}

function useLoader<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null); const [loading, setLoading] = useState(false); const [error, setError] = useState("");
  const refresh = async () => { setLoading(true); setError(""); try { setData(await load()); } catch (reason) { setError(reason instanceof Error ? reason.message : "Error"); } finally { setLoading(false); } };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- each window owns one initial request
  useEffect(() => { void refresh(); }, []);
  return { data, loading, error, refresh };
}

async function perform(action: () => Promise<unknown>, refresh: () => Promise<void>, toast: ToastFn, t: Translate) { await action(); toast(t("admin.actionCompleted"), "ok", "admin"); await refresh(); }

export function UsersApp({ t, toast }: { t: Translate; toast: ToastFn }) {
  const state = useLoader<AdminUser[]>(api.adminUsers); const [dialog, setDialog] = useState<Dialog>(null);
  const simple = (user: AdminUser, action: "lock" | "unlock" | "delete") => setDialog({ title: `${t(`action.${action}`)}: ${user.username}`, fields: [], danger: action === "delete", submit: () => perform(() => action === "lock" ? api.lockUser(user.username) : action === "unlock" ? api.unlockUser(user.username) : api.deleteUser(user.username), state.refresh, toast, t) });
  const create = () => setDialog({ title: t("users.create"), fields: [{ name: "username", label: t("settings.username"), required: true }, { name: "password", label: t("settings.newPassword"), type: "password", required: true }, { name: "groups", label: t("settings.groupsLabel") }], submit: (values) => perform(() => api.createUser({ username: values.username, password: values.password, groups: values.groups.split(",").map((value) => value.trim()).filter(Boolean), create_home: true }), state.refresh, toast, t) });
  return <Shell title={t("app.users")} subtitle={t("users.subtitle")} loading={state.loading} t={t} onRefresh={state.refresh} actions={<button onClick={create}><Plus />{t("users.create")}</button>}><DataState state={state} t={t}>{state.data?.map((user) => <article className="data-row" key={user.username}><strong>{user.username}</strong><span>UID {user.uid}</span><span>{user.home}</span><span>{user.groups.join(", ")}</span><div className="data-actions"><button title={t("action.lock")} onClick={() => simple(user, "lock")}><Lock /></button><button title={t("action.unlock")} onClick={() => simple(user, "unlock")}><Unlock /></button><button title={t("users.password")} onClick={() => setDialog({ title: `${t("users.password")}: ${user.username}`, fields: [{ name: "new_password", label: t("settings.newPassword"), type: "password", required: true }], submit: (values) => perform(() => api.changeUserPassword(user.username, { new_password: values.new_password }), state.refresh, toast, t) })}><RotateCcw /></button><button className="danger" title={t("action.delete")} onClick={() => simple(user, "delete")}><Trash2 /></button></div></article>)}</DataState>{dialog && <AdminActionDialog {...dialog} t={t} onClose={() => setDialog(null)} onSubmit={dialog.submit} />}</Shell>;
}

export function GroupsApp({ t, toast }: { t: Translate; toast: ToastFn }) {
  const state = useLoader<AdminGroup[]>(api.adminGroups); const [dialog, setDialog] = useState<Dialog>(null);
  const create = () => setDialog({ title: t("groups.create"), fields: [{ name: "groupname", label: t("settings.groupName"), required: true }], submit: (values) => perform(() => api.createGroup({ groupname: values.groupname }), state.refresh, toast, t) });
  return <Shell title={t("app.groups")} subtitle={t("groups.subtitle")} loading={state.loading} t={t} onRefresh={state.refresh} actions={<button onClick={create}><Plus />{t("groups.create")}</button>}><DataState state={state} t={t}>{state.data?.map((group) => <article className="data-row" key={group.name}><strong>{group.name}</strong><span>GID {group.gid}</span><span>{group.members.join(", ") || "—"}</span><div className="data-actions"><button title={t("groups.addMember")} onClick={() => setDialog({ title: `${t("groups.addMember")}: ${group.name}`, fields: [{ name: "username", label: t("settings.username"), required: true }], submit: (values) => perform(() => api.addGroupMember(group.name, { username: values.username }), state.refresh, toast, t) })}><Plus /></button><button title={t("groups.removeMember")} onClick={() => setDialog({ title: `${t("groups.removeMember")}: ${group.name}`, fields: [{ name: "username", label: t("settings.username"), required: true }], danger: true, submit: (values) => perform(() => api.removeGroupMember(group.name, values.username), state.refresh, toast, t) })}><Unlock /></button><button className="danger" title={t("action.delete")} onClick={() => setDialog({ title: `${t("action.delete")}: ${group.name}`, fields: [], danger: true, submit: () => perform(() => api.deleteGroup(group.name), state.refresh, toast, t) })}><Trash2 /></button></div></article>)}</DataState>{dialog && <AdminActionDialog {...dialog} t={t} onClose={() => setDialog(null)} onSubmit={dialog.submit} />}</Shell>;
}

export function MountsApp({ t, toast }: { t: Translate; toast: ToastFn }) {
  return <section className="system-app"><NetworkMountsSettingsSection isAdmin t={t} toast={toast} /></section>;
}

export function ServicesApp({ t, toast }: { t: Translate; toast: ToastFn }) {
  const state = useLoader<SystemdService[]>(api.systemdServices); const [dialog, setDialog] = useState<Dialog>(null);
  const action = (service: SystemdService, name: "start" | "stop" | "restart" | "enable" | "disable") => setDialog({ title: `${t(`services.${name}`)}: ${service.name}`, fields: [], danger: name === "stop" || name === "restart", submit: () => perform(() => api.systemdServiceAction(service.name, name, name === "restart"), state.refresh, toast, t) });
  return <Shell title={t("app.services")} subtitle={t("services.subtitle")} loading={state.loading} t={t} onRefresh={state.refresh}><DataState state={state} t={t}>{state.data?.map((service) => <article className="data-row" key={service.name}><strong>{service.name}</strong><span className={`status-badge ${service.status === "active" ? "completed" : "failed"}`}>{service.status}</span><span>{service.enabled}</span><div className="data-actions"><button title={t("services.start")} onClick={() => action(service, "start")}><Play /></button><button title={t("services.stop")} onClick={() => action(service, "stop")}><Square /></button><button title={t("services.restart")} onClick={() => action(service, "restart")}><RotateCcw /></button><button title={service.enabled === "enabled" ? t("services.disable") : t("services.enable")} onClick={() => action(service, service.enabled === "enabled" ? "disable" : "enable")}><Power /></button></div></article>)}</DataState>{dialog && <AdminActionDialog {...dialog} t={t} onClose={() => setDialog(null)} onSubmit={dialog.submit} />}</Shell>;
}

export function StoreAppView({ t, toast }: { t: Translate; toast: ToastFn }) {
  const state = useLoader<StoreApp[]>(api.apps); const [dialog, setDialog] = useState<Dialog>(null);
  const trackedJobs = useRef(new Set<string>()); const notifiedJobs = useRef(new Set<string>());
  const activeJobKey = state.data?.flatMap((app) => app.jobs).filter((job) => ["queued", "running"].includes(job.status)).map((job) => `${job.id}:${job.status}`).join("|") || "";
  useEffect(() => {
    if (!activeJobKey) return;
    const timer = window.setInterval(() => void state.refresh(), 1200);
    return () => window.clearInterval(timer);
    // Polling intentionally uses the loader owned by this app window.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeJobKey]);
  useEffect(() => {
    state.data?.flatMap((app) => app.jobs).filter((job) => job.status === "failed" && trackedJobs.current.has(job.id) && !notifiedJobs.current.has(job.id)).forEach((job) => {
      notifiedJobs.current.add(job.id);
      toast(`${t("store.installationFailed")}: ${job.error || job.log_tail[job.log_tail.length - 1]?.line || t("error.generic")}`, "error", "admin");
    });
  }, [state.data, t, toast]);
  const action = (app: StoreApp, name: "install" | "uninstall" | "update" | "start" | "stop" | "restart") => setDialog({ title: `${t(`store.${name}`)}: ${app.manifest.name}`, fields: [], danger: ["uninstall", "stop", "restart"].includes(name), submit: async () => {
    const result = await api.appAction(app.id, name);
    if (result.job) trackedJobs.current.add(result.job.id);
    toast(result.job ? t("store.actionQueued") : t("admin.actionCompleted"), "ok", "admin");
    await state.refresh();
  } });
  return <Shell title={t("app.store")} subtitle={t("store.subtitle")} loading={state.loading} t={t} onRefresh={state.refresh}><DataState state={state} t={t}><div className="card-grid">{state.data?.map((app) => { const job = app.jobs[app.jobs.length - 1]; const showJob = job && (["queued", "running", "failed"].includes(job.status)); return <article className="data-card" key={app.id}><header><strong>{app.manifest.name}</strong><span className={`status-badge ${app.status}`}>{app.manifest.version} · {app.status}</span></header><p>{app.manifest.description}</p>{showJob && <div className={`app-job-state ${job.status}`} role={job.status === "failed" ? "alert" : "status"}><header><strong>{job.status === "failed" ? t("store.installationFailed") : t("store.operationInProgress")}</strong><span>{t(`task.${job.status}`)} · {job.progress}%</span></header><div className="progress-track"><span style={{ width: `${job.progress}%` }} /></div>{job.error && <p>{job.error}</p>}{job.log_tail.length > 0 && <pre>{job.log_tail.slice(-8).map((entry) => entry.line).join("\n")}</pre>}</div>}<div className="data-actions"><button disabled={Boolean(job && ["queued", "running"].includes(job.status))} onClick={() => action(app, app.state.installed ? "update" : "install")}><PackagePlus />{t(app.state.installed ? "store.update" : "store.install")}</button>{app.state.installed && <><button onClick={() => action(app, "start")}>{t("store.start")}</button><button onClick={() => action(app, "stop")}>{t("store.stop")}</button><button className="danger" onClick={() => action(app, "uninstall")}>{t("store.uninstall")}</button></>}</div></article>; })}</div></DataState>{dialog && <AdminActionDialog {...dialog} t={t} onClose={() => setDialog(null)} onSubmit={dialog.submit} />}</Shell>;
}

export function SambaAppView({ t, toast }: { t: Translate; toast: ToastFn }) {
  const state = useLoader<SambaStatus>(api.sambaStatus); const [dialog, setDialog] = useState<Dialog>(null);
  const service = (action: "start" | "stop" | "restart" | "reload") => setDialog({ title: t(`samba.${action}`), fields: [], danger: action === "stop" || action === "restart", submit: () => perform(() => api.sambaService(action), state.refresh, toast, t) });
  async function saveShares(config: SambaConfig) { await api.saveSambaConfig(config); toast(t("store.actionQueued"), "ok", "admin"); await state.refresh(); }
  async function removeShare(name: string) { const config = await api.appConfig("samba"); await saveShares({ ...config, shares: config.shares.filter((share) => share.name !== name) }); }
  function editShare(share?: SambaShare) { setDialog({ title: share ? t("samba.editShare") : t("samba.addShare"), fields: [{ name: "name", label: t("samba.shareName"), value: share?.name, required: true }, { name: "path", label: t("files.fullPath"), value: share?.path, required: true }, { name: "comment", label: t("samba.comment"), value: share?.comment }, { name: "valid_users", label: t("samba.validUsers"), value: share?.valid_users.join(", ") }], submit: async (values) => { const config = await api.appConfig("samba"); const nextShare: SambaShare = { name: values.name, path: values.path, comment: values.comment, enabled: true, browseable: share?.browseable ?? true, read_only: share?.read_only ?? false, guest_ok: share?.guest_ok ?? false, valid_users: values.valid_users.split(",").map((value) => value.trim()).filter(Boolean), create_mask: share?.create_mask || "0664", directory_mask: share?.directory_mask || "0775" }; await saveShares({ ...config, shares: [...config.shares.filter((item) => item.name !== (share?.name || values.name)), nextShare] }); } }); }
  return <Shell title={t("app.samba")} subtitle={t("samba.subtitle")} loading={state.loading} t={t} onRefresh={state.refresh} actions={<><button onClick={() => editShare()}><Plus />{t("samba.addShare")}</button><button onClick={() => service("start")}><Play />{t("samba.start")}</button><button onClick={() => service("stop")}><Square />{t("samba.stop")}</button><button onClick={() => service("restart")}><RotateCcw />{t("samba.restart")}</button></>}><DataState state={state} t={t}><div className="summary-grid"><article><span>{t("samba.installed")}</span><strong>{state.data?.installed ? t("common.yes") : t("common.no")}</strong></article><article><span>{t("samba.shares")}</span><strong>{state.data?.shares.length || 0}</strong></article></div>{state.data?.shares.map((share) => <article className="data-row" key={share.name}><strong>{share.name}</strong><code>{share.path}</code><span className={`status-badge ${share.enabled ? "completed" : "cancelled"}`}>{share.enabled ? t("common.enabled") : t("common.disabled")}</span><div className="data-actions"><button onClick={() => editShare(share)}>{t("action.edit")}</button><button className="danger" onClick={() => setDialog({ title: `${t("action.delete")}: ${share.name}`, fields: [], danger: true, submit: () => removeShare(share.name) })}><Trash2 /></button></div></article>)}</DataState>{dialog && <AdminActionDialog {...dialog} t={t} onClose={() => setDialog(null)} onSubmit={dialog.submit} />}</Shell>;
}

export { MonitorApp } from "./MonitorApp";
function DataState<T>({ state, t, children }: { state: { data: T | null; loading: boolean; error: string }; t: Translate; children: React.ReactNode }) { if (state.loading && !state.data) return <div className="loading-state">{t("status.loading")}</div>; if (state.error) return <div className="error-state">{state.error}</div>; return <div className="data-list">{children}</div>; }
export { SettingsAppView, isSettingsCategory } from "../settings/SettingsApp";
