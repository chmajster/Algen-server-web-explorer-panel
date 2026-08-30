import { useCallback, useEffect, useMemo, useState } from "react";
import { Archive, Network, Plus, RefreshCw, Shield, Trash2 } from "lucide-react";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import type { ToastFn } from "../../app/types";
import { firewallClient, type Auth, type Backup, type FirewallRule, type FirewallStatus, type ListeningPort, type RuleInput } from "./api/client";
import "../security-tools.css";

type Tab = "overview" | "rules" | "ports" | "backups" | "activity";
const EMPTY_RULE: RuleInput = { action: "allow", direction: "in", protocol: "tcp", port: "", source: "any", destination: "any", interface: "", comment: "", family: "any" };

export function FirewallManagerApp({ permissions, language, toast }: { permissions: readonly string[]; language: string; toast: ToastFn }) {
  const pl = language.toLowerCase().startsWith("pl");
  const tx = {
    passwordRequired: pl ? "Hasło PAM jest wymagane" : "PAM password is required",
    queued: pl ? "Zadanie zapory zostało dodane do kolejki" : "Firewall job queued",
    action: pl ? "Akcja" : "Action",
    direction: pl ? "Kierunek" : "Direction",
    protocol: pl ? "Protokół" : "Protocol",
    port: "Port",
    any: pl ? "Dowolny" : "Any",
    source: pl ? "Źródło" : "Source",
    destination: pl ? "Cel" : "Destination",
    description: pl ? "Opis" : "Description",
    listenAddress: pl ? "Adres nasłuchu" : "Listen address",
    process: pl ? "Proces / usługa" : "Process / service",
    firewallRule: pl ? "Reguła zapory" : "Firewall rule",
    notMatched: pl ? "Brak jawnego dopasowania" : "Not explicitly matched",
    eyebrow: pl ? "Bezpieczeństwo hosta" : "Host security",
    title: "Firewall Manager",
    subtitle: pl ? "Lokalna polityka zapory z kontrolowanymi zmianami, kopiami do wycofania i ochroną przed odcięciem administratora." : "Local firewall policy with typed changes, rollback backups and administrative lockout protection.",
    refresh: pl ? "Odśwież" : "Refresh",
    backend: "Backend",
    noBackend: pl ? "Brak obsługiwanego backendu" : "No supported backend",
    firewall: pl ? "Zapora" : "Firewall",
    active: pl ? "Aktywna" : "Active",
    inactive: pl ? "Nieaktywna" : "Inactive",
    normalizedRules: pl ? "znormalizowanych reguł" : "normalized rules",
    listeningPorts: pl ? "Porty nasłuchujące" : "Listening ports",
    withoutMatch: pl ? "bez jawnego dopasowania" : "without an explicit match",
    sections: pl ? "Sekcje Firewall Manager" : "Firewall sections",
    overview: pl ? "Przegląd" : "Overview",
    rules: pl ? "Reguły" : "Rules",
    openPorts: pl ? "Otwarte porty" : "Open Ports",
    backups: pl ? "Kopie zapasowe" : "Backups",
    activity: pl ? "Aktywność" : "Activity",
    pamPassword: pl ? "Hasło PAM" : "PAM password",
    lockoutAck: pl ? "Rozumiem, że zmiana zapory może przerwać tę sesję." : "I understand a firewall change can disconnect this session.",
    firewallState: pl ? "Stan zapory" : "Firewall state",
    noStatus: pl ? "Brak dostępnego statusu zapory." : "No firewall status available.",
    enable: pl ? "Włącz" : "Enable",
    disable: pl ? "Wyłącz" : "Disable",
    reload: pl ? "Przeładuj" : "Reload",
    rulesHint: pl ? "Lista reguł ujednolicona między backendami. Zmiany nftables są ograniczone do dedykowanej tabeli WebNAS." : "Backend-normalized rule inventory. nftables changes are limited to the dedicated WebNAS table.",
    inbound: pl ? "Przychodzący" : "Inbound",
    outbound: pl ? "Wychodzący" : "Outbound",
    anyProtocol: pl ? "Dowolny protokół" : "Any protocol",
    portRange: pl ? "Port lub zakres" : "Port or range",
    sourceCidr: pl ? "Źródłowy CIDR / any" : "Source CIDR / any",
    destinationCidr: pl ? "Docelowy CIDR / any" : "Destination CIDR / any",
    interface: pl ? "Interfejs" : "Interface",
    addRule: pl ? "Dodaj regułę" : "Add rule",
    firewallRules: pl ? "Reguły zapory" : "Firewall rules",
    deleteRule: pl ? "Usuń regułę" : "Delete rule",
    manualBackup: pl ? "Ręczna kopia zapory" : "Manual firewall backup",
    createBackup: pl ? "Utwórz kopię" : "Create backup",
    created: pl ? "Utworzono" : "Created",
    restore: pl ? "Przywróć" : "Restore",
    time: pl ? "Czas" : "Time",
    actor: pl ? "Użytkownik" : "Actor",
    status: "Status",
  };
  const [tab, setTab] = useState<Tab>("overview");
  const [status, setStatus] = useState<FirewallStatus | null>(null);
  const [rules, setRules] = useState<FirewallRule[]>([]);
  const [ports, setPorts] = useState<ListeningPort[]>([]);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [activity, setActivity] = useState<Array<{ id: number; created_at: number; action: string; actor: string; status: string; summary: string }>>([]);
  const [loading, setLoading] = useState(false);
  const [password, setPassword] = useState("");
  const [ack, setAck] = useState(false);
  const [rule, setRule] = useState<RuleInput>(EMPTY_RULE);
  const can = (permission: string) => permissions.includes(permission);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextStatus, nextRules, nextPorts, nextBackups, nextActivity] = await Promise.all([firewallClient.status(), firewallClient.rules(), firewallClient.ports(), firewallClient.backups(), firewallClient.activity()]);
      setStatus(nextStatus); setRules(nextRules.items); setPorts(nextPorts.items); setBackups(nextBackups.items); setActivity(nextActivity.items);
    } catch (error) { toast(String(error), "error"); }
    finally { setLoading(false); }
  }, [toast]);
  useEffect(() => { void load(); }, [load]);

  const auth = (confirmation: string): Auth => ({ pam_password: password, confirmation, acknowledge_lockout: ack });
  async function mutate(action: () => Promise<unknown>) {
    if (!password) { toast(tx.passwordRequired, "error"); return; }
    try { await action(); toast(tx.queued, "ok"); setPassword(""); await load(); } catch (error) { toast(String(error), "error"); }
  }

  const ruleColumns = useMemo<DataTableColumn<FirewallRule>[]>(() => [
    { key: "action", header: tx.action, render: (row) => <strong>{row.action.toUpperCase()}</strong> },
    { key: "direction", header: tx.direction, render: (row) => row.direction },
    { key: "protocol", header: tx.protocol, render: (row) => row.protocol },
    { key: "port", header: tx.port, render: (row) => row.port || tx.any },
    { key: "source", header: tx.source, render: (row) => row.source },
    { key: "destination", header: tx.destination, render: (row) => row.destination },
    { key: "comment", header: tx.description, render: (row) => row.comment || "—" },
  ], [tx.action, tx.any, tx.description, tx.destination, tx.direction, tx.port, tx.protocol, tx.source]);
  const portColumns = useMemo<DataTableColumn<ListeningPort>[]>(() => [
    { key: "proto", header: tx.protocol, render: (row) => row.protocol },
    { key: "address", header: tx.listenAddress, render: (row) => `${row.address}:${row.port}` },
    { key: "process", header: tx.process, render: (row) => row.process || "—" },
    { key: "rule", header: tx.firewallRule, render: (row) => row.firewall_rule || <span className="security-tone-warning">{tx.notMatched}</span> },
  ], [tx.firewallRule, tx.listenAddress, tx.notMatched, tx.process, tx.protocol]);
  const tabLabel = (item: Tab) => item === "overview" ? tx.overview : item === "rules" ? tx.rules : item === "ports" ? tx.openPorts : item === "backups" ? tx.backups : tx.activity;

  return <section className="security-tool-app">
    <header className="security-tool-header"><div><span className="security-tool-eyebrow">{tx.eyebrow}</span><h2><Shield /> {tx.title}</h2><p>{tx.subtitle}</p></div><button className="security-action" onClick={() => void load()} disabled={loading}><RefreshCw /> {tx.refresh}</button></header>
    <div className="security-stat-grid">
      <article><span>{tx.backend}</span><strong>{status?.backend || "—"}</strong><small>{status?.available_backends.join(", ") || tx.noBackend}</small></article>
      <article><span>{tx.firewall}</span><strong className={status?.active ? "security-tone-ok" : "security-tone-danger"}>{status?.active ? tx.active : tx.inactive}</strong><small>{status?.rules ?? 0} {tx.normalizedRules}</small></article>
      <article><span>{tx.listeningPorts}</span><strong>{ports.length}</strong><small>{ports.filter((item) => !item.firewall_rule).length} {tx.withoutMatch}</small></article>
    </div>
    <nav className="security-tabs" aria-label={tx.sections}>{(["overview", "rules", "ports", "backups", "activity"] as Tab[]).map((item) => <button type="button" key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{tabLabel(item)}</button>)}</nav>
    <div className="security-auth-strip"><label>{tx.pamPassword}<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label><label className="security-check"><input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} /> {tx.lockoutAck}</label></div>
    {tab === "overview" && <div className="security-panel"><h3>{tx.firewallState}</h3><pre>{status?.detail || tx.noStatus}</pre><div className="security-actions">{can("firewall.enable") && <button onClick={() => void mutate(() => firewallClient.enable(auth("firewall:enable")))}>{tx.enable}</button>}{can("firewall.disable") && <button className="danger" onClick={() => void mutate(() => firewallClient.disable(auth("firewall:disable")))}>{tx.disable}</button>}{can("firewall.reload") && <button onClick={() => void mutate(() => firewallClient.reload(auth("firewall:reload")))}><RefreshCw /> {tx.reload}</button>}</div></div>}
    {tab === "rules" && <div className="security-panel"><div className="security-section-title"><div><h3>{tx.rules}</h3><p>{tx.rulesHint}</p></div></div>{can("firewall.rules.create") && <form className="security-form-grid" onSubmit={(event) => { event.preventDefault(); void mutate(() => firewallClient.createRule(rule, auth("firewall:rule:create"))); }}><select value={rule.action} onChange={(event) => setRule({ ...rule, action: event.target.value as RuleInput["action"] })}><option value="allow">ALLOW</option><option value="drop">DROP</option><option value="reject">REJECT</option></select><select value={rule.direction} onChange={(event) => setRule({ ...rule, direction: event.target.value as RuleInput["direction"] })}><option value="in">{tx.inbound}</option><option value="out">{tx.outbound}</option></select><select value={rule.protocol} onChange={(event) => setRule({ ...rule, protocol: event.target.value as RuleInput["protocol"] })}><option value="tcp">TCP</option><option value="udp">UDP</option><option value="any">{tx.anyProtocol}</option></select><input placeholder={tx.portRange} value={rule.port} onChange={(event) => setRule({ ...rule, port: event.target.value })} /><input placeholder={tx.sourceCidr} value={rule.source} onChange={(event) => setRule({ ...rule, source: event.target.value })} /><input placeholder={tx.destinationCidr} value={rule.destination} onChange={(event) => setRule({ ...rule, destination: event.target.value })} /><input placeholder={tx.interface} value={rule.interface} onChange={(event) => setRule({ ...rule, interface: event.target.value })} /><input placeholder={tx.description} value={rule.comment} onChange={(event) => setRule({ ...rule, comment: event.target.value })} /><button className="security-action" type="submit"><Plus /> {tx.addRule}</button></form>}<DataTable rows={rules} columns={ruleColumns} getRowId={(row) => row.id} loading={loading} ariaLabel={tx.firewallRules} actions={can("firewall.rules.delete") ? (row) => <button className="icon-button danger" title={tx.deleteRule} disabled={!row.editable} onClick={() => void mutate(() => firewallClient.deleteRule(row.id, auth("firewall:rule:delete")))}><Trash2 /></button> : undefined} /></div>}
    {tab === "ports" && <div className="security-panel"><h3><Network /> {tx.listeningPorts}</h3><DataTable rows={ports} columns={portColumns} getRowId={(row) => `${row.protocol}:${row.address}:${row.port}:${row.process}`} loading={loading} /></div>}
    {tab === "backups" && <div className="security-panel"><div className="security-section-title"><h3><Archive /> {tx.backups}</h3>{can("firewall.backup") && <button className="security-action" onClick={() => void mutate(() => firewallClient.backup(tx.manualBackup, auth("firewall:backup")))}>{tx.createBackup}</button>}</div><DataTable rows={backups} getRowId={(row) => row.id} columns={[{ key: "id", header: "ID", render: (row) => row.id }, { key: "backend", header: tx.backend, render: (row) => row.backend }, { key: "rules", header: tx.rules, render: (row) => row.rules }, { key: "date", header: tx.created, render: (row) => new Date(row.created_at * 1000).toLocaleString(language) }]} actions={can("firewall.restore") ? (row) => <button onClick={() => void mutate(() => firewallClient.restore(row.id, auth("firewall:restore")))}>{tx.restore}</button> : undefined} /></div>}
    {tab === "activity" && <div className="security-panel"><h3>{tx.activity}</h3><DataTable rows={activity} getRowId={(row) => String(row.id)} columns={[{ key: "time", header: tx.time, render: (row) => new Date(row.created_at * 1000).toLocaleString(language) }, { key: "actor", header: tx.actor, render: (row) => row.actor }, { key: "action", header: tx.action, render: (row) => row.action }, { key: "status", header: tx.status, render: (row) => row.status }]} /></div>}
  </section>;
}
