import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  api,
  type DnsConfiguration,
  type DnsTestResult,
  type NetworkOverview,
  type RoutingSnapshot,
} from "../../api";
import { NetworkSettingsSection } from "./NetworkSettingsSection";

const t = (key: string) => key;
const overview: NetworkOverview = {
  timestamp: 100,
  sample_interval_seconds: 2,
  warnings: [],
  interfaces: [{
    name: "eth0", state: "up", carrier: true, speed_mbps: 1000, duplex: "full", mtu: 1500,
    mac_address: "00:11:22:33:44:55", addresses: [{ family: "ipv4", address: "192.0.2.10", prefix_length: 24, scope: "global" }],
    rx_bytes: 2048, rx_packets: 20, rx_errors: 2, rx_dropped: 4, tx_bytes: 4096, tx_packets: 30,
    tx_errors: 3, tx_dropped: 5, rx_bytes_per_sec: 512, tx_bytes_per_sec: 256, system: false,
  }],
};
const dns: DnsConfiguration = {
  resolv_conf: { path: "/etc/resolv.conf", symlink_target: "../run/systemd/resolve/stub-resolv.conf", mode: "stub", nameservers: ["127.0.0.53"], search: ["lan"], options: ["edns0"] },
  systemd_resolved: { available: true, global_servers: ["1.1.1.1"], global_domains: [], links: [{ interface: "eth0", servers: ["192.0.2.53"], domains: ["lan"] }] },
  warnings: [],
};
const routing: RoutingSnapshot = {
  timestamp: 100,
  read_only: true,
  warnings: [],
  gateways: [{ family: "ipv4", address: "192.0.2.1", device: "eth0", metric: 100, table: "main" }],
  routes: [{ family: "ipv4", destination: "default", gateway: "192.0.2.1", device: "eth0", preferred_source: "192.0.2.10", protocol: "dhcp", scope: "global", type: "unicast", table: "main", metric: 100, nexthops: [] }],
  rules: [{ family: "ipv4", priority: 32766, from: "all", to: "all", table: "main", fwmark: null, input_interface: null, output_interface: null, action: "lookup" }],
};
const dnsResult: DnsTestResult = {
  hostname: "example.com", success: true, addresses: ["93.184.216.34"], tested_at: 101,
  servers: [{ server: "192.0.2.53", success: true, rcode: "NOERROR", addresses: ["93.184.216.34"], latency_ms: 12.34, error: null }],
};

describe("network settings", () => {
  beforeEach(() => {
    vi.spyOn(api, "networkOverview").mockResolvedValue(overview);
    vi.spyOn(api, "networkDns").mockResolvedValue(dns);
    vi.spyOn(api, "networkRouting").mockResolvedValue(routing);
    vi.spyOn(api, "testNetworkDns").mockResolvedValue(dnsResult);
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows interface traffic, errors, link data, addresses, gateway, and DNS", async () => {
    render(<NetworkSettingsSection isAdmin t={t} />);

    expect(screen.queryByRole("tab", { name: "settings.networkResources" })).not.toBeInTheDocument();
    expect(await screen.findByText("eth0")).toBeInTheDocument();
    expect(screen.getByText("1000 Mb/s · full")).toBeInTheDocument();
    expect(screen.getByText("192.0.2.10/24")).toBeInTheDocument();
    expect(await screen.findByText("192.0.2.1")).toBeInTheDocument();
    expect(screen.getByText("192.0.2.53")).toBeInTheDocument();
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
    expect(screen.getByText("4 / 5")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "eth0 network.downloadHistory" })).toBeInTheDocument();
    expect(screen.getByText("network.currentDownload")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("network.searchInterfaces"), { target: { value: "missing" } });
    expect(screen.getByText("network.noMatchingInterfaces")).toBeInTheDocument();
  });

  it("shows DNS configuration and runs a validated name-resolution test", async () => {
    render(<NetworkSettingsSection isAdmin t={t} />);
    fireEvent.click(screen.getByRole("tab", { name: "DNS" }));

    expect(await screen.findByRole("heading", { name: "/etc/resolv.conf" })).toBeInTheDocument();
    expect(screen.getByText("127.0.0.53")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("network.domainToTest"), { target: { value: "example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "network.runDnsTest" }));

    await waitFor(() => expect(api.testNetworkDns).toHaveBeenCalledWith("example.com"));
    expect(await screen.findByText("network.resolutionSucceeded")).toBeInTheDocument();
    expect(screen.getByText("12.34 ms")).toBeInTheDocument();
    expect(screen.getByText("NOERROR")).toBeInTheDocument();
  });

  it("renders gateways, routes, and rules as a read-only view", async () => {
    render(<NetworkSettingsSection isAdmin t={t} />);
    fireEvent.click(screen.getByRole("tab", { name: "network.routing" }));

    expect(await screen.findByText("network.readOnlyHint")).toBeInTheDocument();
    expect(screen.getAllByText("192.0.2.1").length).toBeGreaterThan(0);
    expect(screen.getByText("network.routes (1/1)")).toBeInTheDocument();
    expect(screen.getByText("network.rules (1)")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("network.searchRoutes"), { target: { value: "missing" } });
    expect(screen.getByText("network.routes (0/1)")).toBeInTheDocument();
    expect(screen.getByText("network.noRoutes")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "action.apply" })).not.toBeInTheDocument();
  });
});
