import { request } from "../../../core/api/transport";
import type { SystemLogs, SystemdService } from "../../../core/api/contracts";

export const servicesClient = {
  systemdServices: () => request<SystemdService[]>("/api/admin/system/services"),
  systemdServiceAction: (service: string, action: "start" | "stop" | "restart" | "enable" | "disable", confirm_restart = false) => request<SystemdService>(`/api/admin/system/services/${encodeURIComponent(service)}/${action}`, { method: "POST", body: JSON.stringify({ confirm_restart }) }),
  systemdServiceLogs: (service: string, lines = 200) => request<SystemLogs>(`/api/admin/system/services/${encodeURIComponent(service)}/logs?lines=${lines}`)
} as const;
