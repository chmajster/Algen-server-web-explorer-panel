import { request } from "../../../core/api/transport";

export type DirectoryType = "ldap" | "active_directory" | "freeipa" | "generic";
export type SecurityMode = "ldap" | "starttls" | "ldaps";

export type LdapServer = { host: string; port: number; priority: number };
export type LdapConnection = {
  id: string;
  name: string;
  directory_type: DirectoryType;
  servers: LdapServer[];
  security_mode: SecurityMode;
  verify_tls: boolean;
  ca_certificate: string;
  base_dn: string;
  bind_dn: string;
  bind_password_configured: boolean;
  connect_timeout: number;
  operation_timeout: number;
};

export type LdapEntry = { dn: string; attributes: Record<string, unknown> };
export type Page = { items: LdapEntry[]; count: number; cookie: string; endpoint?: string };
export type Overview = {
  connection: LdapConnection;
  status: string;
  primary_server: string;
  latency_ms: number | null;
  users: number | null;
  groups: number | null;
  organizational_units: number | null;
  disabled_users: number | null;
  locked_users: number | null;
  password_expired_users: number | null;
  capabilities: Record<string, boolean>;
};

export type ConnectionPayload = Omit<LdapConnection, "id" | "bind_password_configured"> & {
  bind_password?: string;
  clear_bind_password?: boolean;
};

const base = "/api/modules/ldap-manager";
const json = (value: unknown) => JSON.stringify(value);

export const ldapManagerClient = {
  connections: () => request<{ items: LdapConnection[] }>(`${base}/connections`),
  createConnection: (payload: ConnectionPayload) => request<LdapConnection>(`${base}/connections`, { method: "POST", body: json(payload) }),
  updateConnection: (id: string, payload: ConnectionPayload) => request<LdapConnection>(`${base}/connections/${encodeURIComponent(id)}`, { method: "PUT", body: json(payload) }),
  deleteConnection: (id: string) => request(`${base}/connections/${encodeURIComponent(id)}`, { method: "DELETE" }),
  overview: (id: string) => request<Overview>(`${base}/connections/${encodeURIComponent(id)}/overview`),
  users: (id: string, search = "") => request<Page>(`${base}/connections/${encodeURIComponent(id)}/users?search=${encodeURIComponent(search)}`),
  groups: (id: string, search = "") => request<Page>(`${base}/connections/${encodeURIComponent(id)}/groups?search=${encodeURIComponent(search)}`),
  ous: (id: string) => request<Page>(`${base}/connections/${encodeURIComponent(id)}/ous`),
  entry: (id: string, dn: string) => request<LdapEntry>(`${base}/connections/${encodeURIComponent(id)}/directory?dn=${encodeURIComponent(dn)}`),
  search: (id: string, payload: Record<string, unknown>) => request<Page>(`${base}/connections/${encodeURIComponent(id)}/search`, { method: "POST", body: json(payload) }),
  createUser: (id: string, payload: Record<string, unknown>) => request<LdapEntry>(`${base}/connections/${encodeURIComponent(id)}/users`, { method: "POST", body: json(payload) }),
  createGroup: (id: string, payload: Record<string, unknown>) => request<LdapEntry>(`${base}/connections/${encodeURIComponent(id)}/groups`, { method: "POST", body: json(payload) }),
  createOu: (id: string, payload: Record<string, unknown>) => request<LdapEntry>(`${base}/connections/${encodeURIComponent(id)}/ous`, { method: "POST", body: json(payload) }),
  deleteUser: (id: string, dn: string) => request(`${base}/connections/${encodeURIComponent(id)}/users?dn=${encodeURIComponent(dn)}`, { method: "DELETE" }),
  deleteGroup: (id: string, dn: string) => request(`${base}/connections/${encodeURIComponent(id)}/groups?dn=${encodeURIComponent(dn)}`, { method: "DELETE" }),
  deleteOu: (id: string, dn: string) => request(`${base}/connections/${encodeURIComponent(id)}/ous?dn=${encodeURIComponent(dn)}`, { method: "DELETE" }),
  addMember: (id: string, groupDn: string, memberDn: string) => request(`${base}/connections/${encodeURIComponent(id)}/groups/members?group_dn=${encodeURIComponent(groupDn)}`, { method: "POST", body: json({ member_dn: memberDn }) }),
  removeMember: (id: string, groupDn: string, memberDn: string) => request(`${base}/connections/${encodeURIComponent(id)}/groups/members?group_dn=${encodeURIComponent(groupDn)}&member_dn=${encodeURIComponent(memberDn)}`, { method: "DELETE" }),
  resetPassword: (id: string, dn: string, password: string, forceChange: boolean) => request(`${base}/connections/${encodeURIComponent(id)}/users/password-reset?dn=${encodeURIComponent(dn)}`, { method: "POST", body: json({ new_password: password, force_change: forceChange }) }),
  diagnostics: (id: string) => request<Record<string, unknown>>(`${base}/connections/${encodeURIComponent(id)}/diagnostics`),
  schema: (id: string) => request<Record<string, unknown>>(`${base}/connections/${encodeURIComponent(id)}/schema`),
  importCsv: (id: string, csvText: string, dryRun: boolean) => request<Record<string, unknown>>(`${base}/connections/${encodeURIComponent(id)}/import/csv`, { method: "POST", body: json({ csv_text: csvText, dry_run: dryRun }) }),
  bulk: (id: string, payload: Record<string, unknown>) => request<Record<string, unknown>>(`${base}/connections/${encodeURIComponent(id)}/bulk`, { method: "POST", body: json(payload) }),
};
