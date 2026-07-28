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

export type PinnedAppId = "files" | "transfers" | "activity" | "identity" | "users" | "groups" | "mounts" | "samba" | "services" | "store" | "logs" | "settings" | "monitor" | "modules" | "access" | "containers" | "ansible" | "hosts" | "module";
export type InterfaceFont = "system" | "segoe" | "arial" | "verdana" | "tahoma" | "georgia" | "monospace";
export type WallpaperItem = { id: string; name: string; url: string; size: number; created_at: number };

export type UserPreferences = {
  language: "pl-PL" | "en-US";
  theme: "light" | "dark" | "system";
  startup_windows: "last" | "none";
  wallpaper: string;
  accent_color: "blue" | "teal" | "green" | "violet" | "rose" | "orange";
  wallpaper_fit: "cover" | "contain" | "stretch" | "center";
  taskbar_alignment: "left" | "center";
  pinned_apps: PinnedAppId[];
  pinned_modules: string[];
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
  interface_scale: number;
  interface_font: InterfaceFont;
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
export type UpdateStatus = { branch: string; local: string; remote: string; installed_version?: string | null; available_version?: string | null; update_available: boolean; available?: boolean; error?: string; source?: string; source_url?: string; released_at?: number | null };
export type UpdateStart = { ok: boolean; pid: number; log: string };
export type UpdateProgress = { state: "idle" | "running" | "completed" | "failed"; running: boolean; pid: number | null; unit?: string | null; exit_code: number | null; started_at: number | null; finished_at: number | null; log: string; lines: string[] };
export type AutoUpdateSettings = {
  check_enabled: boolean;
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
export type LogEntry = {
  id: string;
  timestamp: string | null;
  original_priority?: number;
  original_severity?: "emergency" | "alert" | "critical" | "error" | "warning" | "notice" | "info" | "debug";
  priority: number;
  severity: "emergency" | "alert" | "critical" | "error" | "warning" | "notice" | "info" | "debug";
  severity_inferred?: boolean;
  severity_reason?: string | null;
  source: string;
  unit: string;
  identifier: string;
  hostname: string;
  pid: number | null;
  uid: number | null;
  message: string;
  cursor: string;
  fields: Record<string, unknown>;
};
export type LogSource = { id: string; label: string; available: boolean; status: string; permission: string };
export type LogSourceGroup = { id: string; label: string; items: LogSource[] };
export type LogSourcesResponse = { groups: LogSourceGroup[]; capabilities: { journal: boolean; docker: boolean; live: boolean; export: boolean } };
export type LogQuery = {
  source?: string; query?: string; regex?: boolean; case_sensitive?: boolean; negate?: boolean; message_only?: boolean;
  priority?: number[]; unit?: string; pid?: number | null; uid?: number | null; identifier?: string; transport?: string;
  hostname?: string; device?: string; username?: string; group?: string; boot_id?: string; container_id?: string;
  since?: number | null; until?: number | null; cursor?: string;
  direction?: "older" | "newer"; limit?: number;
};
export type LogEntriesResponse = { items: LogEntry[]; next_cursor: string | null; has_more: boolean; direction: string; limit: number; truncated: boolean };
export type LogBoot = { id: string; index: number; first: string | null; last: string | null; duration_seconds?: number | null; current: boolean };
export type LogService = { unit: string; load: string; active: string; sub: string; description: string };
export type LogContainer = { id: string; name: string; image: string; state: string; status: string };
export type LogSavedView = {
  id: string; name: string; source: string; query: string; filters: Record<string, string | number | boolean | number[]>;
  columns: string[]; sort: "newest" | "oldest"; view_mode: "compact" | "table"; builtin: boolean;
};
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
export type AnsibleDashboard = {
  hosts: number; hosts_online: number; hosts_unreachable: number; host_key_errors: number; groups: number; projects: number;
  playbooks: number; templates: number; active_jobs: number; failed_jobs: number; scheduled: number; ansible_version?: string;
  controller_user_ready?: boolean; last_scan?: Record<string, unknown> | null; last_git_sync?: Record<string, unknown> | null;
};
export type AnsibleHost = {
  id: string; name: string; address: string; port: number; ssh_user: string; credential_id?: string | null;
  python_interpreter: string; connection_type: "ssh" | "paramiko"; environment: string; location: string; tags: string[];
  variables: Record<string, unknown>; fingerprint_status: string; last_test_at?: number | null; last_facts_at?: number | null;
  last_error: string; managed_user_created: boolean; active: boolean; groups?: Array<{ id: string; name: string }>;
  facts?: Record<string, unknown>; created_at: number; updated_at: number;
};
export type AnsibleEnrollmentToken = { id: string; token: string; hostname_pattern: string; expires_at: number };
export type AnsibleGroup = { id: string; name: string; description: string; parent_id?: string | null; variables: Record<string, unknown>; host_ids: string[]; active: boolean; created_at: number; updated_at: number };
export type AnsibleCredential = { id: string; name: string; type: "ssh_private_key" | "ssh_password" | "become_password" | "git_private_key" | "awx_token" | "vault_secret"; username: string; description: string; secret_configured: boolean; active: boolean; created_at: number; updated_at: number };
export type AnsibleProject = { id: string; name: string; source_type: "editor" | "git" | "archive" | "managed_directory"; repository_url: string; revision: string; credential_id?: string | null; sync_before_run: boolean; allow_submodules: boolean; last_commit: string; last_sync_at?: number | null; last_sync_status: string; active: boolean };
export type AnsibleRisk = { code: string; message: string; path?: string; line?: number | null };
export type AnsiblePlaybook = { id: string; project_id: string; name: string; filename: string; content: string; current_version: number; risk_status: string; warnings: AnsibleRisk[]; active: boolean; updated_at: number };
export type AnsibleTemplate = { id: string; name: string; description: string; project_id: string; playbook_id: string; host_ids: string[]; group_ids: string[]; ssh_credential_id?: string | null; become_credential_id?: string | null; vault_credential_id?: string | null; limit_pattern: string; tags: string[]; skip_tags: string[]; check_mode: boolean; diff_mode: boolean; verbosity: number; forks: number; timeout_seconds: number; extra_vars: string; concurrency_policy: string; sync_before_run: boolean; confirmation_required: boolean; active: boolean };
export type AnsibleHostResult = { id: string; host_id?: string | null; host_name: string; status: string; ok_count: number; changed_count: number; failed_count: number; unreachable_count: number; skipped_count: number; rescued_count: number; ignored_count: number; message: string };
export type AnsibleExecution = { id: string; package_job_id?: string | null; template_id?: string | null; retry_of?: string | null; requested_by: string; status: string; stage: string; host_ids: string[]; warnings: AnsibleRisk[]; summary: Record<string, number>; stdout: string; stderr: string; exit_code?: number | null; started_at?: number | null; finished_at?: number | null; created_at: number; host_results?: AnsibleHostResult[] };
export type AnsibleScanHost = { id: string; address: string; hostname: string; port: number; latency_ms?: number | null; ssh_status: string; imported_host_id?: string | null };
export type AnsibleScan = { id: string; request: Record<string, unknown>; status: string; progress: number; discovered: number; package_job_id?: string | null; error: string; created_at: number; hosts?: AnsibleScanHost[] };
export type AnsibleSchedule = { id: string; name: string; template_id: string; kind: "once" | "hourly" | "daily" | "weekly" | "monthly" | "cron"; expression: string; timezone: string; missed_policy: "skip" | "run_once"; next_run_at?: number | null; last_run_at?: number | null; active: boolean };
export type AnsibleValidation = { ok: boolean; errors: AnsibleRisk[]; warnings: AnsibleRisk[]; blocked: AnsibleRisk[]; task_count: number; documents?: number };
export type HostsManagerDashboard = { total: number; online: number; offline: number; unverified: number; fingerprint_errors: number; pending_approval: number; ansible_available: number; power_managed: number; recent_operations: HostsManagerOperation[]; recent_errors: HostsManagerHost[] };
export type HostsManagerHost = AnsibleHost & { hostname: string; fqdn: string; management_address: string; description: string; approved: boolean; registration_status: string; connection_status: string; power_status: string; enrollment_source: string; group_ids: string[]; capabilities?: HostsManagerCapability[] };
export type HostsManagerGroup = AnsibleGroup;
export type HostsManagerCredential = AnsibleCredential & { type: AnsibleCredential["type"] | "redfish" | "ipmi" | "proxmox_api" | "wol" };
export type HostsManagerCapability = { id: string; name: string; icon: string; permission: string; module_id: string; deep_link: string };
export type HostsManagerOperation = { id: string; host_id?: string | null; capability_id: string; module_id: string; status: string; stage: string; progress: number; error: string; details: Record<string, unknown>; created_at: number; updated_at: number };
export type HostsManagerBootstrapOS = "linux" | "windows";
export type HostsManagerSettings = {
  hostname_template: string; next_hostname: string; sequence_width: number; preview_hostnames: string[];
  bootstrap_default_os: HostsManagerBootstrapOS; bootstrap_apply_hostname: boolean; updated_at: number; updated_by: string;
};
export type HostsManagerSettingsUpdate = Pick<HostsManagerSettings, "hostname_template" | "bootstrap_default_os" | "bootstrap_apply_hostname">;
export type HostsManagerEnrollmentInput = {
  bootstrap_os: HostsManagerBootstrapOS; apply_hostname: boolean; expires_minutes: number; port: number; ssh_user: string;
  credential_id: string | null; environment: string; location: string; tags: string[]; group_ids: string[];
  require_approval: boolean; onboard_ansible: boolean;
};
export type HostsManagerEnrollmentToken = {
  id: string; hostname_pattern: string; assigned_hostname: string; bootstrap_os: HostsManagerBootstrapOS;
  apply_hostname: boolean; expires_at: number; created_at?: number; created_by?: string; used_hostname?: string;
  used: boolean; expired?: boolean; revoked?: boolean; token?: string; script_url?: string; command?: string; filename?: string;
};
export type HostsManagerRepository = { id: string; name: string; description: string; url: string; revision: string; last_commit: string; last_sync_at?: number | null; last_sync_status: string; active: boolean; updated_at: number };
export type HostsManagerPowerProfile = { id: string; name: string; provider: "none" | "wol" | "redfish" | "ipmi" | "proxmox"; address: string; mac_address: string; active: boolean; updated_at: number };
export type HostsManagerBackup = { id?: string; filename: string; description?: string; size?: number; checksum?: string; created_at?: number; created_by?: string };
export type DockerPaged<T = Record<string, unknown>> = { items: T[]; total: number; page: number; page_size: number; pages: number };
export type DockerDashboard = { status: ModuleStatus; counts: Record<string, number>; storage: Array<Record<string, unknown>>; security: Array<{ level: string; message: string }>; engine: Record<string, unknown>; usage: { cpu_percent?: number; memory_bytes?: number }; events: Array<Record<string, unknown>>; updates: Array<Record<string, unknown>>; prune_preview: { total?: number; estimated_reclaimable?: number } };
export type DockerContainer = { ID?: string; Names?: string; Image?: string; State?: string; Status?: string; Ports?: string; Size?: string; [key: string]: unknown };
export type DockerContainerSettings = {
  name: string; resource_limits_enabled: boolean; cpu_priority: "low" | "medium" | "high"; memory_mb: number | null;
  auto_restart: boolean; restart_policy: string; portal_enabled: boolean; portal_port: number | null; portal_published_port: number | null;
  portal_protocol: "http" | "https"; compose_managed: boolean;
  available_ports: Array<{ target: number; published: number; protocol: "tcp" | "udp"; host_ip?: string | null }>;
};
export type DockerContainerSettingsUpdate = Pick<DockerContainerSettings, "name" | "resource_limits_enabled" | "cpu_priority" | "memory_mb" | "auto_restart" | "portal_enabled" | "portal_port" | "portal_protocol"> & { confirmation: string };
export type DockerImage = { ID?: string; Repository?: string; Tag?: string; Digest?: string; Size?: string; CreatedSince?: string; consumers?: string[]; [key: string]: unknown };
export type DockerNetworkContainer = { id: string; name: string; endpoint_id?: string; mac_address?: string; ipv4_address?: string; ipv6_address?: string; state?: string; connected?: boolean };
export type DockerNetwork = {
  Name: string; ID?: string; Driver: string; Scope?: string; IPv6?: boolean;
  subnets?: string[]; gateways?: string[]; ip_ranges?: string[];
  container_count?: number; containers?: DockerNetworkContainer[];
  internal?: boolean; attachable?: boolean; system?: boolean;
  options?: Record<string, string>; labels?: Record<string, string>;
  [key: string]: unknown;
};
export type DockerApp = { id: string; name: string; description: string; image: string; container: string; category: string; panel_port: number; ports: string[]; version: string; required_secrets: string[]; architectures: string[]; healthcheck: string; dependencies: string[]; minimum_memory_mb: number; documentation_url: string; update_strategy: string; backup_strategy: string; uninstall_strategy: string; installed: boolean; running: boolean; managed: boolean; status: string };
export type DockerArtifact = { id: string; kind: string; display_name: string; checksum: string; size: number; created_at: number; created_by: string; metadata: Record<string, unknown> };
export type DockerRegistryProvider = "docker_hub" | "ghcr" | "gitlab" | "quay" | "custom";
export type DockerRegistry = { id: string; name: string; provider: DockerRegistryProvider; server: string; username: string; tls: boolean; ca_certificate_configured: boolean; secret_configured: boolean; built_in?: boolean; public_access?: boolean; created_at: number; updated_at: number };
export type DockerRegistrySource = { id: string; name: string; provider: DockerRegistryProvider; server: string; built_in: boolean; public_access: boolean };
export type DockerRegistryCatalogImage = {
  registry_id: string; registry: string; provider: DockerRegistryProvider; repository: string; pull_reference: string;
  description: string; stars: number; official: boolean; automated: boolean | null; [key: string]: unknown;
};
export type DockerRegistryPagination = { page: number; page_size: number; total: number; pages: number; has_next: boolean; truncated: boolean };
export type DockerRegistryCatalogResult = { items: DockerRegistryCatalogImage[]; pagination: DockerRegistryPagination; source: DockerRegistrySource };
export type DockerRegistryTagsResult = { repository: string; pull_reference: string; tags: string[]; pagination: DockerRegistryPagination; source: DockerRegistrySource };
export type DockerPortMapping = { host_ip?: string | null; published: number; target: number; protocol?: "tcp" | "udp" };
export type DockerMount = { type: "volume" | "bind" | "tmpfs"; source?: string; target: string; read_only?: boolean; tmpfs_size_mb?: number | null };
export type DockerContainerCreate = {
  name: string; image: string; pull_policy?: "missing" | "always" | "never";
  environment?: Record<string, string>; secret_environment?: Record<string, string>;
  ports?: DockerPortMapping[]; mounts?: DockerMount[]; network?: string;
  network_aliases?: string[]; hostname?: string | null; working_dir?: string | null; user?: string | null;
  restart_policy?: "no" | "always" | "unless-stopped" | "on-failure";
  limits?: { cpus?: number | null; memory_mb?: number | null; memory_swap_mb?: number | null; pids?: number | null };
  healthcheck?: { type: "none" | "http" | "tcp"; port?: number | null; path?: string; interval_seconds?: number; timeout_seconds?: number; retries?: number; start_period_seconds?: number };
  labels?: Record<string, string>; read_only?: boolean; init?: boolean; auto_start?: boolean; confirmation?: string;
};
export type DockerContainerDefaultsPolicy = {
  resource_limits_enabled: boolean;
  memory_mb: number;
  memory_swap_mb: number;
  cpus: number;
  pids: number;
};
export type DockerContainerAction = {
  action: "start" | "stop" | "restart" | "pause" | "unpause" | "kill" | "rename" | "remove" | "duplicate" | "recreate" | "check_update" | "update";
  timeout?: number; signal?: "KILL" | "TERM" | "HUP" | "INT" | "QUIT" | "USR1" | "USR2";
  force?: boolean; new_name?: string; image?: string | null; confirmation?: string; pam_password?: string | null;
};
export type DockerImageAction = { action: "pull" | "update" | "remove" | "prune" | "save"; image?: string; platform?: "linux/amd64" | "linux/arm64" | "linux/arm/v7"; force?: boolean; confirmation?: string; pam_password?: string | null };
export type DockerComposeSave = { content: string; environment?: Record<string, string>; secret_environment?: Record<string, string> | null; description?: string };
export type DockerComposeAction = { action: "up" | "down" | "start" | "stop" | "restart" | "pull" | "recreate" | "scale" | "delete" | "validate"; services?: string[]; scale?: Record<string, number>; remove_volumes?: boolean; confirmation?: string; pam_password?: string | null };
export type DockerVolumeAction = { action: "remove" | "prune" | "backup" | "restore" | "clone"; target_name?: string | null; backup_id?: string | null; force?: boolean; confirmation?: string; pam_password?: string | null };
export type DockerNetworkAction = { action: "remove" | "prune" | "connect" | "disconnect"; container?: string | null; force?: boolean; confirmation?: string; pam_password?: string | null };
export type DockerEngineAction = { action: "install" | "reinstall" | "update" | "start" | "stop" | "restart" | "enable" | "disable" | "test"; confirmation?: string; pam_password?: string | null };
export type DockerRegistrySave = { name: string; provider: DockerRegistryProvider; server: string; username: string; password?: string | null; tls?: boolean; ca_certificate?: string | null };
export type DockerVolumeCreate = { name: string; labels?: Record<string, string> };
export type DockerNetworkCreate = {
  name: string; driver: "bridge";
  ipv4_mode: "auto" | "manual"; ipv4_subnet: string | null; ipv4_ip_range: string | null; ipv4_gateway: string | null;
  ipv6_mode: "none" | "manual"; ipv6_subnet: string | null; ipv6_ip_range: string | null; ipv6_gateway: string | null;
  internal: boolean; disable_ip_masquerade: boolean; labels: Record<string, string>;
};
export type DockerDefaultBridgeConfig = {
  ipv4_mode: "auto" | "manual"; ipv4_subnet: string | null; ipv4_ip_range: string | null; ipv4_gateway: string | null;
  ipv6_mode: "none" | "manual"; ipv6_subnet: string | null; ipv6_gateway: string | null;
  disable_ip_masquerade: boolean;
};
export type DockerDefaultBridgeSave = DockerDefaultBridgeConfig & { confirmation: string; pam_password: string };
export type DockerPrunePlan = { resources: string[]; items: Array<{ type: string; id?: string; name?: string; size?: string | number | null }>; total: number; estimated_reclaimable: number };
export type DockerAppInstall = { secret_environment?: Record<string, string>; timezone?: string; hostname?: string; panel_port?: number; dns_port?: number; network?: string; confirmation?: string };
export type DockerAppAction = { confirmation?: string; pam_password?: string | null };
export type DockerBackupRestore = { new_name: string; secret_environment?: Record<string, string>; confirmation?: string; pam_password?: string | null };
export type DockerPrune = { resources: Array<"containers" | "images" | "networks" | "volumes" | "build_cache">; confirmation?: string; pam_password?: string | null };
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
export type NetworkIPConfiguration = {
  method: "disabled" | "dhcp" | "slaac" | "dhcpv6" | "manual";
  addresses: Array<{ address: string; prefix: number }>;
  gateway?: string | null;
  metric: number;
  default_route: boolean;
  ignore_auto_routes: boolean;
  ignore_auto_dns: boolean;
  dns: string[];
  search_domains: string[];
  privacy_extensions: boolean;
};
export type NetworkInterfaceConfiguration = {
  name: string;
  kind: "physical" | "bond" | "vlan" | "bridge";
  autostart: boolean;
  mtu: number;
  parent?: string | null;
  vlan_id?: number | null;
  members: string[];
  bond_mode: "active-backup" | "balance-rr" | "balance-xor" | "broadcast" | "802.3ad" | "balance-tlb" | "balance-alb";
  primary?: string | null;
  miimon: number;
  updelay: number;
  downdelay: number;
  lacp_rate: "slow" | "fast";
  xmit_hash_policy: "layer2" | "layer2+3" | "layer3+4";
  stp: boolean;
  forward_delay: number;
  ipv4: NetworkIPConfiguration;
  ipv6: NetworkIPConfiguration;
};
export type NetworkDnsSettings = {
  automatic: boolean;
  servers: string[];
  search_domains: string[];
  routing_domains: string[];
  per_interface: Record<string, string[]>;
  priority: number;
  ignore_dhcp: boolean;
};
export type ManagedNetworkRoute = {
  id?: string;
  name: string;
  family: "ipv4" | "ipv6";
  destination: string;
  route_type: "unicast" | "blackhole" | "unreachable" | "prohibit";
  gateway?: string | null;
  interface?: string | null;
  metric: number;
  table: number;
  source?: string | null;
  autostart: boolean;
  enabled: boolean;
};
export type NetworkTrafficRule = {
  id?: string;
  name: string;
  interface: string;
  direction: "egress" | "ingress";
  guaranteed_kbit: number;
  maximum_kbit: number;
  priority: number;
  protocol: "any" | "tcp" | "udp";
  source_cidr?: string | null;
  destination_cidr?: string | null;
  source_port?: number | null;
  destination_port?: number | null;
  enabled: boolean;
};
export type NetworkChange =
  | { operation: "save_interface"; interface: NetworkInterfaceConfiguration }
  | { operation: "delete_interface"; interface_name: string }
  | { operation: "set_link"; interface_name: string; link_up: boolean }
  | { operation: "save_dns"; dns: NetworkDnsSettings }
  | { operation: "save_route"; route: ManagedNetworkRoute }
  | { operation: "delete_route"; object_id: string }
  | { operation: "save_traffic"; traffic: NetworkTrafficRule }
  | { operation: "delete_traffic"; object_id: string };
export type NetworkPlan = {
  id: string; provider: string; target: string; before: Record<string, unknown>; after: Record<string, unknown>;
  commands: string[][]; warnings: string[]; high_risk: boolean; required_phrase: string;
  rollback_supported: boolean; rollback_seconds: number; client_interface: string | null;
  previous_panel_address?: string | null; predicted_panel_address?: string | null; reachable_addresses?: string[];
  confirmation_timeout_seconds: number; rollback_method: string; automatic_rollback_without_confirmation: boolean;
};
export type NetworkPolicy = {
  change_confirmation_timeout_seconds: number;
  minimum_seconds: number;
  maximum_seconds: number;
  default_seconds: number;
};
export type NetworkTransaction = {
  id: string; transaction_id?: string; provider: string;
  state: "pending_confirmation" | "rollback_started" | "confirmed" | "rolled_back" | "failed";
  status?: "pending_confirmation" | "rollback_pending" | "rollback_started" | "confirmed" | "rolled_back" | "failed";
  confirmed?: boolean; rollback_pending?: boolean; rollback_started?: boolean; rolled_back?: boolean; failed?: boolean;
  started_at: number; deadline: number; rollback_unit: string | null; target: string;
  created_at?: number; deadline_at?: number; remaining_seconds?: number; current_server_time?: number;
  server_time?: number; confirmation_timeout_seconds?: number;
  previous_panel_address?: string | null; predicted_panel_address?: string | null; reachable_addresses?: string[];
};
export type NetworkManagementState = {
  provider: { id: string; writable: boolean; capabilities: Record<string, boolean>; warnings: string[] };
  hostname: string;
  interfaces: NetworkInterfaceDetail[];
  dns: DnsConfiguration;
  routing: RoutingSnapshot;
  managed: {
    interfaces: Record<string, NetworkInterfaceConfiguration>;
    dns: NetworkDnsSettings | null;
    routes: Record<string, ManagedNetworkRoute>;
    traffic: Record<string, NetworkTrafficRule>;
  };
  transaction: NetworkTransaction | null;
  tools: Record<string, boolean>;
};
export type NetworkConnectivityResult = {
  kind: "ping" | "trace" | "tcp"; target: string; port: number | null; success: boolean; duration_ms: number; output: string;
};

let csrfToken = localStorage.getItem("webnas_csrf") || "";
let apiBaseUrl = "";

export function setApiBaseUrl(baseUrl: string) {
  apiBaseUrl = baseUrl.replace(/\/+$/, "");
}

function apiAt(baseUrl: string, path: string) {
  return baseUrl ? `${baseUrl.replace(/\/+$/, "")}${path}` : path;
}

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body instanceof Blob) headers.set("Content-Type", "application/octet-stream");
  else if (options.body !== undefined && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (csrfToken && options.method && options.method !== "GET") headers.set("x-csrf-token", csrfToken);
  const target = apiBaseUrl && url.startsWith("/") ? `${apiBaseUrl}${url}` : url;
  const res = await fetch(target, { ...options, headers, credentials: "include" });
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

async function enrollmentScript(url: string, token: string): Promise<Blob> {
  const target = apiBaseUrl && url.startsWith("/") ? `${apiBaseUrl}${url}` : url;
  const response = await fetch(target, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  if (!response.ok) throw new ApiError("Enrollment script is unavailable", response.status);
  return response.blob();
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
  wallpapers: () => request<{ items: WallpaperItem[]; max_files: number; max_file_size: number }>("/api/settings/wallpapers"),
  uploadWallpaper: (file: File) => { const body = new FormData(); body.set("file", file); return request<WallpaperItem>("/api/settings/wallpapers", { method: "POST", body }); },
  deleteWallpaper: (wallpaperId: string) => request<{ ok: boolean }>(`/api/settings/wallpapers/${encodeURIComponent(wallpaperId)}`, { method: "DELETE", body: "{}" }),
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
  logSources: () => request<LogSourcesResponse>("/api/logs/sources"),
  logEntries: (params: LogQuery = {}, signal?: AbortSignal) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (Array.isArray(value)) value.forEach((item) => query.append(key, String(item)));
      else if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
    });
    return request<LogEntriesResponse>(`/api/logs/entries${query.size ? `?${query}` : ""}`, { signal });
  },
  logBoots: () => request<{ items: LogBoot[]; status: string; error?: string }>("/api/logs/boots"),
  logServices: () => request<{ items: LogService[]; status: string; error?: string }>("/api/logs/services"),
  logService: (unit: string) => request<LogService & { pid: number | null; started_at: string; entries: LogEntry[] }>(`/api/logs/services/${encodeURIComponent(unit)}`),
  logContainers: () => request<{ items: LogContainer[]; status: string; error?: string }>("/api/logs/containers"),
  logFields: () => request<{ items: string[] }>("/api/logs/fields"),
  logSavedViews: () => request<{ items: LogSavedView[] }>("/api/logs/saved-views"),
  createLogSavedView: (payload: Omit<LogSavedView, "id" | "builtin">) => request<LogSavedView>("/api/logs/saved-views", { method: "POST", body: JSON.stringify(payload) }),
  updateLogSavedView: (id: string, payload: Omit<LogSavedView, "id" | "builtin">) => request<LogSavedView>(`/api/logs/saved-views/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteLogSavedView: (id: string) => request<{ ok: boolean }>(`/api/logs/saved-views/${encodeURIComponent(id)}`, { method: "DELETE", body: "{}" }),
  exportLogs: async (payload: LogQuery & { format: "txt" | "json" | "jsonl" | "csv"; limit?: number }) => {
    const headers = new Headers({ "Content-Type": "application/json" });
    const res = await fetch("/api/logs/export", { method: "POST", body: JSON.stringify(payload), headers, credentials: "include" });
    if (!res.ok) {
      const body = await res.text();
      let message = body || res.statusText;
      try {
        const parsed = JSON.parse(body) as { detail?: string | { message?: string } };
        message = typeof parsed.detail === "string" ? parsed.detail : parsed.detail?.message || message;
      } catch { /* plain responses retain their original text */ }
      throw new ApiError(message, res.status);
    }
    const disposition = res.headers.get("content-disposition") || "";
    return { blob: await res.blob(), filename: disposition.match(/filename="([^"]+)"/)?.[1] || `webnas-logs.${payload.format}`, truncated: res.headers.get("x-webnas-truncated") === "true" };
  },
  proxmoxSafety: () => request<ProxmoxSafety>("/api/admin/system/proxmox-safety"),
  networkOverview: () => request<NetworkOverview>("/api/admin/network/overview"),
  networkDns: () => request<DnsConfiguration>("/api/admin/network/dns"),
  testNetworkDns: (hostname: string) => request<DnsTestResult>("/api/admin/network/dns/test", { method: "POST", body: JSON.stringify({ hostname }) }),
  networkRouting: () => request<RoutingSnapshot>("/api/admin/network/routing"),
  networkManagement: () => request<NetworkManagementState>("/api/admin/network/management"),
  testNetworkConnectivity: (kind: "ping" | "trace" | "tcp", target: string, port?: number | null) => request<NetworkConnectivityResult>("/api/admin/network/connectivity/test", { method: "POST", body: JSON.stringify({ kind, target, port: port || null }) }),
  planNetworkChange: (change: NetworkChange) => request<NetworkPlan>("/api/admin/network/plans", { method: "POST", body: JSON.stringify({ change }) }),
  networkPolicy: () => request<NetworkPolicy>("/api/admin/network/policy"),
  saveNetworkPolicy: (change_confirmation_timeout_seconds: number) => request<NetworkPolicy>("/api/admin/network/policy", { method: "PUT", body: JSON.stringify({ change_confirmation_timeout_seconds, confirm: true }) }),
  resetNetworkPolicy: () => request<NetworkPolicy>("/api/admin/network/policy/reset", { method: "POST", body: JSON.stringify({ confirm: true }) }),
  applyNetworkPlan: (plan_id: string, confirmation_phrase = "") => request<NetworkTransaction>("/api/admin/network/apply", { method: "POST", body: JSON.stringify({ plan_id, confirmation_phrase }) }),
  activeNetworkTransaction: (baseUrl = "", signal?: AbortSignal) => request<NetworkTransaction | null>(apiAt(baseUrl, "/api/admin/network/transactions/active"), { signal }),
  networkTransactionStatus: (transaction_id: string, baseUrl = "", signal?: AbortSignal) => request<NetworkTransaction>(apiAt(baseUrl, `/api/admin/network/transactions/${encodeURIComponent(transaction_id)}/status`), { signal }),
  confirmNetworkTransaction: (transaction_id: string, baseUrl = "", signal?: AbortSignal) => baseUrl
    ? request<NetworkTransaction>(apiAt(baseUrl, `/api/admin/network/transactions/${encodeURIComponent(transaction_id)}/confirm`), { method: "POST", signal })
    : request<NetworkTransaction>("/api/admin/network/confirm", { method: "POST", body: JSON.stringify({ transaction_id }), signal }),
  rollbackNetworkTransaction: (transaction_id: string, baseUrl = "", signal?: AbortSignal) => baseUrl
    ? request<NetworkTransaction>(apiAt(baseUrl, `/api/admin/network/transactions/${encodeURIComponent(transaction_id)}/rollback`), { method: "POST", signal })
    : request<NetworkTransaction>("/api/admin/network/rollback", { method: "POST", body: JSON.stringify({ transaction_id }), signal }),
  restartSystem: () => request("/api/admin/system/restart", { method: "POST", body: "{}" }),
  checkUpdates: () => request<UpdateStatus>("/api/admin/system/updates/check"),
  updateProgress: () => request<UpdateProgress>("/api/admin/system/updates/progress"),
  downloadUpdates: (update_config = false) => request<UpdateStart>("/api/admin/system/updates/download", { method: "POST", body: JSON.stringify({ update_config }) }),
  autoUpdate: () => request<AutoUpdateSettings>("/api/admin/system/updates/auto"),
  saveAutoUpdate: (payload: { check_enabled: boolean; enabled: boolean; interval_hours: number; update_config: boolean }) => request<AutoUpdateSettings>("/api/admin/system/updates/auto", { method: "PATCH", body: JSON.stringify(payload) }),
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
  ansibleDashboard: () => request<AnsibleDashboard>("/api/modules/ansible-controller/dashboard"),
  ansibleConfig: () => request<Record<string, unknown>>("/api/modules/ansible-controller/config"),
  saveAnsibleConfig: (payload: Record<string, unknown>) => request<{ job: ModuleJob }>("/api/modules/ansible-controller/config", { method: "PUT", body: JSON.stringify({ ...payload, confirm: true }) }),
  saveAnsibleManagedAccount: (payload: { username: string; sudo_profile: "none" | "nopasswd"; shell: "/bin/bash" | "/bin/sh"; comment: string; authorized_keys_mode: "exclusive"; key_rotation_days: number }) => request<{ managed_username: string; managed_sudo_profile: string; managed_shell: string; managed_comment: string; managed_authorized_keys_mode: string; managed_key_rotation_days: number }>("/api/modules/ansible-controller/managed-account", { method: "PUT", body: JSON.stringify({ ...payload, confirm: true }) }),
  hostsManagerDashboard: () => request<HostsManagerDashboard>("/api/modules/hosts-manager/dashboard"),
  hostsManagerSettings: () => request<HostsManagerSettings>("/api/modules/hosts-manager/settings"),
  saveHostsManagerSettings: (payload: HostsManagerSettingsUpdate) => request<HostsManagerSettings>("/api/modules/hosts-manager/settings", { method: "PUT", body: JSON.stringify(payload) }),
  hostsManagerHosts: (query = "") => request<HostsManagerHost[]>(`/api/modules/hosts-manager/hosts${query ? `?${query}` : ""}`),
  hostsManagerHost: (id: string) => request<HostsManagerHost>(`/api/modules/hosts-manager/hosts/${encodeURIComponent(id)}`),
  saveHostsManagerHost: (payload: Record<string, unknown>, id = "") => request<HostsManagerHost>(id ? `/api/modules/hosts-manager/hosts/${encodeURIComponent(id)}` : "/api/modules/hosts-manager/hosts", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  deleteHostsManagerHost: (id: string) => request<{ ok: boolean }>(`/api/modules/hosts-manager/hosts/${encodeURIComponent(id)}`, { method: "DELETE" }),
  approveHostsManagerHost: (id: string) => request<HostsManagerHost>(`/api/modules/hosts-manager/hosts/${encodeURIComponent(id)}/approve`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  disableHostsManagerHost: (id: string) => request<HostsManagerHost>(`/api/modules/hosts-manager/hosts/${encodeURIComponent(id)}/disable`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  hostsManagerGroups: () => request<HostsManagerGroup[]>("/api/modules/hosts-manager/groups"),
  saveHostsManagerGroup: (payload: Record<string, unknown>, id = "") => request<HostsManagerGroup>(id ? `/api/modules/hosts-manager/groups/${encodeURIComponent(id)}` : "/api/modules/hosts-manager/groups", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  deleteHostsManagerGroup: (id: string) => request<{ ok: boolean }>(`/api/modules/hosts-manager/groups/${encodeURIComponent(id)}`, { method: "DELETE" }),
  hostsManagerCredentials: () => request<HostsManagerCredential[]>("/api/modules/hosts-manager/credentials"),
  createHostsManagerEnrollmentToken: (payload: HostsManagerEnrollmentInput) => request<HostsManagerEnrollmentToken>("/api/modules/hosts-manager/enrollment-tokens", { method: "POST", body: JSON.stringify(payload) }),
  hostsManagerEnrollmentTokens: () => request<HostsManagerEnrollmentToken[]>("/api/modules/hosts-manager/enrollment-tokens"),
  revokeHostsManagerEnrollmentToken: (id: string) => request<{ ok: boolean }>(`/api/modules/hosts-manager/enrollment-tokens/${encodeURIComponent(id)}`, { method: "DELETE" }),
  downloadHostsManagerEnrollmentScript: (url: string, token: string) => enrollmentScript(url, token),
  hostsManagerCapabilities: (id: string) => request<HostsManagerCapability[]>(`/api/modules/hosts-manager/hosts/${encodeURIComponent(id)}/capabilities`),
  hostsManagerActionPlan: (id: string, capability: string, parameters: Record<string, unknown> = {}) => request<Record<string, unknown>>(`/api/modules/hosts-manager/hosts/${encodeURIComponent(id)}/actions/${encodeURIComponent(capability)}/plan`, { method: "POST", body: JSON.stringify({ parameters, confirm: false, confirmation_text: "" }) }),
  executeHostsManagerAction: (id: string, capability: string, parameters: Record<string, unknown> = {}, confirmationText = "") => request<Record<string, unknown>>(`/api/modules/hosts-manager/hosts/${encodeURIComponent(id)}/actions/${encodeURIComponent(capability)}/execute`, { method: "POST", body: JSON.stringify({ parameters, confirm: true, confirmation_text: confirmationText }) }),
  hostsManagerOperations: () => request<HostsManagerOperation[]>("/api/modules/hosts-manager/operations"),
  hostsManagerRepositories: () => request<HostsManagerRepository[]>("/api/modules/hosts-manager/repositories"),
  saveHostsManagerRepository: (payload: Record<string, unknown>, id = "") => request<Record<string, unknown>>(id ? `/api/modules/hosts-manager/repositories/${encodeURIComponent(id)}` : "/api/modules/hosts-manager/repositories", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  syncHostsManagerRepository: (id: string) => request<Record<string, unknown>>(`/api/modules/hosts-manager/repositories/${encodeURIComponent(id)}/sync`, { method: "POST", body: JSON.stringify({ confirm: true, confirmation_text: "" }) }),
  hostsManagerPowerProfiles: () => request<HostsManagerPowerProfile[]>("/api/modules/hosts-manager/power-profiles"),
  saveHostsManagerPowerProfile: (payload: Record<string, unknown>, id = "") => request<Record<string, unknown>>(id ? `/api/modules/hosts-manager/power-profiles/${encodeURIComponent(id)}` : "/api/modules/hosts-manager/power-profiles", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  hostsManagerPowerPlan: (id: string, action: string) => request<Record<string, unknown>>(`/api/modules/hosts-manager/hosts/${encodeURIComponent(id)}/power/plan`, { method: "POST", body: JSON.stringify({ action, confirm: false, confirmation_text: "" }) }),
  executeHostsManagerPower: (id: string, action: string, confirmationText = "") => request<Record<string, unknown>>(`/api/modules/hosts-manager/hosts/${encodeURIComponent(id)}/power/execute`, { method: "POST", body: JSON.stringify({ action, confirm: true, confirmation_text: confirmationText }) }),
  startHostsManagerScan: (payload: Record<string, unknown>) => request<Record<string, unknown>>("/api/modules/hosts-manager/scans", { method: "POST", body: JSON.stringify(payload) }),
  validateHostsManagerInventory: (content: string, format = "yaml") => request<Record<string, unknown>>("/api/modules/hosts-manager/inventory/validate", { method: "POST", body: JSON.stringify({ content, format, confirm: false }) }),
  importHostsManagerInventory: (content: string, format = "yaml") => request<Record<string, unknown>>("/api/modules/hosts-manager/inventory/import", { method: "POST", body: JSON.stringify({ content, format, confirm: true }) }),
  saveHostsManagerCredential: (payload: Record<string, unknown>, id = "") => request<Record<string, unknown>>(id ? `/api/modules/hosts-manager/credentials/${encodeURIComponent(id)}` : "/api/modules/hosts-manager/credentials", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  hostsManagerDiagnostics: () => request<{ schema_version: number; checks: Array<{ id: string; status: string; message: string }> }>("/api/modules/hosts-manager/diagnostics"),
  hostsManagerBackups: () => request<HostsManagerBackup[]>("/api/modules/hosts-manager/backups"),
  createHostsManagerBackup: (description = "") => request<Record<string, unknown>>("/api/modules/hosts-manager/backups", { method: "POST", body: JSON.stringify({ description, include_credentials: false, include_repositories: false, confirm: true }) }),
  ansibleHosts: () => request<AnsibleHost[]>("/api/modules/ansible-controller/hosts"),
  ansibleHost: (id: string) => request<AnsibleHost>(`/api/modules/ansible-controller/hosts/${encodeURIComponent(id)}`),
  saveAnsibleHost: (payload: Record<string, unknown>, id = "") => request<AnsibleHost>(id ? `/api/modules/ansible-controller/hosts/${encodeURIComponent(id)}` : "/api/modules/ansible-controller/hosts", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  createAnsibleEnrollmentToken: (payload: { hostname_pattern: string; ssh_user: string; port: number; credential_id: string | null; environment: string; location: string; tags: string[]; expires_minutes: number }) => request<AnsibleEnrollmentToken>("/api/modules/ansible-controller/enrollment-tokens", { method: "POST", body: JSON.stringify(payload) }),
  deleteAnsibleHost: (id: string) => request<{ ok: boolean }>(`/api/modules/ansible-controller/hosts/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),
  scanAnsibleHostKey: (id: string) => request<{ host_id: string; keys: Array<{ key_type: string; public_key: string; fingerprint: string }>; existing_fingerprint?: string | null; changed: boolean; requires_acceptance: boolean }>(`/api/modules/ansible-controller/hosts/${encodeURIComponent(id)}/ssh-key/scan`, { method: "POST", body: "{}" }),
  acceptAnsibleHostKey: (id: string, key: { public_key: string; fingerprint: string }, replace = false) => request<Record<string, unknown>>(`/api/modules/ansible-controller/hosts/${encodeURIComponent(id)}/ssh-key/accept`, { method: "POST", body: JSON.stringify({ ...key, replace, confirm: true }) }),
  testAnsibleHost: (id: string) => request<{ job: ModuleJob }>(`/api/modules/ansible-controller/hosts/${encodeURIComponent(id)}/test`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  gatherAnsibleFacts: (id: string) => request<{ job: ModuleJob }>(`/api/modules/ansible-controller/hosts/${encodeURIComponent(id)}/facts`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  rotateAnsibleHostKey: (id: string) => request<{ job: ModuleJob }>(`/api/modules/ansible-controller/hosts/${encodeURIComponent(id)}/managed-key/rotate`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  onboardAnsibleHost: (payload: Record<string, unknown>) => request<{ host: AnsibleHost; job: ModuleJob; onboarding_id: string }>("/api/modules/ansible-controller/onboarding", { method: "POST", body: JSON.stringify({ ...payload, confirm: true }) }),
  ansibleGroups: () => request<AnsibleGroup[]>("/api/modules/ansible-controller/groups"),
  saveAnsibleGroup: (payload: Record<string, unknown>, id = "") => request<AnsibleGroup>(id ? `/api/modules/ansible-controller/groups/${encodeURIComponent(id)}` : "/api/modules/ansible-controller/groups", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  ansibleInventory: () => request<{ format: string; content: string }>("/api/modules/ansible-controller/inventory"),
  importAnsibleInventory: (content: string, format: "yaml" | "ini", confirm = false) => request<Record<string, unknown>>("/api/modules/ansible-controller/inventory/import", { method: "POST", body: JSON.stringify({ content, format, confirm }) }),
  ansibleScans: () => request<AnsibleScan[]>("/api/modules/ansible-controller/scans"),
  ansibleScan: (id: string) => request<AnsibleScan>(`/api/modules/ansible-controller/scans/${encodeURIComponent(id)}`),
  startAnsibleScan: (payload: Record<string, unknown>) => request<{ scan: AnsibleScan; job: ModuleJob; address_count: number }>("/api/modules/ansible-controller/scans", { method: "POST", body: JSON.stringify({ ...payload, confirm: true }) }),
  importAnsibleScan: (id: string, hostIds: string[], groupName = "") => request<{ hosts: AnsibleHost[]; imported: number }>(`/api/modules/ansible-controller/scans/${encodeURIComponent(id)}/import`, { method: "POST", body: JSON.stringify({ host_ids: hostIds, group_name: groupName, confirm: true }) }),
  ansibleCredentials: () => request<AnsibleCredential[]>("/api/modules/ansible-controller/credentials"),
  saveAnsibleCredential: (payload: Record<string, unknown>, id = "") => request<AnsibleCredential>(id ? `/api/modules/ansible-controller/credentials/${encodeURIComponent(id)}` : "/api/modules/ansible-controller/credentials", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  deleteAnsibleCredential: (id: string) => request<{ ok: boolean }>(`/api/modules/ansible-controller/credentials/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),
  ansibleProjects: () => request<AnsibleProject[]>("/api/modules/ansible-controller/projects"),
  saveAnsibleProject: (payload: Record<string, unknown>, id = "") => request<AnsibleProject>(id ? `/api/modules/ansible-controller/projects/${encodeURIComponent(id)}` : "/api/modules/ansible-controller/projects", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  syncAnsibleProject: (id: string) => request<{ job: ModuleJob }>(`/api/modules/ansible-controller/projects/${encodeURIComponent(id)}/sync`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  ansiblePlaybooks: () => request<AnsiblePlaybook[]>("/api/modules/ansible-controller/playbooks"),
  validateAnsiblePlaybook: (payload: Record<string, unknown>) => request<AnsibleValidation>("/api/modules/ansible-controller/playbooks/validate", { method: "POST", body: JSON.stringify(payload) }),
  saveAnsiblePlaybook: (payload: Record<string, unknown>, id = "") => request<AnsiblePlaybook>(id ? `/api/modules/ansible-controller/playbooks/${encodeURIComponent(id)}` : "/api/modules/ansible-controller/playbooks", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  deleteAnsiblePlaybook: (id: string) => request<{ ok: boolean }>(`/api/modules/ansible-controller/playbooks/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),
  ansibleTemplates: () => request<AnsibleTemplate[]>("/api/modules/ansible-controller/templates"),
  saveAnsibleTemplate: (payload: Record<string, unknown>, id = "") => request<AnsibleTemplate>(id ? `/api/modules/ansible-controller/templates/${encodeURIComponent(id)}` : "/api/modules/ansible-controller/templates", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  ansibleLaunchPlan: (id: string) => request<Record<string, unknown>>(`/api/modules/ansible-controller/templates/${encodeURIComponent(id)}/plan`),
  launchAnsibleTemplate: (id: string) => request<{ execution: AnsibleExecution; job: ModuleJob }>(`/api/modules/ansible-controller/templates/${encodeURIComponent(id)}/launch`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  ansibleJobs: () => request<AnsibleExecution[]>("/api/modules/ansible-controller/jobs"),
  ansibleJob: (id: string) => request<AnsibleExecution>(`/api/modules/ansible-controller/jobs/${encodeURIComponent(id)}`),
  cancelAnsibleJob: (id: string) => request<{ job: ModuleJob }>(`/api/modules/ansible-controller/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  retryAnsibleJob: (id: string) => request<{ execution: AnsibleExecution; job: ModuleJob }>(`/api/modules/ansible-controller/jobs/${encodeURIComponent(id)}/retry`, { method: "POST", body: JSON.stringify({ confirm: true }) }),
  ansibleSchedules: () => request<AnsibleSchedule[]>("/api/modules/ansible-controller/schedules"),
  saveAnsibleSchedule: (payload: Record<string, unknown>, id = "") => request<AnsibleSchedule>(id ? `/api/modules/ansible-controller/schedules/${encodeURIComponent(id)}` : "/api/modules/ansible-controller/schedules", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  ansibleFacts: (hostId = "") => request<Array<Record<string, unknown>>>(`/api/modules/ansible-controller/facts${hostId ? `?host_id=${encodeURIComponent(hostId)}` : ""}`),
  ansibleDiagnostics: () => request<{ diagnostics: ModuleDiagnostic[] }>("/api/modules/ansible-controller/diagnostics"),
  ansibleBackups: () => request<ModuleBackup[]>("/api/modules/ansible-controller/backups"),
  createAnsibleBackup: (description = "", includeCredentials = false) => request<{ job: ModuleJob }>("/api/modules/ansible-controller/backups", { method: "POST", body: JSON.stringify({ description, include_credentials: includeCredentials, confirm: true }) }),
  restoreAnsibleBackup: (id: string, checksum: string, includeCredentials = false) => request<{ job: ModuleJob }>(`/api/modules/ansible-controller/backups/${encodeURIComponent(id)}/restore`, { method: "POST", body: JSON.stringify({ checksum, include_credentials: includeCredentials, confirm: true }) }),
  deleteAnsibleBackup: (id: string) => request<{ ok: boolean }>(`/api/modules/ansible-controller/backups/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),
  dockerDashboard: () => request<DockerDashboard>("/api/modules/docker/dashboard"),
  dockerEngine: () => request<{ status: ModuleStatus; config: Record<string, unknown>; diagnostics: ModuleDiagnostic[] }>("/api/modules/docker/engine"),
  dockerEngineAction: (payload: DockerEngineAction) => request<{ job?: ModuleJob; diagnostics?: ModuleDiagnostic[] }>("/api/modules/docker/engine/actions", { method: "POST", body: JSON.stringify(payload) }),
  dockerDaemonConfig: () => request<{ config: Record<string, unknown>; path: string; valid: boolean; error: string }>("/api/modules/docker/daemon-config"),
  validateDockerDaemonConfig: (config: Record<string, unknown>) => request<ModuleValidationResult>("/api/modules/docker/daemon-config/validate", { method: "POST", body: JSON.stringify({ config, confirmation: "" }) }),
  saveDockerDaemonConfig: (config: Record<string, unknown>, pamPassword: string) => request<{ job: ModuleJob; validation: ModuleValidationResult }>("/api/modules/docker/daemon-config", { method: "PUT", body: JSON.stringify({ config, confirmation: "daemon.json", pam_password: pamPassword }) }),
  dockerContainers: (params: Record<string, string | number> = {}) => { const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => query.set(key, String(value))); return request<DockerPaged<DockerContainer>>(`/api/modules/docker/containers?${query}`); },
  dockerContainer: (target: string) => request<Record<string, unknown>>(`/api/modules/docker/containers/${encodeURIComponent(target)}`),
  dockerContainerStats: (target: string, historyHours = 1) => request<{ current: Record<string, unknown> | null; history: Array<Record<string, unknown>> }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/stats?history_hours=${historyHours}`),
  dockerContainerLogs: (target: string, params: Record<string, string | number> = {}) => { const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => query.set(key, String(value))); return request<{ lines: string[]; total: number; truncated: boolean }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/logs?${query}`); },
  dockerContainerProcesses: (target: string) => request<{ items: Array<Record<string, string>>; total: number; truncated: boolean }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/processes`),
  dockerContainerCompose: (target: string) => request<{ content: string; secrets_omitted: boolean; environment_keys: string[] }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/compose`),
  dockerContainerSettings: (target: string) => request<DockerContainerSettings>(`/api/modules/docker/containers/${encodeURIComponent(target)}/settings`),
  updateDockerContainerSettings: (target: string, payload: DockerContainerSettingsUpdate) => request<{ job: ModuleJob }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/settings`, { method: "PUT", body: JSON.stringify(payload) }),
  dockerContainerDefaultsPolicy: () => request<DockerContainerDefaultsPolicy>("/api/modules/docker/policy/container-defaults"),
  saveDockerContainerDefaultsPolicy: (payload: DockerContainerDefaultsPolicy) => request<DockerContainerDefaultsPolicy>("/api/modules/docker/policy/container-defaults", { method: "PUT", body: JSON.stringify(payload) }),
  createDockerContainer: (payload: DockerContainerCreate) => request<{ job: ModuleJob }>("/api/modules/docker/containers", { method: "POST", body: JSON.stringify(payload) }),
  dockerContainerAction: (target: string, payload: DockerContainerAction) => request<{ job: ModuleJob }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/actions`, { method: "POST", body: JSON.stringify(payload) }),
  dockerContainerBackup: (target: string) => request<{ job: ModuleJob }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/backup?confirmation=${encodeURIComponent(target)}`, { method: "POST", body: "{}" }),
  dockerContainerExport: (target: string) => request<{ job: ModuleJob }>(`/api/modules/docker/containers/${encodeURIComponent(target)}/export?confirmation=${encodeURIComponent(target)}`, { method: "POST", body: "{}" }),
  importDockerContainerFilesystem: (file: File, repository: string) => { const body = new FormData(); body.set("file", file); body.set("repository", repository); body.set("confirmation", repository); return request<{ job: ModuleJob }>("/api/modules/docker/containers/import", { method: "POST", body }); },
  dockerImages: (params: Record<string, string | number> = {}) => { const query = new URLSearchParams(); Object.entries(params).forEach(([key, value]) => query.set(key, String(value))); return request<DockerPaged<DockerImage>>(`/api/modules/docker/images?${query}`); },
  dockerImageAction: (payload: DockerImageAction) => request<{ job: ModuleJob }>("/api/modules/docker/images/actions", { method: "POST", body: JSON.stringify(payload) }),
  importDockerImage: (file: File) => { const body = new FormData(); body.set("file", file); return request<{ job: ModuleJob }>("/api/modules/docker/images/import", { method: "POST", body }); },
  dockerVolumes: (search = "") => request<DockerPaged>(`/api/modules/docker/volumes?search=${encodeURIComponent(search)}`),
  createDockerVolume: (payload: DockerVolumeCreate) => request<{ job: ModuleJob }>("/api/modules/docker/volumes", { method: "POST", body: JSON.stringify(payload) }),
  dockerVolumeAction: (target: string, payload: DockerVolumeAction) => request<{ job: ModuleJob }>(`/api/modules/docker/volumes/${encodeURIComponent(target)}/actions`, { method: "POST", body: JSON.stringify(payload) }),
  dockerNetworks: (search = "") => request<DockerPaged<DockerNetwork>>(`/api/modules/docker/networks?page_size=200&search=${encodeURIComponent(search)}`),
  dockerNetworkContainers: (target: string) => request<{ items: DockerNetworkContainer[]; total: number; network: string }>(`/api/modules/docker/networks/${encodeURIComponent(target)}/containers`),
  dockerDefaultBridge: () => request<DockerDefaultBridgeConfig>("/api/modules/docker/networks/default-bridge"),
  saveDockerDefaultBridge: (payload: DockerDefaultBridgeSave) => request<{ job: ModuleJob; validation: ModuleValidationResult }>("/api/modules/docker/networks/default-bridge", { method: "PUT", body: JSON.stringify(payload) }),
  createDockerNetwork: (payload: DockerNetworkCreate) => request<{ job: ModuleJob }>("/api/modules/docker/networks", { method: "POST", body: JSON.stringify(payload) }),
  dockerNetworkAction: (target: string, payload: DockerNetworkAction) => request<{ job: ModuleJob }>(`/api/modules/docker/networks/${encodeURIComponent(target)}/actions`, { method: "POST", body: JSON.stringify(payload) }),
  dockerComposeProjects: () => request<ModuleResource>("/api/modules/docker/compose"),
  dockerComposeProject: (project: string) => request<{ name: string; content: string; environment: Record<string, string>; secrets_configured: boolean; history: Array<Record<string, unknown>>; plan: Record<string, unknown> }>(`/api/modules/docker/compose/${encodeURIComponent(project)}`),
  saveDockerComposeProject: (project: string, payload: DockerComposeSave) => request<Record<string, unknown>>(`/api/modules/docker/compose/${encodeURIComponent(project)}`, { method: "PUT", body: JSON.stringify(payload) }),
  validateDockerCompose: (project: string, payload: DockerComposeSave) => request<Record<string, unknown>>(`/api/modules/docker/compose/${encodeURIComponent(project)}/validate`, { method: "POST", body: JSON.stringify(payload) }),
  dockerComposeAction: (project: string, payload: DockerComposeAction) => request<{ job?: ModuleJob; valid?: boolean }>(`/api/modules/docker/compose/${encodeURIComponent(project)}/actions`, { method: "POST", body: JSON.stringify(payload) }),
  rollbackDockerCompose: (project: string, revision: string, confirmation: string) => request<Record<string, unknown>>(`/api/modules/docker/compose/${encodeURIComponent(project)}/history/${encodeURIComponent(revision)}/rollback?confirmation=${encodeURIComponent(confirmation)}`, { method: "POST", body: "{}" }),
  dockerComposeStatus: (project: string) => request<{ items: Array<Record<string, unknown>>; total: number }>(`/api/modules/docker/compose/${encodeURIComponent(project)}/status`),
  dockerComposeLogs: (project: string, service = "") => request<{ lines: string[]; total: number; truncated: boolean }>(`/api/modules/docker/compose/${encodeURIComponent(project)}/logs?tail=500&service=${encodeURIComponent(service)}`),
  dockerApps: (search = "") => request<{ items: DockerApp[]; total: number }>(`/api/modules/docker/apps?search=${encodeURIComponent(search)}`),
  installDockerApp: (id: string, payload: DockerAppInstall) => request<{ job: ModuleJob }>(`/api/modules/docker/apps/${encodeURIComponent(id)}/install`, { method: "POST", body: JSON.stringify(payload) }),
  dockerAppAction: (id: string, action: "start" | "stop" | "restart" | "update" | "remove", payload: DockerAppAction = {}) => request<{ job: ModuleJob }>(`/api/modules/docker/apps/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify(payload) }),
  dockerRegistries: () => request<{ items: DockerRegistry[] }>("/api/modules/docker/registries"),
  dockerRegistrySources: () => request<DockerRegistrySource[]>("/api/modules/docker/registries/sources"),
  dockerRegistryCatalog: (params: { registry_id: string; query: string; page?: number; page_size?: number; official?: "all" | "official" | "unofficial"; sort?: "relevance" | "name" | "stars"; direction?: "asc" | "desc" }) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => value !== undefined && query.set(key, String(value)));
    return request<DockerRegistryCatalogResult>(`/api/modules/docker/registries/catalog?${query}`);
  },
  dockerRegistryTags: (registryId: string, repositoryName: string, page = 1, pageSize = 100) => {
    const query = new URLSearchParams({ registry_id: registryId, repository_name: repositoryName, page: String(page), page_size: String(pageSize) });
    return request<DockerRegistryTagsResult>(`/api/modules/docker/registries/tags?${query}`);
  },
  saveDockerRegistry: (payload: DockerRegistrySave, id = "") => request<{ registry: DockerRegistry; job: ModuleJob }>(id ? `/api/modules/docker/registries/${encodeURIComponent(id)}` : "/api/modules/docker/registries", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }),
  testDockerRegistry: (id: string) => request<{ job: ModuleJob }>(`/api/modules/docker/registries/${encodeURIComponent(id)}/test`, { method: "POST", body: "{}" }),
  logoutDockerRegistry: (id: string) => request<{ job: ModuleJob }>(`/api/modules/docker/registries/${encodeURIComponent(id)}/logout`, { method: "POST", body: "{}" }),
  deleteDockerRegistry: (id: string, confirmation: string) => request<{ ok: boolean }>(`/api/modules/docker/registries/${encodeURIComponent(id)}?confirmation=${encodeURIComponent(confirmation)}`, { method: "DELETE", body: "{}" }),
  dockerBackups: () => request<{ configuration: ModuleBackup[]; artifacts: DockerArtifact[] }>("/api/modules/docker/backups"),
  restoreDockerBackup: (id: string, payload: DockerBackupRestore) => request<{ job: ModuleJob }>(`/api/modules/docker/backups/${encodeURIComponent(id)}/restore`, { method: "POST", body: JSON.stringify(payload) }),
  dockerDiagnostics: () => request<{ generated_at: number; status: ModuleStatus; checks: ModuleDiagnostic[]; config: Record<string, unknown>; prune: Record<string, unknown> }>("/api/modules/docker/diagnostics"),
  dockerEvents: () => request<{ items: Array<Record<string, unknown>>; total: number }>("/api/modules/docker/events?since_seconds=3600&limit=500"),
  dockerPrune: (payload: DockerPrune) => request<{ job: ModuleJob }>("/api/modules/docker/prune", { method: "POST", body: JSON.stringify(payload) }),
  dockerPrunePlan: (resources: DockerPrune["resources"]) => request<DockerPrunePlan>(`/api/modules/docker/prune/plan?resources=${encodeURIComponent(resources.join(","))}`),
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
