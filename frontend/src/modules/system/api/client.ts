import { request } from "../../../core/api/transport";
import type { HostInfo, ProcessMetric, ResourceDashboard, SystemStatus } from "../../../core/api/contracts";

export const systemClient = {
  systemStatus: () => request<SystemStatus>("/api/admin/system/status"),
  hostInfo: () => request<HostInfo>("/api/system/host-info"),
  resources: () => request<ResourceDashboard>("/api/system/resources"),
  resourceProcesses: () => request<ProcessMetric[]>("/api/system/processes")
} as const;
