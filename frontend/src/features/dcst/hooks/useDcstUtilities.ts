import { useMemo, useState } from "react";
import { dcstClient } from "../api/client";
import { emptyFirewallLogFilters, filterFirewallLogs, normalizeFirewallLog, type FirewallLogFilters } from "../domain/firewallLog";

export function useDcstUtilities(onError: (error: unknown) => void, onSuccess: (message: string) => void) {
  const [loading, setLoading] = useState(false);
  const [logs, setLogs] = useState<Array<Record<string, unknown>>>([]);
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown>>({});
  const [filters, setFilters] = useState<FirewallLogFilters>(emptyFirewallLogFilters);
  const [snapshotTime, setSnapshotTime] = useState(0);
  const normalized = useMemo(() => logs.map(normalizeFirewallLog), [logs]);
  const filtered = useMemo(() => filterFirewallLogs(normalized, filters, snapshotTime), [normalized, filters, snapshotTime]);
  const nodes = useMemo(() => [...new Set(normalized.map((row) => String(row.node || "")).filter(Boolean))].sort(), [normalized]);

  function setFilter<K extends keyof FirewallLogFilters>(key: K, value: FirewallLogFilters[K]) {
    setFilters((current) => ({ ...current, [key]: value }));
    if (key === "range") setSnapshotTime(Date.now());
  }

  async function load() {
    setLoading(true);
    try {
      const [nextLogs, nextDiagnostics] = await Promise.all([dcstClient.firewallLogs(), dcstClient.diagnostics()]);
      setLogs(nextLogs); setSnapshotTime(Date.now()); setDiagnostics(nextDiagnostics);
    } catch (error) { onError(error); } finally { setLoading(false); }
  }

  async function testConnection() {
    try { setDiagnostics(await dcstClient.test()); onSuccess("Connection test completed"); } catch (error) { onError(error); }
  }
  async function dryRun() { try { setDiagnostics(await dcstClient.firewallSync(true)); } catch (error) { onError(error); } }
  async function detectDrift() { try { setDiagnostics(await dcstClient.drift()); } catch (error) { onError(error); } }

  return { loading, diagnostics, filters, setFilter, filtered, nodes, load, testConnection, dryRun, detectDrift };
}
