import { request } from "../../../core/api/transport";
import type { SystemLogs, SystemdService } from "../../../core/api/contracts";

const MANAGED_WEBNAS_UNIT_RE = /^webnas(?:-backend-(?:blue|green))?\.service$/;
const MISSING_UNIT_FILE_STATES = new Set(["", "unknown", "not-found", "bad"]);

export function isMissingManagedWebnasUnit(service: SystemdService): boolean {
  if (!MANAGED_WEBNAS_UNIT_RE.test(service.name)) return false;
  if (service.status === "active") return false;
  return MISSING_UNIT_FILE_STATES.has((service.enabled || "").toLowerCase());
}

export function filterUnavailableManagedWebnasUnits(services: SystemdService[]): SystemdService[] {
  return services.filter((service) => !isMissingManagedWebnasUnit(service));
}

export const servicesClient = {
  systemdServices: async () => filterUnavailableManagedWebnasUnits(await request<SystemdService[]>("/api/admin/system/services")),
  systemdServiceAction: (service: string, action: "start" | "stop" | "restart" | "enable" | "disable", confirm_restart = false) => request<SystemdService>(`/api/admin/system/services/${encodeURIComponent(service)}/${action}`, { method: "POST", body: JSON.stringify({ confirm_restart }) }),
  systemdServiceLogs: (service: string, lines = 200) => request<SystemLogs>(`/api/admin/system/services/${encodeURIComponent(service)}/logs?lines=${lines}`)
} as const;
