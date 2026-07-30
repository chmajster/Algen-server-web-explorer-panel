import { History, KeyRound, Lock, Plus, RefreshCw, Search, ShieldCheck, Trash2, Unlock, UserCog, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type IdentityGroup, type IdentityHistory, type IdentityRoles, type IdentityUser, type PermissionMetadata, type RbacRole } from "../../api";
import type { ToastFn, Translate } from "../../app/types";
import { useRefreshOnConnectionRestored } from "../connection/ConnectionStatusMonitor";
import { AdminActionDialog, type AdminField } from "./AdminActionDialog";

type Tab = "users" | "groups" | "roles" | "history";
type Dialog = { title: string; fields: AdminField[]; danger?: boolean; submit: (values: Record<string, string>) => Promise<void> } | null;
type PolicyState = { allow: string[]; deny: string[] };
export type PolicySubject = { type: "user" | "group"; id: string };

const roleValues: RbacRole[] = ["admin", "operator", "auditor", "user"];
const splitNames = (value: string): string[] => [...new Set(value.split(",").map((item) => item.trim()).filter(Boolean))];
const optionalNumber = (value: string): number | null => value.trim() ? Number(value) : null;

export function IdentityApp({ permissions, initialTab = "users", embedded = false, t, toast, onOpenPolicies }: { permissions: string[]; initialTab?: Tab; embedded?: boolean; t: Translate; toast: ToastFn; onOpenPolicies?: (subject: PolicySubject) => void }) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [users, setUsers] = useState<IdentityUser[]>([]);
  const [groups, setGroups] = useState<IdentityGroup[]>([]);
  const [roles, setRoles] = useState<IdentityRoles | null>(null);
  const [history, setHistory] = useState<IdentityHistory[]>([]);
  const [selectedUser, setSelectedUser] = useState<IdentityUser | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<IdentityGroup | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [includeSystem, setIncludeSystem] = useState(false);

  const can = useCallback((permission: string) => permissions.includes(permission), [permissions]);
  const accessibleTabs = useMemo<Tab[]>(() => [...(can("users.view") ? ["users" as const] : []), ...(can("groups.view") ? ["groups" as const] : [])], [can]);
  useEffect(() => { if (!accessibleTabs.includes(tab) && accessibleTabs[0]) setTab(accessibleTabs[0]); }, [accessibleTabs, tab]);
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextUsers, nextGroups, nextRoles, nextHistory] = await Promise.all([
        can("users.view") ? api.identityUsers({ search, role: roleFilter, status: statusFilter, include_system: includeSystem }) : Promise.resolve([]),
        can("groups.view") ? api.identityGroups({ search: tab === "groups" ? search : "", include_system: includeSystem }) : Promise.resolve([]),
        can("access.view") ? api.identityRoles() : Promise.resolve(null),
        can("access.view") ? api.identityHistory() : Promise.resolve([]),
      ]);
      setUsers(nextUsers); setGroups(nextGroups); setRoles(nextRoles); setHistory(nextHistory);
      setSelectedUser((current) => current ? nextUsers.find((item) => item.username === current.username) || null : null);
      setSelectedGroup((current) => current ? nextGroups.find((item) => item.name === current.name) || null : null);
    } catch (error) {
      toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin");
    } finally { setLoading(false); }
  }, [can, includeSystem, roleFilter, search, statusFilter, t, tab, toast]);

  useEffect(() => { void refresh(); }, [refresh]);
  useRefreshOnConnectionRestored(() => { void refresh(); });

  async function perform(action: () => Promise<unknown>) {
    try { await action(); toast(t("admin.actionCompleted"), "ok", "admin"); await refresh(); }
    catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin"); throw error; }
  }

  function createUser() {
    setDialog({ title: t("identity.user.create"), fields: [
      { name: "username", label: t("settings.username"), required: true },
      { name: "password", label: t("settings.newPassword"), type: "password", required: true },
      { name: "gecos", label: t("identity.gecos") },
      { name: "uid", label: t("identity.optionalUid"), type: "number" },
      { name: "gid", label: t("identity.optionalGid"), type: "number" },
      { name: "home", label: t("identity.homeHint") },
      { name: "shell", label: t("identity.shell"), value: "/bin/bash" },
      { name: "groups", label: t("identity.supplementaryGroupsHint") },
      { name: "role", label: t("rbac.role"), type: "select", value: "user", options: roleValues.map((role) => ({ value: role, label: t(`rbac.role.${role}`) })) },
      { name: "force_password_change", label: t("identity.forcePasswordChange"), type: "select", value: "false", options: [{ value: "false", label: t("common.no") }, { value: "true", label: t("common.yes") }] },
    ], submit: (values) => perform(() => api.createIdentityUser({ username: values.username, password: values.password, gecos: values.gecos, uid: optionalNumber(values.uid), gid: optionalNumber(values.gid), home: values.home || null, shell: values.shell || null, role: values.role, groups: splitNames(values.groups), allow: [], deny: [], create_home: true, force_password_change: values.force_password_change === "true" })) });
  }

  function createGroup() {
    setDialog({ title: t("identity.group.create"), fields: [{ name: "groupname", label: t("settings.groupName"), required: true }, { name: "gid", label: t("identity.optionalGid"), type: "number" }], submit: (values) => perform(() => api.createIdentityGroup({ groupname: values.groupname, gid: optionalNumber(values.gid), allow: [], deny: [] })) });
  }

  const metadata = roles?.permissions || [];
  return <section className={`identity-app ${embedded ? "embedded" : ""}`}>
    <header className="feature-header"><div>{!embedded && <h2>{t("app.identity")}</h2>}<p>{t("identity.subtitle")}</p></div><button onClick={() => void refresh()}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button></header>
    <nav className="identity-tabs" aria-label={t("identity.tabs")}>
      {accessibleTabs.map((name) => <button className={tab === name ? "active" : ""} key={name} onClick={() => { setTab(name); setSearch(""); }}>{name === "users" ? <Users /> : name === "groups" ? <UserCog /> : name === "roles" ? <ShieldCheck /> : <History />}<span>{t(`identity.tab.${name}`)}</span></button>)}
    </nav>
    {tab === "users" && can("users.view") && <UsersView users={users} selected={selectedUser} metadata={metadata} search={search} roleFilter={roleFilter} statusFilter={statusFilter} includeSystem={includeSystem} can={can} t={t} onSearch={setSearch} onRole={setRoleFilter} onStatus={setStatusFilter} onSystem={setIncludeSystem} onCreate={createUser} onSelect={setSelectedUser} onDialog={setDialog} perform={perform} onOpenPolicies={onOpenPolicies} />}
    {tab === "groups" && <GroupsView groups={groups} selected={selectedGroup} metadata={metadata} search={search} includeSystem={includeSystem} can={can} t={t} onSearch={setSearch} onSystem={setIncludeSystem} onCreate={createGroup} onSelect={setSelectedGroup} onDialog={setDialog} perform={perform} onOpenPolicies={onOpenPolicies} />}
    {tab === "roles" && roles && <RoleMatrix roles={roles} t={t} />}
    {tab === "history" && <HistoryView items={history} t={t} />}
    {dialog && <AdminActionDialog {...dialog} t={t} onClose={() => setDialog(null)} onSubmit={dialog.submit} />}
  </section>;
}

function UsersView({ users, selected, metadata: _metadata, search, roleFilter, statusFilter, includeSystem, can, t, onSearch, onRole, onStatus, onSystem, onCreate, onSelect, onDialog, perform, onOpenPolicies }: {
  users: IdentityUser[]; selected: IdentityUser | null; metadata: PermissionMetadata[]; search: string; roleFilter: string; statusFilter: string; includeSystem: boolean; can: (permission: string) => boolean; t: Translate;
  onSearch: (value: string) => void; onRole: (value: string) => void; onStatus: (value: string) => void; onSystem: (value: boolean) => void; onCreate: () => void; onSelect: (user: IdentityUser | null) => void; onDialog: (value: Dialog) => void; perform: (action: () => Promise<unknown>) => Promise<void>; onOpenPolicies?: (subject: PolicySubject) => void;
}) {
  return <div className={`identity-workspace ${selected ? "has-details" : ""}`}><div className="identity-list-pane"><div className="identity-toolbar"><label className="identity-search"><Search /><input aria-label={t("action.search")} value={search} onChange={(event) => onSearch(event.target.value)} placeholder={t("identity.searchUsers")} /></label><select aria-label={t("rbac.role")} value={roleFilter} onChange={(event) => onRole(event.target.value)}><option value="">{t("identity.allRoles")}</option>{roleValues.map((role) => <option key={role} value={role}>{t(`rbac.role.${role}`)}</option>)}</select><select aria-label={t("identity.status")} value={statusFilter} onChange={(event) => onStatus(event.target.value)}><option value="">{t("identity.allStatuses")}</option><option value="active">{t("identity.active")}</option><option value="locked">{t("identity.locked")}</option></select><label className="identity-check"><input type="checkbox" checked={includeSystem} onChange={(event) => onSystem(event.target.checked)} />{t("identity.showSystem")}</label>{can("users.create") && <button className="button-primary" onClick={onCreate}><Plus />{t("identity.user.create")}</button>}</div><div className="identity-table-wrap"><table className="identity-table"><thead><tr><th>{t("settings.username")}</th><th>UID</th><th>{t("identity.primaryGroup")}</th><th>{t("rbac.role")}</th><th>{t("identity.status")}</th></tr></thead><tbody>{users.map((user) => <tr className={selected?.username === user.username ? "selected" : ""} key={user.username} tabIndex={0} onClick={() => onSelect(user)} onKeyDown={(event) => { if (event.key === "Enter") onSelect(user); }}><td><strong>{user.username}</strong><span className="identity-badges">{user.linux_admin && <small>{t("identity.linuxAdmin")}</small>}{user.is_system && <small>{t("identity.systemAccount")}</small>}</span></td><td>{user.uid}</td><td>{user.primary_group}</td><td>{t(`rbac.role.${user.role}`)}</td><td>{user.locked ? t("identity.locked") : t("identity.active")}</td></tr>)}</tbody></table></div></div>{selected && <UserDetails user={selected} can={can} t={t} onClose={() => onSelect(null)} onDialog={onDialog} perform={perform} onOpenPolicies={onOpenPolicies} />}</div>;
}

function UserDetails({ user, can, t, onClose, onDialog, perform, onOpenPolicies }: { user: IdentityUser; can: (permission: string) => boolean; t: Translate; onClose: () => void; onDialog: (value: Dialog) => void; perform: (action: () => Promise<unknown>) => Promise<void>; onOpenPolicies?: (subject: PolicySubject) => void }) {
  function editLinuxAccount() { onDialog({ title: `${t("action.edit")}: ${user.username}`, fields: [...(can("users.rename") ? [{ name: "new_username", label: t("identity.newUsername"), value: user.username }] : []), { name: "gecos", label: t("identity.gecos"), value: user.gecos }, { name: "home", label: t("identity.home"), value: user.home }, { name: "shell", label: t("identity.shell"), value: user.shell }, ...(can("users.manage_groups") ? [{ name: "groups_add", label: t("identity.groupsAdd") }, { name: "groups_remove", label: t("identity.groupsRemove") }] : []), { name: "force_password_change", label: t("identity.forcePasswordChange"), type: "select", value: String(user.password_change_required), options: [{ value: "false", label: t("common.no") }, { value: "true", label: t("common.yes") }] }], submit: (values) => perform(() => api.updateIdentityUser(user.username, { new_username: values.new_username && values.new_username !== user.username ? values.new_username : null, gecos: values.gecos, home: values.home !== user.home ? values.home : null, shell: values.shell, groups_add: splitNames(values.groups_add || ""), groups_remove: splitNames(values.groups_remove || ""), move_home: values.home !== user.home, force_password_change: values.force_password_change === "true" })) }); }
  function editQuota() { onDialog({ title: `${t("identity.quota")}: ${user.username}`, fields: [{ name: "soft_mb", label: t("identity.quotaSoft"), type: "number", value: "0", required: true }, { name: "hard_mb", label: t("identity.quotaHard"), type: "number", value: "0" }, { name: "mountpoint", label: t("identity.quotaMount"), value: "/" }], submit: (values) => perform(() => api.setIdentityUserQuota(user.username, Number(values.soft_mb), values.hard_mb ? Number(values.hard_mb) : null, values.mountpoint || null)) }); }
  function simple(kind: "lock" | "unlock" | "password" | "delete") {
    const fields = kind === "password" ? [{ name: "new_password", label: t("settings.newPassword"), type: "password" as const, required: true }, { name: "force_change", label: t("identity.forcePasswordChange"), type: "select" as const, value: "false", options: [{ value: "false", label: t("common.no") }, { value: "true", label: t("common.yes") }] }] : kind === "delete" ? [{ name: "remove_home", label: t("identity.removeHome"), type: "select" as const, value: "false", options: [{ value: "false", label: t("common.no") }, { value: "true", label: t("common.yes") }] }] : [];
    onDialog({ title: `${t(`identity.${kind}`)}: ${user.username}`, fields, danger: kind === "delete" || kind === "lock", submit: (values) => perform(() => kind === "lock" ? api.lockIdentityUser(user.username, true) : kind === "unlock" ? api.lockIdentityUser(user.username, false) : kind === "password" ? api.changeIdentityUserPassword(user.username, values.new_password, values.force_change === "true") : api.deleteIdentityUser(user.username, values.remove_home === "true")) });
  }
  return <aside className="identity-details"><header><div><strong>{user.username}</strong><span>{user.gecos || user.home}</span></div><button aria-label={t("action.close")} onClick={onClose}>×</button></header>{user.linux_admin && <div className="identity-protection"><ShieldCheck />{t("identity.linuxAdminProtection")}</div>}<dl><dt>UID / GID</dt><dd>{user.uid} / {user.gid}</dd><dt>{t("identity.home")}</dt><dd>{user.home}</dd><dt>{t("identity.shell")}</dt><dd>{user.shell}</dd><dt>{t("settings.groupsLabel")}</dt><dd>{user.groups.join(", ")}</dd><dt>{t("rbac.role")}</dt><dd>{t(`rbac.role.${user.role}`)}</dd><dt>{t("identity.effectivePermissions")}</dt><dd>{user.permissions.length}</dd></dl><div className="identity-actions">{can("users.update") && user.manageable && <button onClick={editLinuxAccount}><UserCog />{t("action.edit")}</button>}{can("users.manage_quota") && user.manageable && <button onClick={editQuota}>{t("identity.quota")}</button>}{can("users.lock") && user.manageable && !user.locked && <button onClick={() => simple("lock")}><Lock />{t("identity.lock")}</button>}{can("users.unlock") && user.manageable && user.locked && <button onClick={() => simple("unlock")}><Unlock />{t("identity.unlock")}</button>}{can("users.change_password") && user.manageable && <button onClick={() => simple("password")}><KeyRound />{t("identity.password")}</button>}{can("users.delete") && user.manageable && <button className="button-danger" onClick={() => simple("delete")}><Trash2 />{t("action.delete")}</button>}</div><div className="identity-policy-summary"><strong>{t("identity.permissionSources")}</strong>{Object.entries(user.permission_sources).slice(0, 5).map(([permission, sources]) => <small key={permission}>{permission}: {sources.join(", ")}</small>)}</div>{onOpenPolicies && can("access.view") && <button className="button-primary identity-save" onClick={() => onOpenPolicies({ type: "user", id: user.username })}>{t("identity.openPolicySettings")}</button>}</aside>;
}

function GroupsView({ groups, selected, metadata: _metadata, search, includeSystem, can, t, onSearch, onSystem, onCreate, onSelect, onDialog, perform, onOpenPolicies }: { groups: IdentityGroup[]; selected: IdentityGroup | null; metadata: PermissionMetadata[]; search: string; includeSystem: boolean; can: (permission: string) => boolean; t: Translate; onSearch: (value: string) => void; onSystem: (value: boolean) => void; onCreate: () => void; onSelect: (group: IdentityGroup | null) => void; onDialog: (value: Dialog) => void; perform: (action: () => Promise<unknown>) => Promise<void>; onOpenPolicies?: (subject: PolicySubject) => void }) {
  return <div className={`identity-workspace ${selected ? "has-details" : ""}`}><div className="identity-list-pane"><div className="identity-toolbar"><label className="identity-search"><Search /><input aria-label={t("action.search")} value={search} onChange={(event) => onSearch(event.target.value)} placeholder={t("identity.searchGroups")} /></label><label className="identity-check"><input type="checkbox" checked={includeSystem} onChange={(event) => onSystem(event.target.checked)} />{t("identity.showSystem")}</label>{can("groups.create") && <button className="button-primary" onClick={onCreate}><Plus />{t("identity.group.create")}</button>}</div><div className="identity-table-wrap"><table className="identity-table"><thead><tr><th>{t("settings.groupName")}</th><th>GID</th><th>{t("identity.members")}</th><th>{t("identity.inheriting")}</th></tr></thead><tbody>{groups.map((group) => <tr className={selected?.name === group.name ? "selected" : ""} key={group.name} onClick={() => onSelect(group)}><td><strong>{group.name}</strong>{group.protected && <small>{t("identity.protected")}</small>}</td><td>{group.gid}</td><td>{group.members.length}</td><td>{group.inheriting_count}</td></tr>)}</tbody></table></div></div>{selected && <GroupDetails group={selected} can={can} t={t} onClose={() => onSelect(null)} onDialog={onDialog} perform={perform} onOpenPolicies={onOpenPolicies} />}</div>;
}

function GroupDetails({ group, can, t, onClose, onDialog, perform, onOpenPolicies }: { group: IdentityGroup; can: (permission: string) => boolean; t: Translate; onClose: () => void; onDialog: (value: Dialog) => void; perform: (action: () => Promise<unknown>) => Promise<void>; onOpenPolicies?: (subject: PolicySubject) => void }) {
  function confirm(title: string, fields: AdminField[], danger: boolean, submit: (values: Record<string, string>) => Promise<unknown>) { onDialog({ title, fields, danger, submit: (values) => perform(() => submit(values)) }); }
  return <aside className="identity-details"><header><div><strong>{group.name}</strong><span>GID {group.gid}</span></div><button aria-label={t("action.close")} onClick={onClose}>×</button></header>{group.protected && <div className="identity-protection"><ShieldCheck />{t("identity.groupProtection")}</div>}<div className="identity-actions">{can("groups.rename") && group.manageable && <button onClick={() => confirm(t("identity.renameGroup"), [{ name: "new_name", label: t("identity.newGroupName"), value: group.name, required: true }], false, (values) => api.renameIdentityGroup(group.name, values.new_name))}>{t("identity.renameGroup")}</button>}</div><h3>{t("identity.primaryUsers")}</h3><div className="identity-member-list">{group.primary_users.length ? group.primary_users.map((member) => <span key={member}>{member}</span>) : <span>{t("common.none")}</span>}</div><h3>{t("identity.supplementaryMembers")}</h3><div className="identity-member-list">{group.supplementary_members.length ? group.supplementary_members.map((member) => <span key={member}>{member}{can("groups.manage_members") && group.manageable && <button aria-label={t("groups.removeMember")} onClick={() => confirm(`${t("groups.removeMember")}: ${member}`, [], true, () => api.setIdentityGroupMember(group.name, member, false))}>×</button>}</span>) : <span>{t("common.none")}</span>}</div>{can("groups.manage_members") && group.manageable && <button onClick={() => confirm(t("groups.addMember"), [{ name: "username", label: t("settings.username"), required: true }], false, (values) => api.setIdentityGroupMember(group.name, values.username, true))}><Plus />{t("groups.addMember")}</button>}<h3>{t("identity.inheriting")}</h3><p className="identity-inheritors">{group.inheriting_users.join(", ") || t("common.none")}</p><div className="identity-policy-summary"><strong>{t("identity.groupPolicy")}</strong><small>{t("identity.allowed")}: {group.allow.length}</small><small>{t("identity.denied")}: {group.deny.length}</small></div>{onOpenPolicies && can("access.view") && <button className="button-primary identity-save" onClick={() => onOpenPolicies({ type: "group", id: group.name })}>{t("identity.openPolicySettings")}</button>}{can("groups.delete") && group.manageable && <button className="button-danger identity-delete" onClick={() => confirm(`${t("action.delete")}: ${group.name}`, [], true, () => api.deleteIdentityGroup(group.name))}><Trash2 />{t("action.delete")}</button>}</aside>;
}

export function AccessPolicies({ permissions, initialSubject, t, toast }: { permissions: string[]; initialSubject?: PolicySubject; t: Translate; toast: ToastFn }) {
  const [view, setView] = useState<"roles" | "users" | "groups" | "history">("roles");
  const [roles, setRoles] = useState<IdentityRoles | null>(null);
  const [users, setUsers] = useState<IdentityUser[]>([]);
  const [groups, setGroups] = useState<IdentityGroup[]>([]);
  const [history, setHistory] = useState<IdentityHistory[]>([]);
  const [selectedUser, setSelectedUser] = useState<IdentityUser | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<IdentityGroup | null>(null);
  const [policy, setPolicy] = useState<PolicyState>({ allow: [], deny: [] });
  const [role, setRole] = useState<RbacRole>("user");
  const [query, setQuery] = useState("");
  const can = useCallback((permission: string) => permissions.includes(permission), [permissions]);
  const refresh = useCallback(async () => {
    if (!can("access.view")) return;
    try {
      const [nextRoles, nextUsers, nextGroups, nextHistory] = await Promise.all([
        api.identityRoles(), api.identityUsers({ include_system: false }), api.identityGroups({ include_system: false }), api.identityHistory(),
      ]);
      setRoles(nextRoles); setUsers(nextUsers); setGroups(nextGroups); setHistory(nextHistory);
    } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin"); }
  }, [can, t, toast]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!initialSubject) return;
    if (initialSubject.type === "user") {
      const user = users.find((item) => item.username === initialSubject.id);
      if (user) { setView("users"); chooseUser(user); }
    } else {
      const group = groups.find((item) => item.name === initialSubject.id);
      if (group) { setView("groups"); chooseGroup(group); }
    }
  }, [groups, initialSubject, users]);
  function chooseUser(user: IdentityUser) { setSelectedUser(user); setSelectedGroup(null); setRole(user.role); setPolicy({ allow: user.allow, deny: user.deny }); }
  function chooseGroup(group: IdentityGroup) { setSelectedGroup(group); setSelectedUser(null); setPolicy({ allow: group.allow, deny: group.deny }); }
  async function save() {
    const subject = selectedUser?.username || selectedGroup?.name;
    if (!subject || !window.confirm(`${t("identity.savePolicy")}: ${subject}`)) return;
    try {
      if (selectedUser) await api.saveIdentityUserPolicy(selectedUser.username, { role, ...policy });
      else if (selectedGroup) await api.saveIdentityGroupPolicy(selectedGroup.name, policy);
      toast(t("admin.actionCompleted"), "ok", "admin"); await refresh();
    } catch (error) { toast(error instanceof Error ? error.message : t("error.generic"), "error", "admin"); }
  }
  if (!can("access.view")) return <div className="error-state">{t("identity.accessDenied")}</div>;
  const filteredUsers = users.filter((item) => !query || `${item.username} ${item.role}`.toLowerCase().includes(query.toLowerCase()));
  const filteredGroups = groups.filter((item) => !query || item.name.toLowerCase().includes(query.toLowerCase()));
  const selected = selectedUser || selectedGroup;
  return <section className="identity-app embedded access-policy-editor">
    <nav className="identity-tabs" aria-label={t("settings.accessPolicies")}>{(["roles", "users", "groups", "history"] as const).map((item) => <button key={item} className={view === item ? "active" : ""} onClick={() => setView(item)}>{item === "roles" ? <ShieldCheck /> : item === "users" ? <Users /> : item === "groups" ? <UserCog /> : <History />}<span>{t(`identity.tab.${item}`)}</span></button>)}</nav>
    {view === "roles" && roles && <RoleMatrix roles={roles} t={t} />}
    {(view === "users" || view === "groups") && roles && <div className={`identity-workspace ${selected ? "has-details" : ""}`}><div className="identity-list-pane"><div className="identity-toolbar"><label className="identity-search"><Search /><input aria-label={t("action.search")} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t(view === "users" ? "identity.searchUsers" : "identity.searchGroups")} /></label></div><div className="identity-table-wrap"><table className="identity-table"><thead><tr><th>{t(view === "users" ? "settings.username" : "settings.groupName")}</th><th>{view === "users" ? t("rbac.role") : "GID"}</th></tr></thead><tbody>{view === "users" ? filteredUsers.map((item) => <tr key={item.username} className={selectedUser?.username === item.username ? "selected" : ""} onClick={() => chooseUser(item)}><td>{item.username}</td><td>{t(`rbac.role.${item.role}`)}</td></tr>) : filteredGroups.map((item) => <tr key={item.name} className={selectedGroup?.name === item.name ? "selected" : ""} onClick={() => chooseGroup(item)}><td>{item.name}</td><td>{item.gid}</td></tr>)}</tbody></table></div></div>{selected && <aside className="identity-details"><header><strong>{selectedUser?.username || selectedGroup?.name}</strong></header>{selectedUser && <label className="field-label">{t("rbac.role")}<select disabled={!can("access.manage_roles") || selectedUser.linux_admin} value={role} onChange={(event) => setRole(event.target.value as RbacRole)}>{roleValues.map((item) => <option key={item} value={item}>{t(`rbac.role.${item}`)}</option>)}</select></label>}<PermissionMatrix metadata={roles.permissions} policy={policy} sources={selectedUser?.permission_sources || {}} disabled={selectedUser ? !can("access.manage_user_permissions") || selectedUser.linux_admin : !can("access.manage_group_permissions")} t={t} onChange={setPolicy} />{((selectedUser && can("access.manage_user_permissions") && !selectedUser.linux_admin) || (selectedGroup && can("access.manage_group_permissions"))) && <button className="button-primary identity-save" onClick={() => void save()}>{t("identity.savePolicy")}</button>}</aside>}</div>}
    {view === "history" && <HistoryView items={history} t={t} />}
  </section>;
}

function PermissionMatrix({ metadata, policy, sources, disabled, t, onChange }: { metadata: PermissionMetadata[]; policy: PolicyState; sources: Record<string, string[]>; disabled: boolean; t: Translate; onChange: (value: PolicyState) => void }) {
  const [query, setQuery] = useState(""); const grouped = useMemo(() => { const result = new Map<string, PermissionMetadata[]>(); metadata.filter((item) => !query || `${item.id} ${t(item.label_key)}`.toLowerCase().includes(query.toLowerCase())).forEach((item) => result.set(item.category, [...(result.get(item.category) || []), item])); return result; }, [metadata, query, t]);
  function set(permission: string, state: "inherit" | "allow" | "deny") { onChange({ allow: state === "allow" ? [...new Set([...policy.allow, permission])] : policy.allow.filter((item) => item !== permission), deny: state === "deny" ? [...new Set([...policy.deny, permission])] : policy.deny.filter((item) => item !== permission) }); }
  return <div className="permission-matrix"><label className="identity-search"><Search /><input aria-label={t("identity.searchPermissions")} value={query} onChange={(event) => setQuery(event.target.value)} /></label>{[...grouped.entries()].map(([category, items]) => <section key={category}><h4>{t(`permissions.category.${category}`)}</h4>{items.map((item) => { const state = policy.deny.includes(item.id) ? "deny" : policy.allow.includes(item.id) ? "allow" : "inherit"; return <label className={`permission-row risk-${item.risk}`} key={item.id}><span><strong>{t(item.label_key)}</strong><small>{t(item.description_key)}</small><small>{item.id} · {item.operation} · {item.mutating ? t("identity.mutating") : t("identity.readOnly")} · {t(`identity.risk.${item.risk}`)} · {item.applications.join(", ")}{sources[item.id]?.length ? ` · ${sources[item.id].join(", ")}` : ""}</small></span><select disabled={disabled} value={state} onChange={(event) => set(item.id, event.target.value as "inherit" | "allow" | "deny")} aria-label={`${item.id} ${t("identity.permissionState")}`}><option value="inherit">{t("identity.inherited")}</option><option value="allow">{t("identity.allowed")}</option><option value="deny">{t("identity.denied")}</option></select></label>; })}</section>)}</div>;
}

function RoleMatrix({ roles, t }: { roles: IdentityRoles; t: Translate }) {
  return <div className="identity-role-matrix"><table><thead><tr><th>{t("identity.permission")}</th>{roleValues.map((role) => <th key={role}>{t(`rbac.role.${role}`)}</th>)}</tr></thead><tbody>{roles.permissions.map((permission) => <tr key={permission.id}><td><strong>{t(permission.label_key)}</strong><small>{permission.id}</small></td>{roleValues.map((role) => <td key={role} aria-label={`${permission.id} ${role}`}>{roles.roles[role].includes(permission.id) ? "✓" : "—"}</td>)}</tr>)}</tbody></table></div>;
}

function HistoryView({ items, t }: { items: IdentityHistory[]; t: Translate }) {
  return <div className="identity-history">{items.map((item) => <article key={item.id}><History /><div><strong>{t(`identity.history.${item.action}`)}</strong><span>{item.subject_type}: {item.subject}</span></div><span>{item.actor}</span><time>{new Date(item.created_at * 1000).toLocaleString()}</time></article>)}</div>;
}
