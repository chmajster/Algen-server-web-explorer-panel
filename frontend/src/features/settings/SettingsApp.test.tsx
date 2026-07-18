import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type HostInfo } from "../../api";
import { settingsFixture } from "../../test/settings";
import { SettingsAppView } from "./SettingsApp";

const t = (key: string) => key;
const hostInfo: HostInfo = {
  hostname: "nas-one", operating_system: "Example Linux", kernel_version: "6.12", architecture: "x86_64",
  ip_addresses: ["192.0.2.10"], application_version: "0.1.0", uptime_seconds: 90061,
  cpu: { model: "Example CPU", physical_cores: 4, logical_threads: 8 },
  memory: { total: 16 * 1024 ** 3, used: 8 * 1024 ** 3, free: 8 * 1024 ** 3, percent: 50 },
  gpus: ["Example GPU"], storage: { path: "/", total: 100 * 1024 ** 3, used: 40 * 1024 ** 3, free: 60 * 1024 ** 3, percent: 40 },
};

describe("settings application", () => {
  beforeEach(() => { vi.spyOn(api, "hostInfo").mockResolvedValue(hostInfo); });
  afterEach(() => vi.restoreAllMocks());

  it("loads host information and presents it in expandable panels", async () => {
    render(<SettingsAppView settings={settingsFixture()} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onOpenApp={vi.fn()} />);

    expect(await screen.findByText("nas-one")).toBeInTheDocument();
    expect(api.hostInfo).toHaveBeenCalledOnce();
    expect(screen.getByText("Example Linux")).toBeInTheDocument();
    expect(screen.getByText("settings.hostHardwarePanel").closest("details")).not.toHaveAttribute("open");

    fireEvent.click(screen.getByText("settings.hostHardwarePanel"));

    await waitFor(() => expect(screen.getByText("settings.hostHardwarePanel").closest("details")).toHaveAttribute("open"));
    expect(screen.getByText("Example CPU")).toBeInTheDocument();
    expect(screen.getByText("Example GPU")).toBeInTheDocument();
  });
  it("searches individual settings and opens their category", () => {
    render(<SettingsAppView settings={settingsFixture()} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onOpenApp={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("settings.search"), { target: { value: "wallpaper" } });

    expect(screen.getByRole("heading", { name: "settings.searchResults" })).toBeInTheDocument();
    const result = screen.getByRole("button", { name: "settings.wallpapersettings.category.personalization" });
    fireEvent.click(result);
    expect(screen.getByRole("heading", { name: "settings.category.personalization" })).toBeInTheDocument();
  });

  it("saves theme and taskbar alignment changes", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<SettingsAppView settings={settingsFixture()} t={t} toast={vi.fn()} onSettingsChange={save} onOpenApp={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "settings.category.personalization" }));

    fireEvent.change(screen.getByLabelText("settings.theme"), { target: { value: "dark" } });
    fireEvent.change(screen.getByLabelText("settings.taskbarAlignment"), { target: { value: "left" } });

    await waitFor(() => expect(save).toHaveBeenCalledWith({ theme: "dark" }));
    expect(save).toHaveBeenCalledWith({ taskbar_alignment: "left" });
  });

  it("saves interface scale and larger text accessibility settings", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    render(<SettingsAppView settings={settingsFixture()} t={t} toast={vi.fn()} onSettingsChange={save} onOpenApp={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "settings.category.accessibility" }));

    fireEvent.change(screen.getByLabelText("settings.interfaceScale"), { target: { value: "125" } });
    fireEvent.click(screen.getByLabelText("settings.largerText"));

    await waitFor(() => expect(save).toHaveBeenCalledWith({ interface_scale: 125 }));
    expect(save).toHaveBeenCalledWith({ larger_text: true });
  });

  it("renders administrative categories only for administrators", () => {
    const common = { t, toast: vi.fn(), onSettingsChange: vi.fn().mockResolvedValue(undefined), onOpenApp: vi.fn() };
    const { rerender } = render(<SettingsAppView settings={settingsFixture()} {...common} />);
    expect(screen.queryByRole("button", { name: "settings.category.administration" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "settings.category.network" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "settings.category.networkResources" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "settings.category.identity" })).not.toBeInTheDocument();

    rerender(<SettingsAppView settings={settingsFixture({ is_admin: true })} {...common} />);
    expect(screen.getByRole("button", { name: "settings.category.administration" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.category.network" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.category.networkResources" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.category.identity" })).toBeInTheDocument();
  });

  it("opens Users and groups from the administrator settings category", () => {
    const openApp = vi.fn();
    render(<SettingsAppView settings={settingsFixture({ is_admin: true })} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onOpenApp={openApp} />);

    fireEvent.click(screen.getByRole("button", { name: "settings.category.identity" }));
    fireEvent.click(screen.getByRole("button", { name: "settings.openUsersAndGroups" }));

    expect(openApp).toHaveBeenCalledWith("identity");
  });

  it("reports a failed automatic save", async () => {
    render(<SettingsAppView settings={settingsFixture()} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockRejectedValue(new Error("offline"))} onOpenApp={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "settings.category.personalization" }));
    fireEvent.change(screen.getByLabelText("settings.theme"), { target: { value: "dark" } });
    expect(await screen.findByText("settings.saveError: offline")).toBeInTheDocument();
  });
});
