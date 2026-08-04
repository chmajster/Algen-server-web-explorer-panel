import { request } from "../../../core/api/transport";
import type { Task } from "../../../core/api/contracts";

export const transfersClient = {
  tasks: (status?: string) => request<Task[]>(`/api/files/tasks${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  allTasks: (status?: string) => request<Task[]>(`/api/admin/transfers${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  task: (taskId: string) => request<Task>(`/api/files/tasks/${encodeURIComponent(taskId)}`),
  cancelTask: (taskId: string) => request(`/api/files/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST", body: "{}" }),
  pauseTask: (taskId: string) => request(`/api/files/tasks/${encodeURIComponent(taskId)}/pause`, { method: "POST", body: "{}" }),
  resumeTask: (taskId: string) => request(`/api/files/tasks/${encodeURIComponent(taskId)}/resume`, { method: "POST", body: "{}" }),
  retryTask: (taskId: string) => request<{ task_id: string }>(`/api/files/tasks/${encodeURIComponent(taskId)}/retry`, { method: "POST", body: "{}" }),
  setTaskPriority: (taskId: string, priority: number) => request(`/api/files/tasks/${encodeURIComponent(taskId)}/priority`, { method: "PATCH", body: JSON.stringify({ priority }) }),
} as const;
