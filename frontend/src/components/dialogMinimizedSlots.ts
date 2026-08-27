const minimizedSlots = new Set<number>();

export function reserveDialogMinimizedSlot(): number {
  let slot = 0;
  while (minimizedSlots.has(slot)) slot += 1;
  minimizedSlots.add(slot);
  return slot;
}

export function releaseDialogMinimizedSlot(slot: number | null): void {
  if (slot !== null) minimizedSlots.delete(slot);
}

export function minimizedDialogOffset(slot: number): string {
  return `${slot * 3}rem`;
}
