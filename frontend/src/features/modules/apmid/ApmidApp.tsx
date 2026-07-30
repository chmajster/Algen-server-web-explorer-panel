import { Pencil, Plus, RefreshCw, Search, Trash2, UserPlus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError, api, type AdminUser, type ApmidDashboard, type ApmidHistory, type ApmidItem,
  type ApmidMember, type ApmidResourcePermission, type ApmidRole, type ModuleStatus,
} from "../../../api";
import type { ToastFn, Translate } from "../../../app/types";
import { Modal } from "../../../components/Modal";
import { useRefreshOnConnectionRestored } from "../../connection/ConnectionStatusMonitor";
import { ModuleAppShell, ModuleHealthCard, type ModuleSection } from "../common/ModuleAppShell";

const status: ModuleStatus = {
  installed: true, update_available: false, service_state: "not_applicable", service_enabled: false,
  services: {}, health: "healthy", health_message: "", last_action: "", last_action_status: "",
  last_error: "", metrics: {}, package_version: "1.0.0",
};
const resourcePermissions: ApmidResourcePermission[] = ["view", "update", "members.view", "members.manage", "permissions.view", "permissions.manage", "audit.view", "delete"];
const roles: ApmidRole[] = ["viewer", "operator", "manager", "owner"];

export function ApmidApp({ permissions, t, toast }: { permissions: string[]; t: Translate; toast: ToastFn }) {
  const [section, setSection] = useState<ModuleSection>("overview");
  const [dashboard, setDashboard] = useState<ApmidDashboard | null>(null);
  const [items, setItems] = useState<ApmidItem[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<ApmidItem | null | undefined>();
  const [selected, setSelected] = useState<ApmidItem | null>(null);
  const [history, setHistory] = useState<ApmidHistory[]>([]);
  const canCreate = permissions.includes("apmid.create");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [summary, listing] = await Promise.all([
        api.apmidDashboard(),
        api.apmidItems({ search, status: filter, sort: "code", direction: "asc" }),
      ]);
      setDashboard(summary); setItems(listing.items); setTotal(listing.total);
    } catch (error) {
      toast(message(error, t), "error", "admin", "apmid");
    } finally {
      setLoading(false);
    }
  }, [filter, search, t, toast]);
  useEffect(() => { const timer = window.setTimeout(() => void refresh(), 200); return () => window.clearTimeout(timer); }, [refresh]);
  useEffect(() => { if (section === "audit") void api.apmidHistory().then(setHistory).catch((error: unknown) => toast(message(error, t), "error")); }, [section, t, toast]);
  useRefreshOnConnectionRestored(() => { void refresh(); });

  let content: React.ReactNode;
  if (section === "overview") content = <Dashboard value={dashboard} t={t} />;
  else if (section === "audit") content = <History items={history} t={t} />;
  else content = <section className="apmid-panel">
    <header className="apmid-toolbar">
      <label><Search /><input aria-label={t("action.search")} value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("apmid.search")} /></label>
      <select aria-label={t("apmid.filter.status")} value={filter} onChange={(event) => setFilter(event.target.value)}>
        <option value="">{t("apmid.filter.all")}</option><option value="active">{t("common.enabled")}</option><option value="inactive">{t("common.disabled")}</option>
      </select>
      <span>{t("apmid.total").replace("{count}", String(total))}</span>
      <button type="button" onClick={() => void refresh()}><RefreshCw />{t("action.refresh")}</button>
      {canCreate && <button className="button-primary" type="button" onClick={() => setEditing(null)}><Plus />{t("apmid.create")}</button>}
    </header>
    {loading ? <div className="loading-state">{t("status.loading")}</div> : items.length ? <div className="module-table-wrap"><table>
      <thead><tr><th>{t("apmid.code")}</th><th>{t("common.name")}</th><th>{t("common.status")}</th><th>{t("apmid.businessOwner")}</th><th>{t("apmid.members")}</th><th>{t("apmid.relations")}</th><th>{t("apmid.updated")}</th><th>{t("column.actions")}</th></tr></thead>
      <tbody>{items.map((item) => <tr key={item.id}>
        <td><button className="apmid-code-link" onClick={() => setSelected(item)}>{item.code}</button></td>
        <td>{item.name}</td><td><span className={`apmid-state ${item.active ? "active" : "inactive"}`}>{t(item.active ? "common.enabled" : "common.disabled")}</span></td>
        <td>{item.business_owner || t("common.none")}</td><td>{item.member_count}</td><td>{item.related_count || 0}</td>
        <td>{new Date(item.updated_at * 1000).toLocaleString()}</td>
        <td><div className="module-row-actions"><button onClick={() => setSelected(item)}>{t("action.open")}</button>{permissions.includes("apmid.update") && <button onClick={() => setEditing(item)}><Pencil />{t("action.edit")}</button>}</div></td>
      </tr>)}</tbody>
    </table></div> : <div className="empty-state">{t("apmid.empty")}</div>}
  </section>;
  return <ModuleAppShell className="apmid-app" name={t("apmid.name")} status={status} healthMessage={t("apmid.description")} section={section} sections={["overview", "apmid", ...(permissions.includes("apmid.audit.view") ? ["audit" as const] : [])]} t={t} onSection={setSection} actions={<button onClick={() => void refresh()}><RefreshCw />{t("action.refresh")}</button>}>{content}
    {editing !== undefined && <ItemEditor item={editing} t={t} toast={toast} onClose={() => setEditing(undefined)} onSaved={async () => { setEditing(undefined); await refresh(); }} />}
    {selected && <ApmidDetail itemId={selected.id} t={t} toast={toast} onClose={() => setSelected(null)} onChanged={refresh} />}
  </ModuleAppShell>;
}

function Dashboard({ value, t }: { value: ApmidDashboard | null; t: Translate }) {
  if (!value) return <div className="loading-state">{t("status.loading")}</div>;
  return <><div className="module-health-grid">
    <ModuleHealthCard title={t("apmid.dashboard.total")} value={value.total} />
    <ModuleHealthCard title={t("apmid.dashboard.active")} value={value.active} tone="success" />
    <ModuleHealthCard title={t("apmid.dashboard.members")} value={value.members} />
    <ModuleHealthCard title={t("apmid.dashboard.withoutOwner")} value={value.without_owner} tone={value.without_owner ? "warning" : "success"} />
  </div><section className="apmid-panel"><h3>{t("apmid.dashboard.recent")}</h3><History items={value.recent} t={t} /></section></>;
}

function ItemEditor({ item, t, toast, onClose, onSaved }: { item: ApmidItem | null; t: Translate; toast: ToastFn; onClose: () => void; onSaved: () => void }) {
  const [code, setCode] = useState(item?.code || "");
  const [name, setName] = useState(item?.name || "");
  const [description, setDescription] = useState(item?.description || "");
  const [businessOwner, setBusinessOwner] = useState(item?.business_owner || "");
  const [active, setActive] = useState(item?.active ?? true);
  const [saving, setSaving] = useState(false);
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setSaving(true);
    try {
      await api.saveApmidItem({ code, name, description, active, business_owner: businessOwner || null }, item?.id);
      toast(t("apmid.saved"), "ok"); onSaved();
    } catch (error) { toast(message(error, t), "error"); } finally { setSaving(false); }
  }
  return <Modal title={t(item ? "apmid.edit" : "apmid.create")} closeLabel={t("action.close")} onClose={onClose} footer={<><button onClick={onClose}>{t("action.cancel")}</button><button className="button-primary" type="submit" form="apmid-editor" disabled={saving}>{t("action.save")}</button></>}>
    <form id="apmid-editor" className="module-form-grid" onSubmit={submit}>
      <label>{t("apmid.code")}<input autoFocus required maxLength={64} pattern="[A-Za-z0-9_-]+" value={code} onChange={(event) => setCode(event.target.value.toUpperCase())} /></label>
      <label>{t("common.name")}<input required maxLength={160} value={name} onChange={(event) => setName(event.target.value)} /></label>
      <label>{t("apmid.businessOwner")}<input maxLength={160} value={businessOwner} onChange={(event) => setBusinessOwner(event.target.value)} /></label>
      <label className="check"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />{t("common.enabled")}</label>
      <label className="wide">{t("apmid.descriptionField")}<textarea maxLength={4000} value={description} onChange={(event) => setDescription(event.target.value)} /></label>
    </form>
  </Modal>;
}

type DetailTab = "info" | "members" | "permissions" | "relations" | "history";
function ApmidDetail({ itemId, t, toast, onClose, onChanged }: { itemId: string; t: Translate; toast: ToastFn; onClose: () => void; onChanged: () => Promise<void> }) {
  const [item, setItem] = useState<ApmidItem | null>(null);
  const [members, setMembers] = useState<ApmidMember[]>([]);
  const [history, setHistory] = useState<ApmidHistory[]>([]);
  const [tab, setTab] = useState<DetailTab>("info");
  const [adding, setAdding] = useState(false);
  const effective = new Set(item?.effective_permissions?.effective || []);
  const refresh = useCallback(async () => {
    const next = await api.apmidItem(itemId); setItem(next);
    const allowed = new Set(next.effective_permissions?.effective || []);
    if (allowed.has("members.view")) setMembers(await api.apmidMembers(itemId));
    if (allowed.has("audit.view")) setHistory(await api.apmidItemHistory(itemId));
  }, [itemId]);
  useEffect(() => { void refresh().catch((error: unknown) => toast(message(error, t), "error")); }, [refresh, t, toast]);
  async function remove() {
    if (!item || !window.confirm(t("apmid.deleteConfirm").replace("{code}", item.code))) return;
    try { await api.deleteApmidItem(item.id); await onChanged(); onClose(); } catch (error) { toast(message(error, t), "error"); }
  }
  if (!item) return <Modal wide title={t("apmid.details")} closeLabel={t("action.close")} onClose={onClose}><div className="loading-state">{t("status.loading")}</div></Modal>;
  const tabs: DetailTab[] = ["info", ...(effective.has("members.view") ? ["members" as const] : []), ...(effective.has("permissions.view") ? ["permissions" as const] : []), "relations", ...(effective.has("audit.view") ? ["history" as const] : [])];
  return <Modal wide title={`${item.code} — ${item.name}`} closeLabel={t("action.close")} onClose={onClose} footer={<><span />{effective.has("delete") && <button className="button-danger" onClick={() => void remove()}><Trash2 />{t("action.delete")}</button>}<button onClick={onClose}>{t("action.close")}</button></>}>
    <div className="apmid-detail">
      <nav>{tabs.map((value) => <button key={value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>{t(`apmid.tab.${value}`)}</button>)}</nav>
      {tab === "info" && <dl className="apmid-info"><dt>{t("apmid.code")}</dt><dd>{item.code}</dd><dt>{t("common.name")}</dt><dd>{item.name}</dd><dt>{t("common.status")}</dt><dd>{t(item.active ? "common.enabled" : "common.disabled")}</dd><dt>{t("apmid.businessOwner")}</dt><dd>{item.business_owner || t("common.none")}</dd><dt>{t("apmid.descriptionField")}</dt><dd>{item.description || t("common.none")}</dd><dt>{t("apmid.created")}</dt><dd>{new Date(item.created_at * 1000).toLocaleString()} · {item.created_by}</dd><dt>{t("apmid.updated")}</dt><dd>{new Date(item.updated_at * 1000).toLocaleString()} · {item.updated_by}</dd></dl>}
      {tab === "members" && <Members itemId={itemId} values={members} canManage={effective.has("members.manage")} t={t} toast={toast} onRefresh={async () => { await refresh(); await onChanged(); }} onAdd={() => setAdding(true)} />}
      {tab === "permissions" && <Permissions itemId={itemId} values={members} canManage={effective.has("permissions.manage")} t={t} toast={toast} onRefresh={refresh} />}
      {tab === "relations" && <div className="empty-state">{t("apmid.relationsHint")}</div>}
      {tab === "history" && <History items={history} t={t} />}
    </div>
    {adding && <AddMembers itemId={itemId} existing={new Set(members.map((member) => member.username))} t={t} toast={toast} onClose={() => setAdding(false)} onSaved={async () => { setAdding(false); await refresh(); await onChanged(); }} />}
  </Modal>;
}

function Members({ itemId, values, canManage, t, toast, onRefresh, onAdd }: { itemId: string; values: ApmidMember[]; canManage: boolean; t: Translate; toast: ToastFn; onRefresh: () => Promise<void>; onAdd: () => void }) {
  const [query, setQuery] = useState(""); const [role, setRole] = useState("");
  const visible = values.filter((item) => (!query || item.username.toLowerCase().includes(query.toLowerCase())) && (!role || item.role === role));
  async function change(member: ApmidMember, next: ApmidRole) { try { await api.updateApmidMember(itemId, member.username, next); await onRefresh(); } catch (error) { toast(message(error, t), "error"); } }
  async function remove(member: ApmidMember) { if (!window.confirm(t("apmid.member.removeConfirm").replace("{username}", member.username))) return; try { await api.deleteApmidMember(itemId, member.username); await onRefresh(); } catch (error) { toast(message(error, t), "error"); } }
  return <section><header className="apmid-toolbar"><label><Search /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("apmid.member.search")} /></label><select value={role} onChange={(event) => setRole(event.target.value)}><option value="">{t("apmid.filter.all")}</option>{roles.map((value) => <option key={value} value={value}>{t(`apmid.role.${value}`)}</option>)}</select>{canManage && <button className="button-primary" onClick={onAdd}><UserPlus />{t("apmid.member.add")}</button>}</header>
    <div className="module-table-wrap"><table><thead><tr><th>{t("apmid.member.user")}</th><th>{t("apmid.member.role")}</th><th>{t("apmid.member.assigned")}</th><th>{t("apmid.member.assignedBy")}</th><th>{t("column.actions")}</th></tr></thead><tbody>{visible.map((member) => <tr key={member.username}><td>{member.username}</td><td>{canManage ? <select value={member.role} onChange={(event) => void change(member, event.target.value as ApmidRole)}>{roles.map((value) => <option key={value} value={value}>{t(`apmid.role.${value}`)}</option>)}</select> : t(`apmid.role.${member.role}`)}</td><td>{new Date(member.assigned_at * 1000).toLocaleString()}</td><td>{member.assigned_by}</td><td>{canManage && <button className="button-danger" onClick={() => void remove(member)}>{t("action.delete")}</button>}</td></tr>)}</tbody></table></div>
  </section>;
}

function AddMembers({ itemId, existing, t, toast, onClose, onSaved }: { itemId: string; existing: Set<string>; t: Translate; toast: ToastFn; onClose: () => void; onSaved: () => Promise<void> }) {
  const [users, setUsers] = useState<AdminUser[]>([]); const [selected, setSelected] = useState<string[]>([]); const [role, setRole] = useState<ApmidRole>("viewer"); const [search, setSearch] = useState("");
  useEffect(() => { const timer = window.setTimeout(() => void api.apmidUsers(search).then((items) => setUsers(items.filter((item) => !existing.has(item.username)))).catch((error: unknown) => toast(message(error, t), "error")), 150); return () => window.clearTimeout(timer); }, [existing, search, t, toast]);
  async function submit(event: React.FormEvent) { event.preventDefault(); try { await api.addApmidMembers(itemId, selected, role); await onSaved(); } catch (error) { toast(message(error, t), "error"); } }
  return <Modal title={t("apmid.member.add")} closeLabel={t("action.close")} onClose={onClose} footer={<><button onClick={onClose}>{t("action.cancel")}</button><button form="apmid-add-members" type="submit" className="button-primary" disabled={!selected.length}>{t("action.add")}</button></>}>
    <form id="apmid-add-members" onSubmit={submit} className="apmid-member-picker"><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("apmid.member.search")} /><label>{t("apmid.member.role")}<select value={role} onChange={(event) => setRole(event.target.value as ApmidRole)}>{roles.map((value) => <option key={value} value={value}>{t(`apmid.role.${value}`)}</option>)}</select></label><div>{users.map((user) => <label key={user.username}><input type="checkbox" checked={selected.includes(user.username)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, user.username] : current.filter((value) => value !== user.username))} />{user.username}</label>)}</div></form>
  </Modal>;
}

function Permissions({ itemId, values, canManage, t, toast, onRefresh }: { itemId: string; values: ApmidMember[]; canManage: boolean; t: Translate; toast: ToastFn; onRefresh: () => Promise<void> }) {
  async function change(member: ApmidMember, permission: ApmidResourcePermission, effect: string) {
    const allow = member.permissions.allow.filter((value) => value !== permission); const deny = member.permissions.deny.filter((value) => value !== permission);
    if (effect === "allow") allow.push(permission); if (effect === "deny") deny.push(permission);
    try { await api.updateApmidPermissions(itemId, member.username, allow, deny); await onRefresh(); } catch (error) { toast(message(error, t), "error"); }
  }
  return <div className="module-table-wrap apmid-permissions"><table><thead><tr><th>{t("apmid.member.user")}</th>{resourcePermissions.map((permission) => <th key={permission}>{t(`apmid.permission.${permission}`)}</th>)}<th>{t("column.actions")}</th></tr></thead><tbody>{values.map((member) => <tr key={member.username}><td><strong>{member.username}</strong><small>{t(`apmid.role.${member.role}`)}</small></td>{resourcePermissions.map((permission) => <td key={permission}><select disabled={!canManage} aria-label={`${member.username} ${permission}`} value={member.permissions.deny.includes(permission) ? "deny" : member.permissions.allow.includes(permission) ? "allow" : "role"} onChange={(event) => void change(member, permission, event.target.value)}><option value="role">{t("apmid.permission.roleDefault")}</option><option value="allow">{t("apmid.permission.allow")}</option><option value="deny">{t("apmid.permission.deny")}</option></select><small>{t("apmid.permission.source").replace("{source}", member.permissions.sources[permission])}</small></td>)}<td>{canManage && <button onClick={() => void api.resetApmidPermissions(itemId, member.username).then(onRefresh).catch((error: unknown) => toast(message(error, t), "error"))}>{t("apmid.permission.reset")}</button>}</td></tr>)}</tbody></table></div>;
}

function History({ items, t }: { items: ApmidHistory[]; t: Translate }) {
  return items.length ? <div className="module-table-wrap"><table><thead><tr><th>{t("apmid.history.date")}</th><th>{t("apmid.history.action")}</th><th>{t("apmid.history.actor")}</th><th>{t("apmid.history.target")}</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{new Date(item.created_at * 1000).toLocaleString()}</td><td>{t(`apmid.history.${item.action}`)}</td><td>{item.actor}</td><td>{item.target || "—"}</td></tr>)}</tbody></table></div> : <div className="empty-state">{t("apmid.history.empty")}</div>;
}

function message(error: unknown, t: Translate): string {
  if (error instanceof ApiError && error.code) {
    const key = `apmid.error.${error.code}`;
    const translated = t(key);
    if (translated !== key) return translated;
  }
  return error instanceof Error ? error.message : t("error.generic");
}
