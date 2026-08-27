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
  last_sync_at?: number | null;
  last_sync_status: string;
  last_error: string;
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
};

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
    request<ProxmoxVmList>(
      `/api/modules/proxmox-manager/vms${connectionId ? `?connection_id=${encodeURIComponent(connectionId)}` : ""}`,
    ),
  proxmoxVmPower: (
    connectionId: string,
    vmid: number,
    action: "start" | "stop" | "shutdown" | "reboot",
    confirmationText = "",
  ) =>
    request<Record<string, unknown>>(
      `/api/modules/proxmox-manager/connections/${encodeURIComponent(connectionId)}/vms/${vmid}/power`,
      {
        method: "POST",
        body: JSON.stringify({ action, confirm: true, confirmation_text: confirmationText }),
      },
    ),
} as const;
