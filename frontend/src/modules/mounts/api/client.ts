import { request } from "../../../core/api/transport";
import type { LocalDisk, MountActionResult, NetworkMount, NetworkMountPayload, NetworkMountRoot } from "../../../core/api/contracts";

export const mountsClient = {
  mounts: () => request<NetworkMount[]>("/api/mounts"),
  mountRoots: () => request<NetworkMountRoot[]>("/api/mounts/roots"),
  localDisks: () => request<LocalDisk[]>("/api/files/local-disks"),
  mount: (id: string) => request<NetworkMount>(`/api/mounts/${encodeURIComponent(id)}`),
  createMount: (payload: NetworkMountPayload) => request<NetworkMount>("/api/mounts", { method: "POST", body: JSON.stringify(payload) }),
  updateMount: (id: string, payload: NetworkMountPayload) => request<NetworkMount>(`/api/mounts/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteMount: (id: string, confirm_destructive = true) => request(`/api/mounts/${encodeURIComponent(id)}`, { method: "DELETE", body: JSON.stringify({ confirm_destructive }) }),
  mountAction: (id: string, action: "mount" | "unmount" | "remount" | "test" | "migrate", dry_run = false, force_empty_mountpoint = false) => request<MountActionResult>(`/api/mounts/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify({ dry_run, force_empty_mountpoint, confirm_destructive: ["unmount", "remount", "migrate"].includes(action) }) }),
  mountLogs: (id: string) => request<{ lines: string[] }>(`/api/mounts/${encodeURIComponent(id)}/logs`)
} as const;
