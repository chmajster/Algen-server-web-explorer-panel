import { request } from "../../../core/api/transport";

export type StorageIssue = {
  severity: "warning" | "error" | "critical";
  code: string;
  target: string;
  message: string;
};

export type StorageDevice = {
  name: string;
  kernel_name: string;
  path: string;
  type: string;
  size: number;
  filesystem: string;
  filesystem_version: string;
  label: string;
  uuid: string;
  partuuid?: string;
  mountpoints: string[];
  read_only: boolean;
  removable: boolean;
  hotplug?: boolean;
  rotational?: boolean | null;
  media_type?: "hdd" | "ssd" | "nvme" | "unknown" | string;
  device_mapper?: boolean;
  encrypted?: boolean;
  model: string;
  serial: string;
  transport: string;
  parent_kernel_name: string;
  partition_type: string;
  partition_label: string;
  protected: boolean;
  children: StorageDevice[];
};

export type DeviceHealth = {
  device: string;
  model?: string;
  serial?: string;
  protected: boolean;
  provider: string;
  available: boolean;
  state: string;
  warnings?: string[];
  passed?: boolean | null;
  temperature_c?: number | null;
  power_on_hours?: number | null;
  reallocated_sectors?: number | null;
  pending_sectors?: number | null;
  uncorrectable_sectors?: number | null;
  critical_warning?: number;
  percentage_used?: number | null;
  available_spare_percent?: number | null;
  available_spare_threshold_percent?: number | null;
  media_errors?: number;
  unsafe_shutdowns?: number;
  error_log_entries?: number;
  tool_exit_code?: number;
};

export type FilesystemItem = {
  source: string;
  mount_point: string;
  filesystem: string;
  options: string[];
  read_only: boolean;
  total: number;
  used: number;
  free: number;
  free_percent: number;
  protected: boolean;
};

export type MdArray = {
  name: string;
  activity: string;
  level: string;
  members: string[];
  member_state: string;
  state: string;
};

export type ZfsPool = {
  name: string;
  health: string;
  size: number;
  allocated: number;
  free: number;
  state: string;
};

export type BtrfsFilesystem = {
  mount_point: string;
  state: string;
  available: boolean;
  tool_exit_code?: number;
};

export type StorageSnapshot = {
  state: "ok" | "degraded" | "critical" | string;
  read_only: true;
  generated_at: number;
  duration_ms: number;
  tools: Record<string, boolean>;
  devices: StorageDevice[];
  device_health: DeviceHealth[];
  filesystems: FilesystemItem[];
  md_arrays: MdArray[];
  zfs_pools: ZfsPool[];
  btrfs_filesystems: BtrfsFilesystem[];
  issues: StorageIssue[];
};

export type LvmPhysicalVolume = {
  path: string;
  volume_group: string;
  size: number;
  free: number;
  attributes: string;
};

export type LvmVolumeGroup = {
  name: string;
  size: number;
  free: number;
  pv_count: number;
  lv_count: number;
  attributes: string;
};

export type LvmLogicalVolume = {
  name: string;
  volume_group: string;
  path: string;
  size: number;
  attributes: string;
  pool: string;
  origin: string;
  data_percent: number | null;
  metadata_percent: number | null;
  thin_pool: boolean;
};

export type LvmRelationship = {
  volume_group: string;
  physical_volumes: string[];
  logical_volumes: string[];
};

export type LvmInventory = {
  available: boolean;
  physical_volumes: LvmPhysicalVolume[];
  volume_groups: LvmVolumeGroup[];
  logical_volumes: LvmLogicalVolume[];
  relationships: LvmRelationship[];
};

export type SwapItem = {
  name: string;
  type: string;
  size: number;
  used: number;
  priority: number;
};

export type FstabEntry = {
  source: string;
  resolved_source: string;
  mount_point: string;
  filesystem: string;
  options: string[];
  dump: number;
  pass: number;
  active: boolean;
  current_source: string;
  current_filesystem: string;
  source_matches: boolean;
  source_mismatch: boolean;
  network: boolean;
  noauto: boolean;
  automount: boolean;
  protected: boolean;
  state: "active" | "inactive" | "disabled" | string;
};

export type DiskIoItem = {
  name: string;
  reads_completed: number;
  reads_merged: number;
  bytes_read: number;
  read_ms: number;
  writes_completed: number;
  writes_merged: number;
  bytes_written: number;
  write_ms: number;
  io_in_progress: number;
  io_ms: number;
  weighted_io_ms: number;
  discards_completed: number;
  bytes_discarded: number;
  discard_ms: number;
  flushes_completed: number;
  flush_ms: number;
};

export type IoSample = {
  read_only: true;
  sampled_at: number;
  monotonic_ns: number;
  counter_mode: "cumulative" | string;
  sector_bytes: number;
  delta_ready: boolean;
  devices: DiskIoItem[];
};

export type RaidArray = {
  name: string;
  activity: string;
  level: string;
  members: string[];
  failed_members: string[];
  member_state: string;
  expected_members: number;
  active_members: number;
  missing_members: number;
  blocks: number;
  operation: string;
  progress_percent: number | null;
  finish: string;
  speed: string;
  state: string;
};

export type ZfsMember = {
  name: string;
  path: string;
  state: string;
  read_errors: number;
  write_errors: number;
  checksum_errors: number;
};

export type ZfsScan = {
  action: string;
  state: string;
  progress_percent: number | null;
  raw: string;
};

export type ZfsPoolDetail = {
  name: string;
  health: string;
  size: number;
  allocated: number;
  free: number;
  state: string;
  members: ZfsMember[];
  scan: ZfsScan;
  errors: string;
};

export type ZfsDataset = {
  name: string;
  type: string;
  used: number;
  available: number;
  referenced: number;
  mount_point: string;
};

export type ZfsInventory = {
  available: boolean;
  datasets_available: boolean;
  pools: ZfsPoolDetail[];
  datasets: ZfsDataset[];
};

export type BtrfsDevice = {
  id: number;
  size: number;
  used: number;
  path: string;
};

export type BtrfsErrorDevice = {
  path: string;
  errors: Record<string, number>;
};

export type BtrfsProfile = {
  kind: string;
  profile: string;
  size: number;
  used: number;
};

export type BtrfsScrub = {
  state: string;
  status: string;
  progress_percent: number | null;
  error_summary: string;
};

export type BtrfsDetail = {
  mount_point: string;
  available: boolean;
  state: string;
  uuid: string;
  label: string;
  devices: BtrfsDevice[];
  device_errors: BtrfsErrorDevice[];
  total_errors: number;
  profiles: BtrfsProfile[];
  scrub: BtrfsScrub;
};

export type StoragePools = {
  raid: RaidArray[];
  zfs: ZfsInventory;
  btrfs: BtrfsDetail[];
};

export type StorageDashboard = {
  physical_disks: number;
  total_physical_capacity: number;
  filesystems: number;
  lvm_pv: number;
  lvm_vg: number;
  lvm_lv: number;
  raid_arrays: number;
  zfs_pools: number;
  btrfs_filesystems: number;
  unhealthy_devices: number;
  low_space_filesystems: number;
  device_mapper_entries: number;
  encrypted_entries: number;
};

export type StorageMounts = {
  read_only: true;
  active: FilesystemItem[];
  persistent: FstabEntry[];
  swap: SwapItem[];
};

export type StorageDetails = {
  read_only: true;
  generated_at: number;
  duration_ms: number;
  tools: Record<string, boolean>;
  dashboard: StorageDashboard;
  devices: StorageDevice[];
  device_health: DeviceHealth[];
  lvm: LvmInventory;
  swap: SwapItem[];
  fstab: FstabEntry[];
  mounts: StorageMounts;
  disk_io: DiskIoItem[];
  io: IoSample;
  pools: StoragePools;
  management: {
    mode: "read-only" | string;
    write_api_enabled: boolean;
    future_guardrails: string[];
  };
};

export const storageManagerClient = {
  summary: () => request<StorageSnapshot>("/api/storage/summary"),
  details: () => request<StorageDetails>("/api/storage/details"),
  lvm: () => request<{ read_only: true; lvm: LvmInventory }>("/api/storage/lvm"),
  mounts: () => request<StorageMounts>("/api/storage/mounts"),
  io: () => request<IoSample>("/api/storage/io"),
  pools: () => request<{ read_only: true } & StoragePools>("/api/storage/pools"),
} as const;
