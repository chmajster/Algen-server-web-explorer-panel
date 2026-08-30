import { useCallback, useEffect, useMemo, useState } from "react";
import { Archive, Network, Plus, RefreshCw, Shield, Trash2 } from "lucide-react";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import type { ToastFn } from "../../app/types";
import { firewallClient, type Auth, type Backup, type FirewallRule, type FirewallStatus, type ListeningPort, type RuleInput } from "./api/client";
import "../security-tools.css";

type Tab = "overview" | "rules" | "ports" | "backups" | "activity";
const EMPTY_RULE: RuleInput = { action: "allow", direction: "in", protocol: "tcp", port: "", source: "any", destination: "any", interface: "", comment: "", family: "any" };

export function FirewallManagerApp({ permissions, toast }: { permissions: readonly string[]; toast: ToastFn }) {
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
    if (!password) { toast("PAM password is required", "error"); return; }
    try { await action(); toast("Firewall job queued", "ok"); setPassword(""); await load(); } catch (error) { toast(String(error), "error"); }
  }

  const ruleColumns = useMemo<DataTableColumn<FirewallRule>[]>(() => [
    { key: "action", header: "Action", render: (row) => <strong>{row.action.toUpperCase()}</strong> },
    { key: "direction", header: "Direction", render: (row) => row.direction },
    { key: "protocol", header: "Protocol", render: (row) => row.protocol },
    { key: "port", header: "Port", render: (row) => row.port || "Any" },
    { key: "source", header: "Source", render: (row) => row.source },
    { key: "destination", header: "Destination", render: (row) => row.destination },
    { key: "comment", header: "Description", render: (row) => row.comment || "—" },
  ], []);
  const portColumns = useMemo<DataTableColumn<ListeningPort>[]>(() => [
    { key: "proto", header: "Protocol", render: (row) => row.protocol },
    { key: "address", header: "Listen address", render: (row) => `${row.address}:${row.port}` },
    { key: "process", header: "Process / service", render: (row) => row.process || "—" },
    { key: "rule", header: "Firewall rule", render: (row) => row.firewall_rule || <span className="security-tone-warning">Not explicitly matched</span> },
  ], []);

  return <section className="security-tool-app">
    <header className="security-tool-header"><div><span className="security-tool-eyebrow">Host security</span><h2><Shield /> Firewall Manager</h2><p>Local firewall policy with typed changes, rollback backups and administrative lockout protection.</p></div><button className="security-action" onClick={() => void load()} disabled={loading}><RefreshCw /> Refresh</button></header>
    <div className="security-stat-grid">
      <article><span>Backend</span><strong>{status?.backend || "—"}</strong><small>{status?.available_backends.join(", ") || "No supported backend"}</small></article>
      <article><span>Firewall</span><strong className={status?.active ? "security-tone-ok" : "security-tone-danger"}>{status?.active ? "Active" : "Inactive"}</strong><small>{status?.rules ?? 0} normalized rules</small></article>
      <article><span>Listening ports</span><strong>{ports.length}</strong><small>{ports.filter((item) => !item.firewall_rule).length} without an explicit match</small></article>
    </div>
    <nav className="security-tabs" aria-label="Firewall sections">{(["overview", "rules", "ports", "backups", "activity"] as Tab[]).map((item) => <button type="button" key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item === "ports" ? "Open Ports" : item[0].toUpperCase() + item.slice(1)}</button>)}</nav>
    <div className="security-auth-strip"><label>PAM password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label><label className="security-check"><input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} /> I understand a firewall change can disconnect this session.</label></div>
    {tab === "overview" && <div className="security-panel"><h3>Firewall state</h3><pre>{status?.detail || "No firewall status available."}</pre><div className="security-actions">{can("firewall.enable") && <button onClick={() => void mutate(() => firewallClient.enable(auth("firewall:enable")))}>Enable</button>}{can("firewall.disable") && <button className="danger" onClick={() => void mutate(() => firewallClient.disable(auth("firewall:disable")))}>Disable</button>}{can("firewall.reload") && <button onClick={() => void mutate(() => firewallClient.reload(auth("firewall:reload")))}><RefreshCw /> Reload</button>}</div></div>}
    {tab === "rules" && <div className="security-panel"><div className="security-section-title"><div><h3>Rules</h3><p>Backend-normalized rule inventory. nftables changes are limited to the dedicated WebNAS table.</p></div></div>{can("firewall.rules.create") && <form className="security-form-grid" onSubmit={(event) => { event.preventDefault(); void mutate(() => firewallClient.createRule(rule, auth("firewall:rule:create"))); }}><select value={rule.action} onChange={(event) => setRule({ ...rule, action: event.target.value as RuleInput["action"] })}><option value="allow">ALLOW</option><option value="drop">DROP</option><option value="reject">REJECT</option></select><select value={rule.direction} onChange={(event) => setRule({ ...rule, direction: event.target.value as RuleInput["direction"] })}><option value="in">Inbound</option><option value="out">Outbound</option></select><select value={rule.protocol} onChange={(event) => setRule({ ...rule, protocol: event.target.value as RuleInput["protocol"] })}><option value="tcp">TCP</option><option value="udp">UDP</option><option value="any">Any protocol</option></select><input placeholder="Port or range" value={rule.port} onChange={(event) => setRule({ ...rule, port: event.target.value })} /><input placeholder="Source CIDR / any" value={rule.source} onChange={(event) => setRule({ ...rule, source: event.target.value })} /><input placeholder="Destination CIDR / any" value={rule.destination} onChange={(event) => setRule({ ...rule, destination: event.target.value })} /><input placeholder="Interface" value={rule.interface} onChange={(event) => setRule({ ...rule, interface: event.target.value })} /><input placeholder="Description" value={rule.comment} onChange={(event) => setRule({ ...rule, comment: event.target.value })} /><button className="security-action" type="submit"><Plus /> Add rule</button></form>}<DataTable rows={rules} columns={ruleColumns} getRowId={(row) => row.id} loading={loading} ariaLabel="Firewall rules" actions={can("firewall.rules.delete") ? (row) => <button className="icon-button danger" title="Delete rule" disabled={!row.editable} onClick={() => void mutate(() => firewallClient.deleteRule(row.id, auth("firewall:rule:delete")))}><Trash2 /></button> : undefined} /></div>}
    {tab === "ports" && <div className="security-panel"><h3><Network /> Listening ports</h3><DataTable rows={ports} columns={portColumns} getRowId={(row) => `${row.protocol}:${row.address}:${row.port}:${row.process}`} loading={loading} /></div>}
    {tab === "backups" && <div className="security-panel"><div className="security-section-title"><h3><Archive /> Backups</h3>{can("firewall.backup") && <button className="security-action" onClick={() => void mutate(() => firewallClient.backup("Manual firewall backup", auth("firewall:backup")))}>Create backup</button>}</div><DataTable rows={backups} getRowId={(row) => row.id} columns={[{ key: "id", header: "ID", render: (row) => row.id }, { key: "backend", header: "Backend", render: (row) => row.backend }, { key: "rules", header: "Rules", render: (row) => row.rules }, { key: "date", header: "Created", render: (row) => new Date(row.created_at * 1000).toLocaleString() }]} actions={can("firewall.restore") ? (row) => <button onClick={() => void mutate(() => firewallClient.restore(row.id, auth("firewall:restore")))}>Restore</button> : undefined} /></div>}
    {tab === "activity" && <div className="security-panel"><h3>Activity</h3><DataTable rows={activity} getRowId={(row) => String(row.id)} columns={[{ key: "time", header: "Time", render: (row) => new Date(row.created_at * 1000).toLocaleString() }, { key: "actor", header: "Actor", render: (row) => row.actor }, { key: "action", header: "Action", render: (row) => row.action }, { key: "status", header: "Status", render: (row) => row.status }]} /></div>}
  </section>;
}
