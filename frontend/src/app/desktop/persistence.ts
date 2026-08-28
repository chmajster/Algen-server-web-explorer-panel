import type { RecentApp } from "../types";

export function desktopStorageKeys(username: string) {
  const windows = `webnas_windows_${username}`;
  return {
    windows,
    sessionWindows: `${windows}_session`,
    recentApps: `webnas_recent_apps_${username}`,
    legacyPinnedApps: `webnas_pinned_apps_${username}`,
    draftPrefix: `webnas_window_draft_${username}_`,
  } as const;
}

export function readRecentApps(value: string | null, isKnownApp: (id: string) => boolean): RecentApp[] {
  try {
    const parsed = JSON.parse(value || "[]") as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is RecentApp => Boolean(
      item && typeof item === "object" && "id" in item && "usedAt" in item
      && typeof item.id === "string" && typeof item.usedAt === "number" && isKnownApp(item.id),
    )).slice(0, 8);
  } catch {
    return [];
  }
}

export function pushRecentApp(current: readonly RecentApp[], id: RecentApp["id"], usedAt = Date.now()): RecentApp[] {
  return [{ id, usedAt }, ...current.filter((item) => item.id !== id)].slice(0, 8);
}

export function clearWindowDrafts(storage: Storage, prefix: string) {
  Object.keys(storage).filter((key) => key.startsWith(prefix)).forEach((key) => storage.removeItem(key));
}
