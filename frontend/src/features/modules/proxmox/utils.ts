export type EndpointFields = {
  address: string;
  port: string;
};

export function bytes(value: number): string {
  if (!value) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

export function percent(value: number): string {
  return `${Math.max(0, value * 100).toFixed(1)}%`;
}

export function duration(seconds: number): string {
  if (!seconds) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return [days ? `${days}d` : "", hours ? `${hours}h` : "", minutes ? `${minutes}m` : ""].filter(Boolean).join(" ") || "<1m";
}

export function splitEndpoint(value: string): EndpointFields {
  const trimmed = value.trim();
  const explicitScheme = /^https?:\/\//i.test(trimmed);
  try {
    const parsed = new URL(explicitScheme ? trimmed : `http://${trimmed}`);
    const defaultPort = explicitScheme
      ? parsed.protocol === "http:" ? "80" : "443"
      : "8006";
    const hostname = parsed.hostname.includes(":") ? `[${parsed.hostname}]` : parsed.hostname;
    return {
      address: hostname,
      port: parsed.port || defaultPort,
    };
  } catch {
    return {
      address: trimmed.replace(/^https?:\/\//i, "").replace(/:\d+\/?$/, ""),
      port: trimmed.match(/:(\d+)\/?$/)?.[1] || "8006",
    };
  }
}

export function buildEndpoint(address: string, port: string): string {
  const trimmed = address.trim();
  const explicitScheme = /^https?:\/\//i.test(trimmed);
  const parsed = new URL(explicitScheme ? trimmed : `http://${trimmed}`);
  if (!(["http:", "https:"] as string[]).includes(parsed.protocol)) throw new Error("invalid protocol");
  if (!parsed.hostname || parsed.username || parsed.password || parsed.search || parsed.hash) throw new Error("invalid address");
  if (parsed.pathname !== "/" && parsed.pathname !== "") throw new Error("invalid path");
  if (parsed.port) throw new Error("port must be separate");

  const numericPort = Number(port);
  if (!Number.isInteger(numericPort) || numericPort < 1 || numericPort > 65535) throw new RangeError("invalid port");

  const hostname = parsed.hostname.includes(":") ? `[${parsed.hostname}]` : parsed.hostname;
  const authority = `${hostname}:${numericPort}`;
  return explicitScheme ? `${parsed.protocol}//${authority}` : authority;
}
