import { request } from "../../../core/api/transport";

export type DcstPort = { id: string; name: string; protocol: "tcp" | "udp" | "tcp+udp" | "icmp"; port_from?: number | null; port_to?: number | null; description: string; dependencies?: Array<{ id: string; name: string }> };
export type DcstIPSet = { id: string; name: string; description: string; type: "dynamic" | "manual" | "system"; provider_name: string; sync_status: string; last_error: string; entries: Array<{ id: string; address: string; comment: string }>; dependencies?: Array<{ id: string; name: string }> };
export type DcstTag = { id: string; name: string; apmid: string; environment: string; provider_name: string; sync_status: string; vm_count: number; addresses: string[]; hosts: Array<{ id: string; name: string; address: string; vmid?: number | null; node?: string }> };
export type DcstService = { id: string; name: string; description: string; direction: "IN" | "OUT"; action: "ACCEPT" | "DROP" | "REJECT"; source_type: "tag" | "ipset" | "ip" | "cidr" | "any" | "apmid"; source_value: string; destination_type: "tag" | "ipset" | "ip" | "cidr" | "any" | "apmid"; destination_value: string; port_ids: string[]; enabled: boolean; blocked: boolean; logging: boolean; comment: string; system_service: boolean; sync_status: string; state: "ACTIVE" | "BLOCKED" | "DISABLED" | "PENDING" | "ERROR"; last_error: string };
export type DcstOverview = { services: number; active_services: number; blocked_services: number; ports: number; ipsets: number; tags: number; firewall_rules: number; firewall: Record<string, unknown>; last_inventory_sync: Record<string, unknown>; last_firewall_sync: Record<string, unknown>; recent_changes: Array<Record<string, unknown>> };
export type DcstServiceInput = Omit<DcstService, "id" | "blocked" | "system_service" | "sync_status" | "state" | "last_error">;

const json = (method: string, body: unknown = {}) => ({ method, body: JSON.stringify(body) });

export const dcstClient = {
  overview: () => request<DcstOverview>("/api/modules/dcst/overview"),
  tags: () => request<DcstTag[]>("/api/modules/dcst/tags"),
  syncTags: (dryRun = false) => request<Record<string, unknown>>("/api/modules/dcst/tags/sync", json("POST", { dry_run: dryRun })),
  ipsets: () => request<DcstIPSet[]>("/api/modules/dcst/ipsets"),
  saveIPSet: (payload: { name: string; description: string; entries: string[] }, id = "") => request<DcstIPSet>(id ? `/api/modules/dcst/ipsets/${encodeURIComponent(id)}` : "/api/modules/dcst/ipsets", json(id ? "PUT" : "POST", payload)),
  deleteIPSet: (id: string) => request<{ ok: boolean }>(`/api/modules/dcst/ipsets/${encodeURIComponent(id)}`, { method: "DELETE" }),
  syncIPSet: (id: string, dryRun = false) => request<Record<string, unknown>>(`/api/modules/dcst/ipsets/${encodeURIComponent(id)}/sync`, json("POST", { dry_run: dryRun })),
  ports: () => request<DcstPort[]>("/api/modules/dcst/ports"),
  savePort: (payload: Omit<DcstPort, "id" | "dependencies">, id = "") => request<DcstPort>(id ? `/api/modules/dcst/ports/${encodeURIComponent(id)}` : "/api/modules/dcst/ports", json(id ? "PUT" : "POST", payload)),
  deletePort: (id: string) => request<{ ok: boolean }>(`/api/modules/dcst/ports/${encodeURIComponent(id)}`, { method: "DELETE" }),
  services: (filters: Record<string, string> = {}) => {
    const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value));
    return request<DcstService[]>(`/api/modules/dcst/services${query.size ? `?${query}` : ""}`);
  },
  saveService: (payload: DcstServiceInput, id = "") => request<DcstService>(id ? `/api/modules/dcst/services/${encodeURIComponent(id)}` : "/api/modules/dcst/services", json(id ? "PUT" : "POST", payload)),
  deleteService: (id: string) => request<{ ok: boolean }>(`/api/modules/dcst/services/${encodeURIComponent(id)}`, { method: "DELETE" }),
  cloneService: (id: string) => request<DcstService>(`/api/modules/dcst/services/${encodeURIComponent(id)}/clone`, json("POST")),
  serviceAction: (id: string, action: "block" | "unblock" | "enable" | "disable") => request<Record<string, unknown>>(`/api/modules/dcst/services/${encodeURIComponent(id)}/${action}`, json("POST")),
  syncService: (id: string, dryRun = false, confirmHighRisk = false) => request<Record<string, unknown>>(`/api/modules/dcst/services/${encodeURIComponent(id)}/sync`, json("POST", { dry_run: dryRun, confirm_high_risk: confirmHighRisk })),
  previewService: (id: string) => request<Record<string, unknown>>(`/api/modules/dcst/services/${encodeURIComponent(id)}/preview`),
  bulk: (action: "block" | "unblock" | "enable" | "disable" | "sync", ids: string[]) => request<Record<string, unknown>>(`/api/modules/dcst/services/bulk/${action}`, json("POST", { ids })),
  firewallStatus: () => request<Record<string, unknown>>("/api/modules/dcst/firewall/status"),
  firewallLogs: () => request<Array<Record<string, unknown>>>("/api/modules/dcst/firewall/logs?limit=300"),
  firewallSync: (dryRun = false, confirmHighRisk = false) => request<Record<string, unknown>>("/api/modules/dcst/firewall/sync", json("POST", { dry_run: dryRun, confirm_high_risk: confirmHighRisk })),
  drift: () => request<Record<string, unknown>>("/api/modules/dcst/firewall/drift"),
  test: () => request<Record<string, unknown>>("/api/modules/dcst/firewall/test", json("POST")),
  diagnostics: () => request<Record<string, unknown>>("/api/modules/dcst/diagnostics"),
  audit: () => request<Array<Record<string, unknown>>>("/api/modules/dcst/audit?limit=100"),
};
