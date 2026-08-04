import { request } from "../../../core/api/transport";
import type { AppJob, PackageHistoryItem, PackageModule, PackagePlan, PackageSource, SambaConfig, StorePlugin } from "../../../core/api/contracts";

export const packageCenterClient = {
  apps: (params: Record<string, string | boolean> = {}) => { const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => value !== "" && query.set(key, String(value))); return request<PackageModule[]>(`/api/apps${query.size ? `?${query}` : ""}`); },
  app: (id: string) => request<PackageModule>(`/api/apps/${encodeURIComponent(id)}`),
  appCategories: () => request<string[]>("/api/apps/categories"),
  appInstalled: () => request<PackageModule[]>("/api/apps/installed"),
  appUpdates: () => request<PackageModule[]>("/api/apps/updates"),
  appPlan: (id: string, action: PackagePlan["action"], remove_data = false) => request<PackagePlan>(`/api/apps/${encodeURIComponent(id)}/plan?action=${encodeURIComponent(action)}&remove_data=${remove_data}`, { method: "POST", body: "{}" }),
  appJobs: (status = "", moduleId = "") => { const query = new URLSearchParams(); if (status) query.set("status", status); if (moduleId) query.set("module_id", moduleId); return request<AppJob[]>(`/api/apps/jobs${query.size ? `?${query}` : ""}`); },
  appJob: (id: string) => request<AppJob>(`/api/apps/jobs/${encodeURIComponent(id)}`),
  cancelAppJob: (id: string) => request<AppJob>(`/api/apps/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", body: JSON.stringify({ confirm_plan: true }) }),
  retryAppJob: (id: string) => request<AppJob>(`/api/apps/jobs/${encodeURIComponent(id)}/retry`, { method: "POST", body: JSON.stringify({ confirm_plan: true }) }),
  appHistory: () => request<PackageHistoryItem[]>("/api/apps/history"),
  packageSources: () => request<PackageSource[]>("/api/apps/sources"),
  createPackageSource: (payload: Omit<PackageSource, "id" | "created_at" | "updated_at" | "last_sync_at" | "validation_error" | "metadata">) => request<PackageSource>("/api/apps/sources", { method: "POST", body: JSON.stringify(payload) }),
  updatePackageSource: (id: string, payload: Omit<PackageSource, "id" | "created_at" | "updated_at" | "last_sync_at" | "validation_error" | "metadata">) => request<PackageSource>(`/api/apps/sources/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),
  deletePackageSource: (id: string) => request(`/api/apps/sources/${encodeURIComponent(id)}`, { method: "DELETE", body: "{}" }),
  syncPackageSource: (id: string) => request<PackageSource>(`/api/apps/sources/${encodeURIComponent(id)}/sync`, { method: "POST", body: "{}" }),
  appAction: (id: string, action: "install" | "reinstall" | "uninstall" | "update" | "start" | "stop" | "restart", remove_data = false) => request<{ job?: AppJob; ok?: boolean }>(`/api/apps/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify({ confirm_plan: true, remove_data }) }),
  appLogs: (id: string) => request<{ lines: string[] }>(`/api/apps/${encodeURIComponent(id)}/logs`),
  appConfig: (id: string) => request<SambaConfig>(`/api/apps/${encodeURIComponent(id)}/config`),
  storePlugins: () => request<{ plugins: StorePlugin[]; codex_template: string }>("/api/apps/plugins"),
  createStorePlugin: (plugin: Partial<StorePlugin>) => request<StorePlugin>("/api/apps/plugins", { method: "POST", body: JSON.stringify(plugin) }),
  updateStorePlugin: (id: string, plugin: Partial<StorePlugin>) => request<StorePlugin>(`/api/apps/plugins/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(plugin) }),
  deleteStorePlugin: (id: string) => request(`/api/apps/plugins/${encodeURIComponent(id)}`, { method: "DELETE" })
} as const;
