import type { DiskMetric, NetworkMetric } from "../../../api";

export const MAX_SAMPLES = 90;

export type History = Record<string, number[]>;
export type UsageLevel = "normal" | "warning" | "critical";
export type SortDirection = "asc" | "desc";
export type ProcessSortKey = "cpu_percent" | "memory_percent" | "rss" | "pid" | "name";

export function pushSample(history: History, key: string, value: number | null | undefined): History {
  return {
    ...history,
    [key]: [...(history[key] || []), value ?? 0].slice(-MAX_SAMPLES),
  };
}

export function usageLevel(percent: number): UsageLevel {
  if (percent >= 95) return "critical";
  if (percent >= 85) return "warning";
  return "normal";
}

export function clampPercent(percent: number): number {
  return Math.max(0, Math.min(100, percent));
}

export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(1)}%`;
}

export function formatDuration(value: number | null): string {
  if (value === null) return "—";
  const days = Math.floor(value / 86400);
  const hours = Math.floor((value % 86400) / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  return `${days}d ${hours}h ${minutes}m`;
}

export function dedupeStorage(disks: DiskMetric[]): DiskMetric[] {
  const grouped = new Map<string, DiskMetric>();

  for (const disk of disks) {
    const key = disk.filesystem_id || disk.device || disk.mountpoint || disk.path;
    const previous = grouped.get(key);
    if (!previous) {
      grouped.set(key, { ...disk, paths: Array.from(new Set(disk.paths || [disk.path])) });
      continue;
    }

    const paths = Array.from(new Set([...(previous.paths || [previous.path]), ...(disk.paths || [disk.path])]));
    grouped.set(key, {
      ...previous,
      ...disk,
      path: previous.path,
      paths,
      filesystem_id: previous.filesystem_id || disk.filesystem_id,
      device: previous.device || disk.device,
      mountpoint: previous.mountpoint || disk.mountpoint,
      fs_type: previous.fs_type || disk.fs_type,
    });
  }

  return Array.from(grouped.values());
}

export function selectStorageSummary(disks: DiskMetric[]): DiskMetric | null {
  if (disks.length === 0) return null;
  return disks.reduce((selected, disk) => (disk.percent > selected.percent ? disk : selected));
}

export type NetworkSummary = {
  interfaces: NetworkMetric[];
  rxBytesPerSec: number;
  txBytesPerSec: number;
  rxBytes: number;
  txBytes: number;
};

export function isAggregateNetworkInterface(network: NetworkMetric): boolean {
  return network.state === "up" && !network.system;
}

export function summarizeNetwork(networks: NetworkMetric[]): NetworkSummary {
  const active = networks.filter((network) => network.state === "up");
  const preferred = active.filter(isAggregateNetworkInterface);
  const nonLoopback = active.filter((network) => network.name !== "lo");
  const interfaces = preferred.length > 0 ? preferred : nonLoopback.length > 0 ? nonLoopback : active;

  return interfaces.reduce<NetworkSummary>((summary, network) => ({
    interfaces,
    rxBytesPerSec: summary.rxBytesPerSec + (network.rx_bytes_per_sec || 0),
    txBytesPerSec: summary.txBytesPerSec + (network.tx_bytes_per_sec || 0),
    rxBytes: summary.rxBytes + network.rx_bytes,
    txBytes: summary.txBytes + network.tx_bytes,
  }), {
    interfaces,
    rxBytesPerSec: 0,
    txBytesPerSec: 0,
    rxBytes: 0,
    txBytes: 0,
  });
}
