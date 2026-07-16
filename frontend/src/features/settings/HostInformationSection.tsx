import { ChevronDown, Cpu, HardDrive, RefreshCw, Server } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api, type HostInfo } from "../../api";
import type { Language } from "../../i18n";
import type { Translate } from "../../app/types";

function formatBytes(value: number | null | undefined, language: Language) {
  if (value == null || !Number.isFinite(value)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let amount = Math.max(0, value);
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${new Intl.NumberFormat(language, { maximumFractionDigits: unit ? 1 : 0 }).format(amount)} ${units[unit]}`;
}

function formatUptime(value: number | null, t: Translate) {
  if (value == null || !Number.isFinite(value)) return "—";
  const seconds = Math.max(0, Math.floor(value));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const parts = [];
  if (days) parts.push(`${days} ${t("settings.daysShort")}`);
  if (hours || days) parts.push(`${hours} ${t("settings.hoursShort")}`);
  parts.push(`${minutes} ${t("settings.minutesShort")}`);
  return parts.join(" ");
}

function HostPanel({ title, icon, children, initiallyOpen = false }: { title: string; icon: ReactNode; children: ReactNode; initiallyOpen?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen);
  return <details className="settings-host-panel" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>{icon}<strong>{title}</strong><ChevronDown className="settings-host-chevron" aria-hidden="true" /></summary>
    <div className="settings-host-panel-content">{children}</div>
  </details>;
}

function Details({ rows }: { rows: Array<[string, ReactNode]> }) {
  return <dl className="settings-details">{rows.map(([label, value]) => <div className="settings-detail-pair" key={label}><dt>{label}</dt><dd>{value == null || value === "" ? "—" : value}</dd></div>)}</dl>;
}

export function HostInformationSection({ language, t }: { language: Language; t: Translate }) {
  const [data, setData] = useState<HostInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  async function refresh() {
    setRefreshing(true);
    try { setData(await api.hostInfo()); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("settings.hostInfoUnavailable")); }
    finally { setLoading(false); setRefreshing(false); }
  }

  useEffect(() => {
    let active = true;
    const load = async () => {
      try { const next = await api.hostInfo(); if (active) { setData(next); setError(""); } }
      catch (reason) { if (active) setError(reason instanceof Error ? reason.message : t("settings.hostInfoUnavailable")); }
      finally { if (active) setLoading(false); }
    };
    void load();
    const timer = window.setInterval(() => void load(), 60_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [t]);

  return <section className="settings-host-information" aria-labelledby="settings-host-title">
    <header><div><h3 id="settings-host-title">{t("settings.hostInformation")}</h3><p>{t("settings.hostInformationHint")}</p></div><button type="button" aria-label={t("settings.refreshHostInformation")} title={t("settings.refreshHostInformation")} disabled={refreshing} onClick={() => void refresh()}><RefreshCw className={refreshing ? "spin" : ""} /></button></header>
    {loading && !data ? <div className="loading-state">{t("status.loading")}</div> : error && !data ? <div className="error-state" role="alert">{error}</div> : data && <div className="settings-host-panels">
      <HostPanel title={t("settings.hostSystemPanel")} icon={<Server />} initiallyOpen><Details rows={[
        [t("settings.hostname"), data.hostname],
        [t("settings.operatingSystem"), data.operating_system],
        [t("settings.kernelVersion"), data.kernel_version],
        [t("settings.architecture"), data.architecture],
        [t("settings.ipAddresses"), data.ip_addresses.join(", ") || t("settings.notDetected")],
        [t("settings.systemUptime"), formatUptime(data.uptime_seconds, t)],
      ]} /></HostPanel>
      <HostPanel title={t("settings.hostHardwarePanel")} icon={<Cpu />}><Details rows={[
        [t("settings.cpuModel"), data.cpu.model || t("settings.notDetected")],
        [t("settings.physicalCores"), data.cpu.physical_cores ?? "—"],
        [t("settings.logicalThreads"), data.cpu.logical_threads ?? "—"],
        [t("settings.totalMemory"), formatBytes(data.memory.total, language)],
        [t("settings.graphicsProcessors"), data.gpus.join(", ") || t("settings.notDetected")],
      ]} /></HostPanel>
      <HostPanel title={t("settings.hostStoragePanel")} icon={<HardDrive />}><Details rows={[
        [t("settings.applicationVersion"), data.application_version],
        [t("settings.availableDiskSpace"), data.storage ? formatBytes(data.storage.free, language) : "—"],
        [t("settings.diskCapacity"), data.storage ? formatBytes(data.storage.total, language) : "—"],
        [t("settings.diskUsage"), data.storage ? `${new Intl.NumberFormat(language, { maximumFractionDigits: 1 }).format(data.storage.percent)}%` : "—"],
      ]} />{data.storage && <div className="settings-storage-meter" role="meter" aria-label={t("settings.diskUsage")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={data.storage.percent}><span style={{ width: `${Math.min(100, Math.max(0, data.storage.percent))}%` }} /></div>}</HostPanel>
    </div>}
    {error && data && <p className="settings-host-warning" role="status">{error}</p>}
  </section>;
}
