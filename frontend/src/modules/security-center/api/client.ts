import { request } from "../../../core/api/transport";

export type Severity = "critical" | "high" | "medium" | "low" | "info" | "passed";
export type Finding = { id: string; check_id: string; severity: Severity; title: string; description: string; affected_resource: string; detection_source: string; recommendation: string; timestamp: number; status: "open" | "acknowledged" | "resolved"; category: string };
export type Summary = { score: number; findings: number; last_scan: number | null; severity: Record<string, number>; areas: Record<string, { score: number; findings: number; critical: number; high: number }>; metrics: Record<string, Record<string, unknown>> };
export const securityClient = {
  summary: () => request<Summary>("/api/modules/security-center/summary"),
  findings: () => request<{ items: Finding[]; total: number }>("/api/modules/security-center/findings"),
  scan: () => request("/api/modules/security-center/scan", { method: "POST", body: "{}" }),
  setState: (id: string, status: Finding["status"]) => request(`/api/modules/security-center/findings/${encodeURIComponent(id)}/state`, { method: "POST", body: JSON.stringify({ status }) }),
};
