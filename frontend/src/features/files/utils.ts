export function joinPath(base: string, name: string) { return `${base.replace(/\/$/, "")}/${name}`; }
export function formatSize(size: number) {
  if (!Number.isFinite(size) || size <= 0) return size === 0 ? "0 B" : "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
  return `${(size / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}
export function formatDate(value: number | null | undefined) { return value ? new Date(value * 1000).toLocaleString() : "—"; }
