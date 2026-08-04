import { request } from "../../../core/api/transport";
import type { SettingsMe, SettingsPatch, WallpaperItem } from "../../../core/api/contracts";

export const settingsClient = {
  settingsMe: () => request<SettingsMe>("/api/settings/me"),
  updateSettings: (payload: SettingsPatch) => request<SettingsMe>("/api/settings/me", { method: "PATCH", body: JSON.stringify(payload) }),
  wallpapers: () => request<{ items: WallpaperItem[]; max_files: number; max_file_size: number }>("/api/settings/wallpapers"),
  uploadWallpaper: (file: File) => { const body = new FormData(); body.set("file", file); return request<WallpaperItem>("/api/settings/wallpapers", { method: "POST", body }); },
  deleteWallpaper: (wallpaperId: string) => request<{ ok: boolean }>(`/api/settings/wallpapers/${encodeURIComponent(wallpaperId)}`, { method: "DELETE", body: "{}" }),
  changeMyPassword: (current_password: string, new_password: string) => request("/api/settings/change-password", { method: "POST", body: JSON.stringify({ current_password, new_password }) })
} as const;
