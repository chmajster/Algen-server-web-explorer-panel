import { Check, Copy, Plus, RefreshCw, Search, ShieldCheck, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { request } from "../../core/api/transport";
import type { ToastFn, Translate } from "../../app/types";
import "./rbac-access.css";

type PermissionItem = { id: string; category: string; canonical: string };
type Grant = { permission: string; effect: "allow" | "deny"; resource_type: string; resource_id: string; scope: string };
type Role = { id: string; name: string; description: string; active: number; role_type: "system" | "custom"; protected: number; permissions: Grant[] };
type Group = { id: string; name: string; description: string; active: number; source: string; managed: number; roles: string[]; members: Array<{ provider: string; identity_id: string; username: string }> };
type ExternalGroup = { id: string; external_id: string; distinguished_name: string; name: string; status: string; role_ids: string[]; parent_ids: string[] };
type Policy = { id: string; name: string; description: string; active: number; effect: "allow" | "deny"; permission: string; resource_type: string; resource_id: string; scope: string; conditions: Record<string, unknown>; subjects: Array<{ subject_type: string; subject_id: string }> };
type Audit = { id: number; actor: string; action: string; target: string; timestamp: number; source_ip: string; before_json: string; after_json: string };
type DecisionSource = { effect: string; source_type: string; source_name: string; reason: string; permission: string };
type Effective = { user: { username: string; provider: string; identity_id: string }; allowed: string[]; denied: string[]; permissions: Array<{ result: "ALLOW" | "DENY"; permission: string; reason: string; sources: DecisionSource[] }> };
type Tab = "roles" | "groups" | "policies" | "ldap" | "effective" | "audit";

const tabs: Array<{ id: Tab; label: string }> = [
  { id: "roles", label: "Role" }, { id: "groups", label: "Grupy" }, { id: "policies", label: "Polityki" },
  { id: "ldap", label: "LDAP / Active Directory" }, { id: "effective", label: "Efektywne uprawnienia" }, { id: "audit", label: "Audit log" },
];

async function unwrap<T>(promise: Promise<T | { items: T }>): Promise<T> {
  const value = await promise;
  return value && typeof value === "object" && "items" in value ? (value as { items: T }).items : value as T;
}

export function RbacAccessApp({ t: _t, toast }: { t: Translate; toast: ToastFn }) {
  const [tab, setTab] = useState<Tab>("roles");
  const [roles, setRoles] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<PermissionItem[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [externalGroups, setExternalGroups] = useState<ExternalGroup[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextRoles, nextPermissions, nextGroups, nextPolicies, nextExternal, nextAudit] = await Promise.all([
        unwrap(request<{ items: Role[] }>("/api/rbac/roles")).then((x) => (x as unknown as { items: Role[] }).items ?? x as unknown as Role[]),
        unwrap(request<{ items: PermissionItem[] }>("/api/rbac/permissions")).then((x) => (x as unknown as { items: PermissionItem[] }).items ?? x as unknown as PermissionItem[]),
        unwrap(request<{ items: Group[] }>("/api/rbac/groups")).then((x) => (x as unknown as { items: Group[] }).items ?? x as unknown as Group[]),
        unwrap(request<{ items: Policy[] }>("/api/rbac/policies")).then((x) => (x as unknown as { items: Policy[] }).items ?? x as unknown as Policy[]),
        unwrap(request<{ items: ExternalGroup[] }>("/api/rbac/external-groups")).then((x) => (x as unknown as { items: ExternalGroup[] }).items ?? x as unknown as ExternalGroup[]),
        unwrap(request<{ items: Audit[] }>("/api/rbac/audit?limit=300")).then((x) => (x as unknown as { items: Audit[] }).items ?? x as unknown as Audit[]),
      ]);
      setRoles(nextRoles); setPermissions(nextPermissions); setGroups(nextGroups); setPolicies(nextPolicies); setExternalGroups(nextExternal); setAudit(nextAudit);
    } catch (error) { toast(error instanceof Error ? error.message : "Nie udało się pobrać RBAC", "error", "rbac"); }
    finally { setLoading(false); }
  }, [toast]);

  useEffect(() => { void refresh(); }, [refresh]);

  return <section className="rbac-access">
    <header className="feature-header"><div><h2>Dostęp i bezpieczeństwo</h2><p>Role, granularne permissions, grupy lokalne, LDAP/AD, polityki, scope i explain mode.</p></div><button onClick={() => void refresh()}><RefreshCw className={loading ? "spin" : ""} />Odśwież</button></header>
    <nav className="rbac-tabs" aria-label="Dostęp i bezpieczeństwo">{tabs.map((item) => <button key={item.id} className={tab === item.id ? "active" : ""} onClick={() => setTab(item.id)}>{item.label}</button>)}</nav>
    {tab === "roles" && <RolesPanel roles={roles} permissions={permissions} toast={toast} refresh={refresh} />}
    {tab === "groups" && <GroupsPanel groups={groups} roles={roles} toast={toast} refresh={refresh} />}
    {tab === "policies" && <PoliciesPanel policies={policies} permissions={permissions} toast={toast} refresh={refresh} />}
    {tab === "ldap" && <LdapPanel groups={externalGroups} roles={roles} toast={toast} refresh={refresh} />}
    {tab === "effective" && <EffectivePanel permissions={permissions} toast={toast} />}
    {tab === "audit" && <AuditPanel items={audit} />}
  </section>;
}

function RolesPanel({ roles, permissions, toast, refresh }: { roles: Role[]; permissions: PermissionItem[]; toast: ToastFn; refresh: () => Promise<void> }) {
  const [selected, setSelected] = useState<Role | null>(null);
  const [search, setSearch] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [grants, setGrants] = useState<Set<string>>(new Set());
  const categories = useMemo(() => [...new Set(permissions.map((item) => item.category))].sort(), [permissions]);
  const visible = permissions.filter((p) => p.id.toLowerCase().includes(search.toLowerCase()));
  useEffect(() => { if (!selected) return; setName(selected.name); setDescription(selected.description); setGrants(new Set(selected.permissions.filter((g) => g.effect === "allow" && g.resource_type === "global").map((g) => g.permission))); }, [selected]);
  const toggle = (permission: string) => setGrants((current) => { const next = new Set(current); next.has(permission) ? next.delete(permission) : next.add(permission); return next; });
  const setCategory = (category: string, enabled: boolean) => setGrants((current) => { const next = new Set(current); permissions.filter((p) => p.category === category).forEach((p) => enabled ? next.add(p.canonical) : next.delete(p.canonical)); return next; });
  async function save() {
    const payload = { name, description, active: true, permissions: [...grants].map((permission) => ({ permission, effect: "allow", resource_type: "global", resource_id: "*", scope: "*" })) };
    try { if (selected) await request(`/api/rbac/roles/${encodeURIComponent(selected.id)}`, { method: "PUT", body: JSON.stringify(payload) }); else await request("/api/rbac/roles", { method: "POST", body: JSON.stringify(payload) }); toast("Rola zapisana", "ok", "rbac"); setSelected(null); setName(""); setDescription(""); setGrants(new Set()); await refresh(); }
    catch (error) { toast(error instanceof Error ? error.message : "Błąd zapisu roli", "error", "rbac"); }
  }
  async function duplicate(role: Role) { await request(`/api/rbac/roles/${encodeURIComponent(role.id)}/duplicate`, { method: "POST", body: "{}" }); await refresh(); }
  async function remove(role: Role) { if (role.protected) return; await request(`/api/rbac/roles/${encodeURIComponent(role.id)}`, { method: "DELETE" }); if (selected?.id === role.id) setSelected(null); await refresh(); }
  return <div className="rbac-grid"><div className="rbac-list"><div className="rbac-list-head"><h3>Role</h3><button onClick={() => { setSelected(null); setName(""); setDescription(""); setGrants(new Set()); }}><Plus />Nowa</button></div>{roles.map((role) => <button className={`rbac-role-row ${selected?.id === role.id ? "selected" : ""}`} key={role.id} onClick={() => setSelected(role)}><span><strong>{role.name}</strong><small>{role.role_type === "system" ? "systemowa" : "własna"} · {role.active ? "aktywna" : "nieaktywna"}</small></span><span className="rbac-row-actions"><button title="Duplikuj" onClick={(e) => { e.stopPropagation(); void duplicate(role); }}><Copy /></button>{!role.protected && <button title="Usuń" onClick={(e) => { e.stopPropagation(); void remove(role); }}><Trash2 /></button>}</span></button>)}</div><div className="rbac-editor"><h3>{selected ? `Edytuj: ${selected.name}` : "Nowa rola"}</h3><label>Nazwa<input value={name} disabled={Boolean(selected?.protected)} onChange={(e) => setName(e.target.value)} /></label><label>Opis<textarea value={description} onChange={(e) => setDescription(e.target.value)} /></label><label className="rbac-search"><Search /><input placeholder="Szukaj permission" value={search} onChange={(e) => setSearch(e.target.value)} /></label><div className="rbac-permission-groups">{categories.map((category) => { const categoryPermissions = visible.filter((p) => p.category === category); if (!categoryPermissions.length) return null; const canonical = [...new Set(categoryPermissions.map((p) => p.canonical))]; const all = canonical.every((p) => grants.has(p)); return <fieldset key={category}><legend>{category}<span><button onClick={() => setCategory(category, true)}>Zaznacz</button><button onClick={() => setCategory(category, false)}>Odznacz</button></span></legend>{categoryPermissions.map((permission) => <label className="rbac-permission" key={permission.id}><input type="checkbox" checked={grants.has(permission.canonical)} onChange={() => toggle(permission.canonical)} /><code>{permission.id}</code>{permission.id !== permission.canonical && <small>→ {permission.canonical}</small>}</label>)}</fieldset>; })}</div><button className="button-primary" disabled={!name.trim()} onClick={() => void save()}><Check />Zapisz rolę</button></div></div>;
}

function GroupsPanel({ groups, roles, toast, refresh }: { groups: Group[]; roles: Role[]; toast: ToastFn; refresh: () => Promise<void> }) {
  const [name, setName] = useState(""); const [description, setDescription] = useState(""); const [roleIds, setRoleIds] = useState<Set<string>>(new Set());
  async function create() { try { await request("/api/rbac/groups", { method: "POST", body: JSON.stringify({ name, description, active: true, source: "local", role_ids: [...roleIds] }) }); setName(""); setDescription(""); setRoleIds(new Set()); await refresh(); toast("Grupa utworzona", "ok", "rbac"); } catch (e) { toast(e instanceof Error ? e.message : "Błąd grupy", "error", "rbac"); } }
  return <div className="rbac-grid"><div className="rbac-list"><h3>Grupy lokalne i zarządzane</h3>{groups.map((g) => <div className="rbac-card" key={g.id}><strong>{g.name}</strong><small>{g.source}{g.managed ? " · zarządzana zewnętrznie" : ""}</small><p>{g.description}</p><span>{g.members.length} użytkowników · {g.roles.length} ról</span></div>)}</div><div className="rbac-editor"><h3>Nowa lokalna grupa WebNAS</h3><label>Nazwa<input value={name} onChange={(e) => setName(e.target.value)} /></label><label>Opis<textarea value={description} onChange={(e) => setDescription(e.target.value)} /></label><fieldset><legend>Role</legend>{roles.map((r) => <label className="rbac-permission" key={r.id}><input type="checkbox" checked={roleIds.has(r.id)} onChange={() => setRoleIds((current) => { const n = new Set(current); n.has(r.id) ? n.delete(r.id) : n.add(r.id); return n; })} />{r.name}</label>)}</fieldset><button className="button-primary" disabled={!name.trim()} onClick={() => void create()}><Plus />Utwórz grupę</button></div></div>;
}

function PoliciesPanel({ policies, permissions, toast, refresh }: { policies: Policy[]; permissions: PermissionItem[]; toast: ToastFn; refresh: () => Promise<void> }) {
  const [name, setName] = useState(""); const [permission, setPermission] = useState(""); const [effect, setEffect] = useState<"allow" | "deny">("deny"); const [resourceType, setResourceType] = useState("global"); const [resourceId, setResourceId] = useState("*"); const [scope, setScope] = useState("*"); const [subjectType, setSubjectType] = useState("user"); const [subjectId, setSubjectId] = useState("");
  async function create() { try { await request("/api/rbac/policies", { method: "POST", body: JSON.stringify({ name, effect, permission, resource_type: resourceType, resource_id: resourceId, scope, conditions: {}, subjects: subjectId ? [{ subject_type: subjectType, subject_id: subjectId }] : [] }) }); setName(""); setPermission(""); await refresh(); toast("Polityka utworzona", "ok", "rbac"); } catch (e) { toast(e instanceof Error ? e.message : "Błąd polityki", "error", "rbac"); } }
  return <div className="rbac-grid"><div className="rbac-list"><h3>Polityki</h3>{policies.map((p) => <div className="rbac-card" key={p.id}><strong>{p.name}</strong><small className={p.effect === "deny" ? "deny" : "allow"}>{p.effect.toUpperCase()} · {p.permission}</small><code>{p.resource_type}:{p.resource_id} {p.scope}</code></div>)}</div><div className="rbac-editor"><h3>Nowa polityka</h3><label>Nazwa<input value={name} onChange={(e) => setName(e.target.value)} /></label><label>Efekt<select value={effect} onChange={(e) => setEffect(e.target.value as "allow" | "deny")}><option value="allow">ALLOW</option><option value="deny">DENY</option></select></label><label>Permission<select value={permission} onChange={(e) => setPermission(e.target.value)}><option value="">Wybierz…</option>{permissions.filter((p) => p.id === p.canonical).map((p) => <option key={p.id} value={p.id}>{p.id}</option>)}</select></label><div className="rbac-three"><label>Resource type<input value={resourceType} onChange={(e) => setResourceType(e.target.value)} /></label><label>Resource ID<input value={resourceId} onChange={(e) => setResourceId(e.target.value)} /></label><label>Scope<input value={scope} onChange={(e) => setScope(e.target.value)} /></label></div><div className="rbac-two"><label>Subject<select value={subjectType} onChange={(e) => setSubjectType(e.target.value)}><option value="user">Użytkownik</option><option value="group">Grupa lokalna</option><option value="external_group">Grupa LDAP</option><option value="provider">Źródło tożsamości</option></select></label><label>ID<input value={subjectId} onChange={(e) => setSubjectId(e.target.value)} /></label></div><button className="button-primary" disabled={!name || !permission} onClick={() => void create()}><Plus />Utwórz politykę</button></div></div>;
}

function LdapPanel({ groups, roles, toast, refresh }: { groups: ExternalGroup[]; roles: Role[]; toast: ToastFn; refresh: () => Promise<void> }) {
  const [query, setQuery] = useState(""); const [found, setFound] = useState<Array<{ external_id: string; dn: string; name: string }>>([]); const [status, setStatus] = useState(""); const [selectedGroup, setSelectedGroup] = useState(""); const [selectedRole, setSelectedRole] = useState("");
  async function test() { try { const result = await request<{ status: string }>("/api/ldap/test", { method: "POST", body: "{}" }); setStatus(result.status); } catch (e) { setStatus("Offline"); toast(e instanceof Error ? e.message : "LDAP offline", "error", "rbac"); } }
  async function search() { const result = await request<{ items: Array<{ external_id: string; dn: string; name: string }> }>(`/api/ldap/groups?q=${encodeURIComponent(query)}&limit=100`); setFound(result.items); }
  async function sync() { const result = await request<{ status: string }>("/api/ldap/sync", { method: "POST", body: JSON.stringify({ nested_groups: true, max_depth: 8, max_nodes: 5000, auto_create_local_groups: false }) }); setStatus(result.status); await refresh(); }
  async function map() { if (!selectedGroup || !selectedRole) return; await request("/api/ldap/mappings", { method: "POST", body: JSON.stringify({ external_group_id: selectedGroup, role_id: selectedRole }) }); await refresh(); toast("Mapowanie LDAP zapisane", "ok", "rbac"); }
  return <div className="rbac-ldap"><div className="rbac-toolbar"><button onClick={() => void test()}>Testuj połączenie</button><button onClick={() => void sync()}><RefreshCw />Synchronizuj</button>{status && <span className={`rbac-status ${status.toLowerCase()}`}>{status}</span>}</div><div className="rbac-grid"><div className="rbac-list"><h3>Wyszukiwarka LDAP</h3><label className="rbac-search"><Search /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="np. Linux-Admins" /><button onClick={() => void search()}>Szukaj</button></label>{found.map((g) => <div className="rbac-card" key={g.external_id}><strong>{g.name}</strong><code>{g.dn}</code></div>)}<h3>Zsynchronizowane grupy</h3>{groups.map((g) => <div className="rbac-card" key={g.id}><strong>{g.name}</strong><small>{g.status}</small><code>{g.distinguished_name}</code><span>Role: {g.role_ids.map((id) => roles.find((r) => r.id === id)?.name || id).join(", ") || "brak"}</span></div>)}</div><div className="rbac-editor"><h3>Mapowanie grupa LDAP → rola</h3><label>Grupa<select value={selectedGroup} onChange={(e) => setSelectedGroup(e.target.value)}><option value="">Wybierz…</option>{groups.map((g) => <option value={g.id} key={g.id}>{g.name}</option>)}</select></label><label>Rola<select value={selectedRole} onChange={(e) => setSelectedRole(e.target.value)}><option value="">Wybierz…</option>{roles.map((r) => <option value={r.id} key={r.id}>{r.name}</option>)}</select></label><button className="button-primary" onClick={() => void map()}>Zapisz mapowanie</button><p>Permissions nie są zgadywane z nazwy grupy. Rola określa jawnie wybrane uprawnienia.</p></div></div></div>;
}

function EffectivePanel({ permissions, toast }: { permissions: PermissionItem[]; toast: ToastFn }) {
  const [username, setUsername] = useState(""); const [provider, setProvider] = useState("pam"); const [identityId, setIdentityId] = useState(""); const [effective, setEffective] = useState<Effective | null>(null); const [permission, setPermission] = useState("files.read"); const [resourceType, setResourceType] = useState("global"); const [resourceId, setResourceId] = useState("*"); const [scope, setScope] = useState("*"); const [decision, setDecision] = useState<Effective["permissions"][number] | null>(null);
  async function load() { try { setEffective(await request<Effective>(`/api/rbac/users/${encodeURIComponent(username)}/effective-permissions?auth_provider=${provider}&identity_id=${encodeURIComponent(identityId)}`)); } catch (e) { toast(e instanceof Error ? e.message : "Błąd", "error", "rbac"); } }
  async function simulate() { const value = await request<Effective["permissions"][number]>("/api/rbac/simulate", { method: "POST", body: JSON.stringify({ username, auth_provider: provider, identity_id: identityId, permission, resource_type: resourceType, resource_id: resourceId, scope }) }); setDecision(value); }
  return <div className="rbac-effective"><div className="rbac-toolbar"><input placeholder="Użytkownik" value={username} onChange={(e) => setUsername(e.target.value)} /><select value={provider} onChange={(e) => setProvider(e.target.value)}><option value="local">local</option><option value="pam">pam</option><option value="ldap">ldap</option></select><input placeholder="Identity ID (opcjonalnie)" value={identityId} onChange={(e) => setIdentityId(e.target.value)} /><button onClick={() => void load()}>Pokaż efektywne</button></div>{effective && <table className="rbac-table"><thead><tr><th>Permission</th><th>Wynik</th><th>Źródło</th></tr></thead><tbody>{effective.permissions.map((d) => <tr key={d.permission}><td><code>{d.permission}</code></td><td className={d.result === "DENY" ? "deny" : "allow"}>{d.result}</td><td>{d.sources.map((s) => `${s.source_type}: ${s.source_name}`).join("; ") || d.reason}</td></tr>)}</tbody></table>}<div className="rbac-simulator"><h3>Sprawdź dostęp użytkownika — explain mode</h3><select value={permission} onChange={(e) => setPermission(e.target.value)}>{permissions.filter((p) => p.id === p.canonical).map((p) => <option key={p.id}>{p.id}</option>)}</select><input value={resourceType} onChange={(e) => setResourceType(e.target.value)} placeholder="Resource type" /><input value={resourceId} onChange={(e) => setResourceId(e.target.value)} placeholder="Resource ID" /><input value={scope} onChange={(e) => setScope(e.target.value)} placeholder="Scope" /><button onClick={() => void simulate()}>Sprawdź</button>{decision && <div className={`rbac-decision ${decision.result.toLowerCase()}`}><strong>{decision.result}</strong><span>{decision.reason}</span>{decision.sources.map((s, i) => <code key={i}>{s.source_type} → {s.source_name} {s.reason}</code>)}</div>}</div></div>;
}

function AuditPanel({ items }: { items: Audit[] }) { return <div className="rbac-audit"><table className="rbac-table"><thead><tr><th>Czas</th><th>Actor</th><th>Action</th><th>Target</th><th>IP</th></tr></thead><tbody>{items.map((item) => <tr key={item.id}><td>{new Date(item.timestamp * 1000).toLocaleString()}</td><td>{item.actor}</td><td><code>{item.action}</code></td><td>{item.target}</td><td>{item.source_ip || "—"}</td></tr>)}</tbody></table></div>; }
