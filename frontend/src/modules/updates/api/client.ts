import { request } from "../../../core/api/transport";
import type { AutoUpdateSettings, UpdateCompletionNotice, UpdateProgress, UpdateStart, UpdateStatus } from "../../../core/api/contracts";

export const updatesClient = {
  checkUpdates: () => request<UpdateStatus>("/api/admin/system/updates/check"),
  updateProgress: () => request<UpdateProgress>("/api/admin/system/updates/progress"),
  updatePublicProgress: () => request<UpdateProgress>("/api/system/update-status"),
  downloadUpdates: (update_config = false) => request<UpdateStart>("/api/admin/system/updates/download", { method: "POST", body: JSON.stringify({ update_config }) }),
  autoUpdate: () => request<AutoUpdateSettings>("/api/admin/system/updates/auto"),
  saveAutoUpdate: (payload: { check_enabled: boolean; enabled: boolean; interval_hours: number; update_config: boolean }) => request<AutoUpdateSettings>("/api/admin/system/updates/auto", { method: "PATCH", body: JSON.stringify(payload) }),
  runAutoUpdate: (update_config = false) => request<UpdateStart>("/api/admin/system/updates/auto/run", { method: "POST", body: JSON.stringify({ update_config }) }),
  updateCompletion: () => request<{ notice: UpdateCompletionNotice | null }>("/api/admin/system/updates/completion"),
  acknowledgeUpdateCompletion: (updateId: string) => request<{ ok: boolean; stale: boolean }>("/api/admin/system/updates/completion/acknowledge", { method: "POST", body: JSON.stringify({ update_id: updateId }) })
} as const;
