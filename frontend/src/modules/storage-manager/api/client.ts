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
  mountpoints: string[];
  read_only: boolean;
  removable: boolean;
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
  passed?: boolean | null;
  temperature_c?: number | null;
  power_on_hours?: number | null;
  critical_warning?: number;
  percentage_used?: number | null;
  available_spare_percent?: number | null;
  media_errors?: number;
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
  mount_point: string;
  filesystem: string;
  options: string[];
  dump: number;
  pass: number;
  active: boolean;
  current_source: string;
  current_filesystem: string;
  noauto: boolean;
  automount: boolean;
  protected: boolean;
  state: "active" | "inactive" | "disabled" | string;
};

export type DiskIoItem = {
  name: string;
  reads_completed: number;
  bytes_read: number;
  read_ms: number;
  writes_completed: number;
  bytes_written: number;
  write_ms: number;
  io_in_progress: number;
  io_ms: number;
  weighted_io_ms: number;
};

export type StorageDetails = {
  read_only: true;
  generated_at: number;
  duration_ms: number;
  tools: Record<string, boolean>;
  lvm: {
    available: boolean;
    physical_volumes: LvmPhysicalVolume[];
    volume_groups: LvmVolumeGroup[];
    logical_volumes: LvmLogicalVolume[];
  };
  swap: SwapItem[];
  fstab: FstabEntry[];
  disk_io: DiskIoItem[];
};

export const storageManagerClient = {
  summary: () => request<StorageSnapshot>("/api/storage/summary"),
  details: () => request<StorageDetails>("/api/storage/details"),
} as const;
