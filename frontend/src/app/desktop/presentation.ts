import type { CSSProperties } from "react";
import type { SettingsMe } from "../../api";

export function desktopWallpaperStyle(profile: SettingsMe): CSSProperties {
  if (!profile.wallpaper) return {};
  const size = profile.wallpaper_fit === "stretch" ? "100% 100%" : profile.wallpaper_fit === "center" ? "auto" : profile.wallpaper_fit;
  return { backgroundImage: `url(${JSON.stringify(profile.wallpaper)})`, backgroundSize: size, backgroundPosition: "center", backgroundRepeat: "no-repeat" };
}

export function desktopDateText(date: Date, profile: SettingsMe): string {
  if (profile.date_format === "iso") return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  const options: Intl.DateTimeFormatOptions = profile.date_format === "long"
    ? { weekday: "short", day: "numeric", month: "long" }
    : profile.date_format === "locale" ? {} : { day: "2-digit", month: "2-digit", year: "numeric" };
  return date.toLocaleDateString(profile.language, options);
}
