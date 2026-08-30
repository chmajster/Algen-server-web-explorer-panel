import { useCallback, useEffect, useMemo, useState } from "react";
import { ClipboardCheck, RefreshCw, ScanSearch } from "lucide-react";
import type { ToastFn } from "../../app/types";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { complianceClient, type Benchmark, type ComplianceControl, type ComplianceSummary } from "./api/client";
import "../security-tools.css";

type Category = "all" | "ssh" | "sudo" | "filesystem" | "kernel" | "pam" | "firewall";

export function ComplianceManagerApp({ permissions, language, toast }: { permissions: readonly string[]; language: string; toast: ToastFn }) {
  const pl = language.toLowerCase().startsWith("pl");
  const tx = {
    title: "Compliance Manager",
    posture: pl ? "Zgodność systemu" : "System compliance",
    subtitle: pl
      ? "Audyt read-only zgodności hosta Linux z wybranymi kontrolami CIS-aligned Level 1 dla SSH, sudo, filesystemu, kernela, PAM i firewalla."
      : "Read-only Linux host assessment against selected CIS-aligned Level 1 controls for SSH, sudo, filesystem, kernel, PAM and firewall.",
    refresh: pl ? "Odśwież" : "Refresh",
    scan: pl ? "Uruchom skan zgodności" : "Run compliance scan",
    queued: pl ? "Skan zgodności został dodany do kolejki" : "Compliance scan queued",
    score: pl ? "Wynik zgodności" : "Compliance score",
    passed: pl ? "Zaliczone" : "Passed",
    failed: pl ? "Niezgodne" : "Failed",
    manual: pl ? "Do weryfikacji" : "Manual review",
    errors: pl ? "Błędy odczytu" : "Read errors",
    lastScan: pl ? "Ostatni skan" : "Last scan",
    noScan: pl ? "Nie wykonano jeszcze skanu" : "No scan has been run yet",
    benchmark: pl ? "Profil benchmarku" : "Benchmark profile",
    areas: pl ? "Obszary polityk" : "Policy areas",
    controls: pl ? "Kontrole zgodności" : "Compliance controls",
    id: "ID",
    control: pl ? "Kontrola" : "Control",
    result: pl ? "Wynik" : "Result",
    expected: pl ? "Oczekiwane" : "Expected",
    actual: pl ? "Wykryte" : "Detected",
    recommendation: pl ? "Remediacja" : "Remediation",
    noControls: pl ? "Brak wyników. Uruchom skan zgodności." : "No results. Run a compliance scan.",
    disclaimer: pl ? "Zakres" : "Scope",
  };
  const categories: Array<{ id: Category; label: string }> = [
    { id: "all", label: pl ? "Wszystkie" : "All" },
    { id: "ssh", label: "SSH" },
    { id: "sudo", label: "sudo" },
    { id: "filesystem", label: pl ? "Filesystem" : "Filesystem" },
    { id: "kernel", label: "Kernel" },
    { id: "pam", label: "PAM" },
    { id: "firewall", label: "Firewall" },
  ];
  const statusNames: Record<string, string> = pl
    ? { pass: "ZGODNE", fail: "NIEZGODNE", manual: "WERYFIKACJA", error: "BŁĄD", not_applicable: "N/D" }
    : { pass: "PASS", fail: "FAIL", manual: "MANUAL", error: "ERROR", not_applicable: "N/A" };
  const [category, setCategory] = useState<Category>("all");
  const [summary, setSummary] = useState<ComplianceSummary | null>(null);
  const [controls, setControls] = useState<ComplianceControl[]>([]);
  const [benchmark, setBenchmark] = useState<Benchmark | null>(null);
  const [loading, setLoading] = useState(false);
  const can = (permission: string) => permissions.includes(permission);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextSummary, nextControls, nextBenchmarks] = await Promise.all([
        complianceClient.summary(),
        complianceClient.controls(),
        complianceClient.benchmarks(),
      ]);
      setSummary(nextSummary);
      setControls(nextControls.items);
      setBenchmark(nextBenchmarks.items[0] || null);
    } catch (error) {
      toast(String(error), "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { void load(); }, [load]);

  async function scan() {
    try {
      await complianceClient.scan();
      toast(tx.queued, "ok");
      await load();
    } catch (error) {
      toast(String(error), "error");
    }
  }

  const visible = useMemo(() => category === "all" ? controls : controls.filter((item) => item.category === category), [category, controls]);
  const columns = useMemo<DataTableColumn<ComplianceControl>[]>(() => [
    { key: "id", header: tx.id, render: (row) => <code>{row.id}</code> },
    { key: "control", header: tx.control, render: (row) => <div><strong>{row.title}</strong><small>{row.benchmark_ref}</small></div> },
    { key: "status", header: tx.result, render: (row) => <strong className={`security-tone-${row.status === "fail" || row.status === "error" ? "danger" : row.status === "manual" ? "warning" : "ok"}`}>{statusNames[row.status] || row.status}</strong> },
    { key: "expected", header: tx.expected, render: (row) => <div><strong>{row.expected}</strong><small>{row.actual}</small></div> },
    { key: "remediation", header: tx.recommendation, render: (row) => <small>{row.remediation}</small> },
  ], [statusNames, tx.control, tx.expected, tx.id, tx.recommendation, tx.result]);

  return <section className="security-tool-app">
    <header className="security-tool-header">
      <div><span className="security-tool-eyebrow">{tx.posture}</span><h2><ClipboardCheck /> {tx.title}</h2><p>{tx.subtitle}</p></div>
      <div className="security-actions">
        <button className="security-action" onClick={() => void load()}><RefreshCw /> {tx.refresh}</button>
        {can("compliance.scan") && <button className="security-action" onClick={() => void scan()}><ScanSearch /> {tx.scan}</button>}
      </div>
    </header>

    <div className="security-stat-grid">
      <article><span>{tx.score}</span><strong className={(summary?.score ?? 100) < 70 ? "security-tone-danger" : (summary?.score ?? 100) < 90 ? "security-tone-warning" : "security-tone-ok"}>{summary?.score ?? "—"}/100</strong><small>{summary?.total ?? 0} {tx.controls.toLowerCase()}</small></article>
      <article><span>{tx.passed} / {tx.failed}</span><strong>{summary ? `${summary.passed} / ${summary.failed}` : "—"}</strong><small>{tx.manual}: {summary?.manual ?? 0}</small></article>
      <article><span>{tx.lastScan}</span><strong>{summary?.last_scan ? new Date(summary.last_scan * 1000).toLocaleString(language) : "—"}</strong><small>{summary?.last_scan ? `${tx.errors}: ${summary.error}` : tx.noScan}</small></article>
    </div>

    {benchmark && <div className="security-panel"><h3>{tx.benchmark}: {benchmark.name}</h3><p>{benchmark.scope}</p><small><strong>{tx.disclaimer}:</strong> {benchmark.disclaimer}</small></div>}

    <div className="security-panel">
      <h3>{tx.areas}</h3>
      <div className="security-stat-grid">{Object.entries(summary?.categories || {}).map(([name, area]) => <article key={name}><span>{name.toUpperCase()}</span><strong>{area.score ?? "—"}/100</strong><small>{area.passed} {tx.passed.toLowerCase()} · {area.failed} {tx.failed.toLowerCase()}</small></article>)}</div>
    </div>

    <nav className="security-tabs" aria-label={tx.areas}>{categories.map((item) => <button key={item.id} className={category === item.id ? "active" : ""} onClick={() => setCategory(item.id)}>{item.label}</button>)}</nav>
    <div className="security-panel"><h3>{tx.controls}</h3><DataTable rows={visible} columns={columns} getRowId={(row) => row.id} loading={loading} emptyTitle={tx.noControls} /></div>
  </section>;
}
