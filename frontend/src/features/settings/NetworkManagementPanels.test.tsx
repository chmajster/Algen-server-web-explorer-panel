import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, setApiBaseUrl, type NetworkManagementState, type NetworkPlan, type NetworkTransaction } from "../../api";
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
  warnings: [], high_risk: false, required_phrase: "", rollback_supported: true, rollback_seconds: 15, client_interface: null,
};
const now = Date.now() / 1000;
const transaction: NetworkTransaction = {
  id: "b".repeat(32), state: "pending_confirmation", status: "pending_confirmation", provider: "networkmanager",
  started_at: now, deadline: now + 15, deadline_at: now + 15, rollback_unit: "rollback.service", target: "eth1",
  previous_panel_address: window.location.origin, predicted_panel_address: "http://192.0.2.20",
  reachable_addresses: [window.location.origin, "http://192.0.2.20"],
};

describe("network management settings", () => {
  beforeEach(() => {
    sessionStorage.clear();
    setApiBaseUrl("");
    const current = Date.now() / 1000;
    transaction.started_at = current;
    transaction.deadline = current + 15;
    transaction.deadline_at = current + 15;
    vi.spyOn(api, "networkManagement").mockResolvedValue(state);
    vi.spyOn(api, "activeNetworkTransaction").mockResolvedValue(null);
    vi.spyOn(api, "planNetworkChange").mockResolvedValue(plan);
    vi.spyOn(api, "applyNetworkPlan").mockResolvedValue(transaction);
    vi.spyOn(api, "confirmNetworkTransaction").mockResolvedValue({ ...transaction, state: "confirmed" });
    vi.spyOn(api, "rollbackNetworkTransaction").mockResolvedValue({ ...transaction, state: "rolled_back" });
    vi.spyOn(api, "networkTransactionStatus").mockResolvedValue(transaction);
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
    expect(await screen.findByText(/Automatyczne przywrócenie za 00:15/)).toBeInTheDocument();
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
    vi.mocked(api.activeNetworkTransaction).mockResolvedValue(transaction);
    render(<NetworkSettingsSection isAdmin t={t} />);
    fireEvent.click(await screen.findByRole("button", { name: /Zachowaj konfigurację/ }));
    await waitFor(() => expect(api.confirmNetworkTransaction).toHaveBeenCalledWith(transaction.id, "", expect.any(AbortSignal)));
  });

  it("restores a pending transaction from session storage while the API is unavailable", async () => {
    sessionStorage.setItem("webnas_network_transaction", JSON.stringify(transaction));
    vi.mocked(api.networkManagement).mockRejectedValue(new Error("offline"));
    vi.mocked(api.networkTransactionStatus).mockRejectedValue(new Error("offline"));
    render(<NetworkSettingsSection isAdmin t={t} />);
    expect(await screen.findByRole("button", { name: /Zachowaj konfigurację/ })).toBeInTheDocument();
    expect(screen.getByText(/Automatyczne przywrócenie za 00:1[45]/)).toBeInTheDocument();
  });

  it("tries the current and predicted panel addresses with one reconnect loop", async () => {
    vi.mocked(api.networkManagement).mockResolvedValue({ ...state, transaction });
    vi.mocked(api.activeNetworkTransaction).mockResolvedValue(transaction);
    vi.mocked(api.networkTransactionStatus)
      .mockRejectedValueOnce(new Error("old address unavailable"))
      .mockResolvedValue(transaction);
    render(<NetworkSettingsSection isAdmin t={t} />);
    await waitFor(() => {
      expect(api.networkTransactionStatus).toHaveBeenCalledWith(transaction.id, "", expect.any(AbortSignal));
      expect(api.networkTransactionStatus).toHaveBeenCalledWith(transaction.id, "http://192.0.2.20", expect.any(AbortSignal));
    });
  });

  it("keeps confirmation pending locally and sends it after reconnect", async () => {
    vi.mocked(api.networkManagement).mockResolvedValue({ ...state, transaction });
    vi.mocked(api.activeNetworkTransaction).mockResolvedValue(transaction);
    vi.mocked(api.networkTransactionStatus).mockRejectedValue(new Error("offline"));
    vi.mocked(api.confirmNetworkTransaction).mockRejectedValueOnce(new Error("offline"));
    render(<NetworkSettingsSection isAdmin t={t} />);
    fireEvent.click(await screen.findByRole("button", { name: /Zachowaj konfigurację/ }));
    expect(await screen.findByText("Wysyłanie potwierdzenia")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Zachowaj konfigurację/ })).toBeEnabled();
    expect(sessionStorage.getItem("webnas_network_transaction")).toContain(transaction.id);

    vi.mocked(api.networkTransactionStatus).mockResolvedValue(transaction);
    vi.mocked(api.confirmNetworkTransaction).mockResolvedValue({ ...transaction, state: "confirmed", status: "confirmed" });
    await waitFor(() => expect(api.confirmNetworkTransaction).toHaveBeenCalledTimes(2), { timeout: 3000 });
    expect((await screen.findAllByText("Konfiguracja zachowana")).length).toBeGreaterThan(0);
  });

  it("synchronizes the countdown with backend time without resetting it", async () => {
    const localNow = Date.now() / 1000;
    const synchronized = {
      ...transaction,
      deadline: localNow + 10,
      deadline_at: localNow + 10,
      current_server_time: localNow + 5,
      remaining_seconds: 5,
    };
    vi.mocked(api.networkManagement).mockResolvedValue({ ...state, transaction: synchronized });
    vi.mocked(api.activeNetworkTransaction).mockResolvedValue(synchronized);
    vi.mocked(api.networkTransactionStatus).mockResolvedValue(synchronized);
    render(<NetworkSettingsSection isAdmin t={t} />);
    expect(await screen.findByText(/Automatyczne przywrócenie za 00:0[45]/)).toBeInTheDocument();
  });

  it("enters rollback state after the local deadline while polling continues", async () => {
    const expiring = { ...transaction, deadline: Date.now() / 1000 + 0.2, deadline_at: Date.now() / 1000 + 0.2 };
    vi.mocked(api.networkManagement).mockResolvedValue({ ...state, transaction: expiring });
    vi.mocked(api.activeNetworkTransaction).mockResolvedValue(expiring);
    vi.mocked(api.networkTransactionStatus).mockRejectedValue(new Error("offline"));
    render(<NetworkSettingsSection isAdmin t={t} />);
    expect((await screen.findAllByText("Trwa przywracanie poprzedniej konfiguracji", {}, { timeout: 1500 })).length).toBeGreaterThan(0);
    expect(api.networkTransactionStatus).toHaveBeenCalled();
  });

  it("stops reconnect attempts after a terminal backend status", async () => {
    const rolledBack = { ...transaction, state: "rolled_back" as const, status: "rolled_back" as const, rolled_back: true };
    vi.mocked(api.networkManagement).mockResolvedValue({ ...state, transaction });
    vi.mocked(api.activeNetworkTransaction).mockResolvedValue(transaction);
    vi.mocked(api.networkTransactionStatus).mockResolvedValue(rolledBack);
    render(<NetworkSettingsSection isAdmin t={t} />);
    expect((await screen.findAllByText("Przywrócono poprzednią konfigurację")).length).toBeGreaterThan(0);
    const calls = vi.mocked(api.networkTransactionStatus).mock.calls.length;
    await new Promise((resolve) => window.setTimeout(resolve, 600));
    expect(api.networkTransactionStatus).toHaveBeenCalledTimes(calls);
  });
});
