import { describe, expect, it } from "vitest";
import {
  addressInNetwork,
  isUsableIpv4Gateway,
  networkInNetwork,
  parseAddress,
  parseNetwork,
} from "./networkValidation";

describe("Docker network IP validation", () => {
  it("validates IPv4 CIDRs, contained ranges, and usable gateways", () => {
    expect(parseNetwork("172.20.0.0/16")?.version).toBe(4);
    expect(networkInNetwork("172.20.10.0/24", "172.20.0.0/16")).toBe(true);
    expect(networkInNetwork("172.21.0.0/24", "172.20.0.0/16")).toBe(false);
    expect(isUsableIpv4Gateway("172.20.0.1", "172.20.0.0/16")).toBe(true);
    expect(isUsableIpv4Gateway("172.20.0.0", "172.20.0.0/16")).toBe(false);
    expect(parseAddress("256.20.0.1")).toBeNull();
  });

  it("validates compressed IPv6, embedded IPv4, CIDRs, and containment", () => {
    expect(parseAddress("fd42:20::1")?.version).toBe(6);
    expect(parseAddress("::ffff:192.0.2.1")?.version).toBe(6);
    expect(parseNetwork("fd42:20::/64")?.version).toBe(6);
    expect(networkInNetwork("fd42:20:0:0:10::/80", "fd42:20::/64")).toBe(true);
    expect(addressInNetwork("fd42:20::1", "fd42:20::/64")).toBe(true);
    expect(addressInNetwork("fd42:21::1", "fd42:20::/64")).toBe(false);
    expect(parseAddress("fd42:::1")).toBeNull();
  });
});
