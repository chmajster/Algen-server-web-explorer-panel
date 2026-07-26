import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, type NetworkManagementState, type NetworkPlan, type NetworkTransaction } from "../../api";
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
  dns: { resolv_conf: { path: "/etc/resolv.conf", symlink_target: null, mode: "static", nameservers: ["1.1.1.1"], search: [], options: [] }, systemd_resolved: { available: false, global_servers: [], links: [] }, warnings: [] },
  routing: { timestamp: 1, routes: [], rules: [], gateways: [{ family: "ipv4", address: "192.0.2.1", device: "eth0", metric: 100, table: "main" }], warnings: [], read_only: true },
  managed: { interfaces: {}, dns: null, routes: {}, traffic: {} },
  transaction: null,
  tools: { tc: true, ip: true },
};
const plan: NetworkPlan = {
  id: "a".repeat(32), provider: "networkmanager", target: "eth1", before: {}, after: {}, commands: [["nmcli", "connection", "add"]],
  warnings: [], high_risk: false, required_phrase: "", rollback_supported: true, rollback_seconds: 90, client_interface: null,
};
const transaction: NetworkTransaction = {
  id: "b".repeat(32), state: "pending_confirmation", provider: "networkmanager", started_at: 100, deadline: 190, rollback_unit: "rollback.service", target: "eth1",
};

describe("network management settings", () => {
  beforeEach(() => {
    vi.spyOn(api, "networkManagement").mockResolvedValue(state);
    vi.spyOn(api, "planNetworkChange").mockResolvedValue(plan);
    vi.spyOn(api, "applyNetworkPlan").mockResolvedValue(transaction);
    vi.spyOn(api, "confirmNetworkTransaction").mockResolvedValue({ ...transaction, state: "confirmed" });
    vi.spyOn(api, "rollbackNetworkTransaction").mockResolvedValue({ ...transaction, state: "rolled_back" });
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows all five areas and provider summary", async () => {
    render(<NetworkSettingsSection isAdmin t={t} />);
    expect((await screen.findAllByText("nas-one")).length).toBeGreaterThan(0);
    for (const key of ["network.tab.general", "network.tab.interfaces", "network.tab.traffic", "network.tab.routes", "network.tab.connectivity"]) {
      expect(screen.getByRole("tab", { name: key })).toBeInTheDocument();
    }
    expect(screen.getByText("networkmanager · zapis dostępny")).toBeInTheDocument();
  });

  it("creates an interface through plan preview and apply", async () => {
    render(<NetworkSettingsSection isAdmin t={t} />);
    await screen.findAllByText("nas-one");
    fireEvent.click(screen.getByRole("tab", { name: "network.tab.interfaces" }));
    fireEvent.click(screen.getByRole("button", { name: /Utwórz/ }));
    fireEvent.change(screen.getByLabelText("Nazwa"), { target: { value: "eth1" } });
    fireEvent.click(screen.getByRole("button", { name: "Przejdź do planu" }));
    await waitFor(() => expect(api.planNetworkChange).toHaveBeenCalledWith(expect.objectContaining({ operation: "save_interface", interface: expect.objectContaining({ name: "eth1" }) })));
    expect(await screen.findByRole("dialog", { name: "Podgląd planu zmian" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zastosuj plan" }));
    await waitFor(() => expect(api.applyNetworkPlan).toHaveBeenCalledWith(plan.id, ""));
    expect(await screen.findByText(/rollback za/)).toBeInTheDocument();
  });

  it("requires the exact phrase for a high-risk plan", async () => {
    vi.mocked(api.planNetworkChange).mockResolvedValue({ ...plan, high_risk: true, required_phrase: "APPLY eth0", target: "eth0", warnings: ["Aktywne połączenie"] });
    render(<NetworkSettingsSection isAdmin t={t} />);
    await screen.findAllByText("nas-one");
    fireEvent.click(screen.getByRole("tab", { name: "network.tab.interfaces" }));
    fireEvent.click(screen.getByText("eth0"));
    fireEvent.click(screen.getByRole("button", { name: /Rozłącz/ }));
    const dialog = await screen.findByRole("dialog", { name: "Podgląd planu zmian" });
    const apply = screen.getByRole("button", { name: "Zastosuj plan" });
    expect(apply).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Wpisz dokładnie: APPLY eth0"), { target: { value: "APPLY eth0" } });
    expect(apply).toBeEnabled();
    expect(dialog).toHaveTextContent("Aktywne połączenie");
  });

  it("confirms a pending transaction", async () => {
    vi.mocked(api.networkManagement).mockResolvedValue({ ...state, transaction });
    render(<NetworkSettingsSection isAdmin t={t} />);
    fireEvent.click(await screen.findByRole("button", { name: /Zachowaj zmiany/ }));
    await waitFor(() => expect(api.confirmNetworkTransaction).toHaveBeenCalledWith(transaction.id));
  });
});
