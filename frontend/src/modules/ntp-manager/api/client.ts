import { request } from "../../../core/api/transport";

export type NtpHealth = "healthy" | "degraded" | "unsynchronized" | "unavailable";
export type NtpMode = "disabled" | "client" | "server" | "client_server";
export type NtpSourceKind = "server" | "pool";

export type NtpStatus = {
  backend: string;
  available: boolean;
  role: NtpMode;
  synchronized: boolean;
  timezone: string;
  system_time: number;
  local_time?: string;
  rtc_time?: string;
  rtc_local_tz?: boolean;
  ntp_service_enabled?: boolean;
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
  last_sync?: string;
  service: string;
  service_state: string;
  enabled: boolean;
  source_count?: number;
  unmanaged_config_detected?: boolean;
};

export type NtpSource = {
  server: string;
  kind?: NtpSourceKind;
  prefer?: boolean;
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

export type NtpAllowedNetwork = {
  cidr: string;
  description: string;
  enabled: boolean;
};

export type NtpConfiguration = {
  mode: NtpMode;
  sources: NtpSource[];
  allowed_networks: NtpAllowedNetwork[];
  local_time_when_unsynced: boolean;
  local_stratum: number;
  backend: string;
  managed_path: string;
  unmanaged_config_detected: boolean;
};

export type NtpClient = {
  address: string;
  hostname: string;
  ntp_requests: number;
  dropped: number;
  last_activity: string;
};

export type NtpFirewall = {
  backend: string;
  status: "open" | "blocked" | "unknown";
  managed_by_webnas: boolean;
};

export type NtpDiagnosticCheck = {
  code: string;
  status: "PASS" | "WARNING" | "FAIL";
  detail: string;
};

export type NtpHistory = {
  timestamp: number;
  server: string;
  stratum: number | null;
  offset: string;
  synchronized: boolean;
};

export type NtpBackup = {
  id: string;
  timestamp: number;
  actor: string;
  change: string;
  path: string;
  existed: boolean;
};

export type NtpDiagnostics = NtpStatus & {
  health: NtpHealth;
  metrics: Record<string, string | number | null>;
  sources: NtpSource[];
  summary: {
    source_count: number;
    selected_count: number;
    reachable_count: number;
    client_count?: number;
  };
  firewall?: NtpFirewall;
  warnings: string[];
  collected_at: number;
  checks?: NtpDiagnosticCheck[];
};

export const ntpManagerClient = {
  dashboard: () => request<NtpDiagnostics>("/api/modules/ntp-manager/dashboard"),
  status: () => request<NtpStatus>("/api/modules/ntp-manager/status"),
  config: () => request<NtpConfiguration>("/api/modules/ntp-manager/config"),
  validateConfig: (configuration: Omit<NtpConfiguration, "backend" | "managed_path" | "unmanaged_config_detected">) =>
    request("/api/modules/ntp-manager/config/validate", {
      method: "POST",
      body: JSON.stringify(configuration),
    }),
  saveConfig: (configuration: Omit<NtpConfiguration, "backend" | "managed_path" | "unmanaged_config_detected">) =>
    request("/api/modules/ntp-manager/config", {
      method: "PUT",
      body: JSON.stringify({ configuration, confirm: true }),
    }),
  sources: () => request<{ items: NtpSource[] }>("/api/modules/ntp-manager/sources"),
  add: (server: string, kind: NtpSourceKind = "server", prefer = false) =>
    request("/api/modules/ntp-manager/sources", {
      method: "POST",
      body: JSON.stringify({ server, kind, prefer, enabled: true, confirm: true }),
    }),
  update: (original: string, source: NtpSource) =>
    request(`/api/modules/ntp-manager/sources/${encodeURIComponent(original)}`, {
      method: "PUT",
      body: JSON.stringify({
        server: source.server,
        kind: source.kind || "server",
        prefer: Boolean(source.prefer),
        enabled: source.enabled !== false,
        confirm: true,
      }),
    }),
  remove: (server: string) =>
    request(`/api/modules/ntp-manager/sources/${encodeURIComponent(server)}?confirm=true`, {
      method: "DELETE",
    }),
  test: (server: string) =>
    request<{ server: string; ok: boolean; address?: string; stratum: number | null; offset_ms: number | null; delay_ms: number; status: string }>(
      "/api/modules/ntp-manager/test",
      { method: "POST", body: JSON.stringify({ server }) },
    ),
  clients: () => request<{ items: NtpClient[]; total: number }>("/api/modules/ntp-manager/clients"),
  sync: () => request<{ id: string }>("/api/modules/ntp-manager/sync", { method: "POST" }),
  resync: () => request<{ id: string }>("/api/modules/ntp-manager/sync", { method: "POST" }),
  service: (action: "start" | "stop" | "restart") =>
    request("/api/modules/ntp-manager/service", {
      method: "POST",
      body: JSON.stringify({ action, confirm: true }),
    }),
  timezones: (search = "") =>
    request<{ items: string[]; total: number }>(`/api/modules/ntp-manager/timezones?search=${encodeURIComponent(search)}`),
  setTimezone: (timezone: string) =>
    request("/api/modules/ntp-manager/timezone", {
      method: "PUT",
      body: JSON.stringify({ timezone, confirm: true }),
    }),
  diagnostics: () => request<NtpDiagnostics>("/api/modules/ntp-manager/diagnostics"),
  firewall: () => request<NtpFirewall>("/api/modules/ntp-manager/firewall"),
  openFirewall: () => request<NtpFirewall>("/api/modules/ntp-manager/firewall/open", {
    method: "POST",
    body: JSON.stringify({ confirm: true }),
  }),
  backups: () => request<{ items: NtpBackup[] }>("/api/modules/ntp-manager/backups"),
  restoreBackup: (id: string) => request(`/api/modules/ntp-manager/backups/${encodeURIComponent(id)}/restore`, {
    method: "POST",
    body: JSON.stringify({ confirm: true }),
  }),
  history: (limit = 200) => request<{ items: NtpHistory[]; total: number }>(`/api/modules/ntp-manager/history?limit=${limit}`),
  installChrony: () => request<{ installed: boolean; backend: string }>("/api/modules/ntp-manager/chrony/install", { method: "POST" }),
} as const;
