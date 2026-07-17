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
  username?: string;
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

export type PinnedAppId = "files" | "transfers" | "activity" | "identity" | "users" | "groups" | "mounts" | "samba" | "services" | "store" | "logs" | "settings" | "monitor" | "modules" | "access" | "module";

export type UserPreferences = {
  language: "pl-PL" | "en-US";
  theme: "light" | "dark" | "system";
  startup_windows: "last" | "none";
  wallpaper: string;
  accent_color: "blue" | "teal" | "green" | "violet" | "rose" | "orange";
  wallpaper_fit: "cover" | "contain" | "stretch" | "center";
  taskbar_alignment: "left" | "center";
  pinned_apps: PinnedAppId[];
  start_pinned_apps: PinnedAppId[];
  desktop_shortcut_apps: PinnedAppId[];
  show_desktop_shortcuts: boolean;
  desktop_shortcut_size: "small" | "medium" | "large";
  show_welcome_widget: boolean;
  show_notifications: boolean;
  show_transfer_indicator: boolean;
  window_transparency: boolean;
  animations_enabled: boolean;
  clock_show_seconds: boolean;
  date_format: "locale" | "short" | "long" | "iso";
  time_format: "12" | "24";
  interface_scale: 90 | 100 | 110 | 125;
  larger_text: boolean;
  high_contrast: boolean;
  reduced_motion: boolean;
  strong_active_borders: boolean;
  always_show_focus: boolean;
  file_default_view: "list" | "grid" | "large";
  file_compact_rows: boolean;
  file_show_hidden: boolean;
  file_confirm_delete: boolean;
  file_confirm_overwrite: boolean;
  file_page_size: 25 | 50 | 100 | 200;
  file_default_sort: "name" | "size" | "type" | "modified";
  file_sort_direction: "asc" | "desc";
  file_remember_last_path: boolean;
  transfer_success_notifications: boolean;
  transfer_error_notifications: boolean;
  transfer_open_failed_details: boolean;
  transfer_remember_filter: boolean;
  notification_transfer: boolean;
  notification_errors: boolean;
  notification_admin: boolean;
  notification_auto_hide: boolean;
  notification_limit: number;
  first_day_of_week: "monday" | "sunday" | "locale";
  widgets_enabled: boolean;
  desktop_widgets: DesktopWidget[];
};

export type DesktopWidgetId = "cpu" | "ram" | "disks" | "transfers" | "services" | "alerts";
export type DesktopWidget = { id: DesktopWidgetId; visible: boolean; x: number; y: number; width: number; height: number };

export type SettingsMe = UserPreferences & {
  username: string;
  uid: number;
  gid: number;
  groups: string[];
  home: string;
  shell: string;
  gecos: string;
  is_admin: boolean;
  role: "admin" | "operator" | "auditor" | "user";
  role_source: string;
  permissions: string[];
};

export type SettingsPatch = Partial<UserPreferences>;

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string, public field?: string, public details?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
  }
}

export type AdminUser = SettingsMe & { is_system: boolean; manageable: boolean };
export type AdminGroup = { name: string; gid: number; members: string[] };
export type SystemStatus = { service: string; version: string; port: number; data_dir: string; log_dir: string; temp_dir: string };
export type HostInfo = {
  hostname: string;
  operating_system: string;
  kernel_version: string;
  architecture: string;
  ip_addresses: string[];
  application_version: string;
  uptime_seconds: number | null;
  cpu: { model: string; physical_cores: number | null; logical_threads: number | null };
  memory: UsageMetric;
  gpus: string[];
  storage: UsageMetric & { path: string } | null;
};
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
export type ActivityCategory = "login" | "file" | "configuration" | "administration" | "module";
export type ActivityStatus = "success" | "failure" | "info" | "queued" | "cancelled";
export type ActivityEvent = {
  id: number;
  created_at: number;
  actor: string;
  category: ActivityCategory;
  action: string;
  target: string;
  status: ActivityStatus;
  summary: string;
  details: Record<string, unknown>;
  source: string;
};
export type ActivityResponse = {
  items: ActivityEvent[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  scope: "own" | "global";
};
export type ActivitySummary = {
  total: number;
  categories: Record<ActivityCategory, number>;
  statuses: Record<ActivityStatus, number>;
  latest_at: number | null;
  scope: "own" | "global";
};
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
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  created_at: number;
  finished_at?: number | null;
  log_tail: Array<{ id: number; created_at: number; stream: string; line: string }>;
  error: string;
  current_step?: string;
  stage?: string;
  requested_by?: string;
  operation?: string;
  warnings?: string[];
  result?: Record<string, unknown>;
  cancellation_requested?: boolean;
  cancellable?: boolean;
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
  packages?: { apt: string[]; dnf: string[]; yum: string[] };
  services?: Array<{ name: string; required: boolean }>;
  config?: { primary_file?: string | null; backup_paths: string[]; validation_command: string[] };
  capabilities?: ModuleCapability;
};

export type ModuleCapability = {
  install: boolean; update: boolean; uninstall: boolean; configure: boolean; service_control: boolean; reload: boolean;
  logs: boolean; diagnostics: boolean; backups: boolean; import_export: boolean; healthcheck: boolean;
  resources: string[]; actions: string[];
};
export type ModuleResource = { resource: string; items: Array<Record<string, unknown>>; total: number; [key: string]: unknown };
export type ModuleConnection = { base_url: string; username: string; secret_configured: boolean };
export type RbacRole = "admin" | "operator" | "auditor" | "user";
export type RbacAssignment = { username: string; uid?: number; role: RbacRole; allow: string[]; deny: string[]; permissions: string[]; role_source: string; is_admin: boolean };
export type RbacRoles = { roles: Record<RbacRole, string[]>; permissions: string[] };
export type PermissionRisk = "low" | "medium" | "high" | "critical";
export type PermissionMetadata = { id: string; category: string; operation: string; applications: string[]; risk: PermissionRisk; mutating: boolean; label_key: string; description_key: string };
export type IdentityProfile = { username: string; role: RbacRole; role_source: "linux-admin" | "assignment" | "default"; linux_admin: boolean; is_admin: boolean; permissions: string[]; effective_permissions?: string[]; denied_permissions: string[]; permission_sources: Record<string, string[]> };
export type IdentityUser = IdentityProfile & { uid: number; gid: number; primary_group: string; supplementary_groups: string[]; groups: string[]; home: string; shell: string; gecos: string; locked: boolean; password_change_required: boolean; is_system: boolean; manageable: boolean; allow: string[]; deny: string[] };
export type IdentityGroup = { name: string; groupname: string; gid: number; primary_users: string[]; supplementary_members: string[]; members: string[]; is_system: boolean; protected: boolean; manageable: boolean; allow: string[]; deny: string[]; inheriting_users: string[]; inheriting_count: number };
export type IdentityRoles = { roles: Record<RbacRole, string[]>; permissions: PermissionMetadata[] };
export type IdentityHistory = { id: number; created_at: number; actor: string; subject_type: "user" | "group" | "migration"; subject: string; action: string; previous: Record<string, unknown>; current: Record<string, unknown>; status: string; error_code: string };
export type ModuleManifest = PackageManifest;
export type ModuleHealth = "healthy" | "degraded" | "failed" | "unknown" | "not_installed";
export type ModuleStatus = {
  installed: boolean;
  package_version?: string | null;
  available_version?: string | null;
  update_available: boolean;
  service_state: string;
  service_enabled: boolean;
  services: Record<string, { state: string; enabled: boolean; required: boolean; uptime_seconds?: number | null }>;
  configuration_valid?: boolean | null;
  health: ModuleHealth;
  health_message: string;
  last_action: string;
  last_action_status: string;
  last_action_time?: number | null;
  last_error: string;
  metrics: Record<string, unknown>;
};
export type ModuleJob = AppJob;
export type ModuleJobStage = string;
export type ModuleConfig = Record<string, unknown>;
export type ModuleValidationResult = { ok: boolean; errors: string[]; warnings: string[]; changes: Array<{ kind: string; name: string; before?: unknown; after?: unknown }>; generated_config: string; validator_output: string; confirmations_required: string[] };
export type ModuleApplyPlan = { validation: ModuleValidationResult; steps: string[]; services: string[]; config_paths: string[]; warnings: string[] };
export type ModuleDiagnostic = { status: "ok" | "info" | "warning" | "critical"; title: string; description: string; details: string; severity: "ok" | "info" | "warning" | "critical"; recommended_action: string };
export type ModuleBackup = { id: string; module_id: string; created_at: number; created_by: string; description: string; automatic: boolean; checksum: string; package_version: string; size: number; files: string[] };
export type ModuleLogSource = { id: string; label: string };
export type ModuleSummary = PackageModule & { module_status: ModuleStatus; capabilities: ModuleCapability; active_job?: ModuleJob | null };
export type PackagePlan = {
  module_id: string;
  action: "install" | "reinstall" | "update" | "uninstall" | "start" | "stop" | "restart" | "reload" | "enable" | "disable" | "apply" | "diagnostics" | "restore" | "firewall" | "manage";
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
  valid_groups?: string[];
  write_list?: string[];
  read_list?: string[];
  admin_users?: string[];
  force_user?: string | null;
  force_group?: string | null;
  force_create_mode?: string;
  force_directory_mode?: string;
  inherit_permissions?: boolean;
  veto_files?: string;
  recycle_bin?: boolean;
  recycle_versions?: boolean;
  vfs_objects?: string[];
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
export type SambaModuleUser = SambaUser & { status: string; groups: string[]; last_changed?: number | null };
export type SambaSession = { id: string; username: string; client: string; ip: string; protocol: string; share: string; open_files: number; connected_at?: number | string | null; pid?: number | null };
export type SambaShareAccess = { share: string; path: string; resolved_path: string; exists: boolean; is_directory: boolean; read_only: boolean; mode: string | null; ok: boolean; warnings: string[]; errors: string[] };
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
  removable: boolean;
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
export type NetworkInterfaceAddress = {
  family: "ipv4" | "ipv6";
  address: string;
  prefix_length: number;
  scope: string;
};
export type NetworkInterfaceDetail = {
  name: string;
  state: "up" | "down" | "dormant" | "lowerlayerdown" | "unknown";
  carrier: boolean | null;
  speed_mbps: number | null;
  duplex: "full" | "half" | null;
  mtu: number | null;
  mac_address: string | null;
  addresses: NetworkInterfaceAddress[];
  rx_bytes: number;
  rx_packets: number;
  rx_errors: number;
  rx_dropped: number;
  tx_bytes: number;
  tx_packets: number;
  tx_errors: number;
  tx_dropped: number;
  rx_bytes_per_sec: number | null;
  tx_bytes_per_sec: number | null;
  system: boolean;
};
export type NetworkOverview = {
  timestamp: number;
  sample_interval_seconds: number | null;
  interfaces: NetworkInterfaceDetail[];
  warnings: string[];
};
export type DnsConfiguration = {
  resolv_conf: {
    path: string;
    symlink_target: string | null;
    mode: "stub" | "uplink" | "static";
    nameservers: string[];
    search: string[];
    options: string[];
  };
  systemd_resolved: {
    available: boolean;
    global_servers: string[];
    global_domains?: string[];
    links: Array<{ interface: string; servers: string[]; domains: string[] }>;
  };
  warnings: string[];
};
export type DnsTestResult = {
  hostname: string;
  success: boolean;
  addresses: string[];
  servers: Array<{
    server: string;
    success: boolean;
    rcode: string | null;
    addresses: string[];
    latency_ms: number | null;
    error: string | null;
  }>;
  tested_at: number;
};
export type NetworkRoute = {
  family: "ipv4" | "ipv6";
  destination: string;
  gateway: string | null;
  device: string | null;
  preferred_source: string | null;
  protocol: string | null;
  scope: string | null;
  type: string;
  table: string;
  metric: number | null;
  nexthops: Array<{ gateway: string | null; device: string | null; weight: number | null }>;
};
export type NetworkRule = {
  family: "ipv4" | "ipv6";
  priority: number | null;
  from: string;
  to: string;
  table: string | null;
  fwmark: string | null;
  input_interface: string | null;
  output_interface: string | null;
  action: string;
};
export type RoutingSnapshot = {
  timestamp: number;
  routes: NetworkRoute[];
  rules: NetworkRule[];
  gateways: Array<{ family: "ipv4" | "ipv6"; address: string; device: string | null; metric: number | null; table: string }>;
  warnings: string[];
  read_only: true;
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

export async function login(username: string, password: string, rememberMe = false) {
  const data = await request<{ username: string; home: string; csrf_token: string }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password, remember_me: rememberMe })
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
  allTasks: (status?: string) => request<Task[]>(`/api/admin/transfers${status ? `?status=${encodeURIComponent(status)}` : ""}`),
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
  activity: (params: { category?: ActivityCategory | ""; status?: ActivityStatus | ""; actor?: string; search?: string; page?: number; page_size?: number } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") query.set(key, String(value));
    });
    return request<ActivityResponse>(`/api/activity${query.size ? `?${query}` : ""}`);
  },
  activitySummary: () => request<ActivitySummary>("/api/activity/summary"),
  settingsMe: () => request<SettingsMe>("/api/settings/me"),
  updateSettings: (payload: SettingsPatch) => request<SettingsMe>("/api/settings/me", { method: "PATCH", body: JSON.stringify(payload) }),
  changeMyPassword: (current_password: string, new_password: string) => request("/api/settings/change-password", { method: "POST", body: JSON.stringify({ current_password, new_password }) }),
  identityMe: () => request<IdentityProfile>("/api/identity/me"),
  identityPermissions: () => request<PermissionMetadata[]>("/api/identity/permissions"),
  identityRoles: () => request<IdentityRoles>("/api/identity/roles"),
  identityHistory: (limit = 200) => request<IdentityHistory[]>(`/api/identity/history?limit=${limit}`),
  identityUsers: (params: { search?: string; role?: string; status?: string; include_system?: boolean } = {}) => { const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== "" && value !== false) query.set(key, String(value)); }); return request<IdentityUser[]>(`/api/identity/users${query.size ? `?${query}` : ""}`); },
  identityUser: (username: string) => request<IdentityUser>(`/api/identity/users/${encodeURIComponent(username)}`),
  createIdentityUser: (payload: Record<string, unknown>) => request<IdentityUser>("/api/identity/users", { method: "POST", body: JSON.stringify(payload) }),
  updateIdentityUser: (username: string, payload: Record<string, unknown>) => request<IdentityUser>(`/api/identity/users/${encodeURIComponent(username)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteIdentityUser: (username: string, remove_home: boolean) => request(`/api/identity/users/${encodeURIComponent(username)}`, { method: "DELETE", body: JSON.stringify({ confirm: true, remove_home }) }),
  lockIdentityUser: (username: string, locked: boolean) => request(`/api/identity/users/${encodeURIComponent(username)}/${locked ? "lock" : "unlock"}`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  changeIdentityUserPassword: (username: string, new_password: string, force_change: boolean) => request(`/api/identity/users/${encodeURIComponent(username)}/password`, { method: "POST", body: JSON.stringify({ new_password, force_change, confirm: true }) }),
  setIdentityUserQuota: (username: string, soft_mb: number, hard_mb: number | null, mountpoint: string | null) => request(`/api/identity/users/${encodeURIComponent(username)}/quota`, { method: "POST", body: JSON.stringify({ soft_mb, hard_mb, mountpoint, confirm: true }) }),
  saveIdentityUserPolicy: (username: string, policy: { role: RbacRole; allow: string[]; deny: string[] }) => request<IdentityUser>(`/api/identity/users/${encodeURIComponent(username)}/policy`, { method: "PUT", body: JSON.stringify({ ...policy, confirm: true }) }),
  identityEffectivePermissions: (username: string) => request<IdentityProfile>(`/api/identity/users/${encodeURIComponent(username)}/effective-permissions`),
  identityGroups: (params: { search?: string; include_system?: boolean } = {}) => { const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== "" && value !== false) query.set(key, String(value)); }); return request<IdentityGroup[]>(`/api/identity/groups${query.size ? `?${query}` : ""}`); },
  createIdentityGroup: (payload: Record<string, unknown>) => request<IdentityGroup>("/api/identity/groups", { method: "POST", body: JSON.stringify(payload) }),
  renameIdentityGroup: (groupname: string, new_name: string) => request<IdentityGroup>(`/api/identity/groups/${encodeURIComponent(groupname)}`, { method: "PATCH", body: JSON.stringify({ new_name, confirm: true }) }),
  deleteIdentityGroup: (groupname: string) => request(`/api/identity/groups/${encodeURIComponent(groupname)}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),
  setIdentityGroupMember: (groupname: string, username: string, present: boolean) => request<IdentityGroup>(present ? `/api/identity/groups/${encodeURIComponent(groupname)}/members` : `/api/identity/groups/${encodeURIComponent(groupname)}/members/${encodeURIComponent(username)}`, { method: present ? "POST" : "DELETE", body: JSON.stringify({ username, confirm: true }) }),
  saveIdentityGroupPolicy: (groupname: string, policy: { allow: string[]; deny: string[] }) => request<IdentityGroup>(`/api/identity/groups/${encodeURIComponent(groupname)}/policy`, { method: "PUT", body: JSON.stringify({ ...policy, confirm: true }) }),
  adminUsers: () => request<AdminUser[]>("/api/admin/users"),
  createUser: (payload: Record<string, unknown>) => request<AdminUser>("/api/admin/users", { method: "POST", body: JSON.stringify(payload) }),
  patchUser: (username: string, payload: Record<string, unknown>) => request<AdminUser>(`/api/admin/users/${encodeURIComponent(username)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteUser: (username: string) => request(`/api/admin/users/${encodeURIComponent(username)}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),
  lockUser: (username: string) => request(`/api/admin/users/${encodeURIComponent(username)}/lock`, { method: "POST", body: "{}" }),
  unlockUser: (username: string) => request(`/api/admin/users/${encodeURIComponent(username)}/unlock`, { method: "POST", body: "{}" }),
  changeUserPassword: (username: string, payload: Record<string, unknown>) => request(`/api/admin/users/${encodeURIComponent(username)}/change-password`, { method: "POST", body: JSON.stringify(payload) }),
  setUserQuota: (username: string, payload: Record<string, unknown>) => request(`/api/admin/users/${encodeURIComponent(username)}/quota`, { method: "POST", body: JSON.stringify(payload) }),
  adminGroups: () => request<AdminGroup[]>("/api/admin/groups"),
  createGroup: (payload: Record<string, unknown>) => request("/api/admin/groups", { method: "POST", body: JSON.stringify(payload) }),
  deleteGroup: (groupname: string) => request(`/api/admin/groups/${encodeURIComponent(groupname)}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),
  addGroupMember: (groupname: string, payload: Record<string, unknown>) => request(`/api/admin/groups/${encodeURIComponent(groupname)}/members`, { method: "POST", body: JSON.stringify(payload) }),
  removeGroupMember: (groupname: string, username: string) => request(`/api/admin/groups/${encodeURIComponent(groupname)}/members/${encodeURIComponent(username)}`, { method: "DELETE", body: "{}" }),
  chown: (payload: Record<string, unknown>) => request("/api/admin/files/ownership", { method: "POST", body: JSON.stringify(payload) }),
  chmod: (path: string, mode: string) => request("/api/files/chmod", { method: "POST", body: JSON.stringify({ path, mode }) }),
  systemStatus: () => request<SystemStatus>("/api/admin/system/status"),
  hostInfo: () => request<HostInfo>("/api/system/host-info"),
  resources: () => request<ResourceDashboard>("/api/system/resources"),
  systemLogs: (lines = 160) => request<SystemLogs>(`/api/admin/system/logs?lines=${lines}`),
  proxmoxSafety: () => request<ProxmoxSafety>("/api/admin/system/proxmox-safety"),
  networkOverview: () => request<NetworkOverview>("/api/admin/network/overview"),
  networkDns: () => request<DnsConfiguration>("/api/admin/network/dns"),
  testNetworkDns: (hostname: string) => request<DnsTestResult>("/api/admin/network/dns/test", { method: "POST", body: JSON.stringify({ hostname }) }),
  networkRouting: () => request<RoutingSnapshot>("/api/admin/network/routing"),
  restartSystem: () => request("/api/admin/system/restart", { method: "POST", body: "{}" }),
  checkUpdates: () => request<UpdateStatus>("/api/admin/system/updates/check"),
  downloadUpdates: (update_config = false) => request<UpdateStart>("/api/admin/system/updates/download", { method: "POST", body: JSON.stringify({ update_config }) }),
  autoUpdate: () => request<AutoUpdateSettings>("/api/admin/system/updates/auto"),
  saveAutoUpdate: (payload: { enabled: boolean; interval_hours: number; update_config: boolean }) => request<AutoUpdateSettings>("/api/admin/system/updates/auto", { method: "PATCH", body: JSON.stringify(payload) }),
  runAutoUpdate: (update_config = false) => request<UpdateStart & { updated?: boolean; skipped?: boolean; reason?: string }>("/api/admin/system/updates/auto/run", { method: "POST", body: JSON.stringify({ update_config }) }),
  systemdServices: () => request<SystemdService[]>("/api/admin/system/services"),
  systemdServiceAction: (service: string, action: "start" | "stop" | "restart" | "enable" | "disable", confirm_restart = false) => request<SystemdService>(`/api/admin/system/services/${encodeURIComponent(service)}/${action}`, { method: "POST", body: JSON.stringify({ confirm_restart }) }),
  systemdServiceLogs: (service: string, lines = 200) => request<SystemLogs>(`/api/admin/system/services/${encodeURIComponent(service)}/logs?lines=${lines}`),
  apps: (params: Record<string, string | boolean> = {}) => { const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => value !== "" && query.set(key, String(value))); return request<PackageModule[]>(`/api/apps${query.size ? `?${query}` : ""}`); },
  app: (id: string) => request<PackageModule>(`/api/apps/${encodeURIComponent(id)}`),
  appCategories: () => request<string[]>("/api/apps/categories"),
  appInstalled: () => request<PackageModule[]>("/api/apps/installed"),
  appUpdates: () => request<PackageModule[]>("/api/apps/updates"),
  appPlan: (id: string, action: PackagePlan["action"], remove_data = false) => request<PackagePlan>(`/api/apps/${encodeURIComponent(id)}/plan?action=${encodeURIComponent(action)}&remove_data=${remove_data}`, { method: "POST", body: "{}" }),
  appJobs: (status = "", moduleId = "") => { const query = new URLSearchParams(); if (status) query.set("status", status); if (moduleId) query.set("module_id", moduleId); return request<AppJob[]>(`/api/apps/jobs${query.size ? `?${query}` : ""}`); },
  appJob: (id: string) => request<AppJob>(`/api/apps/jobs/${encodeURIComponent(id)}`),
  cancelAppJob: (id: string) => request<AppJob>(`/api/apps/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", body: JSON.stringify({ confirm_plan: true }) }),
  retryAppJob: (id: string) => request<AppJob>(`/api/apps/jobs/${encodeURIComponent(id)}/retry`, { method: "POST", body: JSON.stringify({ confirm_plan: true }) }),
  appHistory: () => request<PackageHistoryItem[]>("/api/apps/history"),
  packageSources: () => request<PackageSource[]>("/api/apps/sources"),
  createPackageSource: (payload: Omit<PackageSource, "id" | "created_at" | "updated_at" | "last_sync_at" | "validation_error" | "metadata">) => request<PackageSource>("/api/apps/sources", { method: "POST", body: JSON.stringify(payload) }),
  updatePackageSource: (id: string, payload: Omit<PackageSource, "id" | "created_at" | "updated_at" | "last_sync_at" | "validation_error" | "metadata">) => request<PackageSource>(`/api/apps/sources/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),
  deletePackageSource: (id: string) => request(`/api/apps/sources/${encodeURIComponent(id)}`, { method: "DELETE", body: "{}" }),
  syncPackageSource: (id: string) => request<PackageSource>(`/api/apps/sources/${encodeURIComponent(id)}/sync`, { method: "POST", body: "{}" }),
  appAction: (id: string, action: "install" | "reinstall" | "uninstall" | "update" | "start" | "stop" | "restart", remove_data = false) => request<{ job?: AppJob; ok?: boolean }>(`/api/apps/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify({ confirm_plan: true, remove_data }) }),
  modules: () => request<ModuleSummary[]>("/api/modules"),
  module: (id: string) => request<ModuleSummary>(`/api/modules/${encodeURIComponent(id)}`),
  moduleStatus: (id: string) => request<ModuleStatus>(`/api/modules/${encodeURIComponent(id)}/status`),
  moduleResource: (id: string, resource: string, limit = 200, search = "") => request<ModuleResource>(`/api/modules/${encodeURIComponent(id)}/resources/${encodeURIComponent(resource)}?limit=${limit}&search=${encodeURIComponent(search)}`),
  moduleAction: (id: string, action: string, payload: Record<string, unknown> = {}) => request<{ job: ModuleJob }>(`/api/modules/${encodeURIComponent(id)}/actions/${encodeURIComponent(action)}`, { method: "POST", body: JSON.stringify({ confirm: true, payload }) }),
  moduleConnection: (id: string) => request<ModuleConnection>(`/api/modules/${encodeURIComponent(id)}/connection`),
  saveModuleConnection: (id: string, connection: Omit<ModuleConnection, "secret_configured"> & { secret?: string }) => request<ModuleConnection>(`/api/modules/${encodeURIComponent(id)}/connection`, { method: "PUT", body: JSON.stringify({ ...connection, confirm: true }) }),
  saveDockerCompose: (project: string, content: string) => request<{ name: string; updated_at: number; size: number }>(`/api/modules/docker/compose/${encodeURIComponent(project)}`, { method: "PUT", body: JSON.stringify({ content, confirm: true }) }),
  dockerCompose: (project: string) => request<{ name: string; content: string; updated_at: number; size: number }>(`/api/modules/docker/compose/${encodeURIComponent(project)}`),
  moduleConfig: (id: string) => request<ModuleConfig>(`/api/modules/${encodeURIComponent(id)}/config`),
  validateModuleConfig: (id: string, config: ModuleConfig) => request<ModuleValidationResult>(`/api/modules/${encodeURIComponent(id)}/validate`, { method: "POST", body: JSON.stringify({ config }) }),
  applyModuleConfig: (id: string, config: ModuleConfig, confirmations: string[] = []) => request<{ job: ModuleJob }>(`/api/modules/${encodeURIComponent(id)}/apply`, { method: "POST", body: JSON.stringify({ config, confirm: true, create_backup: true, confirm_smb1: confirmations.includes("smb1") }) }),
  moduleLogs: (id: string, source = "", lines = 200, search = "", level = "") => { const query = new URLSearchParams({ source, lines: String(lines), search, level }); return request<{ sources: ModuleLogSource[]; source: string; lines: string[]; truncated: boolean }>(`/api/modules/${encodeURIComponent(id)}/logs?${query}`); },
  moduleDiagnostics: (id: string) => request<{ diagnostics: ModuleDiagnostic[]; job?: ModuleJob | null }>(`/api/modules/${encodeURIComponent(id)}/diagnostics`),
  runModuleDiagnostics: (id: string) => request<{ job: ModuleJob }>(`/api/modules/${encodeURIComponent(id)}/diagnostics`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  moduleBackups: (id: string) => request<ModuleBackup[]>(`/api/modules/${encodeURIComponent(id)}/backups`),
  createModuleBackup: (id: string, description = "") => request<ModuleBackup>(`/api/modules/${encodeURIComponent(id)}/backups`, { method: "POST", body: JSON.stringify({ confirm: true, description }) }),
  restoreModuleBackup: (id: string, backupId: string) => request<{ job: ModuleJob }>(`/api/modules/${encodeURIComponent(id)}/backups/${encodeURIComponent(backupId)}/restore`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  deleteModuleBackup: (id: string, backupId: string) => request(`/api/modules/${encodeURIComponent(id)}/backups/${encodeURIComponent(backupId)}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),
  moduleService: (id: string, action: "start" | "stop" | "restart" | "reload" | "enable" | "disable") => request<{ job: ModuleJob }>(`/api/modules/${encodeURIComponent(id)}/service/${action}`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  sambaModuleUsers: () => request<SambaModuleUser[]>("/api/modules/samba/users"),
  sambaModuleUserAction: (username: string, action: "add" | "password" | "enable" | "disable" | "remove", password = "") => request("/api/modules/samba/users/" + encodeURIComponent(username) + "/" + action, { method: "POST", body: JSON.stringify({ password, confirm: true }) }),
  sambaSessions: () => request<SambaSession[]>("/api/modules/samba/sessions"),
  testSambaShare: (name: string) => request<SambaShareAccess>(`/api/modules/samba/shares/${encodeURIComponent(name)}/test`),
  removeSambaShare: (name: string) => request<{ job: ModuleJob }>(`/api/modules/samba/shares/${encodeURIComponent(name)}`, { method: "DELETE", body: JSON.stringify({ confirm: true, create_backup: true }) }),
  uninstallModule: (id: string, options: { remove_config: boolean; remove_data: boolean; create_backup: boolean; confirm_name?: string }) => request<{ job: ModuleJob }>(`/api/modules/${encodeURIComponent(id)}/uninstall`, { method: "POST", body: JSON.stringify({ confirm: true, ...options }) }),
  validateSambaImport: (content: string) => request<{ config: SambaConfig; validation: ModuleValidationResult }>("/api/modules/samba/import/validate", { method: "POST", body: JSON.stringify({ content }) }),
  sambaFirewall: () => request<{ adapter: string; ports: string[]; can_manage: boolean; plan: string[][] }>("/api/modules/samba/firewall"),
  openSambaFirewall: (confirm = true) => request<{ ok?: boolean; plan: string[][]; requires_confirmation?: boolean }>("/api/modules/samba/firewall/open", { method: "POST", body: JSON.stringify({ confirm }) }),
  rbacMe: () => request<{ role: RbacRole; permissions: string[]; role_source: string; is_admin: boolean }>("/api/rbac/me"),
  rbacRoles: () => request<RbacRoles>("/api/rbac/roles"),
  rbacAssignments: () => request<RbacAssignment[]>("/api/rbac/assignments"),
  saveRbacAssignment: (assignment: Pick<RbacAssignment, "username" | "role" | "allow" | "deny">) => request<RbacAssignment>(`/api/rbac/assignments/${encodeURIComponent(assignment.username)}`, { method: "PUT", body: JSON.stringify(assignment) }),
  appLogs: (id: string) => request<{ lines: string[] }>(`/api/apps/${encodeURIComponent(id)}/logs`),
  appConfig: (id: string) => request<SambaConfig>(`/api/apps/${encodeURIComponent(id)}/config`),
  storePlugins: () => request<{ plugins: StorePlugin[]; codex_template: string }>("/api/apps/plugins"),
  createStorePlugin: (plugin: Partial<StorePlugin>) => request<StorePlugin>("/api/apps/plugins", { method: "POST", body: JSON.stringify(plugin) }),
  updateStorePlugin: (id: string, plugin: Partial<StorePlugin>) => request<StorePlugin>(`/api/apps/plugins/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(plugin) }),
  deleteStorePlugin: (id: string) => request(`/api/apps/plugins/${encodeURIComponent(id)}`, { method: "DELETE" }),
  saveSambaConfig: (config: SambaConfig, confirm_smb1 = false) => request<{ job: ModuleJob }>("/api/apps/samba/config", { method: "PUT", body: JSON.stringify({ config, confirm_smb1 }) }),
  setSambaPassword: (username: string, password: string) => request("/api/apps/samba/smbpasswd", { method: "POST", body: JSON.stringify({ username, password }) }),
  sambaStatus: () => request<SambaStatus>("/api/apps/samba/status"),
  sambaUsers: () => request<SambaUser[]>("/api/apps/samba/users"),
  sambaPreview: (config: SambaConfig) => request<{ config: string; validation: SambaValidation }>("/api/apps/samba/preview", { method: "POST", body: JSON.stringify({ config }) }),
  sambaApply: (config: SambaConfig, confirm_smb1 = false) => request<{ job: ModuleJob }>("/api/apps/samba/apply", { method: "POST", body: JSON.stringify({ config, confirm_smb1 }) }),
  sambaRollback: () => request("/api/apps/samba/rollback", { method: "POST", body: "{}" }),
  sambaService: (action: "start" | "stop" | "restart" | "reload") => request<{ ok: boolean; status: SambaStatus }>("/api/apps/samba/service", { method: "POST", body: JSON.stringify({ action }) }),
  enableSambaUser: (username: string, password: string) => request("/api/apps/samba/users/enable", { method: "POST", body: JSON.stringify({ username, password }) }),
  disableSambaUser: (username: string) => request("/api/apps/samba/users/disable", { method: "POST", body: JSON.stringify({ username }) }),
  mounts: () => request<NetworkMount[]>("/api/mounts"),
  mountRoots: () => request<NetworkMountRoot[]>("/api/mounts/roots"),
  localDisks: () => request<LocalDisk[]>("/api/files/local-disks"),
  mount: (id: string) => request<NetworkMount>(`/api/mounts/${encodeURIComponent(id)}`),
  createMount: (payload: NetworkMountPayload) => request<NetworkMount>("/api/mounts", { method: "POST", body: JSON.stringify(payload) }),
  updateMount: (id: string, payload: NetworkMountPayload) => request<NetworkMount>(`/api/mounts/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteMount: (id: string, confirm_destructive = true) => request(`/api/mounts/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ confirm_destructive }) }),
  mountAction: (id: string, action: "mount" | "unmount" | "remount" | "test" | "migrate", dry_run = false, force_empty_mountpoint = false) => request<MountActionResult>(`/api/mounts/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify({ dry_run, force_empty_mountpoint, confirm_destructive: ["unmount", "remount", "migrate"].includes(action) }) }),
  mountLogs: (id: string) => request<{ lines: string[] }>(`/api/mounts/${encodeURIComponent(id)}/logs`)
};

export function downloadUrl(path: string) {
  return `/api/files/download?path=${encodeURIComponent(path)}`;
}
