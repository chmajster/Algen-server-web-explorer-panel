import { request } from "../../../core/api/transport";

export type SecretType =
  | "username_password"
  | "ssh_password"
  | "ssh_private_key"
  | "become_password"
  | "api_token"
  | "generic_secret"
  | "proxmox_api"
  | "redfish"
  | "ipmi"
  | "git_private_key"
  | "wol";

export type SecretUsage = {
  module: string;
  resource: string;
  resource_id?: string;
  name?: string;
  role?: string;
  count: number;
};

export type SecretItem = {
  id: string;
  name: string;
  type: SecretType;
  username: string;
  description: string;
  environment_id: string | null;
  shared_with: string[];
  secret_configured: boolean;
  passphrase_configured: boolean;
  active: boolean;
  created_at: number;
  updated_at: number;
  usage_count: number;
  usage: SecretUsage[];
};

export type SecretInput = {
  name: string;
  type: SecretType;
  username: string;
  secret: string;
  passphrase: string;
  description: string;
  environment_id: string | null;
  shared_with: string[];
  confirm: boolean;
};

export type SecretAuditItem = {
  id: string;
  secret_id: string;
  action: string;
  consumer_module: string;
  purpose: string;
  actor: string;
  details: Record<string, unknown>;
  created_at: number;
};

export const secretsManagerClient = {
  status: () => request<{ status: string; authoritative: boolean; secrets: number; migration_completed: boolean; migration_error: string }>("/api/modules/secrets-manager/status"),
  types: () => request<{ types: SecretType[] }>("/api/modules/secrets-manager/types"),
  shareTargets: () => request<{ modules: Array<{ id: string; name: string }> }>("/api/modules/secrets-manager/share-targets"),
  secrets: () => request<SecretItem[]>("/api/modules/secrets-manager/secrets"),
  create: (payload: SecretInput) => request<SecretItem>("/api/modules/secrets-manager/secrets", { method: "POST", body: JSON.stringify(payload) }),
  update: (id: string, payload: SecretInput) => request<SecretItem>(`/api/modules/secrets-manager/secrets/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),
  remove: (id: string) => request<{ ok: boolean }>(`/api/modules/secrets-manager/secrets/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),
  audit: (secretId = "") => request<{ items: SecretAuditItem[] }>(`/api/modules/secrets-manager/audit${secretId ? `?secret_id=${encodeURIComponent(secretId)}` : ""}`),
} as const;
