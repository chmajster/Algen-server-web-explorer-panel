import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type ResourceDashboard } from "../../api";
import { settingsFixture } from "../../test/settings";
import { ntpManagerClient } from "../../modules/ntp-manager/api/client";
import { DesktopWidgets } from "./DesktopWidgets";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, api: { ...actual.api, resources: vi.fn(), modules: vi.fn() } };
});

vi.mock("../../modules/ntp-manager/api/client", () => ({
  ntpManagerClient: { dashboard: vi.fn() },
}));

const resources = {
  scope: "admin", timestamp: 1, cpu_percent: 25, cpu_cores: [25], cpu_logical_cores: 4, cpu_frequency_mhz: null,
  ram: { total: 1000, used: 500, free: 500, percent: 50 }, swap: { total: 0, used: 0, free: 0, percent: 0 }, allowed_roots: [], mountpoints: [],
  uptime_seconds: 10, load_average: null, temperature_c: null, webnas_service: "active", hostname: "nas", os_name: "Linux", kernel_version: "6", boot_time: null,
  network_interfaces: [], disk_io: [], alerts: [], processes: [], warnings: [],
} satisfies ResourceDashboard;

const ntpDashboard = {
  backend: "chrony", available: true, role: "client_server" as const, synchronized: true, timezone: "Europe/Warsaw", system_time: 1,
  source: "time.cloudflare.com", offset: "+0.7 ms", stratum: 3, reachability: "", jitter: "", service: "chronyd", service_state: "active", enabled: true,
  health: "healthy" as const, metrics: {}, sources: [], summary: { source_count: 2, selected_count: 1, reachable_count: 2, client_count: 12 },
  firewall: { backend: "firewalld", status: "open" as const, managed_by_webnas: false }, warnings: [], collected_at: 1,
};

describe("DesktopWidgets", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.resources).mockResolvedValue(resources);
    vi.mocked(api.modules).mockResolvedValue([]);
    vi.mocked(ntpManagerClient.dashboard).mockResolvedValue(ntpDashboard);
  });

  it("renders live resource values and persists widget visibility", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<DesktopWidgets profile={settingsFixture({ permissions: ["modules.view", "widgets.manage"] })} tasks={[]} toasts={[]} t={(key) => key} onSettingsChange={save} />);

    await waitFor(() => expect(screen.getByText("25%")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "widgets.customize" }));
    fireEvent.click(screen.getByRole("button", { name: "widgets.cpu" }));

    expect(save).toHaveBeenCalledWith(expect.objectContaining({ desktop_widgets: expect.arrayContaining([expect.objectContaining({ id: "cpu", visible: false })]) }));
  });

  it("renders NTP dashboard data only for users with ntp.view", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(<DesktopWidgets profile={settingsFixture({ permissions: ["ntp.view"] })} tasks={[]} toasts={[]} t={(key) => key} onSettingsChange={save} />);

    await waitFor(() => expect(screen.getByTestId("ntp-dashboard-widget")).toBeInTheDocument());
    expect(screen.getByText("Synchronizacja: OK")).toBeInTheDocument();
    expect(screen.getByText("time.cloudflare.com")).toBeInTheDocument();
    expect(screen.getByText("+0.7 ms")).toBeInTheDocument();
    expect(screen.getByText("Client + Server")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();

    rerender(<DesktopWidgets profile={settingsFixture({ permissions: [] })} tasks={[]} toasts={[]} t={(key) => key} onSettingsChange={save} />);
    expect(screen.queryByTestId("ntp-dashboard-widget")).not.toBeInTheDocument();
  });
});
