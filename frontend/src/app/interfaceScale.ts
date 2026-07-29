export const INTERFACE_SCALE_DEFAULT = 100;
export const INTERFACE_SCALE_OPTIONS = [80, 90, 100, 110, 125] as const;
export const ALLOWED_UI_SCALES = [0.8, 0.9, 1, 1.1, 1.25] as const;

function nearestInterfaceScale(value: number): number {
  return INTERFACE_SCALE_OPTIONS.reduce((nearest, option) =>
    Math.abs(option - value) < Math.abs(nearest - value) ? option : nearest
  );
}

export function normalizeInterfaceScale(value: unknown): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return INTERFACE_SCALE_DEFAULT;
  if (ALLOWED_UI_SCALES.includes(parsed as (typeof ALLOWED_UI_SCALES)[number])) return Math.round(parsed * 100);
  if (parsed < 50 || parsed > 200) return INTERFACE_SCALE_DEFAULT;
  return nearestInterfaceScale(parsed);
}

export function interfaceScaleFactor(value: unknown): number {
  return normalizeInterfaceScale(value) / 100;
}

export function migrateLegacyInterfaceScale(value: unknown, largerText: boolean): number {
  const normalized = normalizeInterfaceScale(value);
  return largerText ? nearestInterfaceScale(normalized * 1.1) : normalized;
}
