import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, ScanSearch, ShieldCheck } from "lucide-react";
import type { ToastFn } from "../../app/types";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { securityClient, type Finding, type Summary } from "./api/client";
import "../security-tools.css";

type Tab = "overview" | "findings" | "authentication" | "network" | "updates" | "certificates" | "audit";

export function SecurityCenterApp({ permissions, language, toast }: { permissions: readonly string[]; language: string; toast: ToastFn }) {
  const pl = language.toLowerCase().startsWith("pl");
  const tx = {
    queued: pl ? "Skan bezpieczeństwa został dodany do kolejki" : "Security scan queued",
    severity: pl ? "Ważność" : "Severity",
    finding: pl ? "Znalezisko" : "Finding",
    resource: pl ? "Zasób" : "Affected resource",
    source: pl ? "Źródło wykrycia" : "Detection source",
    status: "Status",
    posture: pl ? "Stan bezpieczeństwa" : "Security posture",
    title: "Security Center",
    subtitle: pl ? "Zbiorczy obraz bezpieczeństwa hosta i WebNAS. Naprawy pozostają jawnymi działaniami administratora." : "Aggregated host and WebNAS security signals. Remediation remains an explicit administrator action.",
    refresh: pl ? "Odśwież" : "Refresh",
    scan: pl ? "Uruchom skan bezpieczeństwa" : "Run Security Scan",
    score: pl ? "Wynik bezpieczeństwa" : "Security Score",
    activeFindings: pl ? "aktywnych znalezisk" : "active findings",
    criticalHigh: pl ? "Krytyczne / wysokie" : "Critical / High",
    prioritize: pl ? "Te znaleziska obsłuż w pierwszej kolejności" : "Prioritize these findings first",
    lastScan: pl ? "Ostatni skan" : "Last scan",
    jobs: pl ? "Skany działają jako zadania WebNAS" : "Scans run as WebNAS jobs",
    sections: pl ? "Sekcje Security Center" : "Security Center sections",
    areas: pl ? "Obszary bezpieczeństwa" : "Security areas",
    findingsCount: pl ? "znalezisk" : "finding(s)",
    audit: "Audit",
    auditHint: pl ? "Skany bezpieczeństwa i zmiany stanu znalezisk są zapisywane we wspólnym Centrum aktywności." : "Security scan and finding state changes are written to the shared Activity Center.",
    highest: pl ? "Znaleziska o najwyższym priorytecie" : "Highest priority findings",
    securityFindings: pl ? "Znaleziska bezpieczeństwa" : "Security Findings",
    noFindings: pl ? "Brak znalezisk" : "No findings",
    acknowledge: pl ? "Potwierdź" : "Acknowledge",
    resolve: pl ? "Rozwiąż" : "Resolve",
  };
  const tabNames: Record<Tab, string> = {
    overview: pl ? "Przegląd" : "Overview",
    findings: pl ? "Znaleziska" : "Findings",
    authentication: pl ? "Uwierzytelnianie" : "Authentication",
    network: pl ? "Sieć" : "Network",
    updates: pl ? "Aktualizacje" : "Updates",
    certificates: pl ? "Certyfikaty" : "Certificates",
    audit: "Audit",
  };
  const severityNames: Record<string, string> = pl ? { critical: "KRYTYCZNE", high: "WYSOKIE", medium: "ŚREDNIE", low: "NISKIE", info: "INFO" } : {};
  const statusNames: Record<string, string> = pl ? { open: "otwarte", acknowledged: "potwierdzone", resolved: "rozwiązane" } : {};
  const areaNames: Record<string, string> = pl ? { authentication: "Uwierzytelnianie", network: "Sieć", updates: "Aktualizacje", tls: "TLS / certyfikaty", audit: "Audit" } : {};
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
  async function scan() { try { await securityClient.scan(); toast(tx.queued, "ok"); await load(); } catch (error) { toast(String(error), "error"); } }
  async function setState(item: Finding, status: Finding["status"]) { try { await securityClient.setState(item.id, status); await load(); } catch (error) { toast(String(error), "error"); } }

  const columns = useMemo<DataTableColumn<Finding>[]>(() => [
    { key: "severity", header: tx.severity, render: (row) => <strong className={`security-tone-${row.severity === "critical" || row.severity === "high" ? "danger" : row.severity === "medium" ? "warning" : "ok"}`}>{severityNames[row.severity] || row.severity.toUpperCase()}</strong> },
    { key: "title", header: tx.finding, render: (row) => <div><strong>{row.title}</strong><small>{row.description}</small></div> },
    { key: "resource", header: tx.resource, render: (row) => row.affected_resource },
    { key: "source", header: tx.source, render: (row) => row.detection_source },
    { key: "status", header: tx.status, render: (row) => statusNames[row.status] || row.status },
  ], [severityNames, statusNames, tx.finding, tx.resource, tx.severity, tx.source, tx.status]);
  const visible = findings.filter((item) => tab === "findings" || tab === "overview" || tab === "authentication" && item.category === "authentication" || tab === "network" && item.category === "network" || tab === "updates" && item.category === "updates" || tab === "certificates" && item.category === "tls");

  return <section className="security-tool-app">
    <header className="security-tool-header"><div><span className="security-tool-eyebrow">{tx.posture}</span><h2><ShieldCheck /> {tx.title}</h2><p>{tx.subtitle}</p></div><div className="security-actions"><button className="security-action" onClick={() => void load()}><RefreshCw /> {tx.refresh}</button>{can("security.scan") && <button className="security-action" onClick={() => void scan()}><ScanSearch /> {tx.scan}</button>}</div></header>
    <div className="security-stat-grid"><article><span>{tx.score}</span><strong className={(summary?.score ?? 100) < 60 ? "security-tone-danger" : (summary?.score ?? 100) < 85 ? "security-tone-warning" : "security-tone-ok"}>{summary?.score ?? "—"}/100</strong><small>{summary?.findings ?? 0} {tx.activeFindings}</small></article><article><span>{tx.criticalHigh}</span><strong>{summary ? `${summary.severity.critical ?? 0} / ${summary.severity.high ?? 0}` : "—"}</strong><small>{tx.prioritize}</small></article><article><span>{tx.lastScan}</span><strong>{summary?.last_scan ? new Date(summary.last_scan * 1000).toLocaleTimeString(language) : "—"}</strong><small>{tx.jobs}</small></article></div>
    <nav className="security-tabs" aria-label={tx.sections}>{(["overview", "findings", "authentication", "network", "updates", "certificates", "audit"] as Tab[]).map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{tabNames[item]}</button>)}</nav>
    {tab === "overview" && <div className="security-panel"><h3>{tx.areas}</h3><div className="security-stat-grid">{Object.entries(summary?.areas || {}).map(([name, area]) => <article key={name}><span>{areaNames[name] || name}</span><strong>{area.score}/100</strong><small>{area.findings} {tx.findingsCount}</small></article>)}</div></div>}
    {tab === "audit" ? <div className="security-panel"><h3>{tx.audit}</h3><p>{tx.auditHint}</p></div> : <div className="security-panel"><h3>{tab === "overview" ? tx.highest : tab === "findings" ? tx.securityFindings : `${tabNames[tab]} — ${pl ? "znaleziska" : "findings"}`}</h3><DataTable rows={visible} columns={columns} getRowId={(row) => row.id} loading={loading} emptyTitle={tx.noFindings} actions={can("security.findings.manage") ? (row) => <div className="security-actions">{row.status !== "acknowledged" && <button onClick={() => void setState(row, "acknowledged")}>{tx.acknowledge}</button>}{row.status !== "resolved" && <button onClick={() => void setState(row, "resolved")}>{tx.resolve}</button>}</div> : undefined} /></div>}
  </section>;
}
