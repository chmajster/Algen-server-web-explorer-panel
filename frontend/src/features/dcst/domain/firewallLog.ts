export type FirewallLogFilters = {
  search: string;
  node: string;
  direction: string;
  action: string;
  source: string;
  destination: string;
  range: string;
};

export const emptyFirewallLogFilters: FirewallLogFilters = {
  search: "",
  node: "",
  direction: "",
  action: "",
  source: "",
  destination: "",
  range: "",
};

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

export function syncTimestamp(value: unknown): number | null {
  const record = asRecord(value);
  const raw = record.at ?? record.timestamp ?? record.time ?? record.updated_at;
  if (raw === undefined || raw === null || raw === "") return null;
  const numeric = Number(raw);
  if (Number.isFinite(numeric)) return numeric > 10_000_000_000 ? numeric : numeric * 1000;
  const parsed = new Date(String(raw)).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

export function relativeTime(value: unknown): string {
  const timestamp = syncTimestamp(value);
  if (!timestamp) return "never";
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} d ago`;
}

export function exactTime(value: unknown): string {
  const timestamp = syncTimestamp(value);
  return timestamp ? new Date(timestamp).toLocaleString() : "—";
}

export function recordSummary(record: Record<string, unknown>): Array<[string, unknown]> {
  const entries = Object.entries(record).filter(([, value]) => typeof value !== "object").slice(0, 10);
  return entries.length ? entries : [["status", "No structured data"]];
}

function firewallLogToken(raw: string, key: string): string {
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return raw.match(new RegExp(`(?:^|\\s)${escaped}=([^\\s]+)`, "i"))?.[1] || "";
}

export function normalizeFirewallLog(row: Record<string, unknown>): Record<string, unknown> {
  const raw = String(row.t || row.msg || row.message || row.raw || JSON.stringify(row));
  const prefixedTime = raw.match(/\b\d{4}-\d{2}-\d{2}[T ][0-9:.+-]+Z?\b/)?.[0] || "";
  const time = row.time || row.timestamp || row.at || firewallLogToken(raw, "TIME") || prefixedTime;
  const direction = String(row.direction || row.dir || firewallLogToken(raw, "DIRECTION") || firewallLogToken(raw, "DIR") || "").toUpperCase();
  const action = String(row.action || row.policy_action || firewallLogToken(raw, "ACTION") || "").toUpperCase();
  const source = String(row.source || row.src || row.src_ip || firewallLogToken(raw, "SRC") || firewallLogToken(raw, "SOURCE") || "");
  const destination = String(row.destination || row.dst || row.dst_ip || firewallLogToken(raw, "DST") || firewallLogToken(raw, "DESTINATION") || "");
  return { ...row, dcst_time: time, dcst_direction: direction, dcst_action: action, dcst_source: source, dcst_destination: destination, dcst_raw: raw };
}

export function filterFirewallLogs(rows: readonly Record<string, unknown>[], filters: FirewallLogFilters, snapshotTime: number): Record<string, unknown>[] {
  const rangeMs = filters.range === "15m" ? 15 * 60_000 : filters.range === "1h" ? 60 * 60_000 : filters.range === "24h" ? 24 * 60 * 60_000 : 0;
  return rows.filter((row) => {
    const raw = String(row.dcst_raw || JSON.stringify(row)).toLowerCase();
    const timestamp = syncTimestamp({ time: row.dcst_time });
    return (!filters.search || raw.includes(filters.search.toLowerCase()))
      && (!filters.node || String(row.node || "").toLowerCase() === filters.node.toLowerCase())
      && (!filters.direction || String(row.dcst_direction || "").toUpperCase() === filters.direction)
      && (!filters.action || String(row.dcst_action || "").toUpperCase() === filters.action)
      && (!filters.source || String(row.dcst_source || "").toLowerCase().includes(filters.source.toLowerCase()))
      && (!filters.destination || String(row.dcst_destination || "").toLowerCase().includes(filters.destination.toLowerCase()))
      && (!rangeMs || !timestamp || snapshotTime - timestamp <= rangeMs);
  });
}
