import { describe, expect, it } from "vitest";

import type { DiskMetric, NetworkMetric } from "../../../api";
import type { History } from "./monitorUtils";
import { dedupeStorage, MAX_SAMPLES, pushSample, summarizeNetwork, usageLevel } from "./monitorUtils";

describe("monitorUtils", () => {
  it("keeps resource history bounded", () => {
    let history: History = {};
    for (let index = 0; index < MAX_SAMPLES + 20; index += 1) history = pushSample(history, "cpu", index);
    expect(history.cpu).toHaveLength(MAX_SAMPLES);
    expect(history.cpu[0]).toBe(20);
  });

  it("uses a single threshold helper", () => {
    expect(usageLevel(84.9)).toBe("normal");
    expect(usageLevel(85)).toBe("warning");
    expect(usageLevel(94.9)).toBe("warning");
    expect(usageLevel(95)).toBe("critical");
  });

  it("deduplicates aliases that point to the same filesystem", () => {
    const base: DiskMetric = { path: "/data", filesystem_id: "fs-1", device: "/dev/sda1", mountpoint: "/data", fs_type: "ext4", total: 100, used: 50, free: 50, percent: 50 };
    const result = dedupeStorage([base, { ...base, path: "/srv/data", paths: ["/srv/data"] }]);
    expect(result).toHaveLength(1);
    expect(result[0].paths).toEqual(expect.arrayContaining(["/data", "/srv/data"]));
  });

  it("excludes backend-classified virtual and system interfaces when a normal interface is active", () => {
    const interfaces: NetworkMetric[] = [
      { name: "eth0", state: "up", rx_bytes: 100, tx_bytes: 200, rx_bytes_per_sec: 10, tx_bytes_per_sec: 20, system: false },
      { name: "br0", state: "up", rx_bytes: 1000, tx_bytes: 2000, rx_bytes_per_sec: 100, tx_bytes_per_sec: 200, system: true },
      { name: "veth1234", state: "up", rx_bytes: 500, tx_bytes: 600, rx_bytes_per_sec: 50, tx_bytes_per_sec: 60, system: true },
      { name: "lo", state: "up", rx_bytes: 900, tx_bytes: 900, rx_bytes_per_sec: 90, tx_bytes_per_sec: 90, system: true },
    ];
    const summary = summarizeNetwork(interfaces);
    expect(summary.interfaces.map((item) => item.name)).toEqual(["eth0"]);
    expect(summary.rxBytesPerSec).toBe(10);
    expect(summary.txBytesPerSec).toBe(20);
  });

  it("falls back to active non-loopback traffic when only system-classified links are available", () => {
    const interfaces: NetworkMetric[] = [
      { name: "docker0", state: "up", rx_bytes: 1000, tx_bytes: 2000, rx_bytes_per_sec: 100, tx_bytes_per_sec: 200, system: true },
      { name: "lo", state: "up", rx_bytes: 900, tx_bytes: 900, rx_bytes_per_sec: 90, tx_bytes_per_sec: 90, system: true },
    ];
    const summary = summarizeNetwork(interfaces);
    expect(summary.interfaces.map((item) => item.name)).toEqual(["docker0"]);
    expect(summary.rxBytesPerSec).toBe(100);
    expect(summary.txBytesPerSec).toBe(200);
  });
});
