import { request } from "../../../core/api/transport";
import type { SecretItem } from "../../secrets-manager/api/client";

export type WebhookItem = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  url: string;
  method: "POST" | "PUT" | "PATCH";
  events: string[];
  timeout_seconds: number;
  max_attempts: number;
  headers: Record<string, string>;
  auth_type: "none" | "bearer" | "basic" | "api_key_header" | "secret_header";
  secret_id: string | null;
  auth_header_name: string;
  signing_secret_id: string | null;
  allow_private_networks: boolean;
  created_at: number;
  updated_at: number;
};

export type WebhookInput = Omit<WebhookItem, "id" | "created_at" | "updated_at">;
export type DeliveryItem = {
  id: string;
  webhook_id: string;
  event_id: string;
  event_type: string;
  attempt: number;
  status: string;
  http_status: number | null;
  duration_ms: number;
  error_category: string;
  response_preview: string;
  created_at: number;
};

export const webhookManagerClient = {
  dashboard: () => request<{ enabled_webhooks: number; successful_deliveries_24h: number; failed_deliveries_24h: number; retry_deliveries_24h: number; deliveries_24h: number; queue_depth: number }>("/api/modules/webhook-manager/dashboard"),
  events: () => request<{ events: string[] }>("/api/modules/webhook-manager/events"),
  webhooks: () => request<{ items: WebhookItem[] }>("/api/modules/webhook-manager/webhooks"),
  create: (payload: WebhookInput) => request<WebhookItem>("/api/modules/webhook-manager/webhooks", { method: "POST", body: JSON.stringify(payload) }),
  update: (id: string, payload: WebhookInput) => request<WebhookItem>(`/api/modules/webhook-manager/webhooks/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),
  remove: (id: string) => request<{ ok: boolean }>(`/api/modules/webhook-manager/webhooks/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),
  setEnabled: (id: string, enabled: boolean) => request<WebhookItem>(`/api/modules/webhook-manager/webhooks/${encodeURIComponent(id)}/enabled?enabled=${enabled ? "true" : "false"}`, { method: "PUT", body: "{}" }),
  test: (id: string) => request<DeliveryItem>(`/api/modules/webhook-manager/webhooks/${encodeURIComponent(id)}/test`, { method: "POST", body: "{}" }),
  deliveries: (params: { webhook_id?: string; status?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => value !== undefined && value !== "" && query.set(key, String(value)));
    return request<{ items: DeliveryItem[] }>(`/api/modules/webhook-manager/deliveries?${query}`);
  },
  secrets: () => request<SecretItem[]>("/api/modules/webhook-manager/secret-choices"),
} as const;
