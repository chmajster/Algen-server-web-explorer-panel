import { request } from "../../../core/api/transport";
import type { SettingsMe, SettingsPatch, WallpaperItem } from "../../../core/api/contracts";

export type TransportSettings = {
  use_https: boolean;
  tls_cert: string;
  tls_key: string;
  scheme: "http" | "https";
  public_port: number;
};

type AuthMe = {
  username: string;
  home: string;
  csrf_token: string;
  auth_provider?: "local" | "pam" | "ldap";
};

export const settingsClient = {
  settingsMe: () => request<SettingsMe>("/api/settings/me"),
  updateSettings: (payload: SettingsPatch) => request<SettingsMe>("/api/settings/me", { method: "PATCH", body: JSON.stringify(payload) }),
  wallpapers: () => request<{ items: WallpaperItem[]; max_files: number; max_file_size: number }>("/api/settings/wallpapers"),
  uploadWallpaper: (file: File) => { const body = new FormData(); body.set("file", file); return request<WallpaperItem>("/api/settings/wallpapers", { method: "POST", body }); },
  deleteWallpaper: (wallpaperId: string) => request<{ ok: boolean }>(`/api/settings/wallpapers/${wallpaperId}`, { method: "DELETE", body: "{}" }),
  transportSettings: () => request<TransportSettings>("/api/settings/transport"),
  saveTransportSettings: (payload: Pick<TransportSettings, "use_https" | "tls_cert" | "tls_key">) => request<TransportSettings>("/api/settings/transport", { method: "PUT", body: JSON.stringify(payload) }),
  changeMyPassword: async (current_password: string, new_password: string) => {
    const session = await request<AuthMe>("/api/auth/me", { cache: "no-store" });
    if (session.auth_provider === "local") {
      return request("/api/settings/authentication/local-password", {
        method: "POST",
        body: JSON.stringify({ current_password, new_password }),
      });
    }
    if (session.auth_provider === "ldap") {
      throw new Error("LDAP passwords are managed by the directory service and cannot be changed by WebNAS.");
    }
    return request("/api/settings/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    });
  },
} as const;
