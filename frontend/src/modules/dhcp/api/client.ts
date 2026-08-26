import { request } from "../../../core/api/transport";
import type { AppJob } from "../../../core/api/contracts";

export type DhcpBackend = "kea" | "isc" | "none";
export type DhcpHealth = "healthy" | "degraded" | "failed" | "unknown" | "not_installed";
export type DhcpThresholds = { warning: number; critical: number; emergency: number };
export type DhcpUtilization = { subnet_id: string; subnet: string; pool_start: string; pool_end: string; used: number; available: number; total: number; usage_percent: number; level: "normal" | "warning" | "critical" | "emergency" };
export type DhcpSubnet = { id: string; name: string; cidr: string; gateway: string; subnet_mask: string; pool_start: string; pool_end: string; dns_servers: string[]; domain_name: string; search_domain: string; lease_time: number; max_lease_time: number; ntp_servers: string[]; broadcast_address: string; tftp_server: string; boot_filename: string; pxe_enabled: boolean; enabled: boolean; description: string; utilization?: DhcpUtilization | null };
export type DhcpReservation = { id: string; hostname: string; mac_address: string; ipv4_address: string; subnet_id: string; description: string; client_identifier: string; enabled: boolean; create_dns_record: boolean; dns_provider: "auto" | "pihole" | "adguard-home" };
export type DhcpLease = { id: string; hostname: string; ipv4_address: string; mac_address: string; client_identifier: string; subnet_id: string; subnet: string; lease_start: number | null; lease_end: number | null; remaining_seconds: number; state: string; reserved: boolean };
export type DhcpInterface = { name: string; state: string; mac_address: string; ipv4_addresses: string[]; subnets: string[]; dhcp_enabled: boolean };
export type DhcpConfiguration = { interfaces: string[]; authoritative: boolean; default_lease_time: number; max_lease_time: number; thresholds: DhcpThresholds; subnets: DhcpSubnet[]; reservations: DhcpReservation[] };
export type DhcpStatus = { installed: boolean; backend: DhcpBackend; version: string; service: string; service_state: string; service_enabled: boolean; uptime_seconds: number | null; interfaces: string[]; active_leases: number; available_addresses: number; used_addresses: number; subnet_count: number; reservation_count: number; last_errors: string[]; last_config_change: number | null; configuration_valid: boolean | null; health: DhcpHealth; blocked_by_proxmox: boolean };
export type DhcpValidation = { ok: boolean; backend: DhcpBackend; issues: Array<{ level: "error" | "warning"; code: string; message: string; object_id: string }>; native_output: string; candidate_sha256: string };
export type DhcpPlan = { validation: DhcpValidation; added_subnets: string[]; removed_subnets: string[]; changed_subnets: string[]; added_reservations: string[]; removed_reservations: string[]; changed_reservations: string[]; changed_global_options: string[]; warnings: string[] };
export type DhcpDiagnostic = { status: "PASS" | "WARNING" | "FAIL"; code: string; title: string; detail: string; recommendation: string };
export type DhcpBackup = { id: string; backend: DhcpBackend; version: string; timestamp: number; actor: string; description: string; automatic: boolean; sha256: string; files: string[]; subnets: number; reservations: number };

type Confirmation = { confirmation: string; pam_password: string };
const secure = (confirmation: string, pam_password: string) => ({ confirmation, pam_password });

export const dhcpClient = {
  dhcpAccess: () => request<{ installed: boolean; allowed: boolean; blocked_by_proxmox: boolean }>("/api/modules/dhcp/access"),
  dhcpStatus: () => request<DhcpStatus>("/api/modules/dhcp/status"),
  dhcpSubnets: () => request<{ items: DhcpSubnet[]; total: number }>("/api/modules/dhcp/subnets"),
  dhcpReservations: () => request<{ items: DhcpReservation[]; total: number }>("/api/modules/dhcp/reservations"),
  dhcpLeases: (params: { search?: string; subnet_id?: string; state?: string; sort?: string } = {}) => {
    const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => value && query.set(key, value));
    return request<{ items: DhcpLease[]; total: number }>(`/api/modules/dhcp/leases?${query}`);
  },
  dhcpInterfaces: () => request<{ items: DhcpInterface[]; total: number }>("/api/modules/dhcp/interfaces"),
  dhcpConfig: () => request<DhcpConfiguration>("/api/modules/dhcp/config"),
  validateDhcpConfig: (configuration: DhcpConfiguration) => request<DhcpValidation>("/api/modules/dhcp/config/validate", { method: "POST", body: JSON.stringify(configuration) }),
  planDhcpConfig: (configuration: DhcpConfiguration) => request<DhcpPlan>("/api/modules/dhcp/config/plan", { method: "POST", body: JSON.stringify(configuration) }),
  applyDhcpConfig: (configuration: DhcpConfiguration, confirmation: Confirmation) => request<{ job: AppJob }>("/api/modules/dhcp/config/apply", { method: "POST", body: JSON.stringify({ configuration, ...confirmation }) }),
  createDhcpSubnet: (subnet: DhcpSubnet, confirmation: Confirmation) => request<{ job: AppJob }>("/api/modules/dhcp/subnets", { method: "POST", body: JSON.stringify({ subnet, ...confirmation }) }),
  updateDhcpSubnet: (subnet: DhcpSubnet, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/dhcp/subnets/${encodeURIComponent(subnet.id)}`, { method: "PUT", body: JSON.stringify({ subnet, ...confirmation }) }),
  deleteDhcpSubnet: (id: string, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/dhcp/subnets/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify(confirmation) }),
  setDhcpSubnetEnabled: (id: string, enabled: boolean, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/dhcp/subnets/${encodeURIComponent(id)}/${enabled ? "enable" : "disable"}`, { method: "POST", body: JSON.stringify(confirmation) }),
  cloneDhcpSubnet: (id: string, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/dhcp/subnets/${encodeURIComponent(id)}/clone`, { method: "POST", body: JSON.stringify(confirmation) }),
  createDhcpReservation: (reservation: DhcpReservation, confirmation: Confirmation) => request<{ job: AppJob }>("/api/modules/dhcp/reservations", { method: "POST", body: JSON.stringify({ reservation, ...confirmation }) }),
  updateDhcpReservation: (reservation: DhcpReservation, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/dhcp/reservations/${encodeURIComponent(reservation.id)}`, { method: "PUT", body: JSON.stringify({ reservation, ...confirmation }) }),
  deleteDhcpReservation: (id: string, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/dhcp/reservations/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify(confirmation) }),
  setDhcpReservationEnabled: (id: string, enabled: boolean, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/dhcp/reservations/${encodeURIComponent(id)}/${enabled ? "enable" : "disable"}`, { method: "POST", body: JSON.stringify(confirmation) }),
  convertDhcpLease: (id: string, values: { hostname?: string; description?: string; create_dns_record?: boolean; dns_provider?: string } & Confirmation) => request<{ job: AppJob }>(`/api/modules/dhcp/leases/${encodeURIComponent(id)}/reservation`, { method: "POST", body: JSON.stringify(values) }),
  addDhcpLeaseToHosts: (id: string, ssh_user: string, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/dhcp/leases/${encodeURIComponent(id)}/hosts`, { method: "POST", body: JSON.stringify({ ssh_user, ...confirmation }) }),
  dhcpBackups: () => request<{ items: DhcpBackup[] }>("/api/modules/dhcp/backups"),
  createDhcpBackup: (description: string, confirmation: Confirmation) => request<{ job: AppJob }>("/api/modules/dhcp/backups", { method: "POST", body: JSON.stringify({ description, ...confirmation }) }),
  restoreDhcpBackup: (id: string, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/dhcp/backups/${encodeURIComponent(id)}/restore`, { method: "POST", body: JSON.stringify(confirmation) }),
  deleteDhcpBackup: (id: string, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/dhcp/backups/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify(confirmation) }),
  dhcpLogs: (params: { search?: string; level?: string; limit?: number; since?: string } = {}) => { const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => value !== undefined && value !== "" && query.set(key, String(value))); return request<{ source: string; sources: Array<{ id: string; label: string }>; lines: string[]; truncated: boolean }>(`/api/modules/dhcp/logs?${query}`); },
  dhcpDiagnostics: () => request<{ items: DhcpDiagnostic[] }>("/api/modules/dhcp/diagnostics", { method: "POST", body: "{}" }),
  controlDhcpService: (action: "start" | "stop" | "restart" | "reload" | "enable" | "disable", confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/dhcp/service/${action}`, { method: "POST", body: JSON.stringify(confirmation) }),
  dhcpConfirmation: secure,
} as const;
