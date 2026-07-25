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
  beforeEach(() => {
    vi.spyOn(api, "hostInfo").mockResolvedValue(hostInfo);
    vi.spyOn(api, "wallpapers").mockResolvedValue({ items: [], max_files: 24, max_file_size: 10 * 1024 * 1024 });
    vi.spyOn(api, "identityUsers").mockResolvedValue([]);
    vi.spyOn(api, "identityGroups").mockResolvedValue([]);
    vi.spyOn(api, "identityRoles").mockResolvedValue({ permissions: [], roles: { admin: [], operator: [], auditor: [], user: [] } });
    vi.spyOn(api, "identityHistory").mockResolvedValue([]);
  });
  afterEach(() => { vi.restoreAllMocks(); window.sessionStorage.clear(); });

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
  it("searches for wallpaper and opens the nested wallpaper gallery", async () => {
    render(<SettingsAppView settings={settingsFixture()} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onOpenApp={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("settings.search"), { target: { value: "wallpaper" } });

    expect(screen.getByRole("heading", { name: "settings.searchResults" })).toBeInTheDocument();
    const result = screen.getByRole("button", { name: "settings.wallpapersettings.category.personalization" });
    fireEvent.click(result);
    expect(screen.getByRole("heading", { name: "settings.wallpaper" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "action.back" })).toBeInTheDocument();
    expect(await screen.findByRole("radiogroup", { name: "settings.builtInWallpapers" })).toBeInTheDocument();
  });

  it("selects a built-in wallpaper and uploads a private wallpaper", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const uploaded = { id: "a".repeat(32), name: "mountains.png", url: `/api/settings/wallpapers/${"a".repeat(32)}`, size: 128, created_at: 100 };
    const upload = vi.spyOn(api, "uploadWallpaper").mockResolvedValue(uploaded);
    render(<SettingsAppView settings={settingsFixture()} t={t} toast={vi.fn()} onSettingsChange={save} onOpenApp={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "settings.category.personalization" }));
    fireEvent.click(screen.getByRole("button", { name: /settings.wallpaper/ }));
    fireEvent.click(screen.getByRole("radio", { name: "settings.wallpaperPreset.aurora" }));
    await waitFor(() => expect(save).toHaveBeenCalledWith({ wallpaper: "/wallpapers/aurora.svg" }));

    const file = new File(["image"], "mountains.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("settings.addWallpaper"), { target: { files: [file] } });
    await waitFor(() => expect(upload).toHaveBeenCalledWith(file));
    await waitFor(() => expect(save).toHaveBeenCalledWith({ wallpaper: uploaded.url }));
    expect(screen.getByRole("radio", { name: "mountains.png" })).toBeInTheDocument();
  });

  it("reports the active settings section so the window can restore it", () => {
    const onSectionChange = vi.fn();
    render(<SettingsAppView settings={settingsFixture()} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onOpenApp={vi.fn()} onSectionChange={onSectionChange} />);

    fireEvent.click(screen.getByRole("button", { name: "settings.category.personalization" }));

    expect(onSectionChange).toHaveBeenCalledWith("personalization");
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

    const scale = screen.getByLabelText("settings.interfaceScale");
    expect(scale).toHaveAttribute("min", "50");
    expect(scale).toHaveAttribute("max", "200");
    fireEvent.change(scale, { target: { value: "175" } });
    fireEvent.blur(scale);
    fireEvent.click(screen.getByLabelText("settings.largerText"));

    await waitFor(() => expect(save).toHaveBeenCalledWith({ interface_scale: 175 }));
    expect(save).toHaveBeenCalledWith({ larger_text: true });
  });

  it("renders administrative categories only for administrators", () => {
    const common = { t, toast: vi.fn(), onSettingsChange: vi.fn().mockResolvedValue(undefined), onOpenApp: vi.fn() };
    const { rerender } = render(<SettingsAppView settings={settingsFixture()} {...common} />);
    expect(screen.queryByRole("button", { name: "settings.category.administration" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "settings.category.network" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "settings.category.networkResources" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "settings.category.identity" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "settings.category.policies" })).not.toBeInTheDocument();

    rerender(<SettingsAppView settings={settingsFixture({ is_admin: true })} {...common} />);
    expect(screen.getByRole("button", { name: "settings.category.administration" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.category.network" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.category.networkResources" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.category.identity" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings.category.policies" })).toBeInTheDocument();
  });

  it("embeds the complete Users and groups module in administrator settings", async () => {
    const openApp = vi.fn();
    render(<SettingsAppView settings={settingsFixture({ is_admin: true, permissions: ["users.view", "groups.view", "access.view"] })} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onOpenApp={openApp} />);

    fireEvent.click(screen.getByRole("button", { name: "settings.category.identity" }));

    expect(await screen.findByRole("navigation", { name: "identity.tabs" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "identity.tab.users" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "identity.tab.groups" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "identity.tab.roles" })).toBeInTheDocument();
    await waitFor(() => expect(api.identityUsers).toHaveBeenCalled());
    expect(openApp).not.toHaveBeenCalled();
  });

  it("runs an update manually from administration settings", async () => {
    vi.spyOn(api, "systemStatus").mockResolvedValue({ service: "webnas", version: "1", port: 5000, data_dir: "/var/lib/webnas", log_dir: "/var/log/webnas", temp_dir: "/tmp" });
    vi.spyOn(api, "checkUpdates").mockResolvedValue({ branch: "main", local: "a".repeat(40), remote: "b".repeat(40), installed_version: "1.4.2", available_version: "1.5.0", update_available: true, available: true, source: "GitHub · example/repository", source_url: "https://github.com/example/repository", released_at: Math.floor((Date.now() - 2 * 86_400_000) / 1000) });
    vi.spyOn(api, "autoUpdate").mockResolvedValue({ check_enabled: true, enabled: false, interval_hours: 12, update_config: true, last_checked: null, last_run: null, last_error: "", last_pid: null, next_check: null });
    vi.spyOn(api, "proxmoxSafety").mockResolvedValue({ is_proxmox: false, safe_mode_enabled: false, protected_paths: [], blocked_admin_features: [], allowed_roots_effective: [], service_user: "webnas", warnings: [] });
    const run = vi.spyOn(api, "runAutoUpdate").mockResolvedValue({ ok: true, pid: 123, log: "/var/log/webnas/update.log", updated: true });
    const progress = vi.spyOn(api, "updateProgress").mockResolvedValue({ state: "completed", running: false, pid: 123, exit_code: 0, started_at: 10, finished_at: 20, log: "/var/log/webnas/update.log", lines: ["Downloading", "Installation complete"] });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<SettingsAppView settings={settingsFixture({ is_admin: true })} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onOpenApp={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "settings.category.administration" }));
    await screen.findByText("settings.updateAvailable");
    expect(screen.getByRole("link", { name: "GitHub · example/repository" })).toHaveAttribute("href", "https://github.com/example/repository");
    expect(screen.getByText(/\(2 d 0 godz\. 0 min desktop\.timeAgo\)/)).toBeInTheDocument();
    expect(screen.getByText("v1.4.2")).toBeInTheDocument();
    expect(screen.getByText("v1.5.0")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /settings.updateNow/ }));
    await waitFor(() => expect(run).toHaveBeenCalledWith(false));
    expect(await screen.findByRole("dialog", { name: "settings.updateProgressTitle" })).toBeInTheDocument();
    await waitFor(() => expect(progress).toHaveBeenCalled());
    expect(await screen.findByText("settings.updatePhase.completed")).toBeInTheDocument();
    expect(screen.getByText(/Installation complete/)).toBeInTheDocument();
  });

  it("configures the 12-hour update check policy independently from automatic installation", async () => {
    vi.spyOn(api, "autoUpdate").mockResolvedValue({ check_enabled: true, enabled: false, interval_hours: 12, update_config: false, last_checked: null, last_run: null, last_error: "", last_pid: null, next_check: 100 });
    vi.spyOn(api, "dockerContainerDefaultsPolicy").mockResolvedValue({ resource_limits_enabled: true, memory_mb: 512, memory_swap_mb: 1024, cpus: 1, pids: 128 });
    const saveAuto = vi.spyOn(api, "saveAutoUpdate").mockImplementation(async (payload) => ({ ...payload, last_checked: null, last_run: null, last_error: "", last_pid: null, next_check: 200 }));
    render(<SettingsAppView settings={settingsFixture({ is_admin: true })} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onOpenApp={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "settings.category.policies" }));
    expect(await screen.findByText("settings.policyCategoryChecking")).toBeInTheDocument();
    expect(screen.getAllByText("updates.check_enabled")).toHaveLength(2);
    fireEvent.click(screen.getByText("updates.check_interval_hours").closest("button")!);
    expect(screen.getAllByText("12 h")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: /settings.editRule/ }));
    expect(screen.getByLabelText("settings.updateInterval")).toHaveValue("12");
    fireEvent.change(screen.getByLabelText("settings.updateInterval"), { target: { value: "24" } });
    await waitFor(() => expect(saveAuto).toHaveBeenCalledWith({ check_enabled: true, enabled: false, interval_hours: 24, update_config: false }));
    fireEvent.click(screen.getByRole("button", { name: /settings.policyCategoryInstallation/ }));
    fireEvent.click(screen.getByRole("button", { name: /settings.editRule/ }));
    fireEvent.click(screen.getByLabelText("settings.automaticUpdates"));
    await waitFor(() => expect(saveAuto).toHaveBeenLastCalledWith({ check_enabled: true, enabled: true, interval_hours: 24, update_config: false }));
  });

  it("edits the default container resource policy", async () => {
    vi.spyOn(api, "autoUpdate").mockResolvedValue({ check_enabled: true, enabled: false, interval_hours: 12, update_config: false, last_checked: null, last_run: null, last_error: "", last_pid: null, next_check: 100 });
    vi.spyOn(api, "dockerContainerDefaultsPolicy").mockResolvedValue({ resource_limits_enabled: true, memory_mb: 512, memory_swap_mb: 1024, cpus: 1, pids: 128 });
    const save = vi.spyOn(api, "saveDockerContainerDefaultsPolicy").mockImplementation(async (value) => value);
    render(<SettingsAppView settings={settingsFixture({ is_admin: true })} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onOpenApp={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "settings.category.policies" }));
    fireEvent.click(await screen.findByRole("button", { name: /settings.policyCategoryContainers/ }));
    fireEvent.click(screen.getByRole("button", { name: /settings.editRule/ }));
    fireEvent.change(screen.getByLabelText("docker.field.memoryMb"), { target: { value: "2048" } });
    fireEvent.change(screen.getByLabelText("docker.field.memorySwapMb"), { target: { value: "4096" } });
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));

    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ memory_mb: 2048, memory_swap_mb: 4096, cpus: 1, pids: 128 })));
  });

  it("restores a persisted update result after the service reconnects", async () => {
    vi.spyOn(api, "systemStatus").mockResolvedValue({ service: "webnas", version: "1", port: 5000, data_dir: "/var/lib/webnas", log_dir: "/var/log/webnas", temp_dir: "/tmp" });
    vi.spyOn(api, "checkUpdates").mockResolvedValue({ branch: "main", local: "b".repeat(40), remote: "b".repeat(40), update_available: false, available: true });
    vi.spyOn(api, "autoUpdate").mockResolvedValue({ check_enabled: true, enabled: false, interval_hours: 12, update_config: false, last_checked: null, last_run: 20, last_error: "", last_pid: 321, next_check: null });
    vi.spyOn(api, "proxmoxSafety").mockResolvedValue({ is_proxmox: false, safe_mode_enabled: false, protected_paths: [], blocked_admin_features: [], allowed_roots_effective: [], service_user: "webnas", warnings: [] });
    vi.spyOn(api, "updateProgress").mockResolvedValue({ state: "completed", running: false, pid: 321, unit: "webnas-self-update-20.service", exit_code: 0, started_at: Math.floor(Date.now() / 1000), finished_at: Math.floor(Date.now() / 1000), log: "/var/log/webnas/update.log", lines: ["Installation complete"] });
    render(<SettingsAppView settings={settingsFixture({ is_admin: true })} initialSection="administration" t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockResolvedValue(undefined)} onOpenApp={vi.fn()} />);

    expect(await screen.findByRole("dialog", { name: "settings.updateProgressTitle" })).toBeInTheDocument();
    expect(screen.getByText("settings.updatePhase.completed")).toBeInTheDocument();
    expect(screen.getByText("Installation complete")).toBeInTheDocument();
  });

  it("reports a failed automatic save", async () => {
    render(<SettingsAppView settings={settingsFixture()} t={t} toast={vi.fn()} onSettingsChange={vi.fn().mockRejectedValue(new Error("offline"))} onOpenApp={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "settings.category.personalization" }));
    fireEvent.change(screen.getByLabelText("settings.theme"), { target: { value: "dark" } });
    expect(await screen.findByText("settings.saveError: offline")).toBeInTheDocument();
  });
});
