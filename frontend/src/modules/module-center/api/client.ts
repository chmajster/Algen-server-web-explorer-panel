import { request } from "../../../core/api/transport";
import type { ModuleBackup, ModuleConfig, ModuleConnection, ModuleDiagnostic, ModuleJob, ModuleLogSource, ModuleResource, ModuleStatus, ModuleSummary, ModuleValidationResult } from "../../../core/api/contracts";

export const moduleCenterClient = {
  modules: () => request<ModuleSummary[]>("/api/modules"),
  module: (id: string) => request<ModuleSummary>(`/api/modules/${encodeURIComponent(id)}`),
  moduleStatus: (id: string) => request<ModuleStatus>(`/api/modules/${encodeURIComponent(id)}/status`),
  moduleResource: (id: string, resource: string, limit = 200, search = "") => request<ModuleResource>(`/api/modules/${encodeURIComponent(id)}/resources/${encodeURIComponent(resource)}?limit=${limit}&search=${encodeURIComponent(search)}`),
  moduleAction: (id: string, action: string, payload: Record<string, unknown> = {}) => request<{ job: ModuleJob }>(`/api/modules/${encodeURIComponent(id)}/actions/${encodeURIComponent(action)}`, { method: "POST", body: JSON.stringify({ confirm: true, payload }) }),
  moduleConnection: (id: string) => request<ModuleConnection>(`/api/modules/${encodeURIComponent(id)}/connection`),
  saveModuleConnection: (id: string, connection: Omit<ModuleConnection, "secret_configured"> & { secret?: string }) => request<ModuleConnection>(`/api/modules/${encodeURIComponent(id)}/connection`, { method: "PUT", body: JSON.stringify({ ...connection, confirm: true }) }),
  saveDockerCompose: (project: string, content: string) => request<{ name: string; updated_at: number; size: number }>(`/api/modules/docker/compose/${encodeURIComponent(project)}`, { method: "PUT", body: JSON.stringify({ content, confirm: true }) }),
  dockerCompose: (project: string) => request<{ name: string; content: string; updated_at: number; size: number }>(`/api/modules/docker/compose/${encodeURIComponent(project)}`),
  moduleConfig: (id: string) => request<ModuleConfig>(`/api/modules/${encodeURIComponent(id)}/config`),
  validateModuleConfig: (id: string, config: ModuleConfig) => request<ModuleValidationResult>(`/api/modules/${encodeURIComponent(id)}/validate`, { method: "POST", body: JSON.stringify({ config }) }),
  applyModuleConfig: (id: string, config: ModuleConfig, confirmations: string[] = []) => request<{ job: ModuleJob }>(`/api/modules/${encodeURIComponent(id)}/apply`, { method: "POST", body: JSON.stringify({ config, confirm: true, create_backup: true, confirm_smb1: confirmations.includes("smb1") }) }),
  moduleLogs: (id: string, source = "", lines = 200, search = "", level = "") => { const query = new URLSearchParams({ source, lines: String(lines), search, level }); return request<{ sources: ModuleLogSource[]; source: string; lines: string[]; truncated: boolean }>(`/api/modules/${encodeURIComponent(id)}/logs?${query}`); },
  moduleDiagnostics: (id: string) => request<{ diagnostics: ModuleDiagnostic[]; job?: ModuleJob | null }>(`/api/modules/${encodeURIComponent(id)}/diagnostics`),
  runModuleDiagnostics: (id: string) => request<{ job: ModuleJob }>(`/api/modules/${encodeURIComponent(id)}/diagnostics`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  moduleBackups: (id: string) => request<ModuleBackup[]>(`/api/modules/${encodeURIComponent(id)}/backups`),
  createModuleBackup: (id: string, description = "") => request<ModuleBackup>(`/api/modules/${encodeURIComponent(id)}/backups`, { method: "POST", body: JSON.stringify({ confirm: true, description }) }),
  restoreModuleBackup: (id: string, backupId: string) => request<{ job: ModuleJob }>(`/api/modules/${encodeURIComponent(id)}/backups/${encodeURIComponent(backupId)}/restore`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  deleteModuleBackup: (id: string, backupId: string) => request(`/api/modules/${encodeURIComponent(id)}/backups/${encodeURIComponent(backupId)}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),
  moduleService: (id: string, action: "start" | "stop" | "restart" | "reload" | "enable" | "disable") => request<{ job: ModuleJob }>(`/api/modules/${encodeURIComponent(id)}/service/${action}`, { method: "POST", body: JSON.stringify({ confirm: true }) })
} as const;
