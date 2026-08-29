import { request } from "../../../core/api/transport";

export type AlertSeverity = "info" | "warning" | "error" | "critical";
export type AlertState = "firing" | "acknowledged" | "resolved";
export type AlertSinkType = "webhook" | "ntfy" | "smtp";

export type AlertItem = {
  id: string;
  fingerprint: string;
  rule_id: string;
  source: string;
  event_key: string;
  title: string;
  object_ref: string;
  severity: AlertSeverity;
  state: AlertState;
  details: Record<string, unknown>;
  occurrences: number;
  first_seen_at: number;
  last_seen_at: number;
  last_notified_at: number | null;
  acknowledged_at: number | null;
  acknowledged_by: string;
  acknowledgement_note: string;
  resolved_at: number | null;
  resolved_by: string;
};

export type AlertDashboard = {
  alerts: Partial<Record<AlertState, number>>;
  pending_deliveries: number;
  failed_deliveries: number;
};

export type AlertRule = {
  id: string;
  name: string;
  source: string;
  severity: AlertSeverity;
  cooldown_seconds: number;
  enabled: boolean;
  matcher: Record<string, unknown>;
  sink_ids: string[];
  built_in: boolean;
  created_at: number;
  updated_at: number;
  updated_by: string;
};

export type AlertRuleInput = Pick<AlertRule, "name" | "source" | "severity" | "cooldown_seconds" | "enabled" | "matcher" | "sink_ids">;

export type AlertSink = {
  id: string;
  name: string;
  type: AlertSinkType;
  enabled: boolean;
  configured: boolean;
  created_at: number;
  updated_at: number;
  updated_by: string;
};

export type AlertSinkInput = {
  name: string;
  type: AlertSinkType;
  enabled: boolean;
  url?: string;
  token?: string;
  smtp_host?: string;
  smtp_port?: number;
  smtp_username?: string;
  smtp_password?: string;
  smtp_from?: string;
  smtp_to?: string[];
  smtp_starttls?: boolean;
};

export const alertsClient = {
  alertsDashboard: () => request<AlertDashboard>("/api/alerts/dashboard"),
  alertsList: (params: { state?: AlertState | ""; severity?: AlertSeverity | "" } = {}) => {
    const query = new URLSearchParams();
    if (params.state) query.set("state", params.state);
    if (params.severity) query.set("severity", params.severity);
    return request<AlertItem[]>(`/api/alerts${query.size ? `?${query}` : ""}`);
  },
  alertAcknowledge: (id: string, note = "") => request<AlertItem>(`/api/alerts/${encodeURIComponent(id)}/acknowledge`, { method: "POST", body: JSON.stringify({ note }) }),
  alertResolve: (id: string, note = "") => request<AlertItem>(`/api/alerts/${encodeURIComponent(id)}/resolve`, { method: "POST", body: JSON.stringify({ note }) }),
  alertRules: () => request<AlertRule[]>("/api/alerts/rules"),
  alertRuleCreate: (payload: AlertRuleInput) => request<AlertRule>("/api/alerts/rules", { method: "POST", body: JSON.stringify(payload) }),
  alertRuleUpdate: (id: string, payload: AlertRuleInput) => request<AlertRule>(`/api/alerts/rules/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),
  alertRuleDelete: (id: string) => request<{ ok: boolean }>(`/api/alerts/rules/${encodeURIComponent(id)}`, { method: "DELETE" }),
  alertSinks: () => request<AlertSink[]>("/api/alerts/sinks"),
  alertSinkCreate: (payload: AlertSinkInput) => request<AlertSink>("/api/alerts/sinks", { method: "POST", body: JSON.stringify(payload) }),
  alertSinkDelete: (id: string) => request<{ ok: boolean }>(`/api/alerts/sinks/${encodeURIComponent(id)}`, { method: "DELETE" }),
  alertSinkTest: (id: string) => request<{ ok: boolean; sink_id: string; diagnostic: Record<string, unknown> }>(`/api/alerts/sinks/${encodeURIComponent(id)}/test`, { method: "POST", body: JSON.stringify({ sink_id: id, diagnostic: { source: "ui", message: "Alert Manager test" } }) }),
} as const;
