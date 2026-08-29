import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { KeyRound, LoaderCircle, PlugZap } from "lucide-react";
import type { ToastFn } from "../../app/types";
import { request } from "../../core/api/transport";

type SecurityMode = "ldap" | "starttls" | "ldaps";

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
    title: "LDAP Authentication",
    description: "Po włączeniu LDAP ekran logowania pozwala wybrać LDAP lub PAM. LDAP jest zaznaczony domyślnie, a PAM pozostaje ręcznie dostępną metodą awaryjną.",
    enabled: "Włącz logowanie LDAP",
    enabledHint: "Wyłączenie LDAP przywraca ekran logowania tylko przez PAM. Nie ma automatycznego fallbacku pomiędzy providerami.",
    server: "Serwer LDAP / URI",
    port: "Port",
    security: "Tryb bezpieczeństwa",
    verifyTls: "Weryfikuj certyfikat TLS",
    connectTimeout: "Timeout połączenia (s)",
    operationTimeout: "Timeout operacji (s)",
    baseDn: "Base DN",
    searchBase: "User Search Base DN",
    searchFilter: "User Search Filter",
    usernameAttribute: "Atrybut nazwy użytkownika",
    bindDn: "Bind DN",
    bindPassword: "Bind Password",
    bindPasswordConfigured: "Sekret Bind Password jest skonfigurowany. Pozostaw pole puste, aby go zachować.",
    clearPassword: "Usuń zapisany Bind Password",
    displayName: "Atrybut display name",
    email: "Atrybut e-mail",
    save: "Zapisz LDAP",
    saving: "Zapisywanie…",
    test: "Test LDAP Connection",
    testing: "Testowanie…",
    loadError: "Nie udało się odczytać ustawień LDAP.",
    saved: "Ustawienia LDAP zostały zapisane.",
    testOk: "Połączenie LDAP działa poprawnie.",
  },
  en: {
    title: "LDAP Authentication",
    description: "When LDAP is enabled the login page offers LDAP and PAM. LDAP is selected by default while PAM remains a manually selectable break-glass option.",
    enabled: "Enable LDAP authentication",
    enabledHint: "Disabling LDAP restores PAM-only login. Providers never fall back to each other automatically.",
    server: "LDAP server / URI",
    port: "Port",
    security: "Security mode",
    verifyTls: "Verify TLS certificate",
    connectTimeout: "Connection timeout (s)",
    operationTimeout: "Operation timeout (s)",
    baseDn: "Base DN",
    searchBase: "User Search Base DN",
    searchFilter: "User Search Filter",
    usernameAttribute: "Username attribute",
    bindDn: "Bind DN",
    bindPassword: "Bind Password",
    bindPasswordConfigured: "A Bind Password secret is configured. Leave this field empty to preserve it.",
    clearPassword: "Clear stored Bind Password",
    displayName: "Display name attribute",
    email: "Email attribute",
    save: "Save LDAP",
    saving: "Saving…",
    test: "Test LDAP Connection",
    testing: "Testing…",
    loadError: "Could not load LDAP settings.",
    saved: "LDAP settings were saved.",
    testOk: "LDAP connection is healthy.",
  },
} as const;

function toDraft(value: LdapSettings): LdapDraft {
  return { ...value, bind_password: "", clear_bind_password: false };
}

export function LdapSettingsControl({ active, locale, toast }: Props) {
  const anchorRef = useRef<HTMLSpanElement | null>(null);
  const [target, setTarget] = useState<Element | null>(null);
  const [draft, setDraft] = useState<LdapDraft | null>(null);
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
    void request<LdapSettings>("/api/settings/authentication/ldap")
      .then((value) => { if (!cancelled) setDraft(toDraft(value)); })
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

  const field = (
    label: string,
    value: string | number,
    onChange: (value: string) => void,
    options?: { type?: "text" | "number" | "password"; placeholder?: string },
  ) => <div className="setting-row">
    <div><strong>{label}</strong></div>
    <div className="setting-control"><input type={options?.type || "text"} placeholder={options?.placeholder} value={value} onChange={(event) => onChange(event.target.value)} /></div>
  </div>;

  const card = active && target && draft ? createPortal(
    <div className="settings-card-stack" data-testid="ldap-settings-card">
      <section className="settings-card">
        <h3><KeyRound size={18} /> {text.title}</h3>
        <p>{text.description}</p>
        <div className="setting-row">
          <div><strong>{text.enabled}</strong><small>{text.enabledHint}</small></div>
          <div className="setting-control"><label className="settings-switch"><input type="checkbox" aria-label={text.enabled} checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked, clear_bind_password: false })} /><span aria-hidden="true" /></label></div>
        </div>
        {field(text.server, draft.server, (value) => setDraft({ ...draft, server: value }), { placeholder: "ldap.example.com" })}
        {field(text.port, draft.port, (value) => setDraft({ ...draft, port: Number(value) }), { type: "number" })}
        <div className="setting-row"><div><strong>{text.security}</strong></div><div className="setting-control"><select value={draft.security_mode} onChange={(event) => setDraft({ ...draft, security_mode: event.target.value as SecurityMode })}><option value="ldap">LDAP</option><option value="starttls">LDAP + StartTLS</option><option value="ldaps">LDAPS</option></select></div></div>
        <div className="setting-row"><div><strong>{text.verifyTls}</strong></div><div className="setting-control"><label className="settings-switch"><input type="checkbox" aria-label={text.verifyTls} checked={draft.verify_tls} onChange={(event) => setDraft({ ...draft, verify_tls: event.target.checked })} /><span aria-hidden="true" /></label></div></div>
        {field(text.connectTimeout, draft.connect_timeout, (value) => setDraft({ ...draft, connect_timeout: Number(value) }), { type: "number" })}
        {field(text.operationTimeout, draft.operation_timeout, (value) => setDraft({ ...draft, operation_timeout: Number(value) }), { type: "number" })}
        {field(text.baseDn, draft.base_dn, (value) => setDraft({ ...draft, base_dn: value }), { placeholder: "dc=example,dc=com" })}
        {field(text.searchBase, draft.user_search_base, (value) => setDraft({ ...draft, user_search_base: value }), { placeholder: "ou=people,dc=example,dc=com" })}
        {field(text.searchFilter, draft.user_search_filter, (value) => setDraft({ ...draft, user_search_filter: value }), { placeholder: "(uid={username})" })}
        {field(text.usernameAttribute, draft.username_attribute, (value) => setDraft({ ...draft, username_attribute: value }))}
        {field(text.bindDn, draft.bind_dn, (value) => setDraft({ ...draft, bind_dn: value }))}
        <div className="setting-row">
          <div><strong>{text.bindPassword}</strong>{draft.bind_password_configured && <small>{text.bindPasswordConfigured}</small>}</div>
          <div className="setting-control"><input type="password" autoComplete="new-password" value={draft.bind_password} onChange={(event) => setDraft({ ...draft, bind_password: event.target.value, clear_bind_password: false })} /></div>
        </div>
        {draft.bind_password_configured && !draft.enabled && <div className="setting-row"><div><strong>{text.clearPassword}</strong></div><div className="setting-control"><label className="settings-switch"><input type="checkbox" aria-label={text.clearPassword} checked={draft.clear_bind_password} onChange={(event) => setDraft({ ...draft, clear_bind_password: event.target.checked, bind_password: "" })} /><span aria-hidden="true" /></label></div></div>}
        {field(text.displayName, draft.display_name_attribute, (value) => setDraft({ ...draft, display_name_attribute: value }))}
        {field(text.email, draft.email_attribute, (value) => setDraft({ ...draft, email_attribute: value }))}
        <div className="settings-actions">
          <button className="button-primary" type="button" disabled={saving || testing} onClick={() => void save()}>{saving && <LoaderCircle className="spin" size={16} />}{saving ? text.saving : text.save}</button>
          <button type="button" disabled={saving || testing || !draft.bind_password_configured} onClick={() => void testConnection()}><PlugZap size={16} />{testing ? text.testing : text.test}</button>
        </div>
      </section>
    </div>,
    target,
  ) : null;

  return <><span ref={anchorRef} style={{ display: "none" }} />{card}</>;
}
