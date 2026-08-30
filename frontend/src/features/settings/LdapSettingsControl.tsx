import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Database, KeyRound, LoaderCircle, Plus, PlugZap, RefreshCw, Search, Server, ShieldCheck, Trash2 } from "lucide-react";
import type { ToastFn } from "../../app/types";
import { request } from "../../core/api/transport";
import "../../styles/authentication-settings.css";

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

function cloneDraft(value: LdapDraft): LdapDraft {
  return { ...value, servers: value.servers.map((server) => ({ ...server })) };
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
    setSaved(cloneDraft(next));
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
      setSaved(cloneDraft(next));
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

  const field = (
    label: string,
    value: string | number,
    onChange: (value: string) => void,
    type: "text" | "number" | "password" = "text",
    placeholder = "",
    hint = "",
    wide = false,
    technical = false,
  ) => <label className={`ldap-field ${wide ? "ldap-field--wide" : ""} ${technical ? "ldap-code" : ""}`}>
    <span>{label}</span>
    <input type={type} placeholder={placeholder} value={value} onChange={(event) => onChange(event.target.value)} />
    {hint && <small>{hint}</small>}
  </label>;

  const dirty = Boolean(draft && saved && JSON.stringify(draft) !== JSON.stringify(saved));
  const invalid = draft ? configurationError(draft, pl) : null;
  const enabledServers = draft?.servers.filter((server) => server.enabled && server.host.trim()).length ?? 0;
  const transport = draft?.security_mode === "ldaps" ? "LDAPS" : draft?.security_mode === "starttls" ? "LDAP + StartTLS" : "LDAP";
  const configurationComplete = Boolean(draft && (enabledServers > 0 || draft.dns_srv_domain.trim()) && draft.base_dn.trim() && draft.user_search_base.trim() && draft.bind_dn.trim() && !invalid);
  const sectionItems: Array<{ id: Section; label: string; icon: React.ReactNode }> = [
    { id: "status", label: "Status", icon: <ShieldCheck size={15} /> },
    { id: "connection", label: pl ? "Połączenie" : "Connection", icon: <Server size={15} /> },
    { id: "search", label: pl ? "Wyszukiwanie" : "Search", icon: <Search size={15} /> },
    { id: "access", label: "Access / RBAC", icon: <ShieldCheck size={15} /> },
    { id: "advanced", label: "Advanced", icon: <Database size={15} /> },
    { id: "diagnostics", label: pl ? "Diagnostyka" : "Diagnostics", icon: <PlugZap size={15} /> },
  ];

  const card = active && target ? createPortal(
    <div className="ldap-settings-shell" data-testid="ldap-settings-card">
      {loading && !draft ? <section className="ldap-panel ldap-section"><span className="ldap-inline-status"><LoaderCircle className="spin" size={18} />{pl ? "Wczytywanie konfiguracji LDAP…" : "Loading LDAP configuration…"}</span></section> : loadError && !draft ? <section className="ldap-panel ldap-section">
        <div className="ldap-section__header"><h3>{pl ? "Nie udało się wczytać LDAP" : "Could not load LDAP"}</h3><p>{loadError}</p></div>
        <button type="button" onClick={() => void load()}><RefreshCw size={16} /> {pl ? "Spróbuj ponownie" : "Retry"}</button>
      </section> : draft ? <>
        <section className="ldap-panel">
          <div className="ldap-hero">
            <div className="ldap-hero__top">
              <div className="ldap-hero__title">
                <h3><KeyRound size={18} /> LDAP Authentication</h3>
                <p>{pl ? "Centralne uwierzytelnianie użytkowników WebNAS. Administracja katalogiem pozostaje w osobnym module LDAP Manager." : "Central directory authentication for WebNAS users. Directory administration remains in the separate LDAP Manager module."}</p>
              </div>
              <span className={`ldap-badge ${draft.enabled ? "ldap-badge--ok" : "ldap-badge--muted"}`}>{draft.enabled ? (pl ? "Enabled" : "Enabled") : (pl ? "Disabled" : "Disabled")}</span>
            </div>
            <div className="ldap-summary-grid">
              <div className="ldap-summary-item"><small>{pl ? "Serwery" : "Servers"}</small><strong>{draft.dns_srv_domain.trim() ? "DNS SRV" : `${enabledServers} ${pl ? "aktywnych" : "active"}`}</strong></div>
              <div className="ldap-summary-item"><small>{pl ? "Transport" : "Transport"}</small><strong>{transport}</strong></div>
              <div className="ldap-summary-item"><small>{pl ? "Credentials" : "Credentials"}</small><strong>{draft.bind_password_configured ? (pl ? "Configured" : "Configured") : (pl ? "Missing" : "Missing")}</strong></div>
              <div className="ldap-summary-item"><small>{pl ? "Konfiguracja" : "Configuration"}</small><strong>{configurationComplete ? (pl ? "Complete" : "Complete") : (pl ? "Incomplete" : "Incomplete")}</strong></div>
            </div>
          </div>
          <nav className="ldap-tabs" aria-label="LDAP settings sections">
            {sectionItems.map((item) => <button key={item.id} type="button" className={section === item.id ? "active" : ""} aria-current={section === item.id ? "page" : undefined} onClick={() => setSection(item.id)}>{item.icon}{item.label}</button>)}
          </nav>
        </section>

        <section className="ldap-panel">
          {section === "status" && <div className="ldap-section">
            <div className="ldap-section__header"><h3>Status</h3><p>{pl ? "Stan uwierzytelniania LDAP i gotowość konfiguracji." : "LDAP authentication state and configuration readiness."}</p></div>
            {!configurationComplete && <div className="ldap-warning"><strong>{pl ? "Configuration incomplete" : "Configuration incomplete"}</strong><div>{invalid || (pl ? "Uzupełnij serwer lub DNS SRV, Base DN, User Search Base i Bind DN przed włączeniem LDAP." : "Complete server or DNS SRV, Base DN, User Search Base and Bind DN before enabling LDAP.")}</div></div>}
            <div className="ldap-status-grid">
              <div className="ldap-status-card"><small>LDAP status</small><strong>{draft.enabled ? "Enabled" : "Disabled"}</strong></div>
              <div className="ldap-status-card"><small>{pl ? "Konfiguracja" : "Configuration"}</small><strong>{configurationComplete ? "Complete" : "Missing settings"}</strong></div>
              <div className="ldap-status-card"><small>{pl ? "Serwery" : "Servers"}</small><strong>{enabledServers} / {draft.servers.length} active</strong></div>
              <div className="ldap-status-card"><small>Transport</small><strong>{transport}</strong></div>
              <div className="ldap-status-card"><small>Bind credentials</small><strong>{draft.bind_password_configured ? "Configured" : "Missing"}</strong></div>
              <div className="ldap-status-card"><small>Access policy</small><strong>{policy.mode === "allow_all" ? "Allow all" : "Mapped groups"}</strong></div>
            </div>
            <div className="ldap-switch-row">
              <div><strong>{pl ? "Włącz LDAP Authentication" : "Enable LDAP Authentication"}</strong><small>{pl ? "Aktywacja wykonuje preflight konfiguracji. PAM pozostaje osobnym providerem." : "Activation runs a configuration preflight. PAM remains a separate provider."}</small></div>
              <label className="settings-switch"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked, clear_bind_password: false })} /><span aria-hidden="true" /></label>
            </div>
          </div>}

          {section === "connection" && <div className="ldap-section">
            <div className="ldap-section__header"><h3>{pl ? "Połączenie" : "Connection"}</h3><p>{pl ? "Serwery katalogowe i podstawowy transport LDAP." : "Directory servers and primary LDAP transport."}</p></div>
            <div className="ldap-form-section">
              <h4>Directory</h4>
              <div className="ldap-form-grid">
                <label className="ldap-field"><span>Directory type</span><select value={draft.directory_type} onChange={(event) => setDraft({ ...draft, directory_type: event.target.value as DirectoryType })}><option value="auto">Auto</option><option value="ldap">OpenLDAP</option><option value="active_directory">Active Directory</option><option value="freeipa">FreeIPA</option></select></label>
                <label className="ldap-field"><span>Security</span><select value={draft.security_mode} onChange={(event) => changeSecurityMode(event.target.value as SecurityMode)}><option value="ldap">LDAP</option><option value="starttls">LDAP + StartTLS</option><option value="ldaps">LDAPS</option></select></label>
              </div>
            </div>
            <div className="ldap-form-section">
              <div className="ldap-panel__heading" style={{ padding: 0 }}><div><h4 style={{ margin: 0 }}>LDAP Servers</h4><p>{pl ? "Priorytet i failover dotyczą serwerów tego samego providera." : "Priority and failover apply to servers of the same provider."}</p></div><button type="button" onClick={addServer}><Plus size={16} /> {pl ? "Dodaj serwer" : "Add server"}</button></div>
              <div className="ldap-table-wrap">
                <table className="ldap-table">
                  <thead><tr><th>Host</th><th>Port</th><th>Priority</th><th>Status</th><th>{pl ? "Akcje" : "Actions"}</th></tr></thead>
                  <tbody>{draft.servers.map((server, index) => <tr key={server.id || `new-${index}`}>
                    <td><input aria-label={`LDAP server ${index + 1}`} placeholder="ldap01.company.local" value={server.host} onChange={(event) => updateServer(index, { host: event.target.value })} /></td>
                    <td><input aria-label={`LDAP port ${index + 1}`} type="number" min={1} max={65535} value={server.port} onChange={(event) => updateServer(index, { port: Number(event.target.value) })} /></td>
                    <td><input aria-label={`LDAP priority ${index + 1}`} type="number" min={0} max={65535} value={server.priority} onChange={(event) => updateServer(index, { priority: Number(event.target.value) })} /></td>
                    <td><label className="settings-switch" title={pl ? "Aktywny" : "Enabled"}><input type="checkbox" checked={server.enabled} onChange={(event) => updateServer(index, { enabled: event.target.checked })} /><span aria-hidden="true" /></label></td>
                    <td><div className="ldap-server-actions"><button type="button" className="ldap-icon-button" aria-label={`Remove LDAP server ${index + 1}`} onClick={() => removeServer(index)}><Trash2 size={15} /></button></div></td>
                  </tr>)}</tbody>
                </table>
              </div>
            </div>
            <div className="ldap-form-section">
              <h4>{pl ? "TLS" : "TLS"}</h4>
              <div className="ldap-switch-row"><div><strong>Verify TLS certificate</strong><small>{pl ? "Wyłączaj tylko w kontrolowanym środowisku testowym." : "Disable only in a controlled test environment."}</small></div><label className="settings-switch"><input type="checkbox" checked={draft.verify_tls} onChange={(event) => setDraft({ ...draft, verify_tls: event.target.checked })} /><span aria-hidden="true" /></label></div>
            </div>
          </div>}

          {section === "search" && <div className="ldap-section">
            <div className="ldap-section__header"><h3>{pl ? "Wyszukiwanie i identity mapping" : "Search and identity mapping"}</h3><p>{pl ? "Bazy wyszukiwania, filtry i mapowanie atrybutów użytkownika oraz grup." : "Search bases, filters and user/group attribute mapping."}</p></div>
            <div className="ldap-form-section"><h4>User search</h4><div className="ldap-form-grid">
              {field("Base DN", draft.base_dn, (value) => setDraft({ ...draft, base_dn: value }), "text", "dc=company,dc=local", "", true, true)}
              {field("User Search Base", draft.user_search_base, (value) => setDraft({ ...draft, user_search_base: value }), "text", "ou=People,dc=company,dc=local", "", true, true)}
              {field("User Search Filter", draft.user_search_filter, (value) => setDraft({ ...draft, user_search_filter: value }), "text", "(uid={username})", pl ? "Dokładnie jeden znacznik {username}." : "Exactly one {username} placeholder.", true, true)}
              {field("Username Attribute", draft.username_attribute, (value) => setDraft({ ...draft, username_attribute: value }))}
              {field("Immutable ID Attribute", draft.immutable_id_attribute, (value) => setDraft({ ...draft, immutable_id_attribute: value }), "text", "", pl ? "Puste = automatyczne objectGUID/entryUUID." : "Blank = automatic objectGUID/entryUUID.")}
            </div></div>
            <div className="ldap-form-section"><h4>User attributes</h4><div className="ldap-form-grid">
              {field("Display Name Attribute", draft.display_name_attribute, (value) => setDraft({ ...draft, display_name_attribute: value }))}
              {field("Email Attribute", draft.email_attribute, (value) => setDraft({ ...draft, email_attribute: value }))}
            </div></div>
            <div className="ldap-form-section"><h4>Group search</h4><div className="ldap-form-grid">
              {field("Group Search Base", draft.group_search_base, (value) => setDraft({ ...draft, group_search_base: value }), "text", "ou=Groups,dc=company,dc=local", "", true, true)}
              {field("Group Search Filter", draft.group_search_filter, (value) => setDraft({ ...draft, group_search_filter: value }), "text", "", pl ? "Musi zawierać {username} lub {dn}." : "Must contain {username} or {dn}.", true, true)}
              {field("Group membership attribute", draft.group_membership_attribute, (value) => setDraft({ ...draft, group_membership_attribute: value }))}
            </div></div>
          </div>}

          {section === "access" && <div className="ldap-section">
            <div className="ldap-section__header"><h3>Access Policy / LDAP Group → WebNAS RBAC</h3><p>{pl ? "Deny ma pierwszeństwo przed allow. Mapowania zasilają istniejący WebNAS Identity/RBAC." : "Deny takes precedence over allow. Mappings feed the existing WebNAS Identity/RBAC system."}</p></div>
            <div className="ldap-form-section"><h4>Access Policy</h4><div className="ldap-form-grid">
              <label className="ldap-field"><span>Policy mode</span><select value={policy.mode} onChange={(event) => setPolicy({ ...policy, mode: event.target.value as AccessPolicy["mode"] })}><option value="allow_all">Allow all matched LDAP users</option><option value="mapped_groups">Allow only mapped LDAP groups</option></select></label>
              {field("Allow groups", policy.allow_groups.join(", "), (value) => setPolicy({ ...policy, allow_groups: csvList(value) }))}
              {field("Deny groups", policy.deny_groups.join(", "), (value) => setPolicy({ ...policy, deny_groups: csvList(value) }), "text", "", "", true)}
            </div><div className="settings-actions"><button type="button" onClick={() => void savePolicy()}>Save access policy</button></div></div>
            <div className="ldap-form-section"><div className="ldap-panel__heading" style={{ padding: 0 }}><div><h4 style={{ margin: 0 }}>Group mappings</h4></div></div>
              <div className="ldap-table-wrap"><table className="ldap-table"><thead><tr><th>LDAP Group</th><th>WebNAS Role</th><th>Priority</th><th>Allow / Deny</th><th>{pl ? "Akcje" : "Actions"}</th></tr></thead><tbody>
                {mappings.map((item) => <tr key={item.id}><td><strong>{item.group_dn}</strong></td><td><span className="ldap-badge ldap-badge--muted">{item.role}</span></td><td>{item.priority}</td><td><small>allow: {item.allow.join(", ") || "—"}<br />deny: {item.deny.join(", ") || "—"}</small></td><td><button type="button" className="ldap-icon-button" aria-label={`Remove ${item.group_dn}`} onClick={() => void removeMapping(item.id)}><Trash2 size={15} /></button></td></tr>)}
              </tbody></table></div>
              <div className="ldap-mapping-form"><div className="ldap-form-grid">
                {field("LDAP group DN", mappingDn, setMappingDn, "text", "CN=WebNAS-Operators,OU=Groups,DC=company,DC=local", "", true, true)}
                <label className="ldap-field"><span>WebNAS role</span><select value={mappingRole} onChange={(event) => setMappingRole(event.target.value as GroupMapping["role"])}><option value="user">user</option><option value="auditor">auditor</option><option value="operator">operator</option><option value="admin">admin</option></select></label>
                {field("Allow permissions", mappingAllow, setMappingAllow, "text", "storage.read, files.read")}
                {field("Deny permissions", mappingDeny, setMappingDeny, "text", "users.manage")}
              </div><div className="settings-actions"><button type="button" disabled={!mappingDn.trim()} onClick={() => void addMapping()}><Plus size={16} /> Add group mapping</button></div></div>
            </div>
          </div>}

          {section === "advanced" && <div className="ldap-section">
            <div className="ldap-section__header"><h3>Advanced</h3><p>{pl ? "Zmieniaj te opcje tylko wtedy, gdy wymaga tego środowisko katalogowe." : "Change these options only if required by your directory environment."}</p></div>
            <div className="ldap-form-section"><h4>Service bind</h4><div className="ldap-form-grid">
              {field("Bind DN", draft.bind_dn, (value) => setDraft({ ...draft, bind_dn: value }), "text", "cn=webnas,ou=Service Accounts,dc=company,dc=local", "", true, true)}
              <label className="ldap-field ldap-field--wide"><span>Bind Password</span><input type="password" autoComplete="new-password" value={draft.bind_password} onChange={(event) => setDraft({ ...draft, bind_password: event.target.value, clear_bind_password: false })} />{draft.bind_password_configured && <small>{pl ? "Sekret jest zapisany. API nie zwraca jego wartości." : "Secret is stored. The API never returns its value."}</small>}</label>
              {draft.bind_password_configured && !draft.enabled && <div className="ldap-switch-row ldap-field--wide"><div><strong>{pl ? "Usuń zapisany Bind Password" : "Clear stored Bind Password"}</strong></div><label className="settings-switch"><input type="checkbox" checked={draft.clear_bind_password} onChange={(event) => setDraft({ ...draft, clear_bind_password: event.target.checked, bind_password: "" })} /><span aria-hidden="true" /></label></div>}
            </div></div>
            <div className="ldap-form-section"><h4>Failover and discovery</h4><div className="ldap-form-grid">
              <label className="ldap-field"><span>Failover</span><select value={draft.failover_strategy} onChange={(event) => setDraft({ ...draft, failover_strategy: event.target.value as FailoverStrategy })}><option value="priority">Priority</option><option value="round_robin">Round robin</option></select></label>
              {field("DNS SRV discovery", draft.dns_srv_domain, (value) => setDraft({ ...draft, dns_srv_domain: value }), "text", "_ldap._tcp.dc._msdcs.company.local", "", false, true)}
            </div></div>
            <div className="ldap-form-section"><h4>Timeouts and cache</h4><div className="ldap-form-grid">
              {field("Connect timeout (s)", draft.connect_timeout, (value) => setDraft({ ...draft, connect_timeout: Number(value) }), "number")}
              {field("Operation timeout (s)", draft.operation_timeout, (value) => setDraft({ ...draft, operation_timeout: Number(value) }), "number")}
              {field("Group cache TTL (s)", draft.group_cache_ttl_seconds, (value) => setDraft({ ...draft, group_cache_ttl_seconds: Number(value) }), "number")}
            </div></div>
            <div className="ldap-form-section"><h4>Certificate authority</h4><label className="ldap-field ldap-field--wide ldap-code"><span>Custom CA certificate</span><textarea className="ldap-textarea" value={draft.ca_certificate} onChange={(event) => setDraft({ ...draft, ca_certificate: event.target.value })} placeholder="-----BEGIN CERTIFICATE-----" /></label></div>
          </div>}

          {section === "diagnostics" && <div className="ldap-section">
            <div className="ldap-section__header"><h3>{pl ? "LDAP diagnostics" : "LDAP diagnostics"}</h3><p>DNS → TCP → TLS → certificate → service bind → Base DN → user search → group lookup → NSS → UID/GID/home → RBAC mapping.</p></div>
            <div className="ldap-form-grid">{field(pl ? "Opcjonalny użytkownik testowy" : "Optional test username", diagnosticUser, setDiagnosticUser, "text", "test.user", "", true)}</div>
            {dirty && <div className="ldap-warning">{pl ? "Zapisz zmiany przed uruchomieniem diagnostyki. Diagnostyka używa ostatnio zapisanej konfiguracji." : "Save changes before running diagnostics. Diagnostics uses the last saved configuration."}</div>}
            <div className="settings-actions"><button type="button" disabled={testing || dirty || !draft.bind_password_configured} onClick={() => void runDiagnostics()}>{testing ? <LoaderCircle className="spin" size={16} /> : <PlugZap size={16} />}{testing ? (pl ? "Testowanie…" : "Testing…") : "Run diagnostics"}</button></div>
            {diagnostics && <div className="ldap-diagnostic-list">{diagnostics.steps.map((step) => <div className="ldap-diagnostic-row" key={`${step.name}-${step.detail}`}><strong>{step.name}</strong><span className={`ldap-badge ${step.status === "ok" ? "ldap-badge--ok" : "ldap-badge--muted"}`}>{step.status.toUpperCase()}</span><small>{step.detail}</small></div>)}<div className="ldap-status-card"><small>Overall</small><strong>{diagnostics.overall.toUpperCase()}</strong></div></div>}
          </div>}

          <div className="ldap-action-bar">
            <span className="ldap-inline-status">{invalid ? invalid : dirty ? (pl ? "Niezapisane zmiany" : "Unsaved changes") : (pl ? "Wszystkie zmiany zapisane" : "All changes saved")}</span>
            <div className="ldap-action-bar__actions">
              <button type="button" disabled={loading || !dirty} onClick={() => saved && setDraft(cloneDraft(saved))}><RefreshCw size={16} />{pl ? "Odrzuć" : "Discard"}</button>
              <button className="button-primary" type="button" disabled={saving || testing || Boolean(invalid) || !dirty} onClick={() => void saveSettings()}>{saving ? <LoaderCircle className="spin" size={16} /> : <KeyRound size={16} />}{saving ? (pl ? "Zapisywanie…" : "Saving…") : (pl ? "Zapisz zmiany" : "Save changes")}</button>
            </div>
          </div>
        </section>
      </> : null}
    </div>,
    target,
  ) : null;

  return <><span ref={anchorRef} style={{ display: "none" }} />{card}</>;
}
