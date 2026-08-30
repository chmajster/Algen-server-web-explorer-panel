import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Database, KeyRound, LoaderCircle, PlugZap, Search, Server, ShieldCheck } from "lucide-react";
import type { ToastFn } from "../../app/types";
import { request } from "../../core/api/transport";

type SecurityMode = "ldap" | "starttls" | "ldaps";
type LdapSection = "connection" | "directory" | "mapping";

type LdapSettings = {
  enabled: boolean;
  server: string;
  port: number;
  security_mode: SecurityMode;
  verify_tls: boolean;
  connect_timeout: number;
  operation_timeout: number;
  base_dn: string;
  user_search_base: string;
  user_search_filter: string;
  username_attribute: string;
  bind_dn: string;
  bind_password_configured: boolean;
  display_name_attribute: string;
  email_attribute: string;
};

type LdapDraft = LdapSettings & {
  bind_password: string;
  clear_bind_password: boolean;
};

type Props = {
  active: boolean;
  locale: string;
  toast: ToastFn;
};

const copy = {
  pl: {
    title: "Logowanie LDAP",
    description: "Zewnętrzny katalog użytkowników dla trybu PAM + LDAP. Konfiguracja LDAP jest niezależna od lokalnych kont WebNAS.",
    enabled: "Włącz logowanie LDAP",
    enabledHint: "Po włączeniu LDAP pojawi się jako metoda logowania. PAM pozostaje dostępny jako alternatywa.",
    enabledStatus: "LDAP aktywny",
    disabledStatus: "LDAP wyłączony",
    connection: "Połączenie",
    connectionHint: "Adres serwera, transport TLS oraz limity czasu połączenia z katalogiem.",
    directory: "Wyszukiwanie",
    directoryHint: "Zakres katalogu i filtr używany do odnalezienia konta użytkownika.",
    mapping: "Bind i atrybuty",
    mappingHint: "Konto techniczne LDAP oraz mapowanie danych użytkownika.",
    endpoint: "Endpoint",
    transport: "Transport",
    bindSecret: "Hasło Bind",
    configured: "skonfigurowane",
    notConfigured: "brak",
    server: "Serwer LDAP / URI",
    serverHint: "Hostname albo URI ldap:// / ldaps://.",
    port: "Port",
    security: "Tryb bezpieczeństwa",
    verifyTls: "Weryfikuj certyfikat TLS",
    verifyTlsHint: "Wyłączaj tylko dla kontrolowanych środowisk testowych.",
    connectTimeout: "Timeout połączenia (s)",
    operationTimeout: "Timeout operacji (s)",
    baseDn: "Base DN",
    searchBase: "User Search Base DN",
    searchFilter: "User Search Filter",
    searchFilterHint: "Filtr musi zawierać dokładnie jeden znacznik {username}.",
    usernameAttribute: "Atrybut nazwy użytkownika",
    bindDn: "Bind DN",
    bindPassword: "Bind Password",
    bindPasswordConfigured: "Sekret jest już zapisany. Puste pole zachowa obecne hasło.",
    clearPassword: "Usuń zapisany Bind Password",
    displayName: "Atrybut display name",
    email: "Atrybut e-mail",
    save: "Zapisz LDAP",
    saving: "Zapisywanie…",
    test: "Testuj połączenie",
    testing: "Testowanie…",
    testSavedHint: "Test używa ostatnio zapisanej konfiguracji.",
    dirtyTestHint: "Zapisz zmiany przed wykonaniem testu połączenia.",
    incomplete: "Uzupełnij wymagane pola LDAP przed włączeniem logowania.",
    loading: "Wczytywanie konfiguracji LDAP…",
    loadError: "Nie udało się odczytać ustawień LDAP.",
    saved: "Ustawienia LDAP zostały zapisane.",
    testOk: "Połączenie LDAP działa poprawnie.",
  },
  en: {
    title: "LDAP authentication",
    description: "External user directory for PAM + LDAP mode. LDAP configuration is independent from local WebNAS accounts.",
    enabled: "Enable LDAP authentication",
    enabledHint: "When enabled, LDAP appears as a sign-in method. PAM remains available as an alternative.",
    enabledStatus: "LDAP enabled",
    disabledStatus: "LDAP disabled",
    connection: "Connection",
    connectionHint: "Directory endpoint, TLS transport, and connection timeout settings.",
    directory: "User search",
    directoryHint: "Directory scope and filter used to locate the user account.",
    mapping: "Bind and attributes",
    mappingHint: "LDAP service account and user attribute mapping.",
    endpoint: "Endpoint",
    transport: "Transport",
    bindSecret: "Bind password",
    configured: "configured",
    notConfigured: "none",
    server: "LDAP server / URI",
    serverHint: "Hostname or ldap:// / ldaps:// URI.",
    port: "Port",
    security: "Security mode",
    verifyTls: "Verify TLS certificate",
    verifyTlsHint: "Disable only in controlled test environments.",
    connectTimeout: "Connection timeout (s)",
    operationTimeout: "Operation timeout (s)",
    baseDn: "Base DN",
    searchBase: "User Search Base DN",
    searchFilter: "User Search Filter",
    searchFilterHint: "The filter must contain exactly one {username} placeholder.",
    usernameAttribute: "Username attribute",
    bindDn: "Bind DN",
    bindPassword: "Bind Password",
    bindPasswordConfigured: "A secret is already stored. Leave this field empty to keep it.",
    clearPassword: "Clear stored Bind Password",
    displayName: "Display name attribute",
    email: "Email attribute",
    save: "Save LDAP",
    saving: "Saving…",
    test: "Test connection",
    testing: "Testing…",
    testSavedHint: "The test uses the last saved configuration.",
    dirtyTestHint: "Save changes before testing the connection.",
    incomplete: "Complete the required LDAP fields before enabling authentication.",
    loading: "Loading LDAP configuration…",
    loadError: "Could not load LDAP settings.",
    saved: "LDAP settings were saved.",
    testOk: "LDAP connection is healthy.",
  },
} as const;

function toDraft(value: LdapSettings): LdapDraft {
  return { ...value, bind_password: "", clear_bind_password: false };
}

function fingerprint(value: LdapSettings | LdapDraft): string {
  return JSON.stringify({
    enabled: value.enabled,
    server: value.server,
    port: value.port,
    security_mode: value.security_mode,
    verify_tls: value.verify_tls,
    connect_timeout: value.connect_timeout,
    operation_timeout: value.operation_timeout,
    base_dn: value.base_dn,
    user_search_base: value.user_search_base,
    user_search_filter: value.user_search_filter,
    username_attribute: value.username_attribute,
    bind_dn: value.bind_dn,
    bind_password_configured: value.bind_password_configured,
    display_name_attribute: value.display_name_attribute,
    email_attribute: value.email_attribute,
  });
}

function configurationComplete(value: LdapSettings | LdapDraft): boolean {
  return Boolean(
    value.server.trim()
      && value.base_dn.trim()
      && value.user_search_base.trim()
      && value.user_search_filter.trim()
      && value.user_search_filter.includes("{username}")
      && value.username_attribute.trim()
      && value.bind_dn.trim()
      && Number.isFinite(value.port)
      && value.port >= 1
      && value.port <= 65535
      && Number.isFinite(value.connect_timeout)
      && value.connect_timeout >= 0.5
      && Number.isFinite(value.operation_timeout)
      && value.operation_timeout >= 0.5
  );
}

export function LdapSettingsControl({ active, locale, toast }: Props) {
  const anchorRef = useRef<HTMLSpanElement | null>(null);
  const [target, setTarget] = useState<Element | null>(null);
  const [draft, setDraft] = useState<LdapDraft | null>(null);
  const [saved, setSaved] = useState<LdapSettings | null>(null);
  const [section, setSection] = useState<LdapSection>("connection");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const text = locale.toLowerCase().startsWith("pl") ? copy.pl : copy.en;

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

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setDraft(null);
    setSaved(null);
    void request<LdapSettings>("/api/settings/authentication/ldap")
      .then((value) => {
        if (cancelled) return;
        setSaved(value);
        setDraft(toDraft(value));
      })
      .catch(() => { if (!cancelled) toast(text.loadError, "error", "admin"); });
    return () => { cancelled = true; };
  }, [active, text.loadError, toast]);

  async function save() {
    if (!draft) return;
    setSaving(true);
    try {
      const updated = await request<LdapSettings>("/api/settings/authentication/ldap", {
        method: "PUT",
        body: JSON.stringify({
          enabled: draft.enabled,
          server: draft.server,
          port: Number(draft.port),
          security_mode: draft.security_mode,
          verify_tls: draft.verify_tls,
          connect_timeout: Number(draft.connect_timeout),
          operation_timeout: Number(draft.operation_timeout),
          base_dn: draft.base_dn,
          user_search_base: draft.user_search_base,
          user_search_filter: draft.user_search_filter,
          username_attribute: draft.username_attribute,
          bind_dn: draft.bind_dn,
          bind_password: draft.bind_password,
          clear_bind_password: draft.clear_bind_password,
          display_name_attribute: draft.display_name_attribute,
          email_attribute: draft.email_attribute,
        }),
      });
      setSaved(updated);
      setDraft(toDraft(updated));
      toast(text.saved, "ok", "admin");
    } catch (error) {
      toast(error instanceof Error ? error.message : text.loadError, "error", "admin");
    } finally {
      setSaving(false);
    }
  }

  async function testConnection() {
    setTesting(true);
    try {
      const result = await request<{ ok: boolean; message: string }>("/api/settings/authentication/ldap/test", {
        method: "POST",
        body: "{}",
      });
      toast(result.message || text.testOk, "ok", "admin");
    } catch (error) {
      toast(error instanceof Error ? error.message : text.loadError, "error", "admin");
    } finally {
      setTesting(false);
    }
  }

  function changeSecurityMode(mode: SecurityMode) {
    if (!draft) return;
    const currentPortIsDefault = draft.port === 389 || draft.port === 636;
    setDraft({
      ...draft,
      security_mode: mode,
      port: currentPortIsDefault ? (mode === "ldaps" ? 636 : 389) : draft.port,
    });
  }

  const field = (
    label: string,
    value: string | number,
    onChange: (value: string) => void,
    options?: {
      type?: "text" | "number" | "password";
      placeholder?: string;
      hint?: string;
      min?: number;
      max?: number;
      step?: number;
      autoComplete?: string;
    },
  ) => <label style={{ display: "grid", gap: "0.3rem", minWidth: 0 }}>
    <span style={{ display: "grid", gap: "0.1rem" }}>
      <strong>{label}</strong>
      {options?.hint && <small style={{ color: "var(--text-muted)", lineHeight: 1.3 }}>{options.hint}</small>}
    </span>
    <input
      style={{ width: "100%", minWidth: 0 }}
      type={options?.type || "text"}
      placeholder={options?.placeholder}
      value={value}
      min={options?.min}
      max={options?.max}
      step={options?.step}
      autoComplete={options?.autoComplete}
      onChange={(event) => onChange(event.target.value)}
    />
  </label>;

  const card = active && target ? createPortal(
    <div className="settings-card-stack" data-testid="ldap-settings-card">
      {!draft || !saved ? <section className="settings-card" style={{ padding: "1rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}><LoaderCircle className="spin" size={18} />{text.loading}</div>
      </section> : (() => {
        const dirty = fingerprint(draft) !== fingerprint(saved) || Boolean(draft.bind_password) || draft.clear_bind_password;
        const complete = configurationComplete(draft);
        const savedComplete = configurationComplete(saved);
        const transport = draft.security_mode === "ldaps" ? "LDAPS" : draft.security_mode === "starttls" ? "LDAP + StartTLS" : "LDAP";
        const endpoint = draft.server.trim() ? `${draft.server.trim()}:${draft.port}` : "—";
        const tabs = [
          { id: "connection" as const, label: text.connection, icon: <Server size={15} /> },
          { id: "directory" as const, label: text.directory, icon: <Search size={15} /> },
          { id: "mapping" as const, label: text.mapping, icon: <Database size={15} /> },
        ];

        return <section className="settings-card" style={{ overflow: "hidden" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem", padding: "0.9rem 1rem 0.75rem" }}>
            <div style={{ minWidth: 0 }}>
              <h3 style={{ margin: 0, display: "flex", alignItems: "center", gap: "0.45rem" }}><KeyRound size={18} /> {text.title}</h3>
              <p style={{ margin: "0.35rem 0 0", maxWidth: "60rem" }}>{text.description}</p>
            </div>
            <span style={{ flex: "0 0 auto", padding: "0.25rem 0.55rem", border: "1px solid var(--border-subtle)", borderRadius: "999px", background: draft.enabled ? "var(--surface-selected)" : "var(--surface-secondary)", color: draft.enabled ? "var(--accent)" : "var(--text-secondary)", fontWeight: 600 }}>
              {draft.enabled ? text.enabledStatus : text.disabledStatus}
            </span>
          </div>

          <div className="setting-row" style={{ borderTop: "1px solid var(--border-subtle)" }}>
            <div><strong>{text.enabled}</strong><small>{text.enabledHint}</small></div>
            <div className="setting-control"><label className="settings-switch"><input type="checkbox" aria-label={text.enabled} checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked, clear_bind_password: false })} /><span aria-hidden="true" /></label></div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(11rem, 1fr))", gap: "0.5rem", padding: "0.65rem 1rem", borderTop: "1px solid var(--border-subtle)", background: "var(--surface-secondary)" }}>
            <div style={{ minWidth: 0 }}><small style={{ display: "block", color: "var(--text-muted)" }}>{text.endpoint}</small><strong style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{endpoint}</strong></div>
            <div><small style={{ display: "block", color: "var(--text-muted)" }}>{text.transport}</small><strong>{transport}</strong></div>
            <div><small style={{ display: "block", color: "var(--text-muted)" }}>{text.bindSecret}</small><strong>{draft.bind_password_configured ? text.configured : text.notConfigured}</strong></div>
          </div>

          <div role="tablist" aria-label={text.title} style={{ display: "flex", gap: "0.25rem", overflowX: "auto", padding: "0.5rem 0.65rem", borderTop: "1px solid var(--border-subtle)", borderBottom: "1px solid var(--border-subtle)" }}>
            {tabs.map((tab) => <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={section === tab.id}
              onClick={() => setSection(tab.id)}
              style={{ display: "inline-flex", alignItems: "center", gap: "0.4rem", whiteSpace: "nowrap", borderColor: section === tab.id ? "var(--accent)" : "var(--border-subtle)", background: section === tab.id ? "var(--surface-selected)" : "var(--surface-elevated)", color: section === tab.id ? "var(--accent)" : "var(--text-primary)", fontWeight: section === tab.id ? 600 : 400 }}
            >{tab.icon}{tab.label}</button>)}
          </div>

          <div role="tabpanel" style={{ padding: "0.85rem 1rem 1rem" }}>
            <div style={{ marginBottom: "0.75rem" }}>
              <strong>{section === "connection" ? text.connection : section === "directory" ? text.directory : text.mapping}</strong>
              <p style={{ margin: "0.2rem 0 0", color: "var(--text-muted)" }}>{section === "connection" ? text.connectionHint : section === "directory" ? text.directoryHint : text.mappingHint}</p>
            </div>

            {section === "connection" && <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(15rem, 1fr))", gap: "0.8rem 1rem" }}>
              {field(text.server, draft.server, (value) => setDraft({ ...draft, server: value }), { placeholder: "ldap.example.com", hint: text.serverHint })}
              {field(text.port, draft.port, (value) => setDraft({ ...draft, port: Number(value) }), { type: "number", min: 1, max: 65535, step: 1 })}
              <label style={{ display: "grid", gap: "0.3rem", minWidth: 0 }}><strong>{text.security}</strong><select style={{ width: "100%" }} value={draft.security_mode} onChange={(event) => changeSecurityMode(event.target.value as SecurityMode)}><option value="ldap">LDAP</option><option value="starttls">LDAP + StartTLS</option><option value="ldaps">LDAPS</option></select></label>
              <div style={{ display: "grid", gap: "0.3rem", alignContent: "start" }}><span style={{ display: "grid", gap: "0.1rem" }}><strong>{text.verifyTls}</strong><small style={{ color: "var(--text-muted)", lineHeight: 1.3 }}>{text.verifyTlsHint}</small></span><div style={{ minHeight: "var(--control-height)", display: "flex", alignItems: "center" }}><label className="settings-switch"><input type="checkbox" aria-label={text.verifyTls} checked={draft.verify_tls} onChange={(event) => setDraft({ ...draft, verify_tls: event.target.checked })} /><span aria-hidden="true" /></label></div></div>
              {field(text.connectTimeout, draft.connect_timeout, (value) => setDraft({ ...draft, connect_timeout: Number(value) }), { type: "number", min: 0.5, max: 60, step: 0.5 })}
              {field(text.operationTimeout, draft.operation_timeout, (value) => setDraft({ ...draft, operation_timeout: Number(value) }), { type: "number", min: 0.5, max: 120, step: 0.5 })}
            </div>}

            {section === "directory" && <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(17rem, 1fr))", gap: "0.8rem 1rem" }}>
              {field(text.baseDn, draft.base_dn, (value) => setDraft({ ...draft, base_dn: value }), { placeholder: "dc=example,dc=com" })}
              {field(text.searchBase, draft.user_search_base, (value) => setDraft({ ...draft, user_search_base: value }), { placeholder: "ou=people,dc=example,dc=com" })}
              {field(text.searchFilter, draft.user_search_filter, (value) => setDraft({ ...draft, user_search_filter: value }), { placeholder: "(uid={username})", hint: text.searchFilterHint })}
              {field(text.usernameAttribute, draft.username_attribute, (value) => setDraft({ ...draft, username_attribute: value }), { placeholder: "uid" })}
            </div>}

            {section === "mapping" && <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(17rem, 1fr))", gap: "0.8rem 1rem" }}>
              {field(text.bindDn, draft.bind_dn, (value) => setDraft({ ...draft, bind_dn: value }), { placeholder: "cn=webnas,ou=service,dc=example,dc=com" })}
              {field(text.bindPassword, draft.bind_password, (value) => setDraft({ ...draft, bind_password: value, clear_bind_password: false }), { type: "password", autoComplete: "new-password", hint: draft.bind_password_configured ? text.bindPasswordConfigured : undefined })}
              {field(text.displayName, draft.display_name_attribute, (value) => setDraft({ ...draft, display_name_attribute: value }), { placeholder: "displayName" })}
              {field(text.email, draft.email_attribute, (value) => setDraft({ ...draft, email_attribute: value }), { placeholder: "mail" })}
              {draft.bind_password_configured && !draft.enabled && <div style={{ display: "grid", gap: "0.3rem", alignContent: "start" }}><strong>{text.clearPassword}</strong><div style={{ minHeight: "var(--control-height)", display: "flex", alignItems: "center" }}><label className="settings-switch"><input type="checkbox" aria-label={text.clearPassword} checked={draft.clear_bind_password} onChange={(event) => setDraft({ ...draft, clear_bind_password: event.target.checked, bind_password: "" })} /><span aria-hidden="true" /></label></div></div>}
            </div>}
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: "0.65rem", padding: "0.65rem 1rem", borderTop: "1px solid var(--border-subtle)", background: "var(--surface-secondary)" }}>
            <small style={{ color: draft.enabled && !complete ? "var(--warning)" : "var(--text-muted)" }}>
              {draft.enabled && !complete ? text.incomplete : dirty ? text.dirtyTestHint : text.testSavedHint}
            </small>
            <div className="settings-actions" style={{ margin: 0 }}>
              <button className="button-primary" type="button" disabled={saving || testing || !dirty || (draft.enabled && !complete)} onClick={() => void save()}>{saving && <LoaderCircle className="spin" size={16} />}{saving ? text.saving : text.save}</button>
              <button type="button" disabled={saving || testing || dirty || !savedComplete} onClick={() => void testConnection()}><PlugZap size={16} />{testing ? text.testing : text.test}</button>
            </div>
          </div>
        </section>;
      })()}
    </div>,
    target,
  ) : null;

  return <><span ref={anchorRef} style={{ display: "none" }} />{card}</>;
}
