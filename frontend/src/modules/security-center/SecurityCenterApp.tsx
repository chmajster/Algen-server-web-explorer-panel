import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, ScanSearch, ShieldCheck } from "lucide-react";
import type { ToastFn } from "../../app/types";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { securityClient, type Finding, type Summary } from "./api/client";
import "../security-tools.css";

type Tab = "overview" | "findings" | "authentication" | "network" | "updates" | "certificates" | "audit";

export function SecurityCenterApp({ permissions, toast }: { permissions: readonly string[]; toast: ToastFn }) {
  const [tab, setTab] = useState<Tab>("overview");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(false);
  const can = (permission: string) => permissions.includes(permission);
  const load = useCallback(async () => {
    setLoading(true);
    try { const [nextSummary, nextFindings] = await Promise.all([securityClient.summary(), securityClient.findings()]); setSummary(nextSummary); setFindings(nextFindings.items); }
    catch (error) { toast(String(error), "error"); }
    finally { setLoading(false); }
  }, [toast]);
  useEffect(() => { void load(); }, [load]);
  async function scan() { try { await securityClient.scan(); toast("Security scan queued", "success"); await load(); } catch (error) { toast(String(error), "error"); } }
  async function setState(item: Finding, status: Finding["status"]) { try { await securityClient.setState(item.id, status); await load(); } catch (error) { toast(String(error), "error"); } }

  const columns = useMemo<DataTableColumn<Finding>[]>(() => [
    { key: "severity", header: "Severity", render: (row) => <strong className={`security-tone-${row.severity === "critical" || row.severity === "high" ? "danger" : row.severity === "medium" ? "warning" : "ok"}`}>{row.severity.toUpperCase()}</strong> },
    { key: "title", header: "Finding", render: (row) => <div><strong>{row.title}</strong><small>{row.description}</small></div> },
    { key: "resource", header: "Affected resource", render: (row) => row.affected_resource },
    { key: "source", header: "Detection source", render: (row) => row.detection_source },
    { key: "status", header: "Status", render: (row) => row.status },
  ], []);
  const visible = findings.filter((item) => tab === "findings" || tab === "overview" || tab === "authentication" && item.category === "authentication" || tab === "network" && item.category === "network" || tab === "updates" && item.category === "updates" || tab === "certificates" && item.category === "tls");

  return <section className="security-tool-app">
    <header className="security-tool-header"><div><span className="security-tool-eyebrow">Security posture</span><h2><ShieldCheck /> Security Center</h2><p>Aggregated host and WebNAS security signals. Remediation remains an explicit administrator action.</p></div><div className="security-actions"><button className="security-action" onClick={() => void load()}><RefreshCw /> Refresh</button>{can("security.scan") && <button className="security-action" onClick={() => void scan()}><ScanSearch /> Run Security Scan</button>}</div></header>
    <div className="security-stat-grid"><article><span>Security Score</span><strong className={(summary?.score ?? 100) < 60 ? "security-tone-danger" : (summary?.score ?? 100) < 85 ? "security-tone-warning" : "security-tone-ok"}>{summary?.score ?? "—"}/100</strong><small>{summary?.findings ?? 0} active findings</small></article><article><span>Critical / High</span><strong>{summary ? `${summary.severity.critical ?? 0} / ${summary.severity.high ?? 0}` : "—"}</strong><small>Prioritize these findings first</small></article><article><span>Last scan</span><strong>{summary?.last_scan ? new Date(summary.last_scan * 1000).toLocaleTimeString() : "—"}</strong><small>Scans run as WebNAS jobs</small></article></div>
    <nav className="security-tabs" aria-label="Security Center sections">{(["overview", "findings", "authentication", "network", "updates", "certificates", "audit"] as Tab[]).map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item[0].toUpperCase() + item.slice(1)}</button>)}</nav>
    {tab === "overview" && <div className="security-panel"><h3>Security areas</h3><div className="security-stat-grid">{Object.entries(summary?.areas || {}).map(([name, area]) => <article key={name}><span>{name}</span><strong>{area.score}/100</strong><small>{area.findings} finding(s)</small></article>)}</div></div>}
    {tab === "audit" ? <div className="security-panel"><h3>Audit</h3><p>Security scan and finding state changes are written to the shared Activity Center.</p></div> : <div className="security-panel"><h3>{tab === "overview" ? "Highest priority findings" : tab === "findings" ? "Security Findings" : `${tab[0].toUpperCase() + tab.slice(1)} findings`}</h3><DataTable rows={visible} columns={columns} getRowId={(row) => row.id} loading={loading} emptyTitle="No findings" actions={can("security.findings.manage") ? (row) => <div className="security-actions">{row.status !== "acknowledged" && <button onClick={() => void setState(row, "acknowledged")}>Acknowledge</button>}{row.status !== "resolved" && <button onClick={() => void setState(row, "resolved")}>Resolve</button>}</div> : undefined} /></div>}
  </section>;
}
