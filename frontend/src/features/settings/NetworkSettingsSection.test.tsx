import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  api,
  type DnsConfiguration,
  type DnsTestResult,
  type NetworkInterfaceDetail,
  type NetworkOverview,
  type RoutingSnapshot,
} from "../../api";
import { NetworkSettingsSection, NetworkTrafficChart } from "./NetworkSettingsSection";

const t = (key: string) => key;
const network = (overrides: Partial<NetworkInterfaceDetail> = {}): NetworkInterfaceDetail => ({
  name: "eth0", state: "up", carrier: true, speed_mbps: 1000, duplex: "full", mtu: 1500,
  mac_address: "00:11:22:33:44:55", addresses: [{ family: "ipv4", address: "192.0.2.10", prefix_length: 24, scope: "global" }],
  rx_bytes: 2048, rx_packets: 20, rx_errors: 0, rx_dropped: 0, tx_bytes: 4096, tx_packets: 30,
  tx_errors: 0, tx_dropped: 0, rx_bytes_per_sec: 512, tx_bytes_per_sec: 256, system: false,
  ...overrides,
});
const overview = (interfaces: NetworkInterfaceDetail[] = [network()], warnings: string[] = []): NetworkOverview => ({
  timestamp: 100, sample_interval_seconds: 2, warnings, interfaces,
});
const dns: DnsConfiguration = {
  resolv_conf: { path: "/etc/resolv.conf", symlink_target: "../run/systemd/resolve/stub-resolv.conf", mode: "stub", nameservers: ["127.0.0.53"], search: ["lan"], options: ["edns0"] },
  systemd_resolved: { available: true, global_servers: ["1.1.1.1"], global_domains: [], links: [{ interface: "eth0", servers: ["192.0.2.53"], domains: ["lan"] }] },
  warnings: [],
};
const routing: RoutingSnapshot = {
  timestamp: 100, read_only: true, warnings: [],
  gateways: [{ family: "ipv4", address: "192.0.2.1", device: "eth0", metric: 100, table: "main" }],
  routes: [
    { family: "ipv4", destination: "default", gateway: "192.0.2.1", device: "eth0", preferred_source: "192.0.2.10", protocol: "dhcp", scope: "global", type: "unicast", table: "main", metric: 100, nexthops: [] },
    { family: "ipv6", destination: "2001:db8::/64", gateway: null, device: "eth0", preferred_source: "2001:db8::10", protocol: "kernel", scope: "link", type: "unicast", table: "main", metric: 256, nexthops: [] },
  ],
  rules: [{ family: "ipv4", priority: 32766, from: "all", to: "all", table: "main", fwmark: null, input_interface: null, output_interface: null, action: "lookup" }],
};
const dnsResult = (success = true): DnsTestResult => ({
  hostname: "example.com", success, addresses: success ? ["93.184.216.34"] : [], tested_at: 101,
  servers: [{ server: "192.0.2.53", success, rcode: success ? "NOERROR" : null, addresses: success ? ["93.184.216.34"] : [], latency_ms: success ? 12.34 : null, error: success ? null : "timeout" }],
});

describe("network settings", () => {
  beforeEach(() => {
    vi.spyOn(api, "networkOverview").mockResolvedValue(overview());
    vi.spyOn(api, "networkDns").mockResolvedValue(dns);
    vi.spyOn(api, "networkRouting").mockResolvedValue(routing);
    vi.spyOn(api, "testNetworkDns").mockResolvedValue(dnsResult());
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("is available only to administrators", () => {
    const { rerender } = render(<NetworkSettingsSection isAdmin={false} t={t} />);
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(api.networkOverview).not.toHaveBeenCalled();
    rerender(<NetworkSettingsSection isAdmin t={t} />);
    expect(screen.getByRole("tablist", { name: "settings.category.network" })).toBeInTheDocument();
  });

  it("switches accessible tabs with clicks and keyboard", async () => {
    render(<NetworkSettingsSection isAdmin t={t} />);
    const monitor = screen.getByRole("tab", { name: "network.monitor" });
    expect(monitor).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(monitor, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "DNS" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "network-tab-dns");
    fireEvent.click(screen.getByRole("tab", { name: "network.routing" }));
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "network-tab-routing");
  });

  it("calculates the four summary values and reports a healthy network", async () => {
    vi.mocked(api.networkOverview).mockResolvedValue(overview([
      network(),
      network({ name: "eth1", state: "down", carrier: false, rx_bytes_per_sec: 1024, tx_bytes_per_sec: 512 }),
    ]));
    render(<NetworkSettingsSection isAdmin t={t} />);
    const health = await screen.findByLabelText("network.health.ok");
    expect(health).toBeInTheDocument();
    const summary = screen.getByLabelText("network.summary");
    expect(within(summary).getByText("network.summary.active").parentElement).toHaveTextContent("1");
    expect(within(summary).getByText("network.summary.download").parentElement).toHaveTextContent("/s");
    expect(within(summary).getByText("network.summary.upload").parentElement).toHaveTextContent("/s");
    expect(within(summary).getByText("network.summary.issues").parentElement).toHaveTextContent("0");
  });

  it("distinguishes warning and offline health states", async () => {
    vi.mocked(api.networkOverview).mockResolvedValue(overview([network({ rx_errors: 2 })]));
    const { unmount } = render(<NetworkSettingsSection isAdmin t={t} />);
    expect(await screen.findByLabelText("network.health.warning")).toBeInTheDocument();
    unmount();
    vi.mocked(api.networkOverview).mockResolvedValue(overview([network({ state: "down", carrier: false })]));
    render(<NetworkSettingsSection isAdmin t={t} />);
    expect(await screen.findByLabelText("network.health.offline")).toBeInTheDocument();
  });

  it("searches interfaces by name and IP and clears the query", async () => {
    vi.mocked(api.networkOverview).mockResolvedValue(overview([
      network(),
      network({ name: "backup0", addresses: [{ family: "ipv4", address: "198.51.100.8", prefix_length: 24, scope: "global" }] }),
    ]));
    render(<NetworkSettingsSection isAdmin t={t} />);
    await screen.findByRole("heading", { name: "eth0" });
    const search = screen.getByPlaceholderText("network.searchInterfaces");
    fireEvent.change(search, { target: { value: "backup0" } });
    expect(screen.getByRole("heading", { name: "backup0" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "eth0" })).not.toBeInTheDocument();
    fireEvent.change(search, { target: { value: "192.0.2.10" } });
    expect(screen.getByRole("heading", { name: "eth0" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "network.clearSearch" }));
    expect(screen.getByText("network.visibleInterfaces".replace("{visible}", "2").replace("{total}", "2"))).toBeInTheDocument();
  });

  it("filters active and problematic interfaces", async () => {
    vi.mocked(api.networkOverview).mockResolvedValue(overview([
      network(),
      network({ name: "down0", state: "down", carrier: false }),
      network({ name: "broken0", rx_dropped: 3 }),
    ]));
    render(<NetworkSettingsSection isAdmin t={t} />);
    await screen.findByRole("heading", { name: "eth0" });
    const filter = screen.getByLabelText("network.filter");
    fireEvent.change(filter, { target: { value: "up" } });
    expect(screen.queryByRole("heading", { name: "down0" })).not.toBeInTheDocument();
    fireEvent.change(filter, { target: { value: "errors" } });
    expect(screen.getByRole("heading", { name: "broken0" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "eth0" })).not.toBeInTheDocument();
  });

  it("shows only essential interface data until details are opened", async () => {
    render(<NetworkSettingsSection isAdmin t={t} />);
    const card = (await screen.findByRole("heading", { name: "eth0" })).closest("article")!;
    expect(within(card).getAllByText("192.0.2.10/24").find((item) => item.tagName === "P")).toBeVisible();
    expect(within(card).getAllByText("1 Gb/s").find((item) => !item.closest("details"))).toBeVisible();
    expect(within(card).getByRole("img", { name: "eth0 network.trafficHistory" })).toBeInTheDocument();
    expect(within(card).getByText("00:11:22:33:44:55")).not.toBeVisible();
    fireEvent.click(within(card).getByText("network.interfaceDetails"));
    expect(within(card).getByText("00:11:22:33:44:55")).toBeVisible();
    expect(within(card).getByText("192.0.2.1")).toBeVisible();
    fireEvent.click(within(card).getByText("network.hideDetails"));
    expect(within(card).getByText("00:11:22:33:44:55")).not.toBeVisible();
  });

  it("toggles automatic refresh and changes its interval", async () => {
    render(<NetworkSettingsSection isAdmin t={t} />);
    await screen.findByRole("heading", { name: "eth0" });
    const toggle = screen.getByRole("switch", { name: /network.autoRefresh/ });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.change(screen.getByLabelText("network.refreshFrequency"), { target: { value: "10000" } });
    expect(screen.getByLabelText("network.refreshFrequency")).toHaveValue("10000");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByLabelText("network.refreshFrequency")).not.toBeInTheDocument();
  });

  it("refreshes manually and keeps previous data after a failed refresh", async () => {
    vi.mocked(api.networkOverview).mockResolvedValueOnce(overview()).mockRejectedValueOnce(new Error("offline"));
    render(<NetworkSettingsSection isAdmin t={t} />);
    expect(await screen.findByRole("heading", { name: "eth0" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "network.refreshNow" }));
    expect(await screen.findByText("network.staleData")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "eth0" })).toBeInTheDocument();
    expect(api.networkOverview).toHaveBeenCalledTimes(2);
  });

  it("continues automatic refresh at the selected interval", async () => {
    vi.useFakeTimers();
    render(<NetworkSettingsSection isAdmin t={t} />);
    await act(async () => { await Promise.resolve(); });
    expect(api.networkOverview).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(api.networkOverview).toHaveBeenCalledTimes(2);
  });

  it("deduplicates warnings and renders an empty history without NaN", async () => {
    vi.mocked(api.networkOverview).mockResolvedValue(overview([network()], ["duplicate warning", "duplicate warning"]));
    render(<NetworkSettingsSection isAdmin t={t} />);
    expect(await screen.findAllByText("duplicate warning")).toHaveLength(1);
    const { container } = render(<NetworkTrafficChart rx={[]} tx={[]} label="empty traffic" />);
    expect(screen.getByRole("img", { name: "empty traffic" })).toBeInTheDocument();
    expect(container.innerHTML).not.toContain("NaN");
  });

  it("runs successful and failed DNS tests with detailed server results", async () => {
    vi.mocked(api.testNetworkDns).mockResolvedValueOnce(dnsResult()).mockResolvedValueOnce(dnsResult(false));
    render(<NetworkSettingsSection isAdmin t={t} />);
    fireEvent.click(screen.getByRole("tab", { name: "DNS" }));
    await screen.findByText("network.dnsConfigurationSummary");
    expect(screen.getAllByText("1.1.1.1").find((item) => !item.closest("details"))).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "network.runDnsTest" }));
    expect(await screen.findByText("network.dnsResult.success")).toBeInTheDocument();
    expect(screen.getAllByText("12.34 ms").find((item) => !item.closest("details"))).toBeVisible();
    fireEvent.click(screen.getByText(/network.dnsServerDetails/));
    expect(screen.getByText("NOERROR")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "network.runDnsTest" }));
    expect(await screen.findByText("network.dnsResult.error")).toBeInTheDocument();
    expect(screen.getByText("timeout")).not.toBeVisible();
  });

  it("keeps raw DNS configuration in a collapsed details section", async () => {
    render(<NetworkSettingsSection isAdmin t={t} />);
    fireEvent.click(screen.getByRole("tab", { name: "DNS" }));
    const detailsLabel = await screen.findByText("network.dnsConfigurationDetails");
    expect(screen.getByText("../run/systemd/resolve/stub-resolv.conf")).not.toBeVisible();
    fireEvent.click(detailsLabel);
    expect(screen.getByText("../run/systemd/resolve/stub-resolv.conf")).toBeVisible();
  });

  it("filters and searches IPv4 and IPv6 routes", async () => {
    render(<NetworkSettingsSection isAdmin t={t} />);
    fireEvent.click(screen.getByRole("tab", { name: "network.routing" }));
    await screen.findByText("network.readOnlyHint");
    const family = screen.getByLabelText("network.family");
    fireEvent.change(family, { target: { value: "ipv6" } });
    expect(screen.getAllByText("2001:db8::/64").length).toBeGreaterThan(0);
    expect(screen.queryByText("default")).not.toBeInTheDocument();
    fireEvent.change(family, { target: { value: "all" } });
    fireEvent.change(screen.getByPlaceholderText("network.searchRoutes"), { target: { value: "missing" } });
    expect(screen.getAllByText("network.noRoutes").length).toBeGreaterThan(0);
    expect(screen.getByText("network.visibleRoutes".replace("{visible}", "0").replace("{total}", "2"))).toBeInTheDocument();
  });

  it("keeps advanced routing rules collapsed until requested", async () => {
    render(<NetworkSettingsSection isAdmin t={t} />);
    fireEvent.click(screen.getByRole("tab", { name: "network.routing" }));
    const summary = await screen.findByText("network.routingAdvancedRules".replace("{count}", "1"));
    expect(screen.getByText("32766")).not.toBeVisible();
    fireEvent.click(summary);
    expect(screen.getByText("32766")).toBeVisible();
  });
});
