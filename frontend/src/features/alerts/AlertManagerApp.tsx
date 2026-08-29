import { AlertTriangle, Bell, CheckCircle2, Plus, RefreshCw, Send, Settings2, Trash2 } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  alertsClient,
  type AlertDashboard,
  type AlertItem,
  type AlertRule,
  type AlertSeverity,
  type AlertSink,
  type AlertSinkType,
  type AlertState,
} from "../../modules/alerts/api/client";
import "./alert-manager.css";

const severities: AlertSeverity[] = ["info", "warning", "error", "critical"];
const states: AlertState[] = ["firing", "acknowledged", "resolved"];

const copy = {
  "pl-PL": {
    title: "Alert Manager",
    subtitle: "Centralny cykl życia alertów i dostarczanie powiadomień.",
    alerts: "Alerty", rules: "Reguły", sinks: "Kanały", refresh: "Odśwież",
    firing: "Aktywne", acknowledged: "Potwierdzone", resolved: "Rozwiązane",
    pending: "Oczekujące dostawy", failed: "Nieudane dostawy", all: "Wszystkie",
    acknowledge: "Potwierdź", resolve: "Rozwiąż", occurrences: "Wystąpienia",
    empty: "Brak alertów dla wybranych filtrów.", source: "Źródło", severity: "Poziom",
    lastSeen: "Ostatnio", actions: "Akcje", newRule: "Nowa reguła", name: "Nazwa",
    cooldown: "Cooldown (s)", enabled: "Aktywna", save: "Zapisz", delete: "Usuń",
    builtIn: "wbudowana", assignedSinks: "Kanały", newSink: "Nowy kanał", type: "Typ",
    url: "URL HTTPS", token: "Token", smtpHost: "Host SMTP", smtpPort: "Port",
    smtpUser: "Użytkownik SMTP", smtpPassword: "Hasło SMTP", smtpFrom: "Nadawca",
    smtpTo: "Odbiorcy (po przecinku)", starttls: "STARTTLS", test: "Testuj",
    configured: "sekret zapisany", noPermission: "Brak uprawnień do konfiguracji.",
    error: "Nie udało się wykonać operacji.", create: "Utwórz", matcher: "Matcher JSON",
  },
  "en-US": {
    title: "Alert Manager",
    subtitle: "Central alert lifecycle and notification delivery.",
    alerts: "Alerts", rules: "Rules", sinks: "Sinks", refresh: "Refresh",
    firing: "Firing", acknowledged: "Acknowledged", resolved: "Resolved",
    pending: "Pending deliveries", failed: "Failed deliveries", all: "All",
    acknowledge: "Acknowledge", resolve: "Resolve", occurrences: "Occurrences",
    empty: "No alerts match the selected filters.", source: "Source", severity: "Severity",
    lastSeen: "Last seen", actions: "Actions", newRule: "New rule", name: "Name",
    cooldown: "Cooldown (s)", enabled: "Enabled", save: "Save", delete: "Delete",
    builtIn: "built-in", assignedSinks: "Sinks", newSink: "New sink", type: "Type",
    url: "HTTPS URL", token: "Token", smtpHost: "SMTP host", smtpPort: "Port",
    smtpUser: "SMTP username", smtpPassword: "SMTP password", smtpFrom: "Sender",
    smtpTo: "Recipients (comma separated)", starttls: "STARTTLS", test: "Test",
    configured: "secret configured", noPermission: "You do not have configuration permission.",
    error: "The operation failed.", create: "Create", matcher: "Matcher JSON",
  },
} as const;

type Tab = "alerts" | "rules" | "sinks";

export function AlertManagerApp({
  locale,
  canConfigure,
  canAcknowledge,
}: {
  locale: "pl-PL" | "en-US";
  canConfigure: boolean;
  canAcknowledge: boolean;
}) {
  const c = copy[locale];
  const [tab, setTab] = useState<Tab>("alerts");
  const [dashboard, setDashboard] = useState<AlertDashboard | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [sinks, setSinks] = useState<AlertSink[]>([]);
  const [state, setState] = useState<AlertState | "">("");
  const [severity, setSeverity] = useState<AlertSeverity | "">("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextDashboard, nextAlerts, nextRules] = await Promise.all([
        alertsClient.alertsDashboard(),
        alertsClient.alertsList({ state, severity }),
        alertsClient.alertRules(),
      ]);
      setDashboard(nextDashboard);
      setAlerts(nextAlerts);
      setRules(nextRules);
      if (canConfigure) setSinks(await alertsClient.alertSinks());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : c.error);
    } finally {
      setLoading(false);
    }
  }, [c.error, canConfigure, severity, state]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, 20_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const counts = useMemo(() => ({
    firing: dashboard?.alerts.firing || 0,
    acknowledged: dashboard?.alerts.acknowledged || 0,
    resolved: dashboard?.alerts.resolved || 0,
  }), [dashboard]);

  async function act(action: () => Promise<unknown>) {
    setError("");
    try {
      await action();
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : c.error);
    }
  }

  return <section className="alert-manager" aria-label={c.title}>
    <header className="alert-manager__header">
      <div><h2><Bell aria-hidden="true" />{c.title}</h2><p>{c.subtitle}</p></div>
      <button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{c.refresh}</button>
    </header>

    <div className="alert-manager__summary">
      <Summary label={c.firing} value={counts.firing} tone="critical" />
      <Summary label={c.acknowledged} value={counts.acknowledged} tone="warning" />
      <Summary label={c.resolved} value={counts.resolved} tone="ok" />
      <Summary label={c.pending} value={dashboard?.pending_deliveries || 0} />
      <Summary label={c.failed} value={dashboard?.failed_deliveries || 0} tone="critical" />
    </div>

    <nav className="alert-manager__tabs" aria-label={c.title}>
      {(["alerts", "rules", "sinks"] as const).map((item) => <button key={item} type="button" className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{c[item]}</button>)}
    </nav>

    {error && <div className="alert-manager__error" role="alert"><AlertTriangle />{error}</div>}

    {tab === "alerts" && <div className="alert-manager__panel">
      <div className="alert-manager__filters">
        <label>{c.firing}<select value={state} onChange={(event) => setState(event.target.value as AlertState | "")}><option value="">{c.all}</option>{states.map((item) => <option key={item} value={item}>{c[item]}</option>)}</select></label>
        <label>{c.severity}<select value={severity} onChange={(event) => setSeverity(event.target.value as AlertSeverity | "")}><option value="">{c.all}</option>{severities.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
      </div>
      <div className="alert-manager__table-wrap">
        <table><thead><tr><th>{c.severity}</th><th>{c.source}</th><th>{c.alerts}</th><th>{c.occurrences}</th><th>{c.lastSeen}</th><th>{c.actions}</th></tr></thead>
          <tbody>{alerts.map((item) => <tr key={item.id}>
            <td><span className={`alert-badge severity-${item.severity}`}>{item.severity}</span></td>
            <td><code>{item.source}</code></td>
            <td><strong>{item.title}</strong>{item.object_ref && <small>{item.object_ref}</small>}<span className={`alert-badge state-${item.state}`}>{c[item.state]}</span></td>
            <td>{item.occurrences}</td>
            <td>{new Date(item.last_seen_at * 1000).toLocaleString(locale)}</td>
            <td className="alert-actions">{canAcknowledge && item.state === "firing" && <button type="button" onClick={() => void act(() => alertsClient.alertAcknowledge(item.id))}>{c.acknowledge}</button>}{canAcknowledge && item.state !== "resolved" && <button type="button" onClick={() => void act(() => alertsClient.alertResolve(item.id))}>{c.resolve}</button>}</td>
          </tr>)}</tbody></table>
        {!loading && alerts.length === 0 && <div className="alert-manager__empty">{c.empty}</div>}
      </div>
    </div>}

    {tab === "rules" && <RulesPanel c={c} rules={rules} sinks={sinks} canConfigure={canConfigure} act={act} />}
    {tab === "sinks" && <SinksPanel c={c} sinks={sinks} canConfigure={canConfigure} act={act} />}
  </section>;
}

function Summary({ label, value, tone = "neutral" }: { label: string; value: number; tone?: string }) {
  return <div className={`alert-summary tone-${tone}`}><span>{label}</span><strong>{value}</strong></div>;
}

function RulesPanel({ c, rules, sinks, canConfigure, act }: { c: typeof copy["en-US"] | typeof copy["pl-PL"]; rules: AlertRule[]; sinks: AlertSink[]; canConfigure: boolean; act: (action: () => Promise<unknown>) => Promise<void> }) {
  const [name, setName] = useState("");
  const [source, setSource] = useState("operation.failed");
  const [severity, setSeverity] = useState<AlertSeverity>("error");
  const [cooldown, setCooldown] = useState(300);
  const [selectedSinks, setSelectedSinks] = useState<string[]>([]);
  const [matcher, setMatcher] = useState("{}");

  async function submit(event: FormEvent) {
    event.preventDefault();
    let parsed: Record<string, unknown> = {};
    try { parsed = JSON.parse(matcher) as Record<string, unknown>; } catch { return; }
    await act(() => alertsClient.alertRuleCreate({ name, source, severity, cooldown_seconds: cooldown, enabled: true, matcher: parsed, sink_ids: selectedSinks }));
    setName(""); setMatcher("{}");
  }

  return <div className="alert-manager__panel split-panel">
    <div><h3><Settings2 />{c.rules}</h3><div className="alert-rule-list">{rules.map((rule) => <article key={rule.id} className="alert-card">
      <header><div><strong>{rule.name}</strong>{rule.built_in && <small>{c.builtIn}</small>}</div><span className={`alert-badge severity-${rule.severity}`}>{rule.severity}</span></header>
      <p><code>{rule.source}</code> · {c.cooldown}: {rule.cooldown_seconds}</p>
      <p>{c.assignedSinks}: {rule.sink_ids.map((id) => sinks.find((sink) => sink.id === id)?.name || id).join(", ") || "—"}</p>
      {canConfigure && <footer><button type="button" onClick={() => void act(() => alertsClient.alertRuleUpdate(rule.id, { name: rule.name, source: rule.source, severity: rule.severity, cooldown_seconds: rule.cooldown_seconds, enabled: !rule.enabled, matcher: rule.matcher, sink_ids: rule.sink_ids }))}>{rule.enabled ? "Disable" : "Enable"}</button>{!rule.built_in && <button type="button" className="danger" onClick={() => void act(() => alertsClient.alertRuleDelete(rule.id))}><Trash2 />{c.delete}</button>}</footer>}
    </article>)}</div></div>
    <form onSubmit={(event) => void submit(event)} className="alert-form"><h3><Plus />{c.newRule}</h3>{!canConfigure && <p>{c.noPermission}</p>}
      <label>{c.name}<input required value={name} onChange={(event) => setName(event.target.value)} disabled={!canConfigure} /></label>
      <label>{c.source}<input required pattern="[a-z0-9._-]+" value={source} onChange={(event) => setSource(event.target.value)} disabled={!canConfigure} /></label>
      <label>{c.severity}<select value={severity} onChange={(event) => setSeverity(event.target.value as AlertSeverity)} disabled={!canConfigure}>{severities.map((item) => <option key={item}>{item}</option>)}</select></label>
      <label>{c.cooldown}<input type="number" min="0" max="86400" value={cooldown} onChange={(event) => setCooldown(Number(event.target.value))} disabled={!canConfigure} /></label>
      <label>{c.matcher}<textarea value={matcher} onChange={(event) => setMatcher(event.target.value)} disabled={!canConfigure} /></label>
      <fieldset disabled={!canConfigure}><legend>{c.assignedSinks}</legend>{sinks.map((sink) => <label key={sink.id} className="check"><input type="checkbox" checked={selectedSinks.includes(sink.id)} onChange={(event) => setSelectedSinks((current) => event.target.checked ? [...current, sink.id] : current.filter((id) => id !== sink.id))} />{sink.name}</label>)}</fieldset>
      <button type="submit" disabled={!canConfigure || !name}><Plus />{c.create}</button>
    </form>
  </div>;
}

function SinksPanel({ c, sinks, canConfigure, act }: { c: typeof copy["en-US"] | typeof copy["pl-PL"]; sinks: AlertSink[]; canConfigure: boolean; act: (action: () => Promise<unknown>) => Promise<void> }) {
  const [name, setName] = useState("");
  const [type, setType] = useState<AlertSinkType>("webhook");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState(587);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [starttls, setStarttls] = useState(true);

  async function submit(event: FormEvent) {
    event.preventDefault();
    await act(() => alertsClient.alertSinkCreate({
      name, type, enabled: true, url: type === "smtp" ? undefined : url, token: type === "smtp" ? undefined : token,
      smtp_host: type === "smtp" ? host : undefined, smtp_port: type === "smtp" ? port : undefined,
      smtp_username: type === "smtp" ? username : undefined, smtp_password: type === "smtp" ? password : undefined,
      smtp_from: type === "smtp" ? from : undefined, smtp_to: type === "smtp" ? to.split(",").map((item) => item.trim()).filter(Boolean) : undefined,
      smtp_starttls: type === "smtp" ? starttls : undefined,
    }));
    setName(""); setUrl(""); setToken(""); setPassword("");
  }

  return <div className="alert-manager__panel split-panel">
    <div><h3><Send />{c.sinks}</h3>{sinks.map((sink) => <article key={sink.id} className="alert-card"><header><div><strong>{sink.name}</strong><small>{sink.type} · {sink.configured ? c.configured : ""}</small></div><span className={`alert-badge ${sink.enabled ? "state-firing" : "state-resolved"}`}>{sink.enabled ? c.enabled : "disabled"}</span></header>{canConfigure && <footer><button type="button" onClick={() => void act(() => alertsClient.alertSinkTest(sink.id))}><Send />{c.test}</button><button type="button" className="danger" onClick={() => void act(() => alertsClient.alertSinkDelete(sink.id))}><Trash2 />{c.delete}</button></footer>}</article>)}</div>
    <form onSubmit={(event) => void submit(event)} className="alert-form"><h3><Plus />{c.newSink}</h3>{!canConfigure && <p>{c.noPermission}</p>}
      <label>{c.name}<input required value={name} onChange={(event) => setName(event.target.value)} disabled={!canConfigure} /></label>
      <label>{c.type}<select value={type} onChange={(event) => setType(event.target.value as AlertSinkType)} disabled={!canConfigure}><option value="webhook">Webhook</option><option value="ntfy">ntfy</option><option value="smtp">SMTP</option></select></label>
      {type !== "smtp" ? <><label>{c.url}<input type="url" required pattern="https://.*" value={url} onChange={(event) => setUrl(event.target.value)} disabled={!canConfigure} /></label><label>{c.token}<input type="password" autoComplete="new-password" value={token} onChange={(event) => setToken(event.target.value)} disabled={!canConfigure} /></label></> : <>
        <label>{c.smtpHost}<input required value={host} onChange={(event) => setHost(event.target.value)} disabled={!canConfigure} /></label>
        <label>{c.smtpPort}<input type="number" min="1" max="65535" value={port} onChange={(event) => setPort(Number(event.target.value))} disabled={!canConfigure} /></label>
        <label>{c.smtpUser}<input value={username} onChange={(event) => setUsername(event.target.value)} disabled={!canConfigure} /></label>
        <label>{c.smtpPassword}<input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={!canConfigure} /></label>
        <label>{c.smtpFrom}<input required type="email" value={from} onChange={(event) => setFrom(event.target.value)} disabled={!canConfigure} /></label>
        <label>{c.smtpTo}<input required value={to} onChange={(event) => setTo(event.target.value)} disabled={!canConfigure} /></label>
        <label className="check"><input type="checkbox" checked={starttls} onChange={(event) => setStarttls(event.target.checked)} disabled={!canConfigure} />{c.starttls}</label>
      </>}
      <button type="submit" disabled={!canConfigure || !name}><Plus />{c.create}</button>
    </form>
  </div>;
}
