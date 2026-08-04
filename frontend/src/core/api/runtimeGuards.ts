export type UnknownRecord = Record<string, unknown>;

export function isRecord(value: unknown): value is UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function asRecord(value: unknown): UnknownRecord {
  return isRecord(value) ? value : {};
}

export function asArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

export function asRecordArray(value: unknown): UnknownRecord[] {
  return asArray(value).map(asRecord);
}

export function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : value === null || value === undefined ? fallback : String(value);
}

export function asStringArray(value: unknown): string[] {
  return asArray(value)
    .filter((item) => ["string", "number", "boolean"].includes(typeof item))
    .map(String);
}

export function asFiniteNumber(value: unknown, fallback = 0): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function asOptionalFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function asBoolean(value: unknown, fallback = false): boolean {
  if (typeof value === "boolean") return value;
  if (value === 1 || value === "1" || value === "true") return true;
  if (value === 0 || value === "0" || value === "false") return false;
  return fallback;
}

export function asNumberRecord(value: unknown): Record<string, number> {
  const output: Record<string, number> = {};
  for (const [key, item] of Object.entries(asRecord(value))) {
    output[key] = asFiniteNumber(item, 0);
  }
  return output;
}

export function normalizePagination(value: unknown) {
  const source = asRecord(value);
  const page = Math.max(1, Math.trunc(asFiniteNumber(source.page, 1)));
  const pageSize = Math.max(1, Math.trunc(asFiniteNumber(source.page_size, 20)));
  const total = Math.max(0, Math.trunc(asFiniteNumber(source.total, 0)));
  const pages = Math.max(1, Math.trunc(asFiniteNumber(source.pages, Math.ceil(total / pageSize) || 1)));
  return {
    ...source,
    page,
    page_size: pageSize,
    total,
    pages,
    has_next: asBoolean(source.has_next, page < pages),
    truncated: asBoolean(source.truncated, false),
  };
}
