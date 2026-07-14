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
export type TextFileResponse = {
  path: string;
  content: string;
  encoding: "utf-8";
  size: number;
  mtime_ns: string;
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
  startup_windows: "last" | "none";
  wallpaper: string;
};

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string, public field?: string, public details?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
  }
}

export type AdminUser = SettingsMe & { is_system: boolean; manageable: boolean };
export type AdminGroup = { name: string; gid: number; members: string[] };
export type SystemStatus = { service: string; version: string; port: number; data_dir: string; log_dir: string; temp_dir: string };
export type UpdateStatus = { branch: string; local: string; remote: string; update_available: boolean };
export type UpdateStart = { ok: boolean; pid: number; log: string };
export type AutoUpdateSettings = {
  enabled: boolean;
  interval_hours: number;
  update_config: boolean;
  last_checked: number | null;
  last_run: number | null;
  last_error: string;
  last_pid: number | null;
  next_check: number | null;
};
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
export type DiskMetric = UsageMetric & {
  path: string;
  paths?: string[];
  filesystem_id?: string;
  device?: string | null;
  mountpoint?: string | null;
  fs_type?: string | null;
  read_bytes_per_sec?: number | null;
  write_bytes_per_sec?: number | null;
  read_bytes?: number;
  write_bytes?: number;
};
export type NetworkMetric = {
  name: string;
  state: "up" | "down" | "unknown";
  rx_bytes: number;
  tx_bytes: number;
  rx_bytes_per_sec: number | null;
  tx_bytes_per_sec: number | null;
  system: boolean;
};
export type DiskIoMetric = {
  device: string;
  read_bytes: number;
  write_bytes: number;
  read_bytes_per_sec: number | null;
  write_bytes_per_sec: number | null;
};
export type ResourceAlert = { code: string; severity: "info" | "warning" | "critical"; target: string; value: number | string };
export type ProcessMetric = { pid: number; user: string; name: string; cpu_percent: number; memory_percent: number; rss: number; state: string };
export type ResourceDashboard = {
  scope: "admin" | "user";
  timestamp: number;
  cpu_percent: number | null;
  cpu_cores: Array<number | null>;
  cpu_logical_cores: number;
  cpu_frequency_mhz: number | null;
  ram: UsageMetric;
  swap: UsageMetric;
  allowed_roots: DiskMetric[];
  mountpoints: DiskMetric[];
  uptime_seconds: number | null;
  load_average: number[] | null;
  temperature_c: number | null;
  webnas_service: string | null;
  hostname: string;
  os_name: string;
  kernel_version: string;
  boot_time: number | null;
  network_interfaces: NetworkMetric[];
  disk_io: DiskIoMetric[];
  alerts: ResourceAlert[];
  processes: ProcessMetric[];
  warnings: string[];
};
export type AppJob = {
  id: string;
  app_id?: string;
  module_id: string;
  action: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  created_at: number;
  finished_at?: number | null;
  log_tail: Array<{ id: number; created_at: number; stream: string; line: string }>;
  error: string;
  current_step?: string;
  cancellation_requested?: boolean;
  requires_reboot?: boolean;
  plan?: PackagePlan;
};
export type PackageManifest = {
  id: string;
  name: string;
  description: string;
  long_description: string;
  category: string;
  version: string;
  maintainer: string;
  homepage?: string | null;
  icon: string;
  screenshots: string[];
  license: string;
  supported_distributions: string[];
  supported_architectures: string[];
  apt_packages: string[];
  dnf_packages: string[];
  systemd_services: string[];
  ports: string[];
  dependencies: string[];
  conflicts: string[];
  permissions: string[];
  config_paths: string[];
  data_paths: string[];
  backup_paths: string[];
  proxmox_safe: boolean;
  requires_reboot: boolean;
  requires_root: boolean;
  configurable: boolean;
  removable: boolean;
  changelog: string[];
};
export type PackagePlan = {
  module_id: string;
  action: "install" | "update" | "uninstall" | "start" | "stop" | "restart";
  distribution: { id: string; name: string; version_id: string; architecture: string; package_manager?: string | null };
  compatible: boolean;
  blocked_by_proxmox: boolean;
  packages: string[];
  services: string[];
  ports: string[];
  config_paths: string[];
  data_paths: string[];
  permissions: string[];
  dependencies: string[];
  conflicts: string[];
  warnings: string[];
  requires_reboot: boolean;
  remove_data: boolean;
  previous_version?: string | null;
  target_version?: string | null;
  steps: string[];
};
export type PackageModule = {
  id: string;
  manifest: PackageManifest;
  state: { installed: boolean; installed_version?: string | null; available_version: string; update_available: boolean; requires_reboot: boolean; needs_configuration?: boolean };
  services: Record<string, string>;
  status: string;
  compatible: boolean;
  blocked_by_proxmox: boolean;
  distribution: { id: string; name: string; architecture: string; package_manager?: string | null };
  jobs: AppJob[];
};
export type StoreApp = PackageModule;
export type PackageHistoryItem = { id: number; job_id: string; module_id: string; action: string; status: string; actor: string; created_at: number; finished_at?: number | null; message: string };
export type PackageSource = { id: string; name: string; github_url: string; branch: string; enabled: boolean; created_at: number; updated_at: number; last_sync_at?: number | null; validation_error: string; metadata: Record<string, unknown> };
export type StorePlugin = {
  id: string;
  name: string;
  github_url: string;
  branch: string;
  enabled: boolean;
  codex_instructions: string;
  created_at: number;
  updated_at: number;
};
export type SambaShare = {
  name: string;
  path: string;
  comment: string;
  enabled: boolean;
  browseable: boolean;
  hidden?: boolean;
  read_only: boolean;
  guest_ok: boolean;
  valid_users: string[];
  write_list?: string[];
  read_list?: string[];
  admin_users?: string[];
  force_user?: string | null;
  force_group?: string | null;
  veto_files?: string;
  recycle_bin?: boolean;
  create_directory?: boolean;
  directory_owner?: string;
  directory_group?: string;
  directory_mode?: string;
  advanced_options?: Record<string, string>;
  create_mask: string;
  directory_mask: string;
  allow_proxmox_storage?: boolean;
};
export type SambaConfig = { shares: SambaShare[]; global_options?: Record<string, string> };
export type SambaValidation = { ok: boolean; stdout: string; stderr: string; exit_code?: number };
export type SambaStatus = {
  installed: boolean;
  managed_config: boolean;
  include_configured: boolean;
  external_config: boolean;
  services: Record<string, string>;
  ports: Record<string, boolean>;
  validation: SambaValidation;
  shares: SambaShare[];
  history: Array<Record<string, unknown>>;
  last_backup?: string | null;
  proxmox_safe_mode: boolean;
};
export type SambaUser = { username: string; uid: number; home: string; shell: string; system: boolean; samba_enabled: boolean };
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
  status: "mounted" | "unmounted" | "error" | "testing" | "mounting" | "unmounting" | "remounting" | "missing_packages" | "host_unavailable" | "migration_required" | "migrating" | "manual_intervention_required";
  actual_mounted: boolean;
  last_error: string;
  last_operation: string;
  last_operation_at: number | null;
  missing_packages: string[];
  migration_status: "ready" | "required" | "migrating" | "failed";
  manual_intervention: boolean;
  allowed_users: string[];
  allowed_groups: string[];
  config: Record<string, unknown> & { has_secret?: boolean; automount?: boolean };
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
  username?: string;
  password?: string;
  domain?: string;
  smb_version?: string;
  nfs_version?: string;
  ssh_port?: number;
  ssh_auth?: "key" | "password";
  read_only?: boolean;
  persistent?: boolean;
  automount?: boolean;
  uid?: string;
  gid?: string;
  file_mode?: string;
  dir_mode?: string;
  noexec?: boolean;
  advanced_options?: string[];
  allowed_users?: string[];
  allowed_groups?: string[];
  force_empty_mountpoint?: boolean;
  remove_secret?: boolean;
};
export type NetworkMountRoot = {
  id: string;
  name: string;
  mount_point: string;
  read_only: boolean;
  status: "mounted";
  filesystem: { total: number; used: number; free: number; fs_type: string } | null;
};
export type LocalDisk = {
  device: string;
  mount_point: string;
  name: string;
  fs_type: string;
  read_only: boolean;
  total: number;
  used: number;
  free: number;
};
export type MountActionResult = {
  job?: { id: string; mount_id: string; action: string; status: string; exit_code: number | null; error: string; log_tail: string[] };
  dry_run?: boolean;
  dependencies?: string[];
  command?: string[];
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
  if (options.body instanceof Blob) headers.set("Content-Type", "application/octet-stream");
  else if (!(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (csrfToken && options.method && options.method !== "GET") headers.set("x-csrf-token", csrfToken);
  const res = await fetch(url, { ...options, headers, credentials: "include" });
  if (!res.ok) {
    const body = await res.text();
    let message = body || res.statusText;
    let code: string | undefined;
    let field: string | undefined;
    let details: Record<string, unknown> | undefined;
    try {
      const payload = JSON.parse(body) as { detail?: string | ({ code?: string; message?: string; field?: string } & Record<string, unknown>) };
      if (typeof payload.detail === "string") message = payload.detail;
      else if (payload.detail) {
        message = payload.detail.message || message;
        code = payload.detail.code;
        field = payload.detail.field;
        details = payload.detail;
      }
    } catch {
      // Non-JSON responses use the original response text.
    }
    throw new ApiError(message, res.status, code, field, details);
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
  delete: (path: string | string[]) => request<{ task_id: string; task_ids?: string[] }>("/api/files/delete", { method: "POST", body: JSON.stringify(Array.isArray(path) ? { paths: path } : { path }) }),
  trash: (path: string) => request("/api/files/trash", { method: "POST", body: JSON.stringify({ path }) }),
  preview: (path: string) => request<{ path: string; mime: string; content_base64: string }>(`/api/files/preview?path=${encodeURIComponent(path)}`),
  readText: (path: string) => request<TextFileResponse>(`/api/files/text?path=${encodeURIComponent(path)}`),
  writeText: (path: string, content: string, expected_mtime_ns: string) => request<Omit<TextFileResponse, "content"> & { ok: boolean }>("/api/files/text", {
    method: "PUT",
    body: JSON.stringify({ path, content, expected_mtime_ns }),
  }),
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
  startUpload: (path: string, file: File) => request<{ upload_id: string; offset: number; size: number; path: string; completed: boolean }>("/api/files/uploads", { method: "POST", body: JSON.stringify({ path, filename: file.name, size: file.size }) }),
  uploadChunk: (uploadId: string, offset: number, chunk: Blob, signal?: AbortSignal) => request<{ upload_id: string; offset: number; size: number; path: string; completed: boolean }>(`/api/files/uploads/${encodeURIComponent(uploadId)}`, { method: "PATCH", body: chunk, headers: { "Upload-Offset": String(offset) }, signal }),
  cancelUpload: (uploadId: string) => request(`/api/files/uploads/${encodeURIComponent(uploadId)}`, { method: "DELETE", body: "{}" }),
  settingsMe: () => request<SettingsMe>("/api/settings/me"),
  updateSettings: (payload: Partial<Pick<SettingsMe, "language" | "theme" | "startup_windows" | "wallpaper">>) => request("/api/settings/me", { method: "PATCH", body: JSON.stringify(payload) }),
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
  restartSystem: () => request("/api/admin/system/restart", { method: "POST", body: "{}" }),
  checkUpdates: () => request<UpdateStatus>("/api/admin/system/updates/check"),
  downloadUpdates: (update_config = false) => request<UpdateStart>("/api/admin/system/updates/download", { method: "POST", body: JSON.stringify({ update_config }) }),
  autoUpdate: () => request<AutoUpdateSettings>("/api/admin/system/updates/auto"),
  saveAutoUpdate: (payload: { enabled: boolean; interval_hours: number; update_config: boolean }) => request<AutoUpdateSettings>("/api/admin/system/updates/auto", { method: "PATCH", body: JSON.stringify(payload) }),
  runAutoUpdate: (update_config = false) => request<UpdateStart & { updated?: boolean; skipped?: boolean; reason?: string }>("/api/admin/system/updates/auto/run", { method: "POST", body: JSON.stringify({ update_config }) }),
  systemdServices: () => request<SystemdService[]>("/api/admin/system/services"),
  systemdServiceAction: (service: string, action: "start" | "stop" | "restart" | "enable" | "disable", admin_password: string, confirm_restart = false) => request<SystemdService>(`/api/admin/system/services/${encodeURIComponent(service)}/${action}`, { method: "POST", body: JSON.stringify({ admin_password, confirm_restart }) }),
  systemdServiceLogs: (service: string, lines = 200) => request<SystemLogs>(`/api/admin/system/services/${encodeURIComponent(service)}/logs?lines=${lines}`),
  apps: (params: Record<string, string | boolean> = {}) => { const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => value !== "" && query.set(key, String(value))); return request<PackageModule[]>(`/api/apps${query.size ? `?${query}` : ""}`); },
  app: (id: string) => request<PackageModule>(`/api/apps/${encodeURIComponent(id)}`),
  appCategories: () => request<string[]>("/api/apps/categories"),
  appInstalled: () => request<PackageModule[]>("/api/apps/installed"),
  appUpdates: () => request<PackageModule[]>("/api/apps/updates"),
  appPlan: (id: string, action: PackagePlan["action"], remove_data = false) => request<PackagePlan>(`/api/apps/${encodeURIComponent(id)}/plan?action=${encodeURIComponent(action)}&remove_data=${remove_data}`, { method: "POST", body: "{}" }),
  appJobs: (status = "", moduleId = "") => { const query = new URLSearchParams(); if (status) query.set("status", status); if (moduleId) query.set("module_id", moduleId); return request<AppJob[]>(`/api/apps/jobs${query.size ? `?${query}` : ""}`); },
  appJob: (id: string) => request<AppJob>(`/api/apps/jobs/${encodeURIComponent(id)}`),
  cancelAppJob: (id: string, admin_password: string) => request<AppJob>(`/api/apps/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", body: JSON.stringify({ admin_password, confirm_plan: true }) }),
  retryAppJob: (id: string, admin_password: string) => request<AppJob>(`/api/apps/jobs/${encodeURIComponent(id)}/retry`, { method: "POST", body: JSON.stringify({ admin_password, confirm_plan: true }) }),
  appHistory: () => request<PackageHistoryItem[]>("/api/apps/history"),
  packageSources: () => request<PackageSource[]>("/api/apps/sources"),
  createPackageSource: (payload: Omit<PackageSource, "id" | "created_at" | "updated_at" | "last_sync_at" | "validation_error" | "metadata">) => request<PackageSource>("/api/apps/sources", { method: "POST", body: JSON.stringify(payload) }),
  updatePackageSource: (id: string, payload: Omit<PackageSource, "id" | "created_at" | "updated_at" | "last_sync_at" | "validation_error" | "metadata">) => request<PackageSource>(`/api/apps/sources/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),
  deletePackageSource: (id: string) => request(`/api/apps/sources/${encodeURIComponent(id)}`, { method: "DELETE", body: "{}" }),
  syncPackageSource: (id: string) => request<PackageSource>(`/api/apps/sources/${encodeURIComponent(id)}/sync`, { method: "POST", body: "{}" }),
  appAction: (id: string, action: "install" | "uninstall" | "update" | "start" | "stop" | "restart", admin_password: string, _dry_run = false, remove_data = false) => request<{ job?: AppJob; ok?: boolean }>(`/api/apps/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify({ admin_password, confirm_plan: true, remove_data }) }),
  appLogs: (id: string) => request<{ lines: string[] }>(`/api/apps/${encodeURIComponent(id)}/logs`),
  appConfig: (id: string) => request<SambaConfig>(`/api/apps/${encodeURIComponent(id)}/config`),
  storePlugins: () => request<{ plugins: StorePlugin[]; codex_template: string }>("/api/apps/plugins"),
  createStorePlugin: (plugin: Partial<StorePlugin>) => request<StorePlugin>("/api/apps/plugins", { method: "POST", body: JSON.stringify(plugin) }),
  updateStorePlugin: (id: string, plugin: Partial<StorePlugin>) => request<StorePlugin>(`/api/apps/plugins/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(plugin) }),
  deleteStorePlugin: (id: string) => request(`/api/apps/plugins/${encodeURIComponent(id)}`, { method: "DELETE" }),
  saveSambaConfig: (config: SambaConfig) => request("/api/apps/samba/config", { method: "PUT", body: JSON.stringify(config) }),
  setSambaPassword: (username: string, password: string, admin_password: string) => request("/api/apps/samba/smbpasswd", { method: "POST", body: JSON.stringify({ username, password, admin_password }) }),
  sambaStatus: () => request<SambaStatus>("/api/apps/samba/status"),
  sambaUsers: () => request<SambaUser[]>("/api/apps/samba/users"),
  sambaPreview: (config: SambaConfig) => request<{ config: string; validation: SambaValidation }>("/api/apps/samba/preview", { method: "POST", body: JSON.stringify({ config }) }),
  sambaApply: (config: SambaConfig) => request<SambaStatus>("/api/apps/samba/apply", { method: "POST", body: JSON.stringify({ config }) }),
  sambaRollback: () => request("/api/apps/samba/rollback", { method: "POST", body: "{}" }),
  sambaService: (action: "start" | "stop" | "restart" | "reload", admin_password: string) => request<{ ok: boolean; status: SambaStatus }>("/api/apps/samba/service", { method: "POST", body: JSON.stringify({ action, admin_password }) }),
  enableSambaUser: (username: string, password: string, admin_password: string) => request("/api/apps/samba/users/enable", { method: "POST", body: JSON.stringify({ username, password, admin_password }) }),
  disableSambaUser: (username: string, admin_password: string) => request("/api/apps/samba/users/disable", { method: "POST", body: JSON.stringify({ username, admin_password }) }),
  mounts: () => request<NetworkMount[]>("/api/mounts"),
  mountRoots: () => request<NetworkMountRoot[]>("/api/mounts/roots"),
  localDisks: () => request<LocalDisk[]>("/api/files/local-disks"),
  mount: (id: string) => request<NetworkMount>(`/api/mounts/${encodeURIComponent(id)}`),
  createMount: (payload: NetworkMountPayload) => request<NetworkMount>("/api/mounts", { method: "POST", body: JSON.stringify(payload) }),
  updateMount: (id: string, payload: NetworkMountPayload) => request<NetworkMount>(`/api/mounts/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteMount: (id: string, admin_password: string, confirm_destructive = true) => request(`/api/mounts/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ admin_password, confirm_destructive }) }),
  mountAction: (id: string, action: "mount" | "unmount" | "remount" | "test" | "migrate", admin_password: string, dry_run = false, force_empty_mountpoint = false) => request<MountActionResult>(`/api/mounts/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify({ admin_password, dry_run, force_empty_mountpoint, confirm_destructive: ["unmount", "remount", "migrate"].includes(action) }) }),
  mountLogs: (id: string) => request<{ lines: string[] }>(`/api/mounts/${encodeURIComponent(id)}/logs`)
};

export function downloadUrl(path: string) {
  return `/api/files/download?path=${encodeURIComponent(path)}`;
}
