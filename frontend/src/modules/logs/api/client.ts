import { ApiError, request } from "../../../core/api/transport";
import type { LogBoot, LogContainer, LogEntriesResponse, LogEntry, LogQuery, LogSavedView, LogService, LogSourcesResponse, SystemLogs } from "../../../core/api/contracts";

export const logsClient = {
  systemLogs: (lines = 160) => request<SystemLogs>(`/api/admin/system/logs?lines=${lines}`),
  logSources: () => request<LogSourcesResponse>("/api/logs/sources"),
  logEntries: (params: LogQuery = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (Array.isArray(value)) value.forEach((item) => query.append(key, String(item)));
      else if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
    });
    return request<LogEntriesResponse>(`/api/logs/entries${query.size ? `?${query}` : ""}`, { signal });
  },
  logBoots: () => request<{ items: LogBoot[]; status: string; error?: string }>("/api/logs/boots"),
  logServices: () => request<{ items: LogService[]; status: string; error?: string }>("/api/logs/services"),
  logService: (unit: string) => request<LogService & { pid: number | null; started_at: string; entries: LogEntry[] }>(`/api/logs/services/${encodeURIComponent(unit)}`),
  logContainers: () => request<{ items: LogContainer[]; status: string; error?: string }>("/api/logs/containers"),
  logFields: () => request<{ items: string[] }>("/api/logs/fields"),
  logSavedViews: () => request<{ items: LogSavedView[] }>("/api/logs/saved-views"),
  createLogSavedView: (payload: Omit<LogSavedView, "id" | "builtin">) => request<LogSavedView>("/api/logs/saved-views", { method: "POST", body: JSON.stringify(payload) }),
  updateLogSavedView: (id: string, payload: Omit<LogSavedView, "id" | "builtin">) => request<LogSavedView>(`/api/logs/saved-views/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteLogSavedView: (id: string) => request<{ ok: boolean }>(`/api/logs/saved-views/${encodeURIComponent(id)}`, { method: "DELETE", body: "{}" }),
  exportLogs: async (payload: LogQuery & { format: "txt" | "json" | "jsonl" | "csv"; limit?: number }) => {
    const headers = new Headers({ "Content-Type": "application/json" });
    const res = await fetch("/api/logs/export", { method: "POST", body: JSON.stringify(payload), headers, credentials: "include" });
    if (!res.ok) {
      const body = await res.text();
      let message = body || res.statusText;
      try {
        const parsed = JSON.parse(body) as { detail?: string | { message?: string } };
        message = typeof parsed.detail === "string" ? parsed.detail : parsed.detail?.message || message;
      } catch { /* plain responses retain their original text */ }
      throw new ApiError(message, res.status);
    }
    const disposition = res.headers.get("content-disposition") || "";
    return { blob: await res.blob(), filename: disposition.match(/filename="([^"]+)"/)?.[1] || `webnas-logs.${payload.format}`, truncated: res.headers.get("x-webnas-truncated") === "true" };
  }
} as const;
