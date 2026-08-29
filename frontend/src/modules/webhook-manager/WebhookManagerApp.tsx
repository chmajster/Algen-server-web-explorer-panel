import { FlaskConical, Plus, RefreshCw, Search, Webhook } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { confirmDialog } from "../../components/DialogService";
import { Modal } from "../../components/Modal";
import type { ToastFn } from "../../app/types";
import { webhookManagerClient, type DeliveryItem, type WebhookInput, type WebhookItem } from "./api/client";
import type { SecretItem } from "../secrets-manager/api/client";
import "../infrastructure-managers.css";

type Props = { permissions: string[]; language: string; toast: ToastFn };
const emptyWebhook = (): WebhookInput => ({ name: "", description: "", enabled: true, url: "", method: "POST", events: [], timeout_seconds: 10, max_attempts: 3, headers: {}, auth_type: "none", secret_id: null, auth_header_name: "X-API-Key", signing_secret_id: null, allow_private_networks: false });

export function WebhookManagerApp({ permissions, language, toast }: Props) {
  const pl = language.toLowerCase().startsWith("pl");
  const tx = {
    title: "Webhook Manager", subtitle: pl ? "Centralna wysyłka zdarzeń WebNAS z retry, HMAC i sekretami z Secrets Managera." : "Central WebNAS event delivery with retries, HMAC and Secrets Manager integration.",
    webhooks: "Webhooks", deliveries: pl ? "Dostarczenia" : "Deliveries", add: pl ? "Dodaj webhook" : "Add webhook", refresh: pl ? "Odśwież" : "Refresh",
    enabled: pl ? "Aktywne" : "Enabled", success: pl ? "Sukces 24h" : "Success 24h", failed: pl ? "Błędy 24h" : "Failed 24h", queue: pl ? "Kolejka" : "Queue",
    name: pl ? "Nazwa" : "Name", url: "URL", events: pl ? "Zdarzenia" : "Events", auth: pl ? "Uwierzytelnianie" : "Authentication", actions: pl ? "Akcje" : "Actions",
    edit: pl ? "Edytuj" : "Edit", remove: pl ? "Usuń" : "Delete", test: "Test", disable: pl ? "Wyłącz" : "Disable", enable: pl ? "Włącz" : "Enable",
    save: pl ? "Zapisz" : "Save", close: pl ? "Zamknij" : "Close", description: pl ? "Opis" : "Description", method: "HTTP method", timeout: "Timeout (s)", attempts: pl ? "Próby" : "Attempts",
    headers: pl ? "Dodatkowe nagłówki JSON" : "Additional headers JSON", secret: pl ? "Sekret uwierzytelniania" : "Authentication secret", signing: pl ? "Sekret podpisu HMAC" : "HMAC signing secret",
    private: pl ? "Pozwól na prywatne sieci RFC1918/ULA" : "Allow private RFC1918/ULA networks", search: pl ? "Szukaj" : "Search", status: "Status", http: "HTTP", duration: pl ? "Czas" : "Duration", attempt: pl ? "Próba" : "Attempt", response: pl ? "Odpowiedź" : "Response",
    deleteConfirm: pl ? "Usunąć webhook i jego historię dostarczeń?" : "Delete this webhook and its delivery history?", testResult: pl ? "Wynik testu" : "Test result",
  };
  const [items, setItems] = useState<WebhookItem[]>([]);
  const [deliveries, setDeliveries] = useState<DeliveryItem[]>([]);
  const [events, setEvents] = useState<string[]>([]);
  const [secrets, setSecrets] = useState<SecretItem[]>([]);
  const [dashboard, setDashboard] = useState<{ enabled_webhooks: number; successful_deliveries_24h: number; failed_deliveries_24h: number; queue_depth: number } | null>(null);
  const [tab, setTab] = useState<"webhooks" | "deliveries">("webhooks");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<WebhookItem | null>(null);
  const [form, setForm] = useState<WebhookInput>(emptyWebhook);
  const [headersText, setHeadersText] = useState("{}");
  const [testResult, setTestResult] = useState<DeliveryItem | null>(null);
  const [loading, setLoading] = useState(true);
  const canManage = permissions.includes("webhook-manager.manage");
  const canTest = permissions.includes("webhook-manager.test");
  const canDeliveries = permissions.includes("webhook-manager.deliveries.view");

  const refresh = useCallback(async () => {
    try {
      const [hooks, eventList, secretList, stats] = await Promise.all([webhookManagerClient.webhooks(), webhookManagerClient.events(), webhookManagerClient.secrets(), webhookManagerClient.dashboard()]);
      setItems(hooks.items); setEvents(eventList.events); setSecrets(secretList.filter((item) => item.shared_with.includes("webhook-manager"))); setDashboard(stats);
      if (canDeliveries) setDeliveries((await webhookManagerClient.deliveries({ limit: 500 })).items);
    } catch (error) { toast(error instanceof Error ? error.message : "Webhook Manager error", "error", "admin", "webhook-manager"); }
    finally { setLoading(false); }
  }, [canDeliveries, toast]);
  useEffect(() => { void refresh(); }, [refresh]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items.filter((item) => !needle || [item.name, item.url, item.description, ...item.events].some((value) => value.toLowerCase().includes(needle)));
  }, [items, query]);

  function showEditor(item?: WebhookItem) {
    setEditing(item || null);
    const next = item ? { name: item.name, description: item.description, enabled: item.enabled, url: item.url, method: item.method, events: [...item.events], timeout_seconds: item.timeout_seconds, max_attempts: item.max_attempts, headers: { ...item.headers }, auth_type: item.auth_type, secret_id: item.secret_id, auth_header_name: item.auth_header_name, signing_secret_id: item.signing_secret_id, allow_private_networks: item.allow_private_networks } : emptyWebhook();
    setForm(next); setHeadersText(JSON.stringify(next.headers, null, 2)); setOpen(true);
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    let headers: Record<string, string>;
    try { const parsed = JSON.parse(headersText || "{}"); if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error(); headers = Object.fromEntries(Object.entries(parsed).map(([key, value]) => [key, String(value)])); }
    catch { toast(pl ? "Nagłówki muszą być obiektem JSON." : "Headers must be a JSON object.", "error", "admin", "webhook-manager"); return; }
    const payload = { ...form, headers };
    try {
      const saved = editing ? await webhookManagerClient.update(editing.id, payload) : await webhookManagerClient.create(payload);
      setItems((current) => [...current.filter((item) => item.id !== saved.id), saved].sort((a, b) => a.name.localeCompare(b.name))); setOpen(false); setEditing(null); void refresh();
    } catch (error) { toast(error instanceof Error ? error.message : "Webhook Manager error", "error", "admin", "webhook-manager"); }
  }
  async function remove(item: WebhookItem) { if (!(await confirmDialog(tx.deleteConfirm, (key) => key))) return; try { await webhookManagerClient.remove(item.id); await refresh(); } catch (error) { toast(error instanceof Error ? error.message : "Webhook Manager error", "error", "admin", "webhook-manager"); } }
  async function toggle(item: WebhookItem) { try { await webhookManagerClient.setEnabled(item.id, !item.enabled); await refresh(); } catch (error) { toast(error instanceof Error ? error.message : "Webhook Manager error", "error", "admin", "webhook-manager"); } }
  async function test(item: WebhookItem) { try { setTestResult(await webhookManagerClient.test(item.id)); await refresh(); } catch (error) { toast(error instanceof Error ? error.message : "Webhook test error", "error", "admin", "webhook-manager"); } }

  return <div className="infra-manager-app">
    <header className="infra-manager-header"><div className="infra-manager-title"><Webhook /><div><h2>{tx.title}</h2><p>{tx.subtitle}</p></div></div><div className="infra-manager-actions"><button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{tx.refresh}</button>{canManage && <button className="button-primary" type="button" onClick={() => showEditor()}><Plus />{tx.add}</button>}</div></header>
    <div className="infra-stat-grid"><div className="infra-stat"><strong>{dashboard?.enabled_webhooks ?? "—"}</strong><small>{tx.enabled}</small></div><div className="infra-stat"><strong>{dashboard?.successful_deliveries_24h ?? "—"}</strong><small>{tx.success}</small></div><div className="infra-stat"><strong>{dashboard?.failed_deliveries_24h ?? "—"}</strong><small>{tx.failed}</small></div><div className="infra-stat"><strong>{dashboard?.queue_depth ?? "—"}</strong><small>{tx.queue}</small></div></div>
    <div className="infra-section-title"><div className="infra-tabs"><button type="button" aria-selected={tab === "webhooks"} onClick={() => setTab("webhooks")}>{tx.webhooks}</button>{canDeliveries && <button type="button" aria-selected={tab === "deliveries"} onClick={() => setTab("deliveries")}>{tx.deliveries}</button>}</div><label className="infra-search"><Search /><input value={query} placeholder={tx.search} onChange={(event) => setQuery(event.target.value)} /></label></div>
    {tab === "webhooks" ? <div className="infra-table-wrap"><table className="infra-table"><thead><tr><th>{tx.name}</th><th>{tx.url}</th><th>{tx.events}</th><th>{tx.auth}</th><th>{tx.status}</th><th>{tx.actions}</th></tr></thead><tbody>{filtered.map((item) => <tr key={item.id}><td><strong>{item.name}</strong><small>{item.description}</small></td><td><code>{item.method}</code> {item.url}</td><td><div className="infra-chips">{item.events.slice(0, 4).map((event) => <span key={event}>{event}</span>)}{item.events.length > 4 && <span>+{item.events.length - 4}</span>}</div></td><td>{item.auth_type}{item.signing_secret_id && <small>HMAC</small>}</td><td><span className="infra-badge">{item.enabled ? tx.enabled : tx.disable}</span></td><td><div className="infra-row-actions">{canTest && <button type="button" onClick={() => void test(item)}><FlaskConical />{tx.test}</button>}{canManage && <><button type="button" onClick={() => void toggle(item)}>{item.enabled ? tx.disable : tx.enable}</button><button type="button" onClick={() => showEditor(item)}>{tx.edit}</button><button className="button-danger" type="button" onClick={() => void remove(item)}>{tx.remove}</button></>}</div></td></tr>)}{!loading && filtered.length === 0 && <tr><td className="infra-empty" colSpan={6}>—</td></tr>}</tbody></table></div> : <div className="infra-table-wrap"><table className="infra-table"><thead><tr><th>{tx.status}</th><th>{tx.events}</th><th>{tx.attempt}</th><th>{tx.http}</th><th>{tx.duration}</th><th>{tx.response}</th></tr></thead><tbody>{deliveries.filter((item) => !query || [item.event_type,item.status,item.error_category,item.response_preview].some((value) => String(value).toLowerCase().includes(query.toLowerCase()))).map((item) => <tr key={item.id}><td><span className={`infra-badge ${item.status}`}>{item.status}</span><small>{new Date(item.created_at * 1000).toLocaleString(language)}</small></td><td>{item.event_type}<small>{item.webhook_id}</small></td><td>{item.attempt}</td><td>{item.http_status ?? "—"}</td><td>{Math.round(item.duration_ms)} ms</td><td>{item.error_category || item.response_preview || "—"}</td></tr>)}</tbody></table></div>}

    {open && <Modal title={editing ? `${tx.edit}: ${editing.name}` : tx.add} closeLabel={tx.close} onClose={() => setOpen(false)} footer={<button className="button-primary" type="submit" form="webhook-form">{tx.save}</button>}><form id="webhook-form" className="infra-form" onSubmit={save}>
      <label>{tx.name}<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label>{tx.method}<select value={form.method} onChange={(event) => setForm({ ...form, method: event.target.value as WebhookInput["method"] })}><option>POST</option><option>PUT</option><option>PATCH</option></select></label>
      <label className="infra-form-wide">{tx.url}<input required type="url" value={form.url} onChange={(event) => setForm({ ...form, url: event.target.value })} /></label><label className="infra-form-wide">{tx.description}<textarea rows={2} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
      <label>{tx.timeout}<input type="number" min={1} max={60} value={form.timeout_seconds} onChange={(event) => setForm({ ...form, timeout_seconds: Number(event.target.value) })} /></label><label>{tx.attempts}<input type="number" min={1} max={8} value={form.max_attempts} onChange={(event) => setForm({ ...form, max_attempts: Number(event.target.value) })} /></label>
      <fieldset className="infra-form-wide"><legend>{tx.events}</legend><div className="infra-check-grid">{events.map((eventName) => <label key={eventName}><input type="checkbox" checked={form.events.includes(eventName)} onChange={(event) => setForm({ ...form, events: event.target.checked ? [...new Set([...form.events, eventName])] : form.events.filter((value) => value !== eventName) })} />{eventName}</label>)}</div></fieldset>
      <label>{tx.auth}<select value={form.auth_type} onChange={(event) => setForm({ ...form, auth_type: event.target.value as WebhookInput["auth_type"] })}><option value="none">none</option><option value="bearer">Bearer Token</option><option value="basic">Basic Auth</option><option value="api_key_header">API key header</option><option value="secret_header">Custom secret header</option></select></label>
      <label>{tx.secret}<select value={form.secret_id || ""} onChange={(event) => setForm({ ...form, secret_id: event.target.value || null })}><option value="">—</option>{secrets.map((secret) => <option key={secret.id} value={secret.id}>{secret.name} ({secret.type})</option>)}</select></label>
      {(form.auth_type === "api_key_header" || form.auth_type === "secret_header") && <label>{pl ? "Nazwa nagłówka" : "Header name"}<input value={form.auth_header_name} onChange={(event) => setForm({ ...form, auth_header_name: event.target.value })} /></label>}
      <label>{tx.signing}<select value={form.signing_secret_id || ""} onChange={(event) => setForm({ ...form, signing_secret_id: event.target.value || null })}><option value="">—</option>{secrets.map((secret) => <option key={secret.id} value={secret.id}>{secret.name}</option>)}</select></label>
      <label className="infra-form-wide">{tx.headers}<textarea rows={5} spellCheck={false} value={headersText} onChange={(event) => setHeadersText(event.target.value)} /></label><label><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} /> {tx.enabled}</label><label><input type="checkbox" checked={form.allow_private_networks} onChange={(event) => setForm({ ...form, allow_private_networks: event.target.checked })} /> {tx.private}</label>
    </form></Modal>}
    {testResult && <Modal title={tx.testResult} closeLabel={tx.close} onClose={() => setTestResult(null)}><div className="infra-stat-grid"><div className="infra-stat"><strong>{testResult.status}</strong><small>{tx.status}</small></div><div className="infra-stat"><strong>{testResult.http_status ?? "—"}</strong><small>{tx.http}</small></div><div className="infra-stat"><strong>{Math.round(testResult.duration_ms)} ms</strong><small>{tx.duration}</small></div></div><pre className="infra-log-list">{testResult.error_category || testResult.response_preview || "—"}</pre></Modal>}
  </div>;
}
