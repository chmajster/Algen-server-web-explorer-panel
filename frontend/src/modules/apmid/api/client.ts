import { request } from "../../../core/api/transport";
import type { AdminUser, ApmidBackup, ApmidDashboard, ApmidHistory, ApmidItem, ApmidMember, ApmidResourcePermission, ApmidRole } from "../../../core/api/contracts";

export const apmidClient = {
  apmidAccess: () => request<{ installed: boolean; allowed: boolean }>("/api/modules/apmid/access"),
  apmidDashboard: () => request<ApmidDashboard>("/api/modules/apmid/dashboard"),
  apmidItems: (params: { page?: number; page_size?: number; search?: string; status?: string; sort?: string; direction?: string } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => value !== undefined && value !== "" && query.set(key, String(value)));
    return request<{ items: ApmidItem[]; page: number; page_size: number; total: number }>(`/api/modules/apmid/items?${query}`);
  },
  apmidItem: (id: string) => request<ApmidItem>(`/api/modules/apmid/items/${encodeURIComponent(id)}`),
  saveApmidItem: (payload: Pick<ApmidItem, "code" | "name" | "description" | "active" | "business_owner">, id = "") => request<ApmidItem>(id ? `/api/modules/apmid/items/${encodeURIComponent(id)}` : "/api/modules/apmid/items", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  deleteApmidItem: (id: string) => request<{ ok: boolean }>(`/api/modules/apmid/items/${encodeURIComponent(id)}`, { method: "DELETE" }),
  apmidMembers: (id: string) => request<ApmidMember[]>(`/api/modules/apmid/items/${encodeURIComponent(id)}/members`),
  apmidUsers: (search = "") => request<AdminUser[]>(`/api/modules/apmid/users?search=${encodeURIComponent(search)}`),
  addApmidMembers: (id: string, usernames: string[], role: ApmidRole) => request<ApmidMember[]>(`/api/modules/apmid/items/${encodeURIComponent(id)}/members`, { method: "POST", body: JSON.stringify({ usernames, role }) }),
  updateApmidMember: (id: string, username: string, role: ApmidRole) => request<ApmidMember[]>(`/api/modules/apmid/items/${encodeURIComponent(id)}/members/${encodeURIComponent(username)}`, { method: "PUT", body: JSON.stringify({ role }) }),
  deleteApmidMember: (id: string, username: string) => request<{ ok: boolean }>(`/api/modules/apmid/items/${encodeURIComponent(id)}/members/${encodeURIComponent(username)}`, { method: "DELETE" }),
  apmidPermissions: (id: string) => request<Array<ApmidMember["permissions"]>>(`/api/modules/apmid/items/${encodeURIComponent(id)}/permissions`),
  updateApmidPermissions: (id: string, username: string, allow: ApmidResourcePermission[], deny: ApmidResourcePermission[]) => request<ApmidMember["permissions"]>(`/api/modules/apmid/items/${encodeURIComponent(id)}/members/${encodeURIComponent(username)}/permissions`, { method: "PUT", body: JSON.stringify({ allow, deny }) }),
  resetApmidPermissions: (id: string, username: string) => request<ApmidMember["permissions"]>(`/api/modules/apmid/items/${encodeURIComponent(id)}/members/${encodeURIComponent(username)}/permissions`, { method: "DELETE" }),
  apmidItemHistory: (id: string) => request<ApmidHistory[]>(`/api/modules/apmid/items/${encodeURIComponent(id)}/history`),
  apmidItemRelations: (id: string) => request<Array<{ module: string; resource: string; count: number }>>(`/api/modules/apmid/items/${encodeURIComponent(id)}/relations`),
  apmidHistory: () => request<ApmidHistory[]>("/api/modules/apmid/history"),
  apmidBackups: () => request<ApmidBackup[]>("/api/modules/apmid/backups"),
  createApmidBackup: (description = "") => request<ApmidBackup>("/api/modules/apmid/backups", { method: "POST", body: JSON.stringify({ description }) }),
  restoreApmidBackup: (id: string, confirmation: string) => request<{ ok: boolean; backup_id: string; safety_backup: string }>(`/api/modules/apmid/backups/${encodeURIComponent(id)}/restore`, { method: "POST", body: JSON.stringify({ confirmation }) })
} as const;
