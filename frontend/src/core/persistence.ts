export type StorageScope = "local" | "session";

function browserStorage(scope: StorageScope): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return scope === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function readStorageValue(key: string, scope: StorageScope = "local"): string | null {
  try {
    return browserStorage(scope)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function writeStorageValue(key: string, value: string, scope: StorageScope = "local"): boolean {
  try {
    const storage = browserStorage(scope);
    if (!storage) return false;
    storage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export function removeStorageValue(key: string, scope: StorageScope = "local"): boolean {
  try {
    const storage = browserStorage(scope);
    if (!storage) return false;
    storage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export function parseStoredStringArray(raw: string | null, maxItems = 100): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is string => typeof item === "string" && item.length > 0).slice(0, maxItems);
  } catch {
    return [];
  }
}

export function readStoredEnum<T extends string>(raw: string | null, allowed: readonly T[], fallback: T): T {
  return raw !== null && allowed.includes(raw as T) ? raw as T : fallback;
}

export function readStoredNumber(raw: string | null, fallback: number, minimum: number, maximum: number): number {
  if (raw === null || raw.trim() === "") return fallback;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(minimum, Math.min(maximum, parsed));
}
