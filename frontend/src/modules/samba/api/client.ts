import { request } from "../../../core/api/transport";
import type { ModuleJob, ModuleValidationResult, SambaConfig, SambaModuleUser, SambaSession, SambaShareAccess, SambaStatus, SambaUser, SambaValidation } from "../../../core/api/contracts";

export const sambaClient = {
  sambaModuleUsers: () => request<SambaModuleUser[]>("/api/modules/samba/users"),
  sambaModuleUserAction: (username: string, action: "add" | "password" | "enable" | "disable" | "remove", password = "") => request("/api/modules/samba/users/" + encodeURIComponent(username) + "/" + action, { method: "POST", body: JSON.stringify({ password, confirm: true }) }),
  sambaSessions: () => request<SambaSession[]>("/api/modules/samba/sessions"),
  testSambaShare: (name: string) => request<SambaShareAccess>(`/api/modules/samba/shares/${encodeURIComponent(name)}/test`),
  removeSambaShare: (name: string) => request<{ job: ModuleJob }>(`/api/modules/samba/shares/${encodeURIComponent(name)}`, { method: "DELETE", body: JSON.stringify({ confirm: true, create_backup: true }) }),
  uninstallModule: (id: string, options: { remove_config: boolean; remove_data: boolean; create_backup: boolean; confirm_name?: string }) => request<{ job: ModuleJob }>(`/api/modules/${encodeURIComponent(id)}/uninstall`, { method: "POST", body: JSON.stringify({ confirm: true, ...options }) }),
  validateSambaImport: (content: string) => request<{ config: SambaConfig; validation: ModuleValidationResult }>("/api/modules/samba/import/validate", { method: "POST", body: JSON.stringify({ content }) }),
  sambaFirewall: () => request<{ adapter: string; ports: string[]; can_manage: boolean; plan: string[][] }>("/api/modules/samba/firewall"),
  openSambaFirewall: (confirm = true) => request<{ ok?: boolean; plan: string[][]; requires_confirmation?: boolean }>("/api/modules/samba/firewall/open", { method: "POST", body: JSON.stringify({ confirm }) }),
  saveSambaConfig: (config: SambaConfig, confirm_smb1 = false) => request<{ job: ModuleJob }>("/api/apps/samba/config", { method: "PUT", body: JSON.stringify({ config, confirm_smb1 }) }),
  setSambaPassword: (username: string, password: string) => request("/api/apps/samba/smbpasswd", { method: "POST", body: JSON.stringify({ username, password }) }),
  sambaStatus: () => request<SambaStatus>("/api/apps/samba/status"),
  sambaUsers: () => request<SambaUser[]>("/api/apps/samba/users"),
  sambaPreview: (config: SambaConfig) => request<{ config: string; validation: SambaValidation }>("/api/apps/samba/preview", { method: "POST", body: JSON.stringify({ config }) }),
  sambaApply: (config: SambaConfig, confirm_smb1 = false) => request<{ job: ModuleJob }>("/api/apps/samba/apply", { method: "POST", body: JSON.stringify({ config, confirm_smb1 }) }),
  sambaRollback: () => request("/api/apps/samba/rollback", { method: "POST", body: "{}" }),
  sambaService: (action: "start" | "stop" | "restart" | "reload") => request<{ ok: boolean; status: SambaStatus }>("/api/apps/samba/service", { method: "POST", body: JSON.stringify({ action }) }),
  enableSambaUser: (username: string, password: string) => request("/api/apps/samba/users/enable", { method: "POST", body: JSON.stringify({ username, password }) }),
  disableSambaUser: (username: string) => request("/api/apps/samba/users/disable", { method: "POST", body: JSON.stringify({ username }) })
} as const;
