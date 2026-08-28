import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, setApiBaseUrl, type NetworkManagementState, type NetworkPlan } from "../../api";
import { NetworkSettingsSection } from "./NetworkSettingsSection";

const t = (key: string) => key;

const state: NetworkManagementState = {
  provider: { id: "networkmanager", writable: true, capabilities: { write: true }, warnings: [] },
  hostname: "nas-one",
  interfaces: [{
    name: "eth0", state: "up", carrier: true, speed_mbps: 1000, duplex: "full", mtu: 1500,
    mac_address: "02:00:00:00:00:01", addresses: [{ family: "ipv4", address: "192.0.2.10", prefix_length: 24, scope: "global" }],
    rx_bytes: 1, rx_packets: 1, rx_errors: 0, rx_dropped: 0, tx_bytes: 1, tx_packets: 1, tx_errors: 0, tx_dropped: 0,
    rx_bytes_per_sec: 0, tx_bytes_per_sec: 0, system: false,
  }],
  dns: {
    resolv_conf: { path: "/etc/resolv.conf", symlink_target: null, mode: "static", nameservers: ["1.1.1.1"], search: [], options: [] },
    systemd_resolved: { available: false, global_servers: [], links: [] },
    warnings: [],
  },
  routing: { timestamp: 1, routes: [], rules: [], gateways: [{ family: "ipv4", address: "192.0.2.1", device: "eth0", metric: 100, table: "main" }], warnings: [], read_only: true },
  managed: { interfaces: {}, dns: null, routes: {}, traffic: {} },
  transaction: null,
  tools: { tc: true, ip: true },
};

const plan: NetworkPlan = {
  id: "a".repeat(32), provider: "networkmanager", target: "dns", before: {}, after: {}, commands: [["nmcli", "connection", "modify"]],
  warnings: [], high_risk: false, required_phrase: "", rollback_supported: true, rollback_seconds: 15, client_interface: null,
  confirmation_timeout_seconds: 15, rollback_method: "systemd_transient_timer", automatic_rollback_without_confirmation: true,
};

describe("network DNS management", () => {
  beforeEach(() => {
    sessionStorage.clear();
    setApiBaseUrl("");
    vi.spyOn(api, "networkManagement").mockResolvedValue(state);
    vi.spyOn(api, "activeNetworkTransaction").mockResolvedValue(null);
    vi.spyOn(api, "planNetworkChange").mockResolvedValue(plan);
  });

  afterEach(() => vi.restoreAllMocks());

  it("adds multiple DNS servers and deduplicates them before planning", async () => {
    render(<NetworkSettingsSection isAdmin t={t} />);
    await screen.findAllByText("nas-one");

    fireEvent.click(screen.getByRole("button", { name: "Konfiguruj DNS" }));
    expect(await screen.findByRole("dialog", { name: "Konfiguracja DNS" })).toBeInTheDocument();
    expect(screen.getByLabelText("Serwer DNS 1")).toHaveValue("1.1.1.1");

    fireEvent.click(screen.getByRole("button", { name: "Dodaj serwer DNS" }));
    fireEvent.change(screen.getByLabelText("Serwer DNS 2"), { target: { value: "8.8.8.8" } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj serwer DNS" }));
    fireEvent.change(screen.getByLabelText("Serwer DNS 3"), { target: { value: "8.8.8.8" } });
    fireEvent.click(screen.getByRole("button", { name: "Przejdź do planu" }));

    await waitFor(() => expect(api.planNetworkChange).toHaveBeenCalledWith({
      operation: "save_dns",
      dns: expect.objectContaining({
        servers: ["1.1.1.1", "8.8.8.8"],
        per_interface: { eth0: ["1.1.1.1", "8.8.8.8"] },
      }),
    }));
  });
});
