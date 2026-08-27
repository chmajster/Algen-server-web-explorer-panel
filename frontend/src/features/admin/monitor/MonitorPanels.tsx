import { AlertTriangle, CircleAlert, Info } from "lucide-react";
import { useMemo, useState } from "react";

import type { DiskIoMetric, DiskMetric, NetworkMetric, ProcessMetric, ResourceAlert, ResourceDashboard } from "../../../api";
import type { Translate } from "../../../app/types";
import { formatSize } from "../../files/utils";
import { ResourceChart, UsageBar } from "./ResourceChart";
import type { History, ProcessSortKey, SortDirection } from "./monitorUtils";
import { formatPercent, selectStorageSummary, summarizeNetwork, usageLevel } from "./monitorUtils";

function formatRate(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${formatSize(value)}/s`;
}

function alertMessage(alert: ResourceAlert, t: Translate): string {
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

function MetricCard({ label, value, percent, details, chart }: { label: string; value: string; percent?: number; details: React.ReactNode; chart: React.ReactNode }) {
  return <article className={`monitor-metric ${percent === undefined ? "" : usageLevel(percent)}`}>
    <header><span>{label}</span><strong>{value}</strong></header>
    {percent !== undefined && <UsageBar percent={percent} label={label} compact />}
    <div className="monitor-metric-chart">{chart}</div>
    <div className="monitor-metric-details">{details}</div>
  </article>;
}

export function AlertsPanel({ alerts, warnings, t }: { alerts: ResourceAlert[]; warnings: string[]; t: Translate }) {
  if (alerts.length === 0 && warnings.length === 0) {
    return <div className="monitor-health monitor-health-ok" aria-live="polite"><span className="monitor-state up">{t("monitor.ready")}</span></div>;
  }

  return <section className="monitor-alerts" aria-labelledby="monitor-alerts-title">
    <header><strong id="monitor-alerts-title">{t("monitor.alerts")}</strong><span>{alerts.length}</span></header>
    <div className="monitor-alert-list">
      {alerts.map((alert, index) => <p className={alert.severity} key={`${alert.code}-${alert.target}-${index}`} role="alert"><AlertIcon severity={alert.severity} /><strong>{t(`monitor.severity.${alert.severity}`)}</strong><span>{alertMessage(alert, t)}</span></p>)}
      {warnings.map((warning, index) => <p className="warning" key={`${warning}-${index}`}><AlertTriangle aria-hidden="true" /><strong>{t("monitor.severity.warning")}</strong><span>{warning}</span></p>)}
    </div>
  </section>;
}

export function OverviewCards({ data, storage, history, t }: { data: ResourceDashboard; storage: DiskMetric[]; history: History; t: Translate }) {
  const primaryStorage = selectStorageSummary(storage);
  const network = summarizeNetwork(data.network_interfaces);
  const networkRx = history["network:aggregate:rx"] || [];
  const networkTx = history["network:aggregate:tx"] || [];
  const diskId = primaryStorage ? primaryStorage.filesystem_id || primaryStorage.device || primaryStorage.mountpoint || primaryStorage.path : "";

  return <section className="monitor-overview-grid" aria-label={t("monitor.overview")}>
    <MetricCard
      label={t("monitor.cpu")}
      value={formatPercent(data.cpu_percent)}
      percent={data.cpu_percent ?? 0}
      chart={<ResourceChart compact maximum={100} label={t("monitor.cpu")} series={[{ label: t("monitor.cpu"), values: history.cpu || [] }]} />}
      details={<><span>{t("monitor.cores")} <strong>{data.cpu_logical_cores}</strong></span><span>{t("monitor.cpuFrequency")} <strong>{data.cpu_frequency_mhz === null ? "—" : `${Math.round(data.cpu_frequency_mhz)} MHz`}</strong></span><span>{t("monitor.loadAverage")} <strong>{data.load_average?.map((value) => value.toFixed(2)).join(" / ") || "—"}</strong></span></>}
    />
    <MetricCard
      label={t("monitor.memory")}
      value={formatPercent(data.ram.percent)}
      percent={data.ram.percent}
      chart={<ResourceChart compact maximum={100} label={t("monitor.memory")} series={[{ label: t("monitor.memoryShort"), values: history.ram || [] }]} />}
      details={<><span>{t("monitor.used")} <strong>{formatSize(data.ram.used)} / {formatSize(data.ram.total)}</strong></span><span>{t("monitor.free")} <strong>{formatSize(data.ram.free)}</strong></span><span>{t("monitor.swap")} <strong>{data.swap.total > 0 ? formatPercent(data.swap.percent) : t("monitor.disabled")}</strong></span></>}
    />
    <MetricCard
      label={t("monitor.storage")}
      value={primaryStorage ? formatPercent(primaryStorage.percent) : "—"}
      percent={primaryStorage?.percent}
      chart={<ResourceChart compact label={t("monitor.diskHistory")} series={primaryStorage ? [{ label: t("monitor.read"), values: history[`disk:${diskId}:read`] || [] }, { label: t("monitor.write"), values: history[`disk:${diskId}:write`] || [] }] : []} />}
      details={primaryStorage ? <><span>{t("monitor.used")} <strong>{formatSize(primaryStorage.used)} / {formatSize(primaryStorage.total)}</strong></span><span>{t("monitor.read")} <strong>{formatRate(primaryStorage.read_bytes_per_sec)}</strong></span><span>{t("monitor.write")} <strong>{formatRate(primaryStorage.write_bytes_per_sec)}</strong></span></> : <span>—</span>}
    />
    <MetricCard
      label={t("monitor.network")}
      value={formatRate(network.rxBytesPerSec)}
      chart={<ResourceChart compact label={t("monitor.networkHistory")} series={[{ label: t("monitor.download"), values: networkRx }, { label: t("monitor.upload"), values: networkTx }]} />}
      details={<><span>{t("monitor.download")} <strong>{formatRate(network.rxBytesPerSec)}</strong></span><span>{t("monitor.upload")} <strong>{formatRate(network.txBytesPerSec)}</strong></span><span>{t("monitor.received")} / {t("monitor.sent")} <strong>{formatSize(network.rxBytes)} / {formatSize(network.txBytes)}</strong></span></>}
    />
  </section>;
}

export function CpuPanel({ data, history, t }: { data: ResourceDashboard; history: History; t: Translate }) {
  return <section className="monitor-panel monitor-cpu-panel" aria-labelledby="monitor-cpu-title">
    <header className="monitor-panel-title"><div><h3 id="monitor-cpu-title">{t("monitor.cpu")}</h3><strong>{formatPercent(data.cpu_percent)}</strong></div><span>{data.cpu_logical_cores} {t("monitor.cores")}</span></header>
    <ResourceChart maximum={100} label={t("monitor.cpu")} series={[{ label: t("monitor.cpu"), values: history.cpu || [] }]} />
    <dl className="monitor-stat-grid"><div><dt>{t("monitor.loadAverage")}</dt><dd>{data.load_average?.map((value) => value.toFixed(2)).join(" / ") || "—"}</dd></div><div><dt>{t("monitor.cpuFrequency")}</dt><dd>{data.cpu_frequency_mhz === null ? "—" : `${Math.round(data.cpu_frequency_mhz)} MHz`}</dd></div><div><dt>{t("monitor.temperature")}</dt><dd>{data.temperature_c === null ? "—" : `${data.temperature_c.toFixed(1)} °C`}</dd></div></dl>
    <div className="monitor-core-grid">{data.cpu_cores.map((percent, index) => <div className="monitor-core-row" key={index}><span>{t("monitor.core")} {index}</span><strong>{formatPercent(percent)}</strong><UsageBar compact percent={percent ?? 0} label={`${t("monitor.core")} ${index}`} /></div>)}</div>
  </section>;
}

export function MemoryPanel({ data, history, t }: { data: ResourceDashboard; history: History; t: Translate }) {
  const chartSeries = [{ label: t("monitor.memoryShort"), values: history.ram || [] }];
  if (data.swap.total > 0) chartSeries.push({ label: t("monitor.swap"), values: history.swap || [] });

  return <section className="monitor-panel monitor-memory-panel" aria-labelledby="monitor-memory-title">
    <header className="monitor-panel-title"><div><h3 id="monitor-memory-title">{t("monitor.memory")}</h3><strong>{formatPercent(data.ram.percent)}</strong></div><span>{formatSize(data.ram.used)} / {formatSize(data.ram.total)}</span></header>
    <ResourceChart maximum={100} label={t("monitor.memory")} series={chartSeries} />
    <dl className="monitor-stat-grid"><div><dt>{t("monitor.total")}</dt><dd>{formatSize(data.ram.total)}</dd></div><div><dt>{t("monitor.used")}</dt><dd>{formatSize(data.ram.used)}</dd></div><div><dt>{t("monitor.free")}</dt><dd>{formatSize(data.ram.free)}</dd></div><div><dt>{t("monitor.swap")}</dt><dd>{data.swap.total > 0 ? `${formatSize(data.swap.used)} / ${formatSize(data.swap.total)} · ${formatPercent(data.swap.percent)}` : t("monitor.disabled")}</dd></div></dl>
  </section>;
}

function StorageCard({ disk, history, t }: { disk: DiskMetric; history: History; t: Translate }) {
  const id = disk.filesystem_id || disk.device || disk.mountpoint || disk.path;
  return <article className={`monitor-storage-card ${usageLevel(disk.percent)}`}>
    <header><div><strong>{disk.mountpoint || disk.path}</strong><small>{disk.device || t("monitor.storageUnknown")}{disk.fs_type ? ` · ${disk.fs_type}` : ""}</small></div><b>{disk.percent.toFixed(1)}%</b></header>
    <UsageBar percent={disk.percent} label={disk.mountpoint || disk.path} />
    <div className="monitor-pairs"><span>{t("monitor.used")} <strong>{formatSize(disk.used)} / {formatSize(disk.total)}</strong></span><span>{t("monitor.free")} <strong>{formatSize(disk.free)}</strong></span><span>{t("monitor.read")} <strong>{formatRate(disk.read_bytes_per_sec)}</strong></span><span>{t("monitor.write")} <strong>{formatRate(disk.write_bytes_per_sec)}</strong></span><span>{t("monitor.totalRead")} <strong>{disk.read_bytes === undefined ? "—" : formatSize(disk.read_bytes)}</strong></span><span>{t("monitor.totalWrite")} <strong>{disk.write_bytes === undefined ? "—" : formatSize(disk.write_bytes)}</strong></span></div>
    <ResourceChart label={t("monitor.diskHistory")} series={[{ label: t("monitor.read"), values: history[`disk:${id}:read`] || [] }, { label: t("monitor.write"), values: history[`disk:${id}:write`] || [] }]} />
    <div className="monitor-aliases"><span>{t("monitor.availablePaths")}</span>{(disk.paths || [disk.path]).map((path) => <code key={path}>{path}</code>)}</div>
  </article>;
}

export function StoragePanel({ storage, diskIo, history, t }: { storage: DiskMetric[]; diskIo: DiskIoMetric[]; history: History; t: Translate }) {
  return <section className="monitor-panel" aria-labelledby="monitor-storage-title"><header className="monitor-panel-title"><h3 id="monitor-storage-title">{t("monitor.storage")}</h3><span>{storage.length}</span></header>
    <div className="monitor-storage-grid">{storage.map((disk) => <StorageCard key={disk.filesystem_id || disk.device || disk.mountpoint || disk.path} disk={disk} history={history} t={t} />)}</div>
    {diskIo.length > 0 && <DiskIoTable items={diskIo} t={t} />}
  </section>;
}

function DiskIoTable({ items, t }: { items: DiskIoMetric[]; t: Translate }) {
  return <div className="monitor-table-wrap monitor-disk-io"><table><thead><tr><th>{t("monitor.device")}</th><th>{t("monitor.read")}</th><th>{t("monitor.write")}</th><th>{t("monitor.totalRead")}</th><th>{t("monitor.totalWrite")}</th></tr></thead><tbody>{items.map((item) => <tr key={item.device}><td><code>{item.device}</code></td><td>{formatRate(item.read_bytes_per_sec)}</td><td>{formatRate(item.write_bytes_per_sec)}</td><td>{formatSize(item.read_bytes)}</td><td>{formatSize(item.write_bytes)}</td></tr>)}</tbody></table></div>;
}

function NetworkCard({ network, history, t }: { network: NetworkMetric; history: History; t: Translate }) {
  return <article className="monitor-network-card"><header><div><strong>{network.name}</strong>{network.system && <small>{t("monitor.systemInterface")}</small>}</div><span className={`monitor-state ${network.state}`}>{t(`monitor.state.${network.state}`)}</span></header>
    <div className="monitor-network-stats"><div><span>{t("monitor.download")}</span><strong>{formatRate(network.rx_bytes_per_sec)}</strong></div><div><span>{t("monitor.upload")}</span><strong>{formatRate(network.tx_bytes_per_sec)}</strong></div><div><span>{t("monitor.received")}</span><strong>{formatSize(network.rx_bytes)}</strong></div><div><span>{t("monitor.sent")}</span><strong>{formatSize(network.tx_bytes)}</strong></div></div>
    <ResourceChart label={t("monitor.networkHistory")} series={[{ label: t("monitor.download"), values: history[`net:${network.name}:rx`] || [] }, { label: t("monitor.upload"), values: history[`net:${network.name}:tx`] || [] }]} />
  </article>;
}

export function NetworkPanel({ networks, history, t }: { networks: NetworkMetric[]; history: History; t: Translate }) {
  return <section className="monitor-panel" aria-labelledby="monitor-network-title"><header className="monitor-panel-title"><h3 id="monitor-network-title">{t("monitor.network")}</h3><span>{networks.length}</span></header><div className="monitor-network-grid">{networks.map((network) => <NetworkCard key={network.name} network={network} history={history} t={t} />)}</div>{networks.length === 0 && <div className="monitor-empty">—</div>}</section>;
}

export function AllMountsPanel({ mountpoints, t }: { mountpoints: DiskMetric[]; t: Translate }) {
  const [sort, setSort] = useState<{ key: "mountpoint" | "device" | "percent"; direction: SortDirection }>({ key: "mountpoint", direction: "asc" });
  const sorted = useMemo(() => [...mountpoints].sort((left, right) => {
    const result = sort.key === "percent" ? left.percent - right.percent : String(left[sort.key] || "").localeCompare(String(right[sort.key] || ""));
    return sort.direction === "asc" ? result : -result;
  }), [mountpoints, sort]);
  const updateSort = (key: typeof sort.key) => setSort((current) => ({ key, direction: current.key === key && current.direction === "asc" ? "desc" : "asc" }));

  return <section className="monitor-panel" aria-labelledby="monitor-mounts-title"><header className="monitor-panel-title"><h3 id="monitor-mounts-title">{t("monitor.allMounts")}</h3><span>{mountpoints.length}</span></header><div className="monitor-table-wrap"><table><thead><tr><th><SortButton active={sort.key === "mountpoint"} direction={sort.direction} onClick={() => updateSort("mountpoint")}>{t("monitor.mountpoint")}</SortButton></th><th><SortButton active={sort.key === "device"} direction={sort.direction} onClick={() => updateSort("device")}>{t("monitor.device")}</SortButton></th><th>{t("monitor.filesystem")}</th><th>{t("monitor.total")}</th><th>{t("monitor.used")}</th><th>{t("monitor.free")}</th><th><SortButton active={sort.key === "percent"} direction={sort.direction} onClick={() => updateSort("percent")}>{t("monitor.usage")}</SortButton></th></tr></thead><tbody>{sorted.map((mount, index) => <tr key={`${mount.mountpoint}-${index}`}><td><code>{mount.mountpoint || mount.path}</code></td><td>{mount.device || "—"}</td><td>{mount.fs_type || "—"}</td><td>{formatSize(mount.total)}</td><td>{formatSize(mount.used)}</td><td>{formatSize(mount.free)}</td><td><span className={`monitor-table-usage ${usageLevel(mount.percent)}`}>{mount.percent.toFixed(1)}%</span></td></tr>)}</tbody></table></div></section>;
}

function compareProcess(left: ProcessMetric, right: ProcessMetric, key: ProcessSortKey): number {
  if (key === "name") return left.name.localeCompare(right.name);
  return left[key] - right[key];
}

export function ProcessesPanel({ processes, t }: { processes: ProcessMetric[]; t: Translate }) {
  const [filter, setFilter] = useState("");
  const [limit, setLimit] = useState<"10" | "25" | "50" | "all">("10");
  const [sort, setSort] = useState<{ key: ProcessSortKey; direction: SortDirection }>({ key: "cpu_percent", direction: "desc" });

  const visible = useMemo(() => {
    const needle = filter.trim().toLocaleLowerCase();
    const filtered = needle ? processes.filter((process) => `${process.pid} ${process.user} ${process.name} ${process.state}`.toLocaleLowerCase().includes(needle)) : processes;
    const sorted = [...filtered].sort((left, right) => {
      const result = compareProcess(left, right, sort.key);
      return sort.direction === "asc" ? result : -result;
    });
    return limit === "all" ? sorted : sorted.slice(0, Number(limit));
  }, [filter, limit, processes, sort]);

  const updateSort = (key: ProcessSortKey) => setSort((current) => ({ key, direction: current.key === key && current.direction === "asc" ? "desc" : "asc" }));

  return <section className="monitor-panel monitor-process-panel" aria-labelledby="monitor-process-title"><header className="monitor-panel-title monitor-process-header"><div><h3 id="monitor-process-title">{t("monitor.processes")}</h3><span>{processes.length}</span></div><div className="monitor-process-tools"><input aria-label={t("monitor.processes")} value={filter} onChange={(event) => setFilter(event.target.value)} placeholder={`${t("monitor.processes")}…`} /><select aria-label={t("monitor.processes")} value={limit} onChange={(event) => setLimit(event.target.value as typeof limit)}><option value="10">{t("monitor.processes")} 10</option><option value="25">{t("monitor.processes")} 25</option><option value="50">{t("monitor.processes")} 50</option><option value="all">{t("filter.all")}</option></select></div></header>
    <div className="monitor-table-wrap"><table className="monitor-process-table"><thead><tr><th><SortButton active={sort.key === "pid"} direction={sort.direction} onClick={() => updateSort("pid")}>PID</SortButton></th><th>{t("monitor.user")}</th><th><SortButton active={sort.key === "name"} direction={sort.direction} onClick={() => updateSort("name")}>{t("monitor.process")}</SortButton></th><th>{t("monitor.state")}</th><th><SortButton active={sort.key === "cpu_percent"} direction={sort.direction} onClick={() => updateSort("cpu_percent")}>{t("monitor.cpu")}</SortButton></th><th><SortButton active={sort.key === "memory_percent"} direction={sort.direction} onClick={() => updateSort("memory_percent")}>{t("monitor.memoryShort")}</SortButton></th><th><SortButton active={sort.key === "rss"} direction={sort.direction} onClick={() => updateSort("rss")}>RSS</SortButton></th></tr></thead><tbody>{visible.map((process) => <tr key={process.pid}><td>{process.pid}</td><td>{process.user}</td><td><strong>{process.name}</strong></td><td>{process.state}</td><td><div className="monitor-process-usage"><span>{formatPercent(process.cpu_percent)}</span><UsageBar compact percent={process.cpu_percent} label={`${process.name} ${t("monitor.cpu")}`} /></div></td><td><div className="monitor-process-usage"><span>{formatPercent(process.memory_percent)}</span><UsageBar compact percent={process.memory_percent} label={`${process.name} ${t("monitor.memoryShort")}`} /></div></td><td>{formatSize(process.rss)}</td></tr>)}</tbody></table></div>{visible.length === 0 && <div className="monitor-empty">{t("monitor.noProcesses")}</div>}</section>;
}
