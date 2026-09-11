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
