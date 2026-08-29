import { request } from "../../../core/api/transport";

export type Job = { id:string; type:string; module:string; name:string; description:string; status:string; priority:string; progress:number|null; current_step:string; created_at:number; started_at:number|null; finished_at:number|null; created_by:string; worker:string; retry_count:number; max_retries:number; result:Record<string,unknown>; error:string; message:string; cancellable:boolean; retryable:boolean; parent_job_id:string|null; correlation_id:string|null };
export type JobSummary = { running:number; queued:number; waiting:number; failed:number; completed_today:number; average_execution_seconds:number; workers:number };
export const jobQueueClient = {
  summary: () => request<JobSummary>("/api/jobs/summary"),
  list: (limit=200) => request<{items:Job[];total:number}>(`/api/jobs?limit=${limit}`),
  get: (id:string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}`),
  logs: (id:string) => request<{items:Array<{id:number;created_at:number;level:string;message:string;data:Record<string,unknown>}>}>(`/api/jobs/${encodeURIComponent(id)}/logs`),
  cancel: (id:string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}/cancel`, {method:"POST"}),
  retry: (id:string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}/retry`, {method:"POST"}),
  cleanup: (days=30) => request<{deleted:number}>(`/api/jobs/history?retention_days=${days}`, {method:"DELETE"}),
} as const;
