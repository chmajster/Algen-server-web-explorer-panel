import { request } from "../../../core/api/transport";
import type { ActivityCategory, ActivityResponse, ActivityStatus, ActivitySummary } from "../../../core/api/contracts";

export const activityClient = {
  activity: (params: { category?: ActivityCategory | ""; status?: ActivityStatus | ""; actor?: string; search?: string; page?: number; page_size?: number } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") query.set(key, String(value));
    });
    return request<ActivityResponse>(`/api/activity${query.size ? `?${query}` : ""}`);
  },
  activitySummary: () => request<ActivitySummary>("/api/activity/summary")
} as const;
