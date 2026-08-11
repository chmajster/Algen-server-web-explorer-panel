import { request } from "../../../core/api/transport";
import type { AppJob, CronDiagnostic, CronJob, CronJobInput, CronLogEntry, CronManagerStatus, CronValidation } from "../../../core/api/contracts";

type Confirmation = { confirmation: string; pam_password: string };

export const cronClient = {
  cronAccess: () => request<{ installed: boolean; allowed: boolean; blocked_by_proxmox: boolean }>("/api/modules/cron/access"),
  cronStatus: () => request<CronManagerStatus>("/api/modules/cron/status"),
  cronJobs: (params: { search?: string; username?: string; status?: string; include_external?: boolean } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => value !== undefined && value !== "" && query.set(key, String(value)));
    return request<{ items: CronJob[]; total: number }>(`/api/modules/cron/jobs?${query}`);
  },
  cronJob: (id: string) => request<CronJob>(`/api/modules/cron/jobs/${encodeURIComponent(id)}`),
  createCronJob: (job: CronJobInput, confirmation: Confirmation) => request<{ job: AppJob }>("/api/modules/cron/jobs", { method: "POST", body: JSON.stringify({ ...job, ...confirmation }) }),
  updateCronJob: (id: string, job: CronJobInput, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/cron/jobs/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ ...job, ...confirmation }) }),
  deleteCronJob: (id: string, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/cron/jobs/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify(confirmation) }),
  setCronJobEnabled: (id: string, enabled: boolean, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/cron/jobs/${encodeURIComponent(id)}/${enabled ? "enable" : "disable"}`, { method: "POST", body: JSON.stringify(confirmation) }),
  duplicateCronJob: (id: string, confirmation: Confirmation) => request<{ job: AppJob }>(`/api/modules/cron/jobs/${encodeURIComponent(id)}/duplicate`, { method: "POST", body: JSON.stringify(confirmation) }),
  validateCronJob: (job: Pick<CronJobInput, "schedule" | "user" | "command" | "working_directory" | "environment" | "timeout_seconds">) => request<CronValidation>("/api/modules/cron/validate", { method: "POST", body: JSON.stringify(job) }),
  cronDiagnostics: () => request<{ items: CronDiagnostic[] }>("/api/modules/cron/diagnostics"),
  cronLogs: (params: { source?: string; limit?: number; search?: string; username?: string; job_id?: string } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => value !== undefined && value !== "" && query.set(key, String(value)));
    return request<{ source: string; sources: Array<{ id: string; label: string }>; entries: CronLogEntry[]; truncated: boolean }>(`/api/modules/cron/logs?${query}`);
  },
  cronHistory: (id: string) => request<{ available: boolean; reason: string; entries: Array<{ id: number; job_id: string; action: string; actor: string; details: Record<string, unknown>; created_at: number }> }>(`/api/modules/cron/jobs/${encodeURIComponent(id)}/history`),
} as const;
