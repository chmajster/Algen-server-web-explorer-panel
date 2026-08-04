import { request } from "../../../core/api/transport";
import type { ShutdownPolicy } from "../../../core/api/contracts";

type ScheduledPowerAction = {
  ok: boolean;
  scheduled: boolean;
  mode: string;
  unit: string;
  target: "host" | "application";
  service?: string;
};

export const powerClient = {
  restartSystem: () => request<ScheduledPowerAction>("/api/admin/host/restart", {
    method: "POST",
    body: JSON.stringify({ confirm: true }),
  }),
  restartApplication: () => request<ScheduledPowerAction>("/api/admin/application/restart", {
    method: "POST",
    body: JSON.stringify({ confirm: true }),
  }),
  shutdownStatus: () => request<{ state: "idle" | "scheduled" | "waiting_for_transfers" | "shutting_down" | "cancelled" | "failed"; deadline: number | null; remaining_seconds: number; blocker_count: number; error: string }>("/api/admin/system/shutdown"),
  scheduleShutdown: (delay_seconds = 10) => request<{ state: string; deadline: number | null; remaining_seconds: number; blocker_count: number; error: string }>("/api/admin/system/shutdown", { method: "POST", body: JSON.stringify({ delay_seconds }) }),
  cancelShutdown: () => request<{ state: string }>("/api/admin/system/shutdown", { method: "DELETE" }),
  shutdownPolicy: () => request<ShutdownPolicy>("/api/admin/system/shutdown-policy"),
  saveShutdownPolicy: (policy: ShutdownPolicy) => request<ShutdownPolicy>("/api/admin/system/shutdown-policy", { method: "PUT", body: JSON.stringify(policy) })
} as const;
