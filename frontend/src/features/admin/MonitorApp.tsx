import { AlertTriangle, CircleAlert, Info, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, type DiskMetric, type ProcessMetric, type ResourceAlert, type ResourceDashboard } from "../../api";
import type { Translate } from "../../app/types";
import { formatSize } from "../files/utils";

const MAX_SAMPLES = 60;
type History = Record<string, number[]>;
type SortDirection = "asc" | "desc";

function pushSample(history: History, key: string, value: number | null | undefined) {
  return { ...history, [key]: [...(history[key] || []), value ?? 0].slice(-MAX_SAMPLES) };
}

function usageLevel(percent: number) {
  return percent >= 95 ? "critical" : percent >= 85 ? "warning" : "normal";
}

function formatPercent(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : `${value.toFixed(1)}%`;
}

function formatRate(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : `${formatSize(value)}/s`;
}

function formatDuration(value: number | null) {
  if (value === null) return "—";
  const days = Math.floor(value / 86400);
  const hours = Math.floor((value % 86400) / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  return `${days}d ${hours}h ${minutes}m`;
}

function Sparkline({ values, label }: { values: number[]; label: string }) {
  const maximum = Math.max(...values, 1);
  const points = values.map((value, index) => `${values.length === 1 ? 0 : index * 100 / (values.length - 1)},${30 - value * 27 / maximum}`).join(" ");
  return <svg className="monitor-sparkline" viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label={label}><polyline points={points} /></svg>;
}

function UsageBar({ percent, label }: { percent: number; label: string }) {
  return <div className={`monitor-usage ${usageLevel(percent)}`} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(percent)}><span style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} /></div>;
}

function Metric({ label, value, percent, history }: { label: string; value: string; percent?: number; history?: number[] }) {
  return <article className={`monitor-metric ${percent === undefined ? "" : usageLevel(percent)}`}><span>{label}</span><strong>{value}</strong>{percent !== undefined && <UsageBar percent={percent} label={label} />}{history && <Sparkline values={history} label={label} />}</article>;
}

function alertMessage(alert: ResourceAlert, t: Translate) {
  const unit = alert.code === "cpu_temperature" ? "°C" : "%";
  return `${t(`monitor.alert.${alert.code}`)} · ${alert.target} · ${alert.value}${typeof alert.value === "number" ? unit : ""}`;
}

function AlertIcon({ severity }: { severity: ResourceAlert["severity"] }) {
  if (severity === "critical") return <CircleAlert aria-hidden="true" />;
  if (severity === "warning") return <AlertTriangle aria-hidden="true" />;
  return <Info aria-hidden="true" />;
}

function SortButton({ active, direction, onClick, children }: { active: boolean; direction: SortDirection; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" className="monitor-sort" onClick={onClick}>{children}{active ? (direction === "asc" ? " ↑" : " ↓") : ""}</button>;
}

function StorageCard({ disk, history, t }: { disk: DiskMetric; history: History; t: Translate }) {
  const id = disk.filesystem_id || disk.path;
  return <article className={`monitor-storage-card ${usageLevel(disk.percent)}`}>
    <header><div><strong>{disk.mountpoint || disk.path}</strong><small>{disk.device || t("monitor.storageUnknown")}{disk.fs_type ? ` · ${disk.fs_type}` : ""}</small></div><b>{disk.percent.toFixed(1)}%</b></header>
    <UsageBar percent={disk.percent} label={disk.path} />
    <div className="monitor-pairs"><span>{t("monitor.used")} <strong>{formatSize(disk.used)}</strong></span><span>{t("monitor.free")} <strong>{formatSize(disk.free)}</strong></span><span>{t("monitor.read")} <strong>{formatRate(disk.read_bytes_per_sec)}</strong></span><span>{t("monitor.write")} <strong>{formatRate(disk.write_bytes_per_sec)}</strong></span><span>{t("monitor.totalRead")} <strong>{disk.read_bytes === undefined ? "—" : formatSize(disk.read_bytes)}</strong></span><span>{t("monitor.totalWrite")} <strong>{disk.write_bytes === undefined ? "—" : formatSize(disk.write_bytes)}</strong></span></div>
    <Sparkline values={history[`disk:${id}`] || []} label={t("monitor.diskHistory")} />
    <div className="monitor-aliases"><span>{t("monitor.availablePaths")}</span>{(disk.paths || [disk.path]).map((path) => <code key={path}>{path}</code>)}</div>
  </article>;
}

export function MonitorApp({ t }: { t: Translate }) {
  const [data, setData] = useState<ResourceDashboard | null>(null);
  const [history, setHistory] = useState<History>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [automatic, setAutomatic] = useState(true);
  const [visible, setVisible] = useState(() => document.visibilityState === "visible");
  const [intervalMs, setIntervalMs] = useState(2000);
  const [mountSort, setMountSort] = useState<{ key: "mountpoint" | "device" | "percent"; direction: SortDirection }>({ key: "mountpoint", direction: "asc" });
  const [processSort, setProcessSort] = useState<{ key: "cpu_percent" | "memory_percent" | "rss"; direction: SortDirection }>({ key: "cpu_percent", direction: "desc" });
  const inFlight = useRef(false);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    if (mounted.current) { setLoading(true); setError(""); }
    try {
      const next = await api.resources();
      if (!mounted.current) return;
      setData(next);
      setLastUpdate(new Date(next.timestamp * 1000));
      setHistory((current) => {
        let updated = pushSample(current, "cpu", next.cpu_percent);
        updated = pushSample(updated, "ram", next.ram.percent);
        for (const network of next.network_interfaces) {
          updated = pushSample(updated, `net:${network.name}:rx`, network.rx_bytes_per_sec);
          updated = pushSample(updated, `net:${network.name}:tx`, network.tx_bytes_per_sec);
        }
        for (const disk of next.allowed_roots) updated = pushSample(updated, `disk:${disk.filesystem_id || disk.path}`, (disk.read_bytes_per_sec || 0) + (disk.write_bytes_per_sec || 0));
        return updated;
      });
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : t("error.generic"));
    } finally {
      inFlight.current = false;
      if (mounted.current) setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => { mounted.current = false; };
  }, [refresh]);

  useEffect(() => {
    if (!automatic) return;
    const tick = () => { if (document.visibilityState === "visible") void refresh(); };
    const timer = window.setInterval(tick, intervalMs);
    const onVisibility = () => { const isVisible = document.visibilityState === "visible"; setVisible(isVisible); if (isVisible) void refresh(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisibility); };
  }, [automatic, intervalMs, refresh]);

  function updateMountSort(key: "mountpoint" | "device" | "percent") {
    setMountSort((current) => ({ key, direction: current.key === key && current.direction === "asc" ? "desc" : "asc" }));
  }
  function updateProcessSort(key: "cpu_percent" | "memory_percent" | "rss") {
    setProcessSort((current) => ({ key, direction: current.key === key && current.direction === "asc" ? "desc" : "asc" }));
  }

  const mountpoints = [...(data?.mountpoints || [])].sort((left, right) => {
    const result = mountSort.key === "percent" ? left.percent - right.percent : String(left[mountSort.key] || "").localeCompare(String(right[mountSort.key] || ""));
    return mountSort.direction === "asc" ? result : -result;
  });
  const processes = [...(data?.processes || [])].sort((left: ProcessMetric, right: ProcessMetric) => (processSort.direction === "asc" ? 1 : -1) * (left[processSort.key] - right[processSort.key]));

  return <section className="system-app monitor-app">
    <header className="feature-header"><div><h2>{t("app.monitor")}</h2><p>{t("monitor.subtitle")}</p></div><div className="monitor-controls">
      <label><input type="checkbox" checked={automatic} onChange={(event) => setAutomatic(event.target.checked)} />{t("monitor.autoRefresh")}</label>
      <label>{t("monitor.interval")}<select aria-label={t("monitor.interval")} value={intervalMs} onChange={(event) => setIntervalMs(Number(event.target.value))}><option value={1000}>1 s</option><option value={2000}>2 s</option><option value={5000}>5 s</option><option value={10000}>10 s</option></select></label>
      <button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} />{t("action.refresh")}</button>
    </div></header>
    <div className="monitor-status" aria-live="polite"><span>{loading ? t("status.loading") : t("monitor.ready")}</span><span>{t("monitor.lastUpdate")}: {lastUpdate ? lastUpdate.toLocaleTimeString() : "—"}</span>{!visible && <span>{t("monitor.hiddenPaused")}</span>}</div>
    {error && <p className="error-state compact-error" role="alert">{t("monitor.refreshError")}: {error}</p>}
    {!data && loading && <div className="loading-state">{t("status.loading")}</div>}
    {data && <div className="monitor-content">
      {data.alerts.length > 0 && <section className="monitor-section monitor-alerts" aria-labelledby="monitor-alerts"><h3 id="monitor-alerts">{t("monitor.alerts")}</h3>{data.alerts.map((alert, index) => <p className={alert.severity} key={`${alert.code}-${alert.target}-${index}`} role="alert"><AlertIcon severity={alert.severity} /><strong>{t(`monitor.severity.${alert.severity}`)}</strong><span>{alertMessage(alert, t)}</span></p>)}</section>}
      <section className="monitor-section" aria-labelledby="monitor-overview"><h3 id="monitor-overview">{t("monitor.overview")}</h3><div className="monitor-overview-grid">
        <Metric label={t("monitor.cpu")} value={formatPercent(data.cpu_percent)} percent={data.cpu_percent ?? 0} history={history.cpu || []} />
        <Metric label={t("monitor.memory")} value={`${formatSize(data.ram.used)} / ${formatSize(data.ram.total)} · ${t("monitor.free")}: ${formatSize(data.ram.free)}`} percent={data.ram.percent} history={history.ram || []} />
        <Metric label={t("monitor.swap")} value={data.swap.total ? `${formatSize(data.swap.used)} / ${formatSize(data.swap.total)}` : t("monitor.disabled")} percent={data.swap.total ? data.swap.percent : undefined} />
        <Metric label={t("monitor.loadAverage")} value={data.load_average?.join(" · ") || "—"} />
        <Metric label={t("monitor.temperature")} value={data.temperature_c === null ? "—" : `${data.temperature_c} °C`} />
        <Metric label={t("monitor.uptime")} value={formatDuration(data.uptime_seconds)} />
      </div><dl className="monitor-system-details"><div><dt>{t("monitor.host")}</dt><dd>{data.hostname}</dd></div><div><dt>{t("monitor.system")}</dt><dd>{data.os_name}</dd></div><div><dt>{t("monitor.kernel")}</dt><dd>{data.kernel_version}</dd></div><div><dt>{t("monitor.cpuFrequency")}</dt><dd>{data.cpu_frequency_mhz === null ? "—" : `${data.cpu_frequency_mhz} MHz`}</dd></div><div><dt>{t("monitor.service")}</dt><dd>{data.webnas_service ? t(`monitor.service.${data.webnas_service}`) : t("monitor.restricted")}</dd></div><div><dt>{t("monitor.bootTime")}</dt><dd>{data.boot_time ? new Date(data.boot_time * 1000).toLocaleString() : "—"}</dd></div></dl></section>
      <section className="monitor-section" aria-labelledby="monitor-cores"><h3 id="monitor-cores">{t("monitor.cores")} ({data.cpu_logical_cores})</h3><div className="monitor-core-grid">{data.cpu_cores.map((percent, index) => <div key={index}><span>{t("monitor.core")} {index + 1}</span><strong>{formatPercent(percent)}</strong><UsageBar percent={percent ?? 0} label={`${t("monitor.core")} ${index + 1}`} /></div>)}</div></section>
      <section className="monitor-section" aria-labelledby="monitor-storage"><h3 id="monitor-storage">{t("monitor.storage")}</h3><div className="monitor-storage-grid">{data.allowed_roots.map((disk) => <StorageCard key={disk.filesystem_id || disk.path} disk={disk} history={history} t={t} />)}</div></section>
      {data.scope === "admin" && <section className="monitor-section" aria-labelledby="monitor-mounts"><h3 id="monitor-mounts">{t("monitor.allMounts")}</h3><div className="monitor-table-wrap"><table><thead><tr><th><SortButton active={mountSort.key === "mountpoint"} direction={mountSort.direction} onClick={() => updateMountSort("mountpoint")}>{t("monitor.mountpoint")}</SortButton></th><th><SortButton active={mountSort.key === "device"} direction={mountSort.direction} onClick={() => updateMountSort("device")}>{t("monitor.device")}</SortButton></th><th>{t("monitor.filesystem")}</th><th>{t("monitor.total")}</th><th>{t("monitor.used")}</th><th>{t("monitor.free")}</th><th><SortButton active={mountSort.key === "percent"} direction={mountSort.direction} onClick={() => updateMountSort("percent")}>{t("monitor.usage")}</SortButton></th></tr></thead><tbody>{mountpoints.map((mount, index) => <tr key={`${mount.mountpoint}-${index}`}><td><code>{mount.mountpoint}</code></td><td>{mount.device || "—"}</td><td>{mount.fs_type || "—"}</td><td>{formatSize(mount.total)}</td><td>{formatSize(mount.used)}</td><td>{formatSize(mount.free)}</td><td>{mount.percent.toFixed(1)}%</td></tr>)}</tbody></table></div></section>}
      <section className="monitor-section" aria-labelledby="monitor-network"><h3 id="monitor-network">{t("monitor.network")}</h3><div className="monitor-network-grid">{data.network_interfaces.map((network) => <article key={network.name}><header><div><strong>{network.name}</strong>{network.system && <small>{t("monitor.systemInterface")}</small>}</div><span className={`monitor-state ${network.state}`}>{t(`monitor.state.${network.state}`)}</span></header><div className="monitor-pairs"><span>{t("monitor.received")} <strong>{formatSize(network.rx_bytes)}</strong></span><span>{t("monitor.sent")} <strong>{formatSize(network.tx_bytes)}</strong></span><span>{t("monitor.download")} <strong>{formatRate(network.rx_bytes_per_sec)}</strong></span><span>{t("monitor.upload")} <strong>{formatRate(network.tx_bytes_per_sec)}</strong></span></div><div className="monitor-network-history"><Sparkline values={history[`net:${network.name}:rx`] || []} label={`${network.name} ${t("monitor.downloadHistory")}`} /><Sparkline values={history[`net:${network.name}:tx`] || []} label={`${network.name} ${t("monitor.uploadHistory")}`} /></div></article>)}</div></section>
      {data.scope === "admin" && <section className="monitor-section" aria-labelledby="monitor-processes"><h3 id="monitor-processes">{t("monitor.processes")}</h3><div className="monitor-table-wrap"><table><thead><tr><th>PID</th><th>{t("monitor.user")}</th><th>{t("monitor.process")}</th><th><SortButton active={processSort.key === "cpu_percent"} direction={processSort.direction} onClick={() => updateProcessSort("cpu_percent")}>CPU</SortButton></th><th><SortButton active={processSort.key === "memory_percent"} direction={processSort.direction} onClick={() => updateProcessSort("memory_percent")}>{t("monitor.memoryShort")}</SortButton></th><th><SortButton active={processSort.key === "rss"} direction={processSort.direction} onClick={() => updateProcessSort("rss")}>RSS</SortButton></th><th>{t("monitor.state")}</th></tr></thead><tbody>{processes.length ? processes.map((process) => <tr key={process.pid}><td>{process.pid}</td><td>{process.user}</td><td>{process.name}</td><td>{process.cpu_percent.toFixed(1)}%</td><td>{process.memory_percent.toFixed(1)}%</td><td>{formatSize(process.rss)}</td><td>{process.state}</td></tr>) : <tr><td colSpan={7} className="monitor-empty-cell">{t("monitor.noProcesses")}</td></tr>}</tbody></table></div></section>}
    </div>}
  </section>;
}
