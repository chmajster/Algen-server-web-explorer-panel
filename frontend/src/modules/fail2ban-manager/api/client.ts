import { request } from "../../../core/api/transport";

export type Fail2BanJail = {
  name: string;
  enabled: boolean;
  status: string;
  filter: string;
  backend: string;
  port: string;
  maxretry: number | null;
  findtime: string;
  bantime: string;
  action: string;
  banned_count: number;
  total_banned: number;
  banned_ips: string[];
};

export type Fail2BanStatus = {
  installed: boolean;
  client_available: boolean;
  version: string;
  service_active: boolean;
  service_enabled: boolean;
  responding: boolean;
  active_jails: number;
  currently_banned: number;
  total_banned: number;
  jails: Fail2BanJail[];
};

export type JailConfigInput = {
  enabled: boolean;
  filter: string;
  backend: string;
  port: string;
  maxretry: number | null;
  findtime: string;
  bantime: string;
  action: string;
  confirm: boolean;
};

export const fail2banManagerClient = {
  dashboard: () => request<Fail2BanStatus>("/api/modules/fail2ban-manager/dashboard"),
  jails: () => request<{ items: Fail2BanJail[] }>("/api/modules/fail2ban-manager/jails"),
  config: (jail: string) => request<{ jail: string; path: string; managed: boolean; content: string }>(`/api/modules/fail2ban-manager/jails/${encodeURIComponent(jail)}/config`),
  saveConfig: (jail: string, payload: JailConfigInput) => request<{ ok: boolean }>(`/api/modules/fail2ban-manager/jails/${encodeURIComponent(jail)}/config`, { method: "PUT", body: JSON.stringify(payload) }),
  setEnabled: (jail: string, enabled: boolean) => request<{ ok: boolean }>(`/api/modules/fail2ban-manager/jails/${encodeURIComponent(jail)}/enabled`, { method: "PUT", body: JSON.stringify({ enabled, confirm: true }) }),
  ban: (jail: string, ip: string) => request<{ ok: boolean; ip: string }>(`/api/modules/fail2ban-manager/jails/${encodeURIComponent(jail)}/ban`, { method: "POST", body: JSON.stringify({ ip, confirm: true }) }),
  unban: (jail: string, ip: string) => request<{ ok: boolean; ip: string }>(`/api/modules/fail2ban-manager/jails/${encodeURIComponent(jail)}/unban`, { method: "POST", body: JSON.stringify({ ip, confirm: true }) }),
  reload: () => request<{ ok: boolean }>("/api/modules/fail2ban-manager/reload", { method: "POST", body: JSON.stringify({ confirm: true }) }),
  restart: () => request<{ ok: boolean }>("/api/modules/fail2ban-manager/restart", { method: "POST", body: JSON.stringify({ confirm: true }) }),
  logs: (params: { limit?: number; query?: string; jail?: string; ip?: string; action?: string } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => value !== undefined && value !== "" && query.set(key, String(value)));
    return request<{ items: Array<{ timestamp: string; message: string }> }>(`/api/modules/fail2ban-manager/logs?${query}`);
  },
} as const;
