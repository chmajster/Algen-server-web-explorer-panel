import { request } from "../../../core/api/transport";

export type FirewallStatus = { backend: string; available_backends: string[]; active: boolean; detail: string; rules: number };
export type FirewallRule = { id: string; backend: string; action: string; direction: string; protocol: string; port: string; source: string; destination: string; interface: string; comment: string; family: string; enabled: boolean; editable: boolean };
export type ListeningPort = { protocol: string; state: string; address: string; port: number; peer: string; process: string; firewall_rule?: string | null };
export type Backup = { id: string; description: string; created_at: number; backend: string; rules: number };
export type RuleInput = { action: "allow" | "drop" | "reject"; direction: "in" | "out"; protocol: "any" | "tcp" | "udp"; port: string; source: string; destination: string; interface: string; comment: string; family: "any" | "ipv4" | "ipv6" };
export type Auth = { pam_password: string; confirmation: string; acknowledge_lockout: boolean };
const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });

export const firewallClient = {
  status: () => request<FirewallStatus>("/api/modules/firewall-manager/status"),
  rules: () => request<{ items: FirewallRule[]; total: number }>("/api/modules/firewall-manager/rules"),
  ports: () => request<{ items: ListeningPort[]; total: number }>("/api/modules/firewall-manager/listening-ports"),
  backups: () => request<{ items: Backup[] }>("/api/modules/firewall-manager/backups"),
  activity: () => request<{ items: Array<{ id: number; created_at: number; action: string; actor: string; status: string; summary: string }> }>("/api/modules/firewall-manager/activity"),
  createRule: (rule: RuleInput, auth: Auth) => request("/api/modules/firewall-manager/rules", json("POST", { rule, ...auth })),
  deleteRule: (id: string, auth: Auth) => request(`/api/modules/firewall-manager/rules/${encodeURIComponent(id)}`, json("DELETE", auth)),
  enable: (auth: Auth) => request("/api/modules/firewall-manager/enable", json("POST", auth)),
  disable: (auth: Auth) => request("/api/modules/firewall-manager/disable", json("POST", auth)),
  reload: (auth: Auth) => request("/api/modules/firewall-manager/reload", json("POST", auth)),
  backup: (description: string, auth: Auth) => request("/api/modules/firewall-manager/backups", json("POST", { description, ...auth })),
  restore: (id: string, auth: Auth) => request(`/api/modules/firewall-manager/backups/${encodeURIComponent(id)}/restore`, json("POST", auth)),
};
