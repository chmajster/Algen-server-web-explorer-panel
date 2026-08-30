import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Database, KeyRound, LoaderCircle, Plus, PlugZap, RefreshCw, Search, Server, ShieldCheck, Trash2 } from "lucide-react";
import type { ToastFn } from "../../app/types";
import { request } from "../../core/api/transport";

type SecurityMode = "ldap" | "starttls" | "ldaps";
type FailoverStrategy = "priority" | "round_robin";
type DirectoryType = "auto" | "ldap" | "active_directory" | "freeipa";
type Section = "status" | "connection" | "search" | "access" | "advanced" | "diagnostics";
type LdapServer = { id: string; host: string; port: number; priority: number; enabled: boolean };
type LdapSettings = {
  enabled: boolean;
  directory_type: DirectoryType;
  servers: LdapServer[];
  server: string;
  port: number;
  failover_strategy: FailoverStrategy;
  dns_srv_domain: string;
  security_mode: SecurityMode;
  verify_tls: boolean;
  ca_certificate: string;
  connect_timeout: number;
  operation_timeout: number;
  base_dn: string;
  user_search_base: string;
  user_search_filter: string;
  username_attribute: string;
  immutable_id_attribute: string;
  bind_dn: string;
  bind_password_configured: boolean;
  display_name_attribute: string;
  email_attribute: string;
  group_search_base: string;
  group_search_filter: string;
  group_membership_attribute: string;
  group_cache_ttl_seconds: number;
};
type LdapDraft = LdapSettings & { bind_password: string; clear_bind_password: boolean };
type GroupMapping = { id: string; group_dn: string; role: "admin" | "operator" | "auditor" | "user"; allow: string[]; deny: string[]; priority: number };
type AccessPolicy = { mode: "allow_all" | "mapped_groups"; allow_groups: string[]; deny_groups: string[] };
type DiagnosticStep = { name: string; status: "ok" | "warning" | "error" | "skipped"; detail: string };
type DiagnosticResult = { overall: string; server: string; steps: DiagnosticStep[]; identity: Record<string, string | number | null> };
type Props = { active: boolean; locale: string; toast: ToastFn };

function toDraft(value: LdapSettings): LdapDraft {
  const servers = value.servers?.length
    ? value.servers
    : value.server
      ? [{ id: "", host: value.server, port: value.port || 389, priority: 10, enabled: true }]
      : [];
  return { ...value, servers, bind_password: "", clear_bind_password: false };
}

function csvList(value: string): string[] {
  return value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
}

function configurationError(value: LdapDraft, pl: boolean): string | null {
  const usernamePlaceholders = value.user_search_filter.match(/\{username\}/g)?.length ?? 0;
  if (usernamePlaceholders !== 1) {
    return pl
      ? "User Search Filter musi zawierać dokładnie jeden znacznik {username}."
      : "User Search Filter must contain exactly one {username} placeholder.";
  }
  if (value.group_search_filter && !value.group_search_filter.includes("{username}") && !value.group_search_filter.includes("{dn}")) {
    return pl
      ? "Group Search Filter musi zawierać {username} lub {dn}."
      : "Group Search Filter must contain {username} or {dn}.";
  }
  if (value.servers.some((server) => !server.host.trim() || !Number.isFinite(server.port) || server.port < 1 || server.port > 65535 || !Number.isFinite(server.priority) || server.priority < 0 || server.priority > 65535)) {
    return pl ? "Każdy serwer LDAP musi mieć poprawny host, port i priorytet." : "Every LDAP server must have a valid host, port, and priority.";
  }
  if (!Number.isFinite(value.connect_timeout) || value.connect_timeout < 0.5 || value.connect_timeout > 60) {
    return pl ? "Timeout połączenia musi mieścić się w zakresie 0.5–60 s." : "Connection timeout must be between 0.5 and 60 seconds.";
  }
  if (!Number.isFinite(value.operation_timeout) || value.operation_timeout < 0.5 || value.operation_timeout > 120) {
    return pl ? "Timeout operacji musi mieścić się w zakresie 0.5–120 s." : "Operation timeout must be between 0.5 and 120 seconds.";
  }
  if (!Number.isFinite(value.group_cache_ttl_seconds) || value.group_cache_ttl_seconds < 0 || value.group_cache_ttl_seconds > 86400) {
    return pl ? "Group cache TTL musi mieścić się w zakresie 0–86400 s." : "Group cache TTL must be between 0 and 86400 seconds.";
  }
  if (value.enabled) {
    const hasEnabledServer = value.servers.some((server) => server.enabled && server.host.trim());
    if (!hasEnabledServer && !value.dns_srv_domain.trim()) {
      return pl ? "Włączony LDAP wymaga aktywnego serwera albo DNS SRV discovery." : "Enabled LDAP requires an active server or DNS SRV discovery.";
    }
    if (!value.base_dn.trim() || !value.user_search_base.trim() || !value.bind_dn.trim()) {
      return pl
        ? "Przed włączeniem LDAP uzupełnij Base DN, User Search Base i Bind DN."
        : "Complete Base DN, User Search Base, and Bind DN before enabling LDAP.";
    }
  }
  return null;
}

export function LdapSettingsControl({ active, locale, toast }: Props) {
  const pl = locale.toLowerCase().startsWith("pl");
  const anchorRef = useRef<HTMLSpanElement | null>(null);
  const [target, setTarget] = useState<Element | null>(null);
  const [section, setSection] = useState<Section>("status");
  const [draft, setDraft] = useState<LdapDraft | null>(null);
  const [saved, setSaved] = useState<LdapDraft | null>(null);
  const [mappings, setMappings] = useState<GroupMapping[]>([]);
  const [policy, setPolicy] = useState<AccessPolicy>({ mode: "allow_all", allow_groups: [], deny_groups: [] });
  const [mappingDn, setMappingDn] = useState("");
  const [mappingRole, setMappingRole] = useState<GroupMapping["role"]>("user");
  const [mappingAllow, setMappingAllow] = useState("");
  const [mappingDeny, setMappingDeny] = useState("");
  const [diagnosticUser, setDiagnosticUser] = useState("");
  const [diagnostics, setDiagnostics] = useState<DiagnosticResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

  useEffect(() => {
    if (!active) { setTarget(null); return; }
    const root = anchorRef.current?.parentElement;
    const resolve = () => setTarget(root?.querySelector(".settings-content") || null);
    resolve();
    if (!root) return;
    const observer = new MutationObserver(resolve);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [active]);

  async function fetchData() {
    return Promise.all([
      request<LdapSettings>("/api/settings/authentication/ldap"),
      request<{ items: GroupMapping[] }>("/api/settings/authentication/ldap/group-mappings"),
      request<AccessPolicy>("/api/settings/authentication/ldap/access-policy"),
    ]);
  }

  function applyData(settings: LdapSettings, groupMappings: GroupMapping[], accessPolicy: AccessPolicy) {
    const next = toDraft(settings);
    setDraft(next);
    setSaved(next);
    setMappings(groupMappings);
    setPolicy(accessPolicy);
    setLoadError(null);
  }

  async function load() {
    setLoading(true);
    setLoadError(null);
    try {
      const [settings, groupMappings, accessPolicy] = await fetchData();
      applyData(settings, groupMappings.items, accessPolicy);
    } catch (error) {
      const message = errorText(error);
      setLoadError(message);
      toast(message, "error", "admin");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setDraft(null);
    setSaved(null);
    void fetchData().then(([settings, groupMappings, accessPolicy]) => {
      if (cancelled) return;
      applyData(settings, groupMappings.items, accessPolicy);
    }).catch((error) => {
      if (cancelled) return;
      const message = errorText(error);
      setLoadError(message);
      toast(message, "error", "admin");
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [active, toast]);

  async function saveSettings() {
    if (!draft) return;
    const invalid = configurationError(draft, pl);
    if (invalid) {
      toast(invalid, "error", "admin");
      return;
    }
    setSaving(true);
    try {
      const updated = await request<LdapSettings>("/api/settings/authentication/ldap", {
        method: "PUT",
        body: JSON.stringify({ ...draft, server: "", port: 389 }),
      });
      const next = toDraft(updated);
      setDraft(next);
      setSaved(next);
      toast(pl ? "Ustawienia LDAP Authentication zapisane." : "LDAP Authentication settings saved.", "ok", "admin");
    } catch (error) { toast(errorText(error), "error", "admin"); }
    finally { setSaving(false); }
  }

  async function runDiagnostics() {
    setTesting(true);
    try {
      const result = await request<DiagnosticResult>("/api/settings/authentication/ldap/diagnostics", {
        method: "POST",
        body: JSON.stringify({ username: diagnosticUser }),
      });
      setDiagnostics(result);
      toast(
        result.overall === "healthy"
          ? (pl ? "Diagnostyka zakończona: HEALTHY" : "Diagnostics: HEALTHY")
          : (pl ? `Diagnostyka: ${result.overall}` : `Diagnostics: ${result.overall}`),
        result.overall === "healthy" ? "ok" : "error",
        "admin",
      );
    } catch (error) { toast(errorText(error), "error", "admin"); }
    finally { setTesting(false); }
  }

  async function addMapping() {
    if (!mappingDn.trim()) return;
    try {
      await request("/api/settings/authentication/ldap/group-mappings", {
        method: "POST",
        body: JSON.stringify({ group_dn: mappingDn, role: mappingRole, allow: csvList(mappingAllow), deny: csvList(mappingDeny), priority: 100 }),
      });
      setMappingDn("");
      setMappingAllow("");
      setMappingDeny("");
      await load();
    } catch (error) { toast(errorText(error), "error", "admin"); }
  }

  async function removeMapping(id: string) {
    try {
      await request(`/api/settings/authentication/ldap/group-mappings/${encodeURIComponent(id)}`, { method: "DELETE" });
      await load();
    } catch (error) { toast(errorText(error), "error", "admin"); }
  }

  async function savePolicy() {
    try {
      const next = await request<AccessPolicy>("/api/settings/authentication/ldap/access-policy", { method: "PUT", body: JSON.stringify(policy) });
      setPolicy(next);
      toast(pl ? "Access policy zapisane; istniejące sesje LDAP unieważniono." : "Access policy saved; existing LDAP sessions were invalidated.", "ok", "admin");
    } catch (error) { toast(errorText(error), "error", "admin"); }
  }

  const field = (
    label: string,
    value: string | number,
    onChange: (value: string) => void,
    type: "text" | "number" | "password" = "text",
    placeholder = "",
    hint = "",
  ) => <div className="setting-row">
    <div><strong>{label}</strong>{hint && <small>{hint}</small>}</div>
    <div className="setting-control"><input type={type} placeholder={placeholder} value={value} onChange={(event) => onChange(event.target.value)} /></div>
  </div>;

  function addServer() {
    if (!draft) return;
    setDraft({
      ...draft,
      servers: [...draft.servers, { id: "", host: "", port: draft.security_mode === "ldaps" ? 636 : 389, priority: (draft.servers.length + 1) * 10, enabled: true }],
    });
  }

  function updateServer(index: number, patch: Partial<LdapServer>) {
    if (!draft) return;
    setDraft({ ...draft, servers: draft.servers.map((server, current) => current === index ? { ...server, ...patch } : server) });
  }

  function removeServer(index: number) {
    if (!draft) return;
    setDraft({ ...draft, servers: draft.servers.filter((_, current) => current !== index) });
  }

  function changeSecurityMode(mode: SecurityMode) {
    if (!draft) return;
    setDraft({
      ...draft,
      security_mode: mode,
      servers: draft.servers.map((server) => ({
        ...server,
        port: server.port === 389 || server.port === 636 ? (mode === "ldaps" ? 636 : 389) : server.port,
      })),
    });
  }

  const dirty = Boolean(draft && saved && JSON.stringify(draft) !== JSON.stringify(saved));
  const invalid = draft ? configurationError(draft, pl) : null;
  const enabledServers = draft?.servers.filter((server) => server.enabled && server.host.trim()).length ?? 0;
  const transport = draft?.security_mode === "ldaps" ? "LDAPS" : draft?.security_mode === "starttls" ? "LDAP + StartTLS" : "LDAP";
  const sectionItems: Array<{ id: Section; label: string; icon: React.ReactNode }> = [
    { id: "status", label: "Status", icon: <ShieldCheck size={15} /> },
    { id: "connection", label: pl ? "Połączenie" : "Connection", icon: <Server size={15} /> },
    { id: "search", label: pl ? "Wyszukiwanie" : "Search", icon: <Search size={15} /> },
    { id: "access", label: "Access / RBAC", icon: <ShieldCheck size={15} /> },
    { id: "advanced", label: "Advanced", icon: <Database size={15} /> },
    { id: "diagnostics", label: pl ? "Diagnostyka" : "Diagnostics", icon: <PlugZap size={15} /> },
  ];

  const card = active && target ? createPortal(
    <div className="settings-card-stack" data-testid="ldap-settings-card">
      {loading && !draft ? <section className="settings-card" style={{ padding: "1rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}><LoaderCircle className="spin" size={18} />{pl ? "Wczytywanie konfiguracji LDAP…" : "Loading LDAP configuration…"}</div>
      </section> : loadError && !draft ? <section className="settings-card" style={{ padding: "1rem" }}>
        <h3>{pl ? "Nie udało się wczytać LDAP" : "Could not load LDAP"}</h3>
        <p>{loadError}</p>
        <div className="settings-actions"><button type="button" onClick={() => void load()}><RefreshCw size={16} /> {pl ? "Spróbuj ponownie" : "Retry"}</button></div>
      </section> : draft ? <>
        <section className="settings-card" style={{ overflow: "hidden" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem", padding: "0.9rem 1rem 0.75rem", flexWrap: "wrap" }}>
            <div style={{ minWidth: 0 }}>
              <h3 style={{ margin: 0, display: "flex", alignItems: "center", gap: "0.45rem" }}><KeyRound size={18} /> LDAP Authentication</h3>
              <p style={{ margin: "0.35rem 0 0", maxWidth: "64rem" }}>{pl ? "Wyłącznie logowanie użytkowników do WebNAS przez LDAP. Administracja katalogiem pozostaje w osobnym module LDAP Manager i używa innych credentials." : "Only authenticates users to WebNAS through LDAP. Directory administration remains in the separate LDAP Manager module and uses different credentials."}</p>
            </div>
            <span style={{ padding: "0.25rem 0.55rem", border: "1px solid var(--border-subtle)", borderRadius: "999px", background: draft.enabled ? "var(--surface-selected)" : "var(--surface-secondary)", color: draft.enabled ? "var(--accent)" : "var(--text-secondary)", fontWeight: 600 }}>
              {draft.enabled ? (pl ? "LDAP aktywny" : "LDAP enabled") : (pl ? "LDAP wyłączony" : "LDAP disabled")}
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(10rem, 1fr))", gap: "0.5rem", padding: "0.65rem 1rem", borderTop: "1px solid var(--border-subtle)" }}>
            {[
              [pl ? "Serwery" : "Servers", draft.dns_srv_domain.trim() ? `DNS SRV · ${draft.dns_srv_domain.trim()}` : `${enabledServers} ${pl ? "aktywnych" : "enabled"}`],
              [pl ? "Transport" : "Transport", transport],
              ["Bind password", draft.bind_password_configured ? (pl ? "skonfigurowany" : "configured") : (pl ? "brak" : "not configured")],
              [pl ? "Stan zmian" : "Changes", dirty ? (pl ? "niezapisane" : "unsaved") : (pl ? "zapisane" : "saved")],
            ].map(([label, value]) => <div key={label} style={{ padding: "0.55rem 0.65rem", border: "1px solid var(--border-subtle)", borderRadius: "0.55rem", minWidth: 0 }}><small style={{ display: "block", color: "var(--text-muted)" }}>{label}</small><strong style={{ overflowWrap: "anywhere" }}>{value}</strong></div>)}
          </div>
          <nav className="settings-tabs" style={{ paddingInline: "1rem", overflowX: "auto" }}>
            {sectionItems.map((item) => <button key={item.id} type="button" className={section === item.id ? "active" : ""} onClick={() => setSection(item.id)}><span style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>{item.icon}{item.label}</span></button>)}
          </nav>
        </section>

        {section === "status" && <section className="settings-card">
          <h3>Status</h3>
          <div className="setting-row"><div><strong>{pl ? "Włącz LDAP Authentication" : "Enable LDAP Authentication"}</strong><small>{pl ? "Aktywacja wykonuje preflight. Błędna konfiguracja pozostanie wyłączona. PAM jest osobnym providerem, nie fallbackiem." : "Activation runs a preflight. Invalid configuration remains disabled. PAM is a separate provider, not a fallback."}</small></div><div className="setting-control"><label className="settings-switch"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked, clear_bind_password: false })} /><span aria-hidden="true" /></label></div></div>
          <div className="setting-row"><div><strong>{pl ? "Kompletność konfiguracji" : "Configuration readiness"}</strong><small>{invalid || (pl ? "Konfiguracja jest zgodna z wymaganiami formularza." : "Configuration satisfies the form requirements.")}</small></div><div className="setting-control"><span>{invalid ? (pl ? "WYMAGA POPRAWY" : "NEEDS ATTENTION") : "OK"}</span></div></div>
        </section>}

        {section === "connection" && <section className="settings-card">
          <h3>{pl ? "Połączenie i serwery" : "Connection and servers"}</h3>
          <p>{pl ? "Failover dotyczy wyłącznie serwerów tego samego providera LDAP. Zmiana LDAP/LDAPS automatycznie przełącza standardowe porty 389/636; porty niestandardowe pozostają bez zmian." : "Failover applies only to servers of the same LDAP provider. Switching LDAP/LDAPS updates standard ports 389/636 automatically; custom ports remain unchanged."}</p>
          <div className="setting-row"><div><strong>Directory type</strong></div><div className="setting-control"><select value={draft.directory_type} onChange={(event) => setDraft({ ...draft, directory_type: event.target.value as DirectoryType })}><option value="auto">Auto</option><option value="ldap">OpenLDAP</option><option value="active_directory">Active Directory</option><option value="freeipa">FreeIPA</option></select></div></div>
          {draft.servers.map((server, index) => <div className="setting-row" key={server.id || `new-${index}`}><div><strong>LDAP server {index + 1}</strong><small>{server.enabled ? (pl ? "aktywny" : "enabled") : (pl ? "wyłączony" : "disabled")}</small></div><div className="setting-control" style={{ display: "grid", gridTemplateColumns: "minmax(11rem, 1fr) 6.5rem 6.5rem auto auto", gap: "0.35rem", alignItems: "center" }}><input aria-label={`LDAP server ${index + 1}`} placeholder="dc01.company.local" value={server.host} onChange={(event) => updateServer(index, { host: event.target.value })} /><input aria-label={`LDAP port ${index + 1}`} type="number" min={1} max={65535} value={server.port} onChange={(event) => updateServer(index, { port: Number(event.target.value) })} /><input aria-label={`LDAP priority ${index + 1}`} type="number" min={0} max={65535} value={server.priority} onChange={(event) => updateServer(index, { priority: Number(event.target.value) })} /><label className="settings-switch" title={pl ? "Aktywny" : "Enabled"}><input type="checkbox" checked={server.enabled} onChange={(event) => updateServer(index, { enabled: event.target.checked })} /><span aria-hidden="true" /></label><button type="button" aria-label={`Remove LDAP server ${index + 1}`} onClick={() => removeServer(index)}><Trash2 size={15} /></button></div></div>)}
          <div className="settings-actions"><button type="button" onClick={addServer}><Plus size={16} /> {pl ? "Dodaj serwer" : "Add server"}</button></div>
          <div className="setting-row"><div><strong>Failover</strong></div><div className="setting-control"><select value={draft.failover_strategy} onChange={(event) => setDraft({ ...draft, failover_strategy: event.target.value as FailoverStrategy })}><option value="priority">Priority</option><option value="round_robin">Round robin</option></select></div></div>
          {field("DNS SRV discovery", draft.dns_srv_domain, (value) => setDraft({ ...draft, dns_srv_domain: value }), "text", "_ldap._tcp.dc._msdcs.company.local")}
          <div className="setting-row"><div><strong>Security</strong></div><div className="setting-control"><select value={draft.security_mode} onChange={(event) => changeSecurityMode(event.target.value as SecurityMode)}><option value="ldap">LDAP</option><option value="starttls">LDAP + StartTLS</option><option value="ldaps">LDAPS</option></select></div></div>
          <div className="setting-row"><div><strong>Verify TLS certificate</strong><small>{pl ? "Wyłączaj tylko w kontrolowanych środowiskach testowych." : "Disable only in controlled test environments."}</small></div><div className="setting-control"><label className="settings-switch"><input type="checkbox" checked={draft.verify_tls} onChange={(event) => setDraft({ ...draft, verify_tls: event.target.checked })} /><span aria-hidden="true" /></label></div></div>
          {field("Connect timeout (s)", draft.connect_timeout, (value) => setDraft({ ...draft, connect_timeout: Number(value) }), "number")}
          {field("Operation timeout (s)", draft.operation_timeout, (value) => setDraft({ ...draft, operation_timeout: Number(value) }), "number")}
        </section>}

        {section === "search" && <section className="settings-card">
          <h3>{pl ? "Wyszukiwanie i identity mapping" : "Search and identity mapping"}</h3>
          {field("Base DN", draft.base_dn, (value) => setDraft({ ...draft, base_dn: value }), "text", "dc=company,dc=local")}
          {field("User Search Base", draft.user_search_base, (value) => setDraft({ ...draft, user_search_base: value }))}
          {field("User Search Filter", draft.user_search_filter, (value) => setDraft({ ...draft, user_search_filter: value }), "text", "(uid={username})", pl ? "Dokładnie jeden znacznik {username}." : "Exactly one {username} placeholder.")}
          {field("Username Attribute", draft.username_attribute, (value) => setDraft({ ...draft, username_attribute: value }))}
          {field("Immutable ID Attribute", draft.immutable_id_attribute, (value) => setDraft({ ...draft, immutable_id_attribute: value }), "text", pl ? "puste = objectGUID/entryUUID auto" : "blank = auto objectGUID/entryUUID")}
          {field("Display Name Attribute", draft.display_name_attribute, (value) => setDraft({ ...draft, display_name_attribute: value }))}
          {field("Email Attribute", draft.email_attribute, (value) => setDraft({ ...draft, email_attribute: value }))}
          {field("Group Search Base", draft.group_search_base, (value) => setDraft({ ...draft, group_search_base: value }))}
          {field("Group Search Filter", draft.group_search_filter, (value) => setDraft({ ...draft, group_search_filter: value }), "text", "", pl ? "Musi zawierać {username} lub {dn}." : "Must contain {username} or {dn}.")}
          {field("Group membership attribute", draft.group_membership_attribute, (value) => setDraft({ ...draft, group_membership_attribute: value }))}
        </section>}

        {section === "access" && <section className="settings-card">
          <h3>Access Policy / LDAP Group → WebNAS RBAC</h3>
          <p>{pl ? "Mapping zapisuje wynik do istniejącego WebNAS Identity/RBAC; deny ma pierwszeństwo przed allow." : "Mappings feed the existing WebNAS Identity/RBAC system; deny takes precedence over allow."}</p>
          <div className="setting-row"><div><strong>Policy mode</strong></div><div className="setting-control"><select value={policy.mode} onChange={(event) => setPolicy({ ...policy, mode: event.target.value as AccessPolicy["mode"] })}><option value="allow_all">Allow all matched LDAP users</option><option value="mapped_groups">Allow only mapped LDAP groups</option></select></div></div>
          {field("Allow groups", policy.allow_groups.join(", "), (value) => setPolicy({ ...policy, allow_groups: csvList(value) }))}
          {field("Deny groups", policy.deny_groups.join(", "), (value) => setPolicy({ ...policy, deny_groups: csvList(value) }))}
          <div className="settings-actions"><button type="button" onClick={() => void savePolicy()}>Save access policy</button></div>
          <h4>Group mappings</h4>
          {mappings.map((item) => <div className="setting-row" key={item.id}><div><strong>{item.group_dn}</strong><small>{item.role} · allow: {item.allow.join(", ") || "—"} · deny: {item.deny.join(", ") || "—"}</small></div><div className="setting-control"><button type="button" onClick={() => void removeMapping(item.id)}><Trash2 size={15} /></button></div></div>)}
          <div className="setting-row"><div><strong>LDAP group DN</strong></div><div className="setting-control"><input value={mappingDn} onChange={(event) => setMappingDn(event.target.value)} placeholder="CN=WebNAS-Operators,OU=Groups,DC=company,DC=local" /><select value={mappingRole} onChange={(event) => setMappingRole(event.target.value as GroupMapping["role"])}><option value="user">user</option><option value="auditor">auditor</option><option value="operator">operator</option><option value="admin">admin</option></select></div></div>
          {field("Allow permissions", mappingAllow, setMappingAllow, "text", "storage.read, files.read")}
          {field("Deny permissions", mappingDeny, setMappingDeny, "text", "users.manage")}
          <div className="settings-actions"><button type="button" onClick={() => void addMapping()}><Plus size={16} /> Add mapping</button></div>
        </section>}

        {section === "advanced" && <section className="settings-card">
          <h3>Advanced</h3>
          {field("Bind DN", draft.bind_dn, (value) => setDraft({ ...draft, bind_dn: value }))}
          <div className="setting-row"><div><strong>Bind Password</strong><small>{draft.bind_password_configured ? (pl ? "Sekret jest zapisany. API nie zwraca jego wartości." : "Secret is stored. The API never returns its value.") : ""}</small></div><div className="setting-control"><input type="password" autoComplete="new-password" value={draft.bind_password} onChange={(event) => setDraft({ ...draft, bind_password: event.target.value, clear_bind_password: false })} /></div></div>
          {draft.bind_password_configured && !draft.enabled && <div className="setting-row"><div><strong>{pl ? "Usuń zapisany Bind Password" : "Clear stored Bind Password"}</strong></div><div className="setting-control"><label className="settings-switch"><input type="checkbox" checked={draft.clear_bind_password} onChange={(event) => setDraft({ ...draft, clear_bind_password: event.target.checked, bind_password: "" })} /><span aria-hidden="true" /></label></div></div>}
          {field("Group cache TTL (s)", draft.group_cache_ttl_seconds, (value) => setDraft({ ...draft, group_cache_ttl_seconds: Number(value) }), "number")}
          <div className="setting-row"><div><strong>Custom CA certificate</strong></div><div className="setting-control"><textarea value={draft.ca_certificate} onChange={(event) => setDraft({ ...draft, ca_certificate: event.target.value })} placeholder="-----BEGIN CERTIFICATE-----" /></div></div>
        </section>}

        {section === "diagnostics" && <section className="settings-card">
          <h3>{pl ? "Diagnostyka całego chainu" : "Full-chain diagnostics"}</h3>
          <p>DNS → TCP → TLS → certificate → service bind → Base DN → user search → group lookup → NSS → UID/GID/home → RBAC mapping.</p>
          {field(pl ? "Opcjonalny użytkownik testowy" : "Optional test username", diagnosticUser, setDiagnosticUser)}
          {dirty && <p>{pl ? "Zapisz zmiany przed uruchomieniem diagnostyki. Endpoint diagnostyczny używa ostatnio zapisanej konfiguracji." : "Save changes before running diagnostics. The diagnostics endpoint uses the last saved configuration."}</p>}
          <div className="settings-actions"><button type="button" disabled={testing || dirty || !draft.bind_password_configured} onClick={() => void runDiagnostics()}>{testing ? <LoaderCircle className="spin" size={16} /> : <PlugZap size={16} />}{testing ? (pl ? "Testowanie…" : "Testing…") : "Run diagnostics"}</button></div>
          {diagnostics && <div>{diagnostics.steps.map((step) => <div className="setting-row" key={`${step.name}-${step.detail}`}><div><strong>{step.name}</strong></div><div className="setting-control"><span>{step.status.toUpperCase()}</span><small>{step.detail}</small></div></div>)}<p><strong>Overall:</strong> {diagnostics.overall.toUpperCase()}</p></div>}
        </section>}

        <section className="settings-card">
          {invalid && <p style={{ marginTop: 0 }}>{invalid}</p>}
          <div className="settings-actions"><button className="button-primary" type="button" disabled={saving || testing || Boolean(invalid)} onClick={() => void saveSettings()}>{saving ? <LoaderCircle className="spin" size={16} /> : <KeyRound size={16} />}{saving ? (pl ? "Zapisywanie…" : "Saving…") : (pl ? "Zapisz LDAP Authentication" : "Save LDAP Authentication")}</button><button type="button" disabled={loading} onClick={() => void load()}>{loading ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}{pl ? "Odśwież" : "Refresh"}</button></div>
        </section>
      </> : null}
    </div>,
    target,
  ) : null;

  return <><span ref={anchorRef} style={{ display: "none" }} />{card}</>;
}
