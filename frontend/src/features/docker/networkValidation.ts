export type IpVersion = 4 | 6;

type ParsedAddress = { version: IpVersion; value: bigint; bits: 32 | 128 };
type ParsedNetwork = ParsedAddress & { prefix: number; network: bigint };

function parseIpv4(value: string): bigint | null {
  const parts = value.split(".");
  if (parts.length !== 4 || parts.some((part) => !/^(0|[1-9][0-9]{0,2})$/.test(part))) return null;
  const octets = parts.map(Number);
  if (octets.some((part) => part > 255)) return null;
  return octets.reduce<bigint>((result, part) => (result << 8n) | BigInt(part), 0n);
}

function ipv4Tail(parts: string[]): string[] | null {
  if (!parts.length || !parts[parts.length - 1].includes(".")) return parts;
  const parsed = parseIpv4(parts[parts.length - 1]);
  if (parsed === null) return null;
  return [
    ...parts.slice(0, -1),
    ((parsed >> 16n) & 0xffffn).toString(16),
    (parsed & 0xffffn).toString(16),
  ];
}

function parseIpv6(value: string): bigint | null {
  if (!value || value.includes("%") || (value.match(/::/g) || []).length > 1) return null;
  const compressed = value.includes("::");
  const [leftRaw, rightRaw = ""] = value.split("::");
  const left = ipv4Tail(leftRaw ? leftRaw.split(":") : []);
  const right = ipv4Tail(rightRaw ? rightRaw.split(":") : []);
  if (!left || !right) return null;
  const groups = [...left, ...right];
  if (groups.some((group) => !/^[0-9a-f]{1,4}$/i.test(group))) return null;
  const missing = 8 - groups.length;
  if ((!compressed && missing !== 0) || (compressed && missing < 1)) return null;
  const expanded = compressed ? [...left, ...Array<string>(missing).fill("0"), ...right] : groups;
  return expanded.reduce<bigint>((result, group) => (result << 16n) | BigInt(`0x${group}`), 0n);
}

export function parseAddress(value: string): ParsedAddress | null {
  const trimmed = value.trim();
  const ipv4 = parseIpv4(trimmed);
  if (ipv4 !== null) return { version: 4, value: ipv4, bits: 32 };
  const ipv6 = parseIpv6(trimmed);
  return ipv6 === null ? null : { version: 6, value: ipv6, bits: 128 };
}

export function parseNetwork(value: string): ParsedNetwork | null {
  const [addressValue, prefixValue, extra] = value.trim().split("/");
  if (extra !== undefined || prefixValue === undefined || !/^(0|[1-9][0-9]{0,2})$/.test(prefixValue)) return null;
  const address = parseAddress(addressValue);
  const prefix = Number(prefixValue);
  if (!address || prefix <= 0 || prefix > address.bits) return null;
  const hostBits = BigInt(address.bits - prefix);
  const mask = ((1n << BigInt(address.bits)) - 1n) ^ ((1n << hostBits) - 1n);
  return { ...address, prefix, network: address.value & mask };
}

export function addressInNetwork(addressValue: string, networkValue: string): boolean {
  const address = parseAddress(addressValue);
  const network = parseNetwork(networkValue);
  if (!address || !network || address.version !== network.version) return false;
  const hostBits = BigInt(network.bits - network.prefix);
  const mask = ((1n << BigInt(network.bits)) - 1n) ^ ((1n << hostBits) - 1n);
  return (address.value & mask) === network.network;
}

export function networkInNetwork(rangeValue: string, networkValue: string): boolean {
  const range = parseNetwork(rangeValue);
  const network = parseNetwork(networkValue);
  return Boolean(
    range
      && network
      && range.version === network.version
      && range.prefix >= network.prefix
      && addressInNetwork(rangeValue.split("/")[0], networkValue),
  );
}

export function isUsableIpv4Gateway(addressValue: string, networkValue: string): boolean {
  const address = parseAddress(addressValue);
  const network = parseNetwork(networkValue);
  if (!address || !network || address.version !== 4 || network.version !== 4 || !addressInNetwork(addressValue, networkValue)) return false;
  const broadcast = network.network | ((1n << BigInt(32 - network.prefix)) - 1n);
  return address.value !== network.network && address.value !== broadcast;
}

export function validDockerName(value: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(value) && !value.startsWith("-");
}

export function validLabel(key: string, value: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$/.test(key)
    && value.length <= 512
    && !/[\0\r\n]/.test(value);
}
