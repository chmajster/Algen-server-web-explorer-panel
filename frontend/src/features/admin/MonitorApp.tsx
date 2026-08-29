import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, type ProcessMetric, type ResourceDashboard } from "../../api";
import type { Translate } from "../../app/types";
import { pageIsVisible, subscribePageVisibility } from "../../core/runtime/pageVisibility";
import { Tabs } from "../../components/ui/layout";
import "../../styles/resource-monitor.css";
import { useRefreshOnConnectionRestored } from "../connection/ConnectionStatusMonitor";
import { AlertsPanel, AllMountsPanel, CpuPanel, MemoryPanel, NetworkPanel, OverviewCards, ProcessesPanel, StoragePanel } from "./monitor/MonitorPanels";
import type { History } from "./monitor/monitorUtils";
import { dedupeStorage, formatDuration, pushSample, summarizeNetwork } from "./monitor/monitorUtils";

type MonitorTab = "overview" | "cpu" | "memory" | "network" | "storage" | "processes" | "mounts";

function serviceState(service: string | null): "up" | "down" | "unknown" {
  if (service === "active") return "up";
  if (service === "failed" || service === "inactive") return "down";
  return "unknown";
}

export function MonitorApp({ t }: { t: Translate }) {
  const [data, setData] = useState<ResourceDashboard | null>(null);
  const [processes, setProcesses] = useState<ProcessMetric[] | null>(null);
  const [history, setHistory] = useState<History>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const [automatic, setAutomatic] = useState(true);
  const [visible, setVisible] = useState(pageIsVisible);
  const [intervalMs, setIntervalMs] = useState(2000);
  const [activeTab, setActiveTab] = useState<MonitorTab>("overview");
  const inFlight = useRef(false);
  const processInFlight = useRef(false);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    if (mounted.current) {
      setLoading(true);
      setError("");
    }

    try {
      const dashboard = await api.resources();
      if (!mounted.current) return;

      setData(dashboard);
      if (dashboard.scope !== "admin") setProcesses(null);
      setLastUpdate(new Date(dashboard.timestamp * 1000));
      setHistory((current) => {
        let updated = pushSample(current, "cpu", dashboard.cpu_percent);
        updated = pushSample(updated, "ram", dashboard.ram.percent);
        updated = pushSample(updated, "swap", dashboard.swap.total > 0 ? dashboard.swap.percent : 0);

        const networkSummary = summarizeNetwork(dashboard.network_interfaces);
        updated = pushSample(updated, "network:aggregate:rx", networkSummary.rxBytesPerSec);
        updated = pushSample(updated, "network:aggregate:tx", networkSummary.txBytesPerSec);

        for (const network of dashboard.network_interfaces) {
          updated = pushSample(updated, `net:${network.name}:rx`, network.rx_bytes_per_sec);
          updated = pushSample(updated, `net:${network.name}:tx`, network.tx_bytes_per_sec);
        }

        for (const disk of dedupeStorage(dashboard.allowed_roots)) {
          const id = disk.filesystem_id || disk.device || disk.mountpoint || disk.path;
          updated = pushSample(updated, `disk:${id}:read`, disk.read_bytes_per_sec);
          updated = pushSample(updated, `disk:${id}:write`, disk.write_bytes_per_sec);
        }
        return updated;
      });
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : t("error.generic"));
    } finally {
      inFlight.current = false;
      if (mounted.current) setLoading(false);
    }
  }, [t]);

  const refreshProcesses = useCallback(async () => {
    if (processInFlight.current) return;
    processInFlight.current = true;
    try {
      const next = await api.resourceProcesses();
      if (mounted.current) setProcesses(next);
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : t("error.generic"));
    } finally {
      processInFlight.current = false;
    }
  }, [t]);

  useRefreshOnConnectionRestored(() => { void refresh(); });

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => { mounted.current = false; };
  }, [refresh]);

  useEffect(() => subscribePageVisibility((isVisible) => {
    setVisible(isVisible);
    if (isVisible && automatic) void refresh();
  }), [automatic, refresh]);

  useEffect(() => {
    if (!automatic || !visible) return;
    const timer = window.setInterval(() => { void refresh(); }, intervalMs);
    return () => window.clearInterval(timer);
  }, [automatic, intervalMs, refresh, visible]);

  useEffect(() => {
    if (activeTab !== "processes" || data?.scope !== "admin") return;
    void refreshProcesses();
    if (!automatic || !visible) return;
    const timer = window.setInterval(() => { void refreshProcesses(); }, Math.max(intervalMs, 3000));
    return () => window.clearInterval(timer);
  }, [activeTab, automatic, data?.scope, intervalMs, refreshProcesses, visible]);

  useEffect(() => {
    if (data?.scope !== "admin" && (activeTab === "processes" || activeTab === "mounts")) setActiveTab("overview");
  }, [activeTab, data?.scope]);

  const storage = useMemo(() => dedupeStorage(data?.allowed_roots || []), [data?.allowed_roots]);
  const currentServiceState = serviceState(data?.webnas_service || null);

  const tabs: Array<{ id: MonitorTab; label: string }> = [
    { id: "overview", label: t("monitor.overview") },
    { id: "cpu", label: t("monitor.cpu") },
    { id: "memory", label: t("monitor.memory") },
    { id: "network", label: t("monitor.network") },
    { id: "storage", label: t("monitor.storage") },
  ];
  if (data?.scope === "admin") {
    tabs.push(
      { id: "processes", label: t("monitor.processes") },
      { id: "mounts", label: t("monitor.allMounts") },
    );
  }

  return <section className="system-app monitor-app">
    <header className="monitor-header">
      <div className="monitor-heading">
        <div className="monitor-title-line"><h2>{t("app.monitor")}</h2>{data && <span className={`monitor-state ${currentServiceState}`}>{data.webnas_service ? t(`monitor.service.${data.webnas_service}`) : t("monitor.restricted")}</span>}</div>
        {data && <div className="monitor-host-summary">
          <strong>{data.hostname}</strong><span>{data.os_name}</span><span>{data.kernel_version}</span><span>{t("monitor.uptime")}: {formatDuration(data.uptime_seconds)}</span>{data.temperature_c !== null && <span>{t("monitor.temperature")}: {data.temperature_c.toFixed(1)} °C</span>}{data.boot_time && <span>{t("monitor.bootTime")}: {new Date(data.boot_time * 1000).toLocaleString()}</span>}
        </div>}
      </div>
      <div className="monitor-controls">
        <label className="monitor-auto"><input type="checkbox" checked={automatic} onChange={(event) => setAutomatic(event.target.checked)} /><span>{t("monitor.autoRefresh")}</span></label>
        <label className="monitor-interval"><span>{t("monitor.interval")}</span><select aria-label={t("monitor.interval")} value={intervalMs} onChange={(event) => setIntervalMs(Number(event.target.value))}><option value={1000}>1 s</option><option value={2000}>2 s</option><option value={5000}>5 s</option><option value={10000}>10 s</option></select></label>
        <button type="button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} aria-hidden="true" /><span>{t("action.refresh")}</span></button>
      </div>
    </header>

    <div className="monitor-status" aria-live="polite"><span>{loading ? t("status.loading") : t("monitor.ready")}</span><span>{t("monitor.lastUpdate")}: {lastUpdate ? lastUpdate.toLocaleTimeString() : "—"}</span>{!visible && <span>{t("monitor.hiddenPaused")}</span>}</div>
    {error && <p className="error-state compact-error monitor-refresh-error" role="alert">{t("monitor.refreshError")}: {error}</p>}
    {!data && loading && <div className="loading-state">{t("status.loading")}</div>}

    {data && <>
      <Tabs items={tabs} active={activeTab} onChange={setActiveTab} ariaLabel={t("app.monitor")} className="monitor-section-tabs" />
      <div className="monitor-content" role="tabpanel">
        {activeTab === "overview" && <>
          <AlertsPanel alerts={data.alerts} warnings={data.warnings} t={t} />
          <OverviewCards data={data} storage={storage} history={history} t={t} />
        </>}
        {activeTab === "cpu" && <CpuPanel data={data} history={history} t={t} />}
        {activeTab === "memory" && <MemoryPanel data={data} history={history} t={t} />}
        {activeTab === "network" && <NetworkPanel networks={data.network_interfaces} history={history} t={t} />}
        {activeTab === "storage" && <StoragePanel storage={storage} diskIo={data.disk_io} history={history} t={t} />}
        {activeTab === "processes" && data.scope === "admin" && <ProcessesPanel processes={processes ?? data.processes} t={t} />}
        {activeTab === "mounts" && data.scope === "admin" && <AllMountsPanel mountpoints={data.mountpoints} t={t} />}
      </div>
    </>}
  </section>;
}
