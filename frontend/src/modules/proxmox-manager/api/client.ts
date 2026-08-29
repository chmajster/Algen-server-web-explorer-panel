import { request } from "../../../core/api/transport";

export type ProxmoxCredentialSummary = {
  id: string;
  name: string;
  type: string;
  username: string;
  secret_configured: boolean;
};

export type ProxmoxConnection = {
  id: string;
  name: string;
  endpoint: string;
  credential_id: string;
  credential?: ProxmoxCredentialSummary | null;
  verify_tls: boolean;
  ca_certificate: string;
  default_ssh_user: string;
  project: string;
  environment: string;
  location: string;
  tags: string[];
  sync_proxmox_tags: boolean;
  sync_lxc: boolean;
  sync_templates: boolean;
  active: boolean;
  auto_sync: boolean;
  sync_interval_seconds?: number;
  last_sync_at?: number | null;
  last_sync_started_at?: number | null;
  next_sync_at?: number | null;
  last_sync_duration?: number | null;
  last_sync_result?: string;
  last_sync_status: string;
  last_error: string;
  consecutive_sync_failures?: number;
  backoff_until?: number | null;
};

export type ProxmoxVm = {
  connection_id: string;
  connection_name: string;
  vmid: number;
  name: string;
  node: string;
  type: "qemu" | "lxc";
  status: string;
  template: boolean;
  uptime: number;
  cpu: number;
  maxcpu: number;
  mem: number;
  maxmem: number;
  disk: number;
  maxdisk: number;
  tags: string[];
  host_id?: string | null;
  host_address?: string;
  host_active?: boolean;
  host_approved?: boolean;
  sync_state: "synced" | "not_synced";
};

export type ProxmoxVmList = {
  vms: ProxmoxVm[];
  errors: Array<{ connection_id: string; connection_name: string; error: string }>;
  total: number;
};

export type ProxmoxConnectionInput = {
  name: string;
  endpoint: string;
  credential_id: string;
  verify_tls: boolean;
  ca_certificate: string;
  default_ssh_user: string;
  project: string;
  environment: string;
  location: string;
  tags: string[];
  sync_proxmox_tags: boolean;
  sync_lxc: boolean;
  sync_templates: boolean;
  active: boolean;
  auto_sync: boolean;
  sync_interval_seconds?: number;
};

export type ProxmoxTask = {
  connection_id: string;
  upid: string;
  action: string;
  vmid?: number | null;
  node: string;
  resource_type: string;
  actor: string;
  host_id?: string | null;
  operation_id?: string | null;
  status: "Queued" | "Running" | "Completed" | "Failed";
  exitstatus: string;
  progress: number;
  started_at?: number | null;
  ended_at?: number | null;
  last_error: string;
  created_at: number;
  updated_at: number;
};

export type ProxmoxNode = {
  connection_id: string;
  connection_name: string;
  node: string;
  status: string;
  uptime: number;
  cpu: number;
  maxcpu: number;
  mem: number;
  maxmem: number;
  storage_used: number;
  storage_total: number;
  kernel: string;
  proxmox_version: string;
  load_average: Array<string | number>;
  vms: number;
  lxc: number;
  error: string;
};

export type ProxmoxStorage = {
  connection_id: string;
  connection_name: string;
  node: string;
  storage: string;
  type: string;
  status: string;
  total: number;
  used: number;
  free: number;
  utilization: number;
  shared: boolean;
  content: string;
  enabled: boolean;
};

export type ProxmoxCluster = {
  connection_id: string;
  connection_name: string;
  name: string;
  quorate: boolean;
  nodes: Array<Record<string, unknown>>;
  votes: number;
  online_nodes: number;
  ha_resources: Array<Record<string, unknown>>;
  ha_groups: Array<Record<string, unknown>>;
  errors: Record<string, string>;
};

export type ProxmoxVmDetails = ProxmoxVm & {
  config: Record<string, unknown>;
  current_status: Record<string, unknown>;
  hardware: {
    cores: number;
    sockets: number;
    cpu_type: string;
    memory_mb: number;
    balloon_mb: number;
    machine: string;
    bios: string;
    agent: unknown;
    disks: Array<Record<string, string>>;
    network_adapters: Array<Record<string, string>>;
  };
  os: unknown;
  guest_network: unknown;
  qemu_guest_agent: boolean;
  host_approved: boolean;
  host_tags: string[];
  errors: Record<string, string>;
};

export type ProxmoxSnapshot = {
  name: string;
  description: string;
  date: number;
  parent: string;
  vmstate: boolean;
  current: boolean;
};

function connectionQuery(connectionId = ""): string {
  return connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : "";
}

function vmPath(connectionId: string, vmid: number): string {
  return `/api/modules/proxmox-manager/connections/${encodeURIComponent(connectionId)}/vms/${vmid}`;
}

export const proxmoxManagerClient = {
  proxmoxDashboard: () => request<Record<string, unknown>>("/api/modules/proxmox-manager/dashboard"),
  proxmoxConnections: () => request<ProxmoxConnection[]>("/api/modules/proxmox-manager/connections"),
  saveProxmoxConnection: (payload: ProxmoxConnectionInput, id = "") =>
    request<ProxmoxConnection>(
      id
        ? `/api/modules/proxmox-manager/connections/${encodeURIComponent(id)}`
        : "/api/modules/proxmox-manager/connections",
      { method: id ? "PUT" : "POST", body: JSON.stringify(payload) },
    ),
  deleteProxmoxConnection: (id: string, name: string) =>
    request<{ ok: boolean }>(`/api/modules/proxmox-manager/connections/${encodeURIComponent(id)}`, {
      method: "DELETE",
      body: JSON.stringify({ confirm: true, confirmation_text: name }),
    }),
  testProxmoxConnection: (id: string) =>
    request<Record<string, unknown>>(`/api/modules/proxmox-manager/connections/${encodeURIComponent(id)}/test`, {
      method: "POST",
      body: "{}",
    }),
  syncProxmoxConnection: (id: string, resolveAddresses = true, disableMissing = true) =>
    request<{
      connection_id: string;
      created: number;
      updated: number;
      disabled: number;
      tagged: number;
      tag_errors: Array<{ vmid: number; name: string; error: string }>;
      skipped: Array<{ vmid: number; name: string; reason: string }>;
      hosts: Array<Record<string, unknown>>;
    }>(`/api/modules/proxmox-manager/connections/${encodeURIComponent(id)}/sync`, {
      method: "POST",
      body: JSON.stringify({ resolve_addresses: resolveAddresses, disable_missing: disableMissing }),
    }),
  proxmoxVms: (connectionId = "") =>
    request<ProxmoxVmList>(`/api/modules/proxmox-manager/vms${connectionQuery(connectionId)}`),
  proxmoxVmDetails: (connectionId: string, vmid: number) => request<ProxmoxVmDetails>(vmPath(connectionId, vmid)),
  proxmoxNodes: (connectionId = "") =>
    request<{ nodes: ProxmoxNode[]; errors: Array<Record<string, string>>; total: number }>(`/api/modules/proxmox-manager/nodes${connectionQuery(connectionId)}`),
  proxmoxNodeDetails: (connectionId: string, node: string) =>
    request<Record<string, unknown>>(`/api/modules/proxmox-manager/nodes/${encodeURIComponent(node)}?connection_id=${encodeURIComponent(connectionId)}`),
  proxmoxStorage: (connectionId = "") =>
    request<{ storage: ProxmoxStorage[]; errors: Array<Record<string, string>>; total: number }>(`/api/modules/proxmox-manager/storage${connectionQuery(connectionId)}`),
  proxmoxCluster: (connectionId = "") =>
    request<{ clusters: ProxmoxCluster[]; errors: Array<Record<string, string>>; total: number }>(`/api/modules/proxmox-manager/cluster${connectionQuery(connectionId)}`),
  proxmoxTemplates: (connectionId = "") =>
    request<{ templates: ProxmoxVm[]; errors: Array<Record<string, string>>; total: number }>(`/api/modules/proxmox-manager/templates${connectionQuery(connectionId)}`),
  proxmoxVmBackups: (connectionId: string, vmid: number) =>
    request<{ backups: Array<Record<string, unknown>>; errors: Array<Record<string, string>>; total: number }>(`${vmPath(connectionId, vmid)}/backups`),
  proxmoxVmSnapshots: (connectionId: string, vmid: number) =>
    request<{ snapshots: ProxmoxSnapshot[] }>(`${vmPath(connectionId, vmid)}/snapshots`),
  createProxmoxSnapshot: (connectionId: string, vmid: number, payload: { name: string; description?: string; include_ram?: boolean }) =>
    request<Record<string, unknown>>(`${vmPath(connectionId, vmid)}/snapshots`, { method: "POST", body: JSON.stringify(payload) }),
  deleteProxmoxSnapshot: (connectionId: string, vmid: number, snapshot: string, vmName: string) =>
    request<Record<string, unknown>>(`${vmPath(connectionId, vmid)}/snapshots/${encodeURIComponent(snapshot)}`, {
      method: "DELETE",
      body: JSON.stringify({ confirm: true, confirmation_text: vmName }),
    }),
  rollbackProxmoxSnapshot: (connectionId: string, vmid: number, snapshot: string, vmName: string) =>
    request<Record<string, unknown>>(`${vmPath(connectionId, vmid)}/snapshots/${encodeURIComponent(snapshot)}/rollback`, {
      method: "POST",
      body: JSON.stringify({ confirm: true, confirmation_text: vmName }),
    }),
  cloneProxmoxVm: (connectionId: string, vmid: number, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`${vmPath(connectionId, vmid)}/clone`, { method: "POST", body: JSON.stringify(payload) }),
  validateProxmoxMigration: (connectionId: string, vmid: number, payload: Record<string, unknown>) =>
    request<{ valid: boolean; issues: string[]; warnings: string[] }>(`${vmPath(connectionId, vmid)}/migration/validate`, { method: "POST", body: JSON.stringify(payload) }),
  migrateProxmoxVm: (connectionId: string, vmid: number, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`${vmPath(connectionId, vmid)}/migration`, { method: "POST", body: JSON.stringify(payload) }),
  planProxmoxHardware: (connectionId: string, vmid: number, payload: Record<string, unknown>) =>
    request<{ changes: Array<{ field: string; current: number; new: number }> }>(`${vmPath(connectionId, vmid)}/hardware/plan`, { method: "POST", body: JSON.stringify(payload) }),
  updateProxmoxHardware: (connectionId: string, vmid: number, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`${vmPath(connectionId, vmid)}/hardware`, { method: "PUT", body: JSON.stringify(payload) }),
  resizeProxmoxDisk: (connectionId: string, vmid: number, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`${vmPath(connectionId, vmid)}/disks/resize`, { method: "PUT", body: JSON.stringify(payload) }),
  createProxmoxVm: (connectionId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/modules/proxmox-manager/connections/${encodeURIComponent(connectionId)}/vms`, { method: "POST", body: JSON.stringify(payload) }),
  proxmoxTasks: (connectionId = "", activeOnly = false, limit = 100) => {
    const params = new URLSearchParams();
    if (connectionId) params.set("connection_id", connectionId);
    if (activeOnly) params.set("active_only", "true");
    params.set("limit", String(limit));
    return request<{ tasks: ProxmoxTask[]; total: number }>(`/api/modules/proxmox-manager/tasks?${params.toString()}`);
  },
  proxmoxTask: (upid: string, connectionId = "") =>
    request<ProxmoxTask>(`/api/modules/proxmox-manager/tasks/${encodeURIComponent(upid)}${connectionQuery(connectionId)}`),
  proxmoxTaskLog: (upid: string, connectionId = "") =>
    request<{ log: Array<Record<string, unknown>> }>(`/api/modules/proxmox-manager/tasks/${encodeURIComponent(upid)}/log${connectionQuery(connectionId)}`),
  proxmoxVmPower: (
    connectionId: string,
    vmid: number,
    action: "start" | "stop" | "shutdown" | "reboot",
    confirmationText = "",
  ) =>
    request<Record<string, unknown>>(
      `${vmPath(connectionId, vmid)}/power`,
      {
        method: "POST",
        body: JSON.stringify({ action, confirm: true, confirmation_text: confirmationText }),
      },
    ),
} as const;
