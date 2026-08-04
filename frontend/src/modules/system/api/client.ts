import { request } from "../../../core/api/transport";
import type { HostInfo, ResourceDashboard, SystemStatus } from "../../../core/api/contracts";

export const systemClient = {
  systemStatus: () => request<SystemStatus>("/api/admin/system/status"),
  hostInfo: () => request<HostInfo>("/api/system/host-info"),
  resources: () => request<ResourceDashboard>("/api/system/resources")
} as const;
