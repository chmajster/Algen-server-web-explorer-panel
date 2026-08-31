import { request } from "../../../core/api/transport";

export type NtpHealth = "healthy" | "degraded" | "unsynchronized" | "unavailable";

export type NtpStatus = {
  backend: string;
  available: boolean;
  synchronized: boolean;
  timezone: string;
  system_time: number;
  source: string;
  offset: string;
  offset_seconds?: number | null;
  stratum: number | null;
  reachability: string;
  jitter: string;
  root_delay?: string;
  root_dispersion?: string;
  frequency?: string;
  leap_status?: string;
  service: string;
  service_state: string;
  enabled: boolean;
};

export type NtpSource = {
  server: string;
  selected?: boolean;
  state?: string;
  state_code?: string;
  mode?: string;
  reference?: string;
  address?: string;
  stratum?: number;
  poll?: number;
  reach?: number;
  last_rx?: string;
  delay?: string;
  offset?: string;
  jitter?: string;
  uncertainty?: string;
  std_dev?: string;
  enabled?: boolean;
};

export type NtpDiagnostics = NtpStatus & {
  health: NtpHealth;
  metrics: Record<string, string | number | null>;
  sources: NtpSource[];
  summary: {
    source_count: number;
    selected_count: number;
    reachable_count: number;
  };
  warnings: string[];
  collected_at: number;
};

export const ntpManagerClient = {
  dashboard: () => request<NtpDiagnostics>("/api/modules/ntp-manager/dashboard"),
  sources: () => request<{ items: NtpSource[] }>("/api/modules/ntp-manager/sources"),
  add: (server: string) =>
    request("/api/modules/ntp-manager/sources", {
      method: "POST",
      body: JSON.stringify({ server, confirm: true }),
    }),
  remove: (server: string) =>
    request(`/api/modules/ntp-manager/sources/${encodeURIComponent(server)}?confirm=true`, {
      method: "DELETE",
    }),
  test: (server: string) =>
    request<{ server: string; ok: boolean; addresses: string[]; dns_ms: number }>(
      "/api/modules/ntp-manager/sources/test",
      {
        method: "POST",
        body: JSON.stringify({ server }),
      },
    ),
  resync: () => request<{ id: string }>("/api/modules/ntp-manager/resync", { method: "POST" }),
  service: (action: string) =>
    request("/api/modules/ntp-manager/service", {
      method: "POST",
      body: JSON.stringify({ action, confirm: true }),
    }),
} as const;
