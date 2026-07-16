import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type ResourceDashboard } from "../../api";
import { settingsFixture } from "../../test/settings";
import { DesktopWidgets } from "./DesktopWidgets";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, api: { ...actual.api, resources: vi.fn(), modules: vi.fn() } };
});

const resources = {
  scope: "admin", timestamp: 1, cpu_percent: 25, cpu_cores: [25], cpu_logical_cores: 4, cpu_frequency_mhz: null,
  ram: { total: 1000, used: 500, free: 500, percent: 50 }, swap: { total: 0, used: 0, free: 0, percent: 0 }, allowed_roots: [], mountpoints: [],
  uptime_seconds: 10, load_average: null, temperature_c: null, webnas_service: "active", hostname: "nas", os_name: "Linux", kernel_version: "6", boot_time: null,
  network_interfaces: [], disk_io: [], alerts: [], processes: [], warnings: [],
} satisfies ResourceDashboard;

describe("DesktopWidgets", () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.resources).mockResolvedValue(resources); vi.mocked(api.modules).mockResolvedValue([]); });

  it("renders live resource values and persists widget visibility", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<DesktopWidgets profile={settingsFixture({ permissions: ["modules.view", "widgets.manage"] })} tasks={[]} toasts={[]} t={(key) => key} onSettingsChange={save} />);

    await waitFor(() => expect(screen.getByText("25%")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "widgets.customize" }));
    fireEvent.click(screen.getByRole("button", { name: "widgets.cpu" }));

    expect(save).toHaveBeenCalledWith(expect.objectContaining({ desktop_widgets: expect.arrayContaining([expect.objectContaining({ id: "cpu", visible: false })]) }));
  });
});
