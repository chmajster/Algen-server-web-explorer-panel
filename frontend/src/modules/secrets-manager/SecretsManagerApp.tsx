import { KeyRound, Plus, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { confirmDialog } from "../../components/DialogService";
import { Modal } from "../../components/Modal";
import type { ToastFn } from "../../app/types";
import { secretsManagerClient, type SecretAuditItem, type SecretInput, type SecretItem, type SecretType } from "./api/client";
import "../infrastructure-managers.css";

const TYPES: SecretType[] = [
  "username_password", "ssh_password", "ssh_private_key", "become_password", "api_token",
  "generic_secret", "proxmox_api", "redfish", "ipmi", "git_private_key", "wol",
];

type Props = { permissions: string[]; language: string; toast: ToastFn };
type ShareTarget = { id: string; name: string };

const emptyInput = (): SecretInput => ({
  name: "", type: "username_password", username: "", secret: "", passphrase: "",
  description: "", environment_id: null, shared_with: [], confirm: true,
});

export function SecretsManagerApp({ permissions, language, toast }: Props) {
  const pl = language.toLowerCase().startsWith("pl");
  const text = {
    title: pl ? "Menedżer sekretów" : "Secrets Manager",
    subtitle: pl ? "Centralny, szyfrowany magazyn sekretów WebNAS." : "Central encrypted secret store for WebNAS.",
    add: pl ? "Dodaj sekret" : "Add secret",
    refresh: pl ? "Odśwież" : "Refresh",
    search: pl ? "Szukaj" : "Search",
    allTypes: pl ? "Wszystkie typy" : "All types",
    allModules: pl ? "Wszystkie moduły" : "All modules",
    name: pl ? "Nazwa" : "Name",
    type: pl ? "Typ" : "Type",
    account: pl ? "Konto" : "Account",
    shared: pl ? "Udostępniony" : "Shared with",
    usage: pl ? "Użycia" : "Usage",
    configured: pl ? "Sekret" : "Secret",
    actions: pl ? "Akcje" : "Actions",
    edit: pl ? "Edytuj" : "Edit",
    remove: pl ? "Usuń" : "Delete",
    save: pl ? "Zapisz" : "Save",
    cancel: pl ? "Anuluj" : "Cancel",
    description: pl ? "Opis" : "Description",
    username: pl ? "Login / identyfikator" : "Username / identifier",
    secret: pl ? "Wartość sekretu" : "Secret value",
    secretHint: pl ? "Przy edycji pozostaw puste, aby zachować obecną wartość." : "When editing, leave empty to keep the current value.",
    passphrase: "Passphrase",
    modules: pl ? "Dostęp dla modułów" : "Module access",
    yes: pl ? "ustawiony" : "configured",
    no: pl ? "brak" : "none",
    empty: pl ? "Brak sekretów." : "No secrets.",
    audit: pl ? "Historia użycia" : "Usage history",
    back: pl ? "Sekrety" : "Secrets",
    deleteConfirm: pl ? "Usunąć ten sekret?" : "Delete this secret?",
    migrationError: pl ? "Migracja magazynu Credentials nie została zakończona. Stary runtime pozostaje aktywny." : "Credentials migration did not complete. The legacy runtime remains active.",
  };
  const [items, setItems] = useState<SecretItem[]>([]);
  const [targets, setTargets] = useState<ShareTarget[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [moduleFilter, setModuleFilter] = useState("");
  const [editing, setEditing] = useState<SecretItem | null>(null);
  const [form, setForm] = useState<SecretInput>(emptyInput);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [audit, setAudit] = useState<SecretAuditItem[]>([]);
  const [migrationError, setMigrationError] = useState("");
  const canManage = permissions.includes("secrets-manager.manage");
  const canAudit = permissions.includes("secrets-manager.audit.view");

  const refresh = useCallback(async (initial = false) => {
    if (initial) setLoading(true);
    else setRefreshing(true);
    try {
      const [secrets, shareTargets, status] = await Promise.all([
        secretsManagerClient.secrets(), secretsManagerClient.shareTargets(), secretsManagerClient.status(),
      ]);
      setItems(secrets);
      setTargets(shareTargets.modules);
      setMigrationError(status.migration_error || "");
    } catch (error) {
      toast(error instanceof Error ? error.message : "Secrets Manager error", "error", "admin", "secrets-manager");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [toast]);

  useEffect(() => { void refresh(true); }, [refresh]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items.filter((item) => {
      if (typeFilter && item.type !== typeFilter) return false;
      if (moduleFilter && !item.shared_with.includes(moduleFilter)) return false;
      return !needle || [item.name, item.type, item.username, item.description].some((value) => value.toLowerCase().includes(needle));
    });
  }, [items, moduleFilter, query, typeFilter]);

  function showEditor(item?: SecretItem) {
    setEditing(item || null);
    setForm(item ? {
      name: item.name,
      type: item.type,
      username: item.username,
      secret: "",
      passphrase: "",
      description: item.description,
      environment_id: item.environment_id,
      shared_with: [...item.shared_with],
      confirm: true,
    } : { ...emptyInput(), shared_with: targets.map((target) => target.id) });
    setOpen(true);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    try {
      const saved = editing
        ? await secretsManagerClient.update(editing.id, form)
        : await secretsManagerClient.create(form);
      setItems((current) => [...current.filter((item) => item.id !== saved.id), saved].sort((a, b) => a.name.localeCompare(b.name)));
      setOpen(false);
      setEditing(null);
    } catch (error) {
      toast(error instanceof Error ? error.message : "Secrets Manager error", "error", "admin", "secrets-manager");
    } finally {
      setSaving(false);
    }
  }

  async function remove(item: SecretItem) {
    if (!(await confirmDialog(text.deleteConfirm, (key) => key))) return;
    try {
      await secretsManagerClient.remove(item.id);
      setItems((current) => current.filter((candidate) => candidate.id !== item.id));
    } catch (error) {
      toast(error instanceof Error ? error.message : "Secrets Manager error", "error", "admin", "secrets-manager");
    }
  }

  async function showAudit(item?: SecretItem) {
    try {
      const result = await secretsManagerClient.audit(item?.id || "");
      setAudit(result.items);
      setAuditOpen(true);
    } catch (error) {
      toast(error instanceof Error ? error.message : "Secrets Manager audit error", "error", "admin", "secrets-manager");
    }
  }

  return (
    <div className="infra-manager-app">
      <header className="infra-manager-header">
        <div className="infra-manager-title"><KeyRound /><div><h2>{text.title}</h2><p>{text.subtitle}</p></div></div>
        <div className="infra-manager-actions">
          {canAudit && <button type="button" onClick={() => void showAudit()}><ShieldCheck />{text.audit}</button>}
          <button type="button" onClick={() => void refresh()} disabled={refreshing}><RefreshCw className={refreshing ? "spin" : ""} />{text.refresh}</button>
          {canManage && <button className="button-primary" type="button" onClick={() => showEditor()}><Plus />{text.add}</button>}
        </div>
      </header>

      {migrationError && <div className="infra-manager-warning"><ShieldCheck />{text.migrationError}<small>{migrationError}</small></div>}

      <div className="infra-manager-toolbar">
        <label className="infra-search"><Search /><input type="search" value={query} placeholder={text.search} onChange={(event) => setQuery(event.target.value)} /></label>
        <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value="">{text.allTypes}</option>{TYPES.map((type) => <option key={type} value={type}>{type}</option>)}</select>
        <select value={moduleFilter} onChange={(event) => setModuleFilter(event.target.value)}><option value="">{text.allModules}</option>{targets.map((target) => <option key={target.id} value={target.id}>{target.name}</option>)}</select>
        <span className="infra-count">{filtered.length} / {items.length}</span>
      </div>

      <div className="infra-table-wrap">
        <table className="infra-table">
          <thead><tr><th>{text.name}</th><th>{text.type}</th><th>{text.account}</th><th>{text.shared}</th><th>{text.configured}</th><th>{text.usage}</th><th>{text.actions}</th></tr></thead>
          <tbody>
            {!loading && filtered.map((item) => <tr key={item.id}>
              <td><strong>{item.name}</strong>{item.description && <small>{item.description}</small>}</td>
              <td><code>{item.type}</code></td>
              <td>{item.username || "—"}</td>
              <td><div className="infra-chips">{item.shared_with.slice(0, 4).map((module) => <span key={module}>{module}</span>)}{item.shared_with.length > 4 && <span>+{item.shared_with.length - 4}</span>}</div></td>
              <td><span className={item.secret_configured ? "status-ok" : "status-muted"}>{item.secret_configured ? text.yes : text.no}</span></td>
              <td>{item.usage_count}</td>
              <td><div className="infra-row-actions">{canAudit && <button type="button" onClick={() => void showAudit(item)}>{text.audit}</button>}{canManage && <><button type="button" onClick={() => showEditor(item)}>{text.edit}</button><button className="button-danger" type="button" onClick={() => void remove(item)}>{text.remove}</button></>}</div></td>
            </tr>)}
            {!loading && filtered.length === 0 && <tr><td colSpan={7} className="infra-empty">{text.empty}</td></tr>}
            {loading && <tr><td colSpan={7} className="infra-empty">…</td></tr>}
          </tbody>
        </table>
      </div>

      {open && <Modal title={editing ? `${text.edit}: ${editing.name}` : text.add} closeLabel={text.cancel} onClose={() => setOpen(false)} footer={<button className="button-primary" type="submit" form="secret-manager-form" disabled={saving}>{text.save}</button>}>
        <form id="secret-manager-form" className="infra-form" onSubmit={save}>
          <label>{text.name}<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
          <label>{text.type}<select value={form.type} onChange={(event) => setForm({ ...form, type: event.target.value as SecretType })}>{TYPES.map((type) => <option key={type} value={type}>{type}</option>)}</select></label>
          <label>{text.username}<input value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} /></label>
          <label className="infra-form-wide">{text.description}<textarea rows={2} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
          {form.type !== "wol" && <label className="infra-form-wide">{text.secret}<textarea rows={form.type.includes("key") ? 6 : 2} required={!editing} value={form.secret} onChange={(event) => setForm({ ...form, secret: event.target.value })} /><small>{text.secretHint}</small></label>}
          {(form.type === "ssh_private_key" || form.type === "git_private_key") && <label className="infra-form-wide">{text.passphrase}<input type="password" value={form.passphrase} onChange={(event) => setForm({ ...form, passphrase: event.target.value })} /></label>}
          <fieldset className="infra-form-wide"><legend>{text.modules}</legend><div className="infra-check-grid">{targets.map((target) => <label key={target.id}><input type="checkbox" checked={form.shared_with.includes(target.id)} onChange={(event) => setForm({ ...form, shared_with: event.target.checked ? [...new Set([...form.shared_with, target.id])] : form.shared_with.filter((id) => id !== target.id) })} />{target.name}<small>{target.id}</small></label>)}</div></fieldset>
        </form>
      </Modal>}

      {auditOpen && <Modal title={text.audit} closeLabel={text.back} onClose={() => setAuditOpen(false)}>
        <div className="infra-audit-list">{audit.map((entry) => <div key={entry.id}><strong>{entry.action}</strong><span>{entry.consumer_module || entry.actor || "system"}</span><small>{new Date(entry.created_at * 1000).toLocaleString(language)} {entry.purpose}</small></div>)}{audit.length === 0 && <div className="infra-empty">—</div>}</div>
      </Modal>}
    </div>
  );
}
