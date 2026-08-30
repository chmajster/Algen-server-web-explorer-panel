import { Network, Plus, RefreshCw, Save, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { ToastFn } from "../../app/types";
import { confirmDialog } from "../../components/DialogService";
import { ldapManagerClient, type ConnectionPayload, type LdapConnection, type LdapEntry, type Overview } from "./api/client";
import "../infrastructure-managers.css";

type Props = { permissions: readonly string[]; language: string; toast: ToastFn };
type Tab = "overview" | "connections" | "directory" | "users" | "groups" | "ous" | "import" | "schema" | "diagnostics";

const emptyConnection: ConnectionPayload = {
  name: "",
  directory_type: "generic",
  servers: [{ host: "", port: 389, priority: 10 }],
  security_mode: "starttls",
  verify_tls: true,
  ca_certificate: "",
  base_dn: "",
  bind_dn: "",
  connect_timeout: 5,
  operation_timeout: 15,
  bind_password: "",
};

function valueText(value: unknown): string {
  if (Array.isArray(value)) return value.map(valueText).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "");
}

export function LdapManagerApp({ permissions, language, toast }: Props) {
  const pl = language.toLowerCase().startsWith("pl");
  const [connections, setConnections] = useState<LdapConnection[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [tab, setTab] = useState<Tab>("overview");
  const [loading, setLoading] = useState(false);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [entries, setEntries] = useState<LdapEntry[]>([]);
  const [searchText, setSearchText] = useState("");
  const [directoryBase, setDirectoryBase] = useState("");
  const [directoryFilter, setDirectoryFilter] = useState("(objectClass=*)");
  const [connectionForm, setConnectionForm] = useState<ConnectionPayload>(emptyConnection);
  const [editingId, setEditingId] = useState("");
  const [objectDn, setObjectDn] = useState("");
  const [objectUid, setObjectUid] = useState("");
  const [objectCn, setObjectCn] = useState("");
  const [objectSn, setObjectSn] = useState("");
  const [objectMail, setObjectMail] = useState("");
  const [groupMemberDn, setGroupMemberDn] = useState("");
  const [selectedGroupDn, setSelectedGroupDn] = useState("");
  const [passwordTarget, setPasswordTarget] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [forcePasswordChange, setForcePasswordChange] = useState(false);
  const [csvText, setCsvText] = useState("");
  const [importResult, setImportResult] = useState<Record<string, unknown> | null>(null);
  const [schema, setSchema] = useState<Record<string, unknown> | null>(null);
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null);
  const [bulkDns, setBulkDns] = useState("");
  const [bulkAction, setBulkAction] = useState("disable");
  const [bulkResult, setBulkResult] = useState<Record<string, unknown> | null>(null);

  const selected = useMemo(() => connections.find((item) => item.id === selectedId) || null, [connections, selectedId]);
  const can = (permission: string) => permissions.includes(permission);
  const message = (error: unknown) => error instanceof Error ? error.message : String(error);

  const loadConnections = useCallback(async () => {
    try {
      const result = await ldapManagerClient.connections();
      setConnections(result.items);
      setSelectedId((current) => current && result.items.some((item) => item.id === current) ? current : result.items[0]?.id || "");
    } catch (error) {
      toast(message(error), "error");
    }
  }, [toast]);

  const loadOverview = useCallback(async () => {
    if (!selectedId) { setOverview(null); return; }
    setLoading(true);
    try { setOverview(await ldapManagerClient.overview(selectedId)); }
    catch (error) { toast(message(error), "error"); }
    finally { setLoading(false); }
  }, [selectedId, toast]);

  useEffect(() => { void loadConnections(); }, [loadConnections]);
  useEffect(() => { if (tab === "overview") void loadOverview(); }, [loadOverview, tab]);

  async function loadList(kind: "users" | "groups" | "ous") {
    if (!selectedId) return;
    setLoading(true);
    try {
      const result = kind === "users" ? await ldapManagerClient.users(selectedId, searchText)
        : kind === "groups" ? await ldapManagerClient.groups(selectedId, searchText)
          : await ldapManagerClient.ous(selectedId);
      setEntries(result.items);
    } catch (error) { toast(message(error), "error"); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    if (tab === "users" || tab === "groups" || tab === "ous") void loadList(tab);
    if (tab === "schema" && selectedId) void ldapManagerClient.schema(selectedId).then(setSchema).catch((error) => toast(message(error), "error"));
    if (tab === "diagnostics" && selectedId) void ldapManagerClient.diagnostics(selectedId).then(setDiagnostics).catch((error) => toast(message(error), "error"));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, selectedId]);

  function editConnection(item?: LdapConnection) {
    if (!item) {
      setEditingId("");
      setConnectionForm({ ...emptyConnection, servers: [{ ...emptyConnection.servers[0] }] });
      return;
    }
    setEditingId(item.id);
    setConnectionForm({
      name: item.name,
      directory_type: item.directory_type,
      servers: item.servers.map((server) => ({ ...server })),
      security_mode: item.security_mode,
      verify_tls: item.verify_tls,
      ca_certificate: item.ca_certificate,
      base_dn: item.base_dn,
      bind_dn: item.bind_dn,
      connect_timeout: item.connect_timeout,
      operation_timeout: item.operation_timeout,
      bind_password: "",
    });
  }

  async function saveConnection() {
    try {
      const saved = editingId
        ? await ldapManagerClient.updateConnection(editingId, connectionForm)
        : await ldapManagerClient.createConnection(connectionForm);
      toast(pl ? "Połączenie LDAP zapisane" : "LDAP connection saved", "ok");
      await loadConnections();
      setSelectedId(saved.id);
      editConnection(saved);
    } catch (error) { toast(message(error), "error"); }
  }

  async function deleteConnection(item: LdapConnection) {
    if (!await confirmDialog(`${pl ? "Usunąć połączenie" : "Delete connection"} ${item.name}?`, (key) => key)) return;
    try {
      await ldapManagerClient.deleteConnection(item.id);
      toast(pl ? "Połączenie usunięte" : "Connection deleted", "ok");
      setEditingId("");
      await loadConnections();
    } catch (error) { toast(message(error), "error"); }
  }

  async function runDirectorySearch() {
    if (!selectedId) return;
    setLoading(true);
    try {
      const result = await ldapManagerClient.search(selectedId, {
        base_dn: directoryBase || selected?.base_dn || "",
        scope: "subtree",
        ldap_filter: directoryFilter,
        attributes: ["*"],
        page_size: 200,
      });
      setEntries(result.items);
    } catch (error) { toast(message(error), "error"); }
    finally { setLoading(false); }
  }

  function objectPayload(kind: "user" | "group" | "ou") {
    if (kind === "ou") return { dn: objectDn, object_classes: ["top", "organizationalUnit"], attributes: { ou: objectCn } };
    if (kind === "group") {
      if (selected?.directory_type === "active_directory") return { dn: objectDn, object_classes: ["top", "group"], attributes: { cn: objectCn, sAMAccountName: objectUid || objectCn } };
      return { dn: objectDn, object_classes: ["top", "groupOfNames"], attributes: { cn: objectCn, member: [selected?.bind_dn || objectDn] } };
    }
    if (selected?.directory_type === "active_directory") {
      return { dn: objectDn, object_classes: ["top", "person", "organizationalPerson", "user"], attributes: { cn: objectCn, sn: objectSn || objectCn, sAMAccountName: objectUid, mail: objectMail } };
    }
    return { dn: objectDn, object_classes: ["top", "person", "organizationalPerson", "inetOrgPerson"], attributes: { uid: objectUid, cn: objectCn, sn: objectSn || objectCn, mail: objectMail } };
  }

  async function createObject(kind: "user" | "group" | "ou") {
    if (!selectedId) return;
    try {
      const payload = objectPayload(kind);
      if (kind === "user") await ldapManagerClient.createUser(selectedId, payload);
      else if (kind === "group") await ldapManagerClient.createGroup(selectedId, payload);
      else await ldapManagerClient.createOu(selectedId, payload);
      toast(pl ? "Obiekt LDAP utworzony" : "LDAP object created", "ok");
      setObjectDn(""); setObjectUid(""); setObjectCn(""); setObjectSn(""); setObjectMail("");
      await loadList(kind === "user" ? "users" : kind === "group" ? "groups" : "ous");
    } catch (error) { toast(message(error), "error"); }
  }

  async function deleteObject(kind: "user" | "group" | "ou", dn: string) {
    if (!selectedId || !await confirmDialog(`${pl ? "Usunąć" : "Delete"} ${dn}?`, (key) => key)) return;
    try {
      if (kind === "user") await ldapManagerClient.deleteUser(selectedId, dn);
      else if (kind === "group") await ldapManagerClient.deleteGroup(selectedId, dn);
      else await ldapManagerClient.deleteOu(selectedId, dn);
      await loadList(kind === "user" ? "users" : kind === "group" ? "groups" : "ous");
    } catch (error) { toast(message(error), "error"); }
  }

  async function resetPassword() {
    if (!selectedId || !passwordTarget || !newPassword) return;
    try {
      await ldapManagerClient.resetPassword(selectedId, passwordTarget, newPassword, forcePasswordChange);
      setNewPassword(""); setPasswordTarget(""); setForcePasswordChange(false);
      toast(pl ? "Hasło zresetowane" : "Password reset completed", "ok");
    } catch (error) { toast(message(error), "error"); }
  }

  async function addMembership() {
    if (!selectedId || !selectedGroupDn || !groupMemberDn) return;
    try {
      await ldapManagerClient.addMember(selectedId, selectedGroupDn, groupMemberDn);
      toast(pl ? "Członkostwo dodane" : "Membership added", "ok");
      setGroupMemberDn("");
    } catch (error) { toast(message(error), "error"); }
  }

  async function runImport(dryRun: boolean) {
    if (!selectedId || !csvText.trim()) return;
    try { setImportResult(await ldapManagerClient.importCsv(selectedId, csvText, dryRun)); }
    catch (error) { toast(message(error), "error"); }
  }

  async function runBulk(dryRun: boolean) {
    if (!selectedId) return;
    const targetDns = bulkDns.split("\n").map((item) => item.trim()).filter(Boolean);
    if (!targetDns.length) return;
    try { setBulkResult(await ldapManagerClient.bulk(selectedId, { action: bulkAction, target_dns: targetDns, dry_run: dryRun })); }
    catch (error) { toast(message(error), "error"); }
  }

  const tabs: Array<[Tab, string, string | null]> = [
    ["overview", pl ? "Przegląd" : "Overview", "ldap.connections.read"],
    ["connections", pl ? "Połączenia" : "Connections", "ldap.connections.read"],
    ["directory", "Directory", "ldap.directory.read"],
    ["users", pl ? "Użytkownicy" : "Users", "ldap.users.read"],
    ["groups", pl ? "Grupy" : "Groups", "ldap.groups.read"],
    ["ous", "OU", "ldap.ou.read"],
    ["import", "Import / Export", can("ldap.import") || can("ldap.export") ? null : "__hidden__"],
    ["schema", "Schema", "ldap.schema.read"],
    ["diagnostics", pl ? "Diagnostyka" : "Diagnostics", "ldap.diagnostics.read"],
  ];

  function table(kind: "user" | "group" | "ou") {
    const deletePermission = kind === "user" ? "ldap.users.delete" : kind === "group" ? "ldap.groups.delete" : "ldap.ou.manage";
    return <div className="infra-table-wrap"><table className="infra-table"><thead><tr><th>DN</th><th>{pl ? "Atrybuty" : "Attributes"}</th><th>{pl ? "Akcje" : "Actions"}</th></tr></thead><tbody>
      {entries.map((entry) => <tr key={entry.dn}><td><code>{entry.dn}</code></td><td>{Object.entries(entry.attributes).slice(0, 5).map(([name, value]) => <div key={name}><strong>{name}:</strong> {valueText(value)}</div>)}</td><td><div className="infra-row-actions">
        {kind === "user" && can("ldap.users.password_reset") && <button type="button" onClick={() => setPasswordTarget(entry.dn)}>{pl ? "Hasło" : "Password"}</button>}
        {kind === "group" && can("ldap.groups.update") && <button type="button" onClick={() => setSelectedGroupDn(entry.dn)}>{pl ? "Członkowie" : "Members"}</button>}
        {can(deletePermission) && <button type="button" onClick={() => void deleteObject(kind, entry.dn)}><Trash2 /> {pl ? "Usuń" : "Delete"}</button>}
      </div></td></tr>)}
      {!entries.length && <tr><td colSpan={3}>{loading ? (pl ? "Ładowanie…" : "Loading…") : (pl ? "Brak danych" : "No entries")}</td></tr>}
    </tbody></table></div>;
  }

  return <section className="infra-manager">
    <header className="infra-manager-header">
      <div><h2><Network /> LDAP Manager</h2><p>{pl ? "Zdalne zarządzanie katalogami LDAP, Active Directory i FreeIPA. Ta konfiguracja nie jest używana do logowania do WebNAS." : "Remote administration for LDAP, Active Directory and FreeIPA. These connections are not used for WebNAS sign-in."}</p></div>
      <div className="infra-manager-toolbar">
        <select aria-label="LDAP connection" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}><option value="">{pl ? "Wybierz połączenie" : "Select connection"}</option>{connections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        <button type="button" onClick={() => void loadConnections()}><RefreshCw /> {pl ? "Odśwież" : "Refresh"}</button>
      </div>
    </header>

    <nav className="infra-tabs">{tabs.filter(([, , permission]) => permission !== "__hidden__" && (!permission || can(permission))).map(([id, label]) => <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>)}</nav>

    {tab === "overview" && <div className="infra-panel">
      {!selected ? <p>{pl ? "Dodaj lub wybierz connection." : "Add or select a connection."}</p> : <>
        <div className="infra-stat-grid"><div className="infra-stat"><strong>{overview?.status || "—"}</strong><small>Status</small></div><div className="infra-stat"><strong>{overview?.primary_server || "—"}</strong><small>Server</small></div><div className="infra-stat"><strong>{overview?.latency_ms == null ? "—" : `${overview.latency_ms} ms`}</strong><small>Latency</small></div><div className="infra-stat"><strong>{overview?.users ?? "—"}</strong><small>Users</small></div><div className="infra-stat"><strong>{overview?.groups ?? "—"}</strong><small>Groups</small></div><div className="infra-stat"><strong>{overview?.organizational_units ?? "—"}</strong><small>OU</small></div></div>
        <p><strong>Directory:</strong> {selected.directory_type} · <strong>Base DN:</strong> <code>{selected.base_dn}</code></p>
      </>}
    </div>}

    {tab === "connections" && <div className="infra-panel"><div className="infra-manager-toolbar"><button type="button" onClick={() => editConnection()} disabled={!can("ldap.connections.manage")}><Plus /> {pl ? "Nowe połączenie" : "New connection"}</button>{connections.map((item) => <button key={item.id} type="button" onClick={() => editConnection(item)}>{item.name}</button>)}</div>
      {can("ldap.connections.manage") && <div className="infra-form-grid">
        <label>Name<input value={connectionForm.name} onChange={(event) => setConnectionForm({ ...connectionForm, name: event.target.value })} /></label>
        <label>Type<select value={connectionForm.directory_type} onChange={(event) => setConnectionForm({ ...connectionForm, directory_type: event.target.value as ConnectionPayload["directory_type"] })}><option value="generic">Generic LDAP</option><option value="ldap">OpenLDAP</option><option value="active_directory">Active Directory</option><option value="freeipa">FreeIPA</option></select></label>
        <label>Server<input value={connectionForm.servers[0]?.host || ""} onChange={(event) => setConnectionForm({ ...connectionForm, servers: [{ ...(connectionForm.servers[0] || { port: 389, priority: 10 }), host: event.target.value }] })} /></label>
        <label>Port<input type="number" value={connectionForm.servers[0]?.port || 389} onChange={(event) => setConnectionForm({ ...connectionForm, servers: [{ ...(connectionForm.servers[0] || { host: "", priority: 10 }), port: Number(event.target.value) }] })} /></label>
        <label>Security<select value={connectionForm.security_mode} onChange={(event) => setConnectionForm({ ...connectionForm, security_mode: event.target.value as ConnectionPayload["security_mode"] })}><option value="ldap">LDAP</option><option value="starttls">StartTLS</option><option value="ldaps">LDAPS</option></select></label>
        <label>Base DN<input value={connectionForm.base_dn} onChange={(event) => setConnectionForm({ ...connectionForm, base_dn: event.target.value })} /></label>
        <label>Bind DN<input value={connectionForm.bind_dn} onChange={(event) => setConnectionForm({ ...connectionForm, bind_dn: event.target.value })} /></label>
        <label>Bind password<input type="password" autoComplete="new-password" value={connectionForm.bind_password || ""} placeholder={editingId ? (pl ? "Pozostaw puste, aby zachować" : "Leave blank to keep") : ""} onChange={(event) => setConnectionForm({ ...connectionForm, bind_password: event.target.value })} /></label>
        <label><input type="checkbox" checked={connectionForm.verify_tls} onChange={(event) => setConnectionForm({ ...connectionForm, verify_tls: event.target.checked })} /> Verify TLS certificate</label>
        <label>Custom CA<textarea value={connectionForm.ca_certificate} onChange={(event) => setConnectionForm({ ...connectionForm, ca_certificate: event.target.value })} /></label>
        <div className="infra-row-actions"><button type="button" onClick={() => void saveConnection()}><Save /> {pl ? "Zapisz" : "Save"}</button>{editingId && <button type="button" onClick={() => { const item = connections.find((entry) => entry.id === editingId); if (item) void deleteConnection(item); }}><Trash2 /> {pl ? "Usuń" : "Delete"}</button>}</div>
      </div>}
    </div>}

    {tab === "directory" && <div className="infra-panel"><div className="infra-manager-toolbar"><input placeholder="Base DN" value={directoryBase} onChange={(event) => setDirectoryBase(event.target.value)} /><input placeholder="LDAP filter" value={directoryFilter} onChange={(event) => setDirectoryFilter(event.target.value)} /><button type="button" onClick={() => void runDirectorySearch()}><Search /> Search</button></div>{table("ou")}</div>}

    {(tab === "users" || tab === "groups" || tab === "ous") && <div className="infra-panel">
      <div className="infra-manager-toolbar"><input placeholder={pl ? "Szukaj" : "Search"} value={searchText} onChange={(event) => setSearchText(event.target.value)} /><button type="button" onClick={() => void loadList(tab)}><Search /> Search</button></div>
      {((tab === "users" && can("ldap.users.create")) || (tab === "groups" && can("ldap.groups.create")) || (tab === "ous" && can("ldap.ou.manage"))) && <div className="infra-form-grid"><label>DN<input value={objectDn} onChange={(event) => setObjectDn(event.target.value)} /></label>{tab !== "ous" && <label>{tab === "users" ? "Username" : "Group ID"}<input value={objectUid} onChange={(event) => setObjectUid(event.target.value)} /></label>}<label>{tab === "ous" ? "OU" : "CN"}<input value={objectCn} onChange={(event) => setObjectCn(event.target.value)} /></label>{tab === "users" && <><label>SN<input value={objectSn} onChange={(event) => setObjectSn(event.target.value)} /></label><label>Email<input value={objectMail} onChange={(event) => setObjectMail(event.target.value)} /></label></>}<button type="button" onClick={() => void createObject(tab === "users" ? "user" : tab === "groups" ? "group" : "ou")}><Plus /> {pl ? "Utwórz" : "Create"}</button></div>}
      {table(tab === "users" ? "user" : tab === "groups" ? "group" : "ou")}
      {tab === "users" && passwordTarget && <div className="infra-form-grid"><strong>{passwordTarget}</strong><label>{pl ? "Nowe hasło" : "New password"}<input type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></label><label><input type="checkbox" checked={forcePasswordChange} onChange={(event) => setForcePasswordChange(event.target.checked)} /> {pl ? "Wymuś zmianę przy następnym logowaniu" : "Force change at next sign-in"}</label><button type="button" onClick={() => void resetPassword()}>{pl ? "Resetuj hasło" : "Reset password"}</button></div>}
      {tab === "groups" && selectedGroupDn && <div className="infra-form-grid"><strong>{selectedGroupDn}</strong><label>Member DN<input value={groupMemberDn} onChange={(event) => setGroupMemberDn(event.target.value)} /></label><button type="button" onClick={() => void addMembership()}>{pl ? "Dodaj członka" : "Add member"}</button></div>}
    </div>}

    {tab === "import" && <div className="infra-panel"><h3>CSV Import</h3>{can("ldap.import") && <><textarea rows={10} value={csvText} onChange={(event) => setCsvText(event.target.value)} placeholder="dn,objectClass,uid,cn,sn,mail" /><div className="infra-row-actions"><button type="button" onClick={() => void runImport(true)}>Preview / dry-run</button><button type="button" onClick={() => void runImport(false)}>Execute</button></div>{importResult && <pre>{JSON.stringify(importResult, null, 2)}</pre>}</>}{can("ldap.export") && selectedId && <div><h3>Export</h3><div className="infra-row-actions"><a href={`/api/modules/ldap-manager/connections/${encodeURIComponent(selectedId)}/export/csv?kind=users`} target="_blank" rel="noreferrer">Users CSV</a><a href={`/api/modules/ldap-manager/connections/${encodeURIComponent(selectedId)}/export/csv?kind=groups`} target="_blank" rel="noreferrer">Groups CSV</a></div></div>} {can("ldap.bulk.execute") && <div><h3>Bulk operations</h3><select value={bulkAction} onChange={(event) => setBulkAction(event.target.value)}><option value="enable">Enable</option><option value="disable">Disable</option><option value="export">Validate/export selection</option></select><textarea rows={8} value={bulkDns} onChange={(event) => setBulkDns(event.target.value)} placeholder="One DN per line" /><div className="infra-row-actions"><button type="button" onClick={() => void runBulk(true)}>Preview</button><button type="button" onClick={() => void runBulk(false)}>Execute</button></div>{bulkResult && <pre>{JSON.stringify(bulkResult, null, 2)}</pre>}</div>}</div>}

    {tab === "schema" && <div className="infra-panel"><h3>Schema Browser</h3>{schema ? <pre>{JSON.stringify(schema, null, 2)}</pre> : <p>{pl ? "Schema niedostępna lub ładowanie." : "Schema unavailable or loading."}</p>}</div>}
    {tab === "diagnostics" && <div className="infra-panel"><div className="infra-manager-toolbar"><button type="button" onClick={() => selectedId && void ldapManagerClient.diagnostics(selectedId).then(setDiagnostics).catch((error) => toast(message(error), "error"))}><RefreshCw /> {pl ? "Uruchom diagnostykę" : "Run diagnostics"}</button></div>{diagnostics && <pre>{JSON.stringify(diagnostics, null, 2)}</pre>}</div>}
  </section>;
}
