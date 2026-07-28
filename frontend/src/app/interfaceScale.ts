export const INTERFACE_SCALE_MIN = 50;
export const INTERFACE_SCALE_MAX = 200;
export const INTERFACE_SCALE_STEP = 5;
export const INTERFACE_SCALE_DEFAULT = 100;

export function normalizeInterfaceScale(value: unknown): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return INTERFACE_SCALE_DEFAULT;
  return Math.min(INTERFACE_SCALE_MAX, Math.max(INTERFACE_SCALE_MIN, parsed));
}

export function interfaceScaleFactor(value: unknown): number {
  return normalizeInterfaceScale(value) / 100;
}
