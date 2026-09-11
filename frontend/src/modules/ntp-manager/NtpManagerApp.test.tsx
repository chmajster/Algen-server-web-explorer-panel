import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { confirmDialog } from "../../components/DialogService";
import { ntpManagerClient } from "./api/client";
import { NtpManagerApp } from "./NtpManagerApp";

vi.mock("../../components/DialogService", () => ({ confirmDialog: vi.fn() }));
vi.mock("./api/client", () => ({
  ntpManagerClient: {
    dashboard: vi.fn(), config: vi.fn(), clients: vi.fn(), history: vi.fn(), backups: vi.fn(),
    timezones: vi.fn(), add: vi.fn(), remove: vi.fn(), test: vi.fn(), saveConfig: vi.fn(),
    sync: vi.fn(), service: vi.fn(), setTimezone: vi.fn(), diagnostics: vi.fn(), openFirewall: vi.fn(),
    restoreBackup: vi.fn(), installChrony: vi.fn(),
  },
}));

const dashboard = {
  backend: "chrony", available: true, role: "client_server" as const, synchronized: true, timezone: "Europe/Warsaw", system_time: 1,
  source: "192.0.2.1", offset: "+0.7 ms", stratum: 3, reachability: "", jitter: "1 ms", service: "chronyd", service_state: "active", enabled: true,
  health: "healthy" as const, metrics: {},
  sources: [{ server: "192.0.2.1", selected: true, state: "selected", stratum: 3, reach: 377, kind: "server" as const, enabled: true }],
  summary: { source_count: 1, selected_count: 1, reachable_count: 1, client_count: 1 },
  firewall: { backend: "firewalld", status: "open" as const, managed_by_webnas: false }, warnings: [], collected_at: 1,
};

const config = {
  mode: "client_server" as const,
  sources: [{ server: "192.0.2.1", kind: "server" as const, prefer: true, enabled: true }],
  allowed_networks: [{ cidr: "192.168.10.0/24", description: "Servers", enabled: true }],
  local_time_when_unsynced: false, local_stratum: 10, backend: "chrony", managed_path: "/etc/chrony/conf.d/webnas.conf", unmanaged_config_detected: false,
};

function setupMocks() {
  vi.mocked(ntpManagerClient.dashboard).mockResolvedValue(dashboard);
  vi.mocked(ntpManagerClient.config).mockResolvedValue(config);
  vi.mocked(ntpManagerClient.clients).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(ntpManagerClient.history).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(ntpManagerClient.backups).mockResolvedValue({ items: [] });
  vi.mocked(ntpManagerClient.timezones).mockResolvedValue({ items: ["Europe/Warsaw", "UTC"], total: 2 });
  vi.mocked(ntpManagerClient.add).mockResolvedValue({});
  vi.mocked(ntpManagerClient.saveConfig).mockResolvedValue({});
  vi.mocked(confirmDialog).mockResolvedValue(true);
}

describe("NtpManagerApp", () => {
  beforeEach(() => { vi.clearAllMocks(); setupMocks(); });

  it("adds a typed pool source from the Sources tab", async () => {
    const user = userEvent.setup();
    render(<NtpManagerApp permissions={["ntp.view", "ntp.manage"]} language="pl-PL" toast={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Synchronizacja: OK")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Źródła czasu" }));
    await user.type(screen.getByLabelText("NTP server"), "pool.ntp.org");
    fireEvent.change(screen.getByDisplayValue("server"), { target: { value: "pool" } });
    await user.click(screen.getByRole("button", { name: /Dodaj/ }));

    await waitFor(() => expect(ntpManagerClient.add).toHaveBeenCalledWith("pool.ntp.org", "pool", false));
  });

  it("edits allowed networks and saves client+server configuration", async () => {
    const user = userEvent.setup();
    render(<NtpManagerApp permissions={["ntp.view", "ntp.manage", "ntp.firewall.manage"]} language="pl-PL" toast={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Synchronizacja: OK")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Serwer NTP" }));
    await user.type(screen.getByPlaceholderText("192.168.10.0/24"), "2001:db8::/64");
    await user.type(screen.getByPlaceholderText("Opis, np. VLAN Servers"), "IPv6 LAN");
    await user.click(screen.getByRole("button", { name: /Dodaj sieć/ }));
    expect(screen.getByText("2001:db8::/64")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Zapisz konfigurację serwera/ }));
    await waitFor(() => expect(ntpManagerClient.saveConfig).toHaveBeenCalledWith(expect.objectContaining({
      mode: "client_server",
      allowed_networks: expect.arrayContaining([expect.objectContaining({ cidr: "2001:db8::/64", description: "IPv6 LAN", enabled: true })]),
    })));
  });

  it("keeps mutating controls hidden for ntp.view-only users", async () => {
    render(<NtpManagerApp permissions={["ntp.view"]} language="pl-PL" toast={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Synchronizacja: OK")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Źródła czasu" }));
    expect(screen.queryByRole("button", { name: /Dodaj/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Usuń/ })).not.toBeInTheDocument();
  });
});
