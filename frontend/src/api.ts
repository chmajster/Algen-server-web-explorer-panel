export type FileItem = {
  name: string;
  path: string;
  type: string;
  is_dir: boolean;
  size: number;
  owner: string;
  group: string;
  mode: string;
  permissions: string;
  modified: number;
  mtime: number;
  mime: string;
  can_read: boolean;
  can_write: boolean;
  can_delete: boolean;
  can_rename: boolean;
  is_symlink: boolean;
  target?: string | null;
};
export type FileListResponse = {
  path: string;
  current_path: string;
  parent_path: string | null;
  items: FileItem[];
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  sort: string | null;
  direction: "asc" | "desc";
  can_write: boolean;
  can_upload: boolean;
  can_delete: boolean;
};

export type Task = {
  id: string;
  type: string;
  op: string;
  status: "queued" | "running" | "paused" | "completed" | "failed" | "cancelled";
  priority: number;
  created_at: number;
  source_paths: string[];
  destination_path: string;
  started_at: number | null;
  finished_at: number | null;
  paused_at: number | null;
  bytes_transferred: number;
  total_bytes: number;
  progress_percent: number;
  progress: number;
  speed_bps: number;
  speed_human: string;
  average_speed_bps: number;
  average_speed_human: string;
  eta_seconds: number | null;
  eta_human: string;
  current_file: string;
  files_done: number;
  files_total: number;
  rsync_exit_code: number | null;
  error_message: string;
  log_tail: string[];
  stderr_tail: string[];
  command_preview: string[];
  retry_count: number;
  errors: string[];
};

export type SettingsMe = {
  username: string;
  uid: number;
  gid: number;
  groups: string[];
  home: string;
  shell: string;
  gecos: string;
  is_admin: boolean;
  language: "pl-PL" | "en-US";
  theme: "light" | "dark" | "system";
};

export type AdminUser = SettingsMe & { is_system: boolean; manageable: boolean };
export type AdminGroup = { name: string; gid: number; members: string[] };
export type SystemStatus = { service: string; version: string; port: number; data_dir: string; log_dir: string; temp_dir: string };
export type SystemLogs = { source: string; lines: string[] };
export type SystemdService = {
  name: string;
  status: string;
  sub_state: string;
  enabled: string;
  uptime_seconds: number | null;
  last_error: string;
  managed_by_webnas: boolean;
};
export type UsageMetric = { total: number; used: number; free: number; percent: number };
export type DiskMetric = UsageMetric & { path: string; device?: string; mountpoint?: string; fs_type?: string };
export type ResourceDashboard = {
  scope: "admin" | "user";
  timestamp: number;
  cpu_percent: number | null;
  ram: UsageMetric;
  swap: UsageMetric;
  allowed_roots: DiskMetric[];
  mountpoints: DiskMetric[];
  uptime_seconds: number | null;
  load_average: number[] | null;
  temperature_c: number | null;
  webnas_service: string | null;
  warnings: string[];
};
export type StoreApp = {
  id: string;
  manifest: {
    name: string;
    description: string;
    version: string;
    apt_packages?: string[];
    systemd_services?: string[];
    ports?: string[];
    proxmox_safe?: boolean;
  };
  state: { installed?: boolean; configured?: boolean; history?: unknown[]; config?: SambaConfig };
  services: Record<string, string>;
  status: string;
  jobs: Array<{ id: string; action: string; status: string; progress: number; log_tail: string[]; error: string }>;
};
export type SambaShare = {
  name: string;
  path: string;
  comment: string;
  enabled: boolean;
  browseable: boolean;
  read_only: boolean;
  guest_ok: boolean;
  valid_users: string[];
  force_user?: string | null;
  create_mask: string;
  directory_mask: string;
  allow_proxmox_storage?: boolean;
};
export type SambaConfig = { shares: SambaShare[] };
export type NetworkMount = {
  id: string;
  name: string;
  type: "smb" | "nfs" | "sshfs" | "webdav";
  host: string;
  remote: string;
  mount_point: string;
  owner: string;
  read_only: boolean;
  persistent: boolean;
  status: "mounted" | "unmounted" | "error" | "testing" | "mounting" | "unmounting";
  last_error: string;
  allowed_users: string[];
  allowed_groups: string[];
  config: Record<string, unknown>;
  fs: { total: number; used: number; free: number; fs_type: string } | null;
  jobs: Array<{ id: string; action: string; status: string; exit_code: number | null; error: string; log_tail: string[] }>;
};
export type NetworkMountPayload = {
  admin_password: string;
  name: string;
  type: NetworkMount["type"];
  host: string;
  share?: string;
  export_path?: string;
  remote_path?: string;
  mount_point?: string;
  username?: string;
  password?: string;
  domain?: string;
  smb_version?: string;
  nfs_version?: string;
  ssh_port?: number;
  ssh_auth?: "key" | "password";
  read_only?: boolean;
  persistent?: boolean;
  uid?: string;
  gid?: string;
  file_mode?: string;
  dir_mode?: string;
  noexec?: boolean;
  advanced_options?: string[];
  allowed_users?: string[];
  allowed_groups?: string[];
  force_empty_mountpoint?: boolean;
};
export type ProxmoxSafety = {
  is_proxmox: boolean;
  safe_mode_enabled: boolean;
  protected_paths: string[];
  blocked_admin_features: string[];
  allowed_roots_effective: string[];
  service_user: string;
  warnings: string[];
};

let csrfToken = localStorage.getItem("webnas_csrf") || "";

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (csrfToken && options.method && options.method !== "GET") headers.set("x-csrf-token", csrfToken);
  const res = await fetch(url, { ...options, headers, credentials: "include" });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function login(username: string, password: string) {
  const data = await request<{ username: string; home: string; csrf_token: string }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password })
  });
  csrfToken = data.csrf_token;
  localStorage.setItem("webnas_csrf", csrfToken);
  return data;
}

export async function me() {
  const data = await request<{ username: string; home: string; csrf_token: string }>("/api/auth/me");
  csrfToken = data.csrf_token;
  localStorage.setItem("webnas_csrf", csrfToken);
  return data;
}

export function logout() {
  return request("/api/auth/logout", { method: "POST", body: "{}" }).finally(() => {
    csrfToken = "";
    localStorage.removeItem("webnas_csrf");
  });
}

export const api = {
  list: (path?: string, params: Record<string, string | number | boolean | null | undefined> = {}) => {
    const query = new URLSearchParams({ path: path || "" });
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
    });
    return request<FileListResponse>(`/api/files/list?${query.toString()}`);
  },
  tree: (path?: string) => request<{ path: string; items: FileItem[] }>(`/api/files/tree?path=${encodeURIComponent(path || "")}`),
  mkdir: (path: string) => request("/api/files/mkdir", { method: "POST", body: JSON.stringify({ path }) }),
  create: (path: string) => request("/api/files/create", { method: "POST", body: JSON.stringify({ path }) }),
  copy: (src: string | string[], dst: string, priority = 0) => request<{ task_id: string }>("/api/files/copy", { method: "POST", body: JSON.stringify(Array.isArray(src) ? { srcs: src, dst, priority } : { src, dst, priority }) }),
  move: (src: string | string[], dst: string, priority = 0) => request<{ task_id: string }>("/api/files/move", { method: "POST", body: JSON.stringify(Array.isArray(src) ? { srcs: src, dst, priority } : { src, dst, priority }) }),
  rename: (src: string, dst: string) => request("/api/files/rename", { method: "POST", body: JSON.stringify({ src, dst }) }),
  delete: (path: string) => request<{ task_id: string }>("/api/files/delete", { method: "POST", body: JSON.stringify({ path }) }),
  trash: (path: string) => request("/api/files/trash", { method: "POST", body: JSON.stringify({ path }) }),
  preview: (path: string) => request<{ path: string; mime: string; content_base64: string }>(`/api/files/preview?path=${encodeURIComponent(path)}`),
  stat: (path: string) => request<FileItem>(`/api/files/stat?path=${encodeURIComponent(path)}`),
  search: (path: string, query: string) => request<{ items: FileItem[] }>(`/api/files/search?path=${encodeURIComponent(path)}&query=${encodeURIComponent(query)}`),
  tasks: (status?: string) => request<Task[]>(`/api/files/tasks${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  task: (taskId: string) => request<Task>(`/api/files/tasks/${encodeURIComponent(taskId)}`),
  cancelTask: (taskId: string) => request("/api/files/tasks/" + encodeURIComponent(taskId) + "/cancel", { method: "POST", body: "{}" }),
  pauseTask: (taskId: string) => request("/api/files/tasks/" + encodeURIComponent(taskId) + "/pause", { method: "POST", body: "{}" }),
  resumeTask: (taskId: string) => request("/api/files/tasks/" + encodeURIComponent(taskId) + "/resume", { method: "POST", body: "{}" }),
  retryTask: (taskId: string) => request<{ task_id: string }>("/api/files/tasks/" + encodeURIComponent(taskId) + "/retry", { method: "POST", body: "{}" }),
  setTaskPriority: (taskId: string, priority: number) => request("/api/files/tasks/" + encodeURIComponent(taskId) + "/priority", { method: "PATCH", body: JSON.stringify({ priority }) }),
  upload: (path: string, file: File) => {
    const body = new FormData();
    body.set("path", path);
    body.set("file", file);
    return request("/api/files/upload", { method: "POST", body });
  },
  settingsMe: () => request<SettingsMe>("/api/settings/me"),
  updateSettings: (payload: Partial<Pick<SettingsMe, "language" | "theme">>) => request("/api/settings/me", { method: "PATCH", body: JSON.stringify(payload) }),
  changeMyPassword: (current_password: string, new_password: string) => request("/api/settings/change-password", { method: "POST", body: JSON.stringify({ current_password, new_password }) }),
  adminUsers: () => request<AdminUser[]>("/api/admin/users"),
  createUser: (payload: Record<string, unknown>) => request<AdminUser>("/api/admin/users", { method: "POST", body: JSON.stringify(payload) }),
  patchUser: (username: string, payload: Record<string, unknown>) => request<AdminUser>(`/api/admin/users/${encodeURIComponent(username)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteUser: (username: string, admin_password: string) => request(`/api/admin/users/${encodeURIComponent(username)}`, { method: "DELETE", body: JSON.stringify({ admin_password, confirm: true }) }),
  lockUser: (username: string, admin_password: string) => request(`/api/admin/users/${encodeURIComponent(username)}/lock`, { method: "POST", body: JSON.stringify({ admin_password }) }),
  unlockUser: (username: string, admin_password: string) => request(`/api/admin/users/${encodeURIComponent(username)}/unlock`, { method: "POST", body: JSON.stringify({ admin_password }) }),
  changeUserPassword: (username: string, payload: Record<string, unknown>) => request(`/api/admin/users/${encodeURIComponent(username)}/change-password`, { method: "POST", body: JSON.stringify(payload) }),
  setUserQuota: (username: string, payload: Record<string, unknown>) => request(`/api/admin/users/${encodeURIComponent(username)}/quota`, { method: "POST", body: JSON.stringify(payload) }),
  adminGroups: () => request<AdminGroup[]>("/api/admin/groups"),
  createGroup: (payload: Record<string, unknown>) => request("/api/admin/groups", { method: "POST", body: JSON.stringify(payload) }),
  deleteGroup: (groupname: string, admin_password: string) => request(`/api/admin/groups/${encodeURIComponent(groupname)}`, { method: "DELETE", body: JSON.stringify({ admin_password, confirm: true }) }),
  addGroupMember: (groupname: string, payload: Record<string, unknown>) => request(`/api/admin/groups/${encodeURIComponent(groupname)}/members`, { method: "POST", body: JSON.stringify(payload) }),
  removeGroupMember: (groupname: string, username: string, admin_password: string) => request(`/api/admin/groups/${encodeURIComponent(groupname)}/members/${encodeURIComponent(username)}`, { method: "DELETE", body: JSON.stringify({ admin_password }) }),
  chown: (payload: Record<string, unknown>) => request("/api/admin/files/ownership", { method: "POST", body: JSON.stringify(payload) }),
  chmod: (path: string, mode: string) => request("/api/files/chmod", { method: "POST", body: JSON.stringify({ path, mode }) }),
  systemStatus: () => request<SystemStatus>("/api/admin/system/status"),
  resources: () => request<ResourceDashboard>("/api/system/resources"),
  systemLogs: (lines = 160) => request<SystemLogs>(`/api/admin/system/logs?lines=${lines}`),
  proxmoxSafety: () => request<ProxmoxSafety>("/api/admin/system/proxmox-safety"),
  restartSystem: (admin_password: string) => request("/api/admin/system/restart", { method: "POST", body: JSON.stringify({ admin_password }) }),
  systemdServices: () => request<SystemdService[]>("/api/admin/system/services"),
  systemdServiceAction: (service: string, action: "start" | "stop" | "restart" | "enable" | "disable", admin_password: string, confirm_restart = false) => request<SystemdService>(`/api/admin/system/services/${encodeURIComponent(service)}/${action}`, { method: "POST", body: JSON.stringify({ admin_password, confirm_restart }) }),
  systemdServiceLogs: (service: string, lines = 200) => request<SystemLogs>(`/api/admin/system/services/${encodeURIComponent(service)}/logs?lines=${lines}`),
  apps: () => request<StoreApp[]>("/api/apps"),
  app: (id: string) => request<StoreApp>(`/api/apps/${encodeURIComponent(id)}`),
  appAction: (id: string, action: "install" | "uninstall" | "update" | "start" | "stop" | "restart", admin_password: string, dry_run = false) => request(`/api/apps/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify({ admin_password, dry_run }) }),
  appLogs: (id: string) => request<{ lines: string[] }>(`/api/apps/${encodeURIComponent(id)}/logs`),
  appConfig: (id: string) => request<SambaConfig>(`/api/apps/${encodeURIComponent(id)}/config`),
  saveSambaConfig: (config: SambaConfig) => request("/api/apps/samba/config", { method: "PUT", body: JSON.stringify(config) }),
  setSambaPassword: (username: string, password: string, admin_password: string) => request("/api/apps/samba/smbpasswd", { method: "POST", body: JSON.stringify({ username, password, admin_password }) }),
  mounts: () => request<NetworkMount[]>("/api/mounts"),
  mount: (id: string) => request<NetworkMount>(`/api/mounts/${encodeURIComponent(id)}`),
  createMount: (payload: NetworkMountPayload) => request<NetworkMount>("/api/mounts", { method: "POST", body: JSON.stringify(payload) }),
  updateMount: (id: string, payload: NetworkMountPayload) => request<NetworkMount>(`/api/mounts/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteMount: (id: string, admin_password: string) => request(`/api/mounts/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ admin_password }) }),
  mountAction: (id: string, action: "mount" | "unmount" | "remount" | "test", admin_password: string, dry_run = false, force_empty_mountpoint = false) => request(`/api/mounts/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify({ admin_password, dry_run, force_empty_mountpoint }) }),
  mountLogs: (id: string) => request<{ lines: string[] }>(`/api/mounts/${encodeURIComponent(id)}/logs`)
};

export function downloadUrl(path: string) {
  return `/api/files/download?path=${encodeURIComponent(path)}`;
}
