import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { within } from "@testing-library/react";
import { api, type AppJob, type ModuleSummary, type PackageModule, type PackagePlan } from "../../api";
import en from "../../locales/en-US.json";
import pl from "../../locales/pl-PL.json";
import { PackageCenterApp } from "./PackageCenterApp";

vi.mock("../../api", () => ({ api: { apps: vi.fn(), modules: vi.fn(), module: vi.fn(), appCategories: vi.fn(), appJobs: vi.fn(), appHistory: vi.fn(), packageSources: vi.fn(), appPlan: vi.fn(), appAction: vi.fn(), cancelAppJob: vi.fn(), retryAppJob: vi.fn() } }));

function module(id: string, overrides: Partial<PackageModule> = {}): PackageModule {
  return {
    id,
    manifest: { id, name: id === "samba" ? "Samba" : "Nginx", description: `${id} description`, long_description: `${id} long description`, category: id === "samba" ? "file_sharing" : "web_server", version: "1.0.0", maintainer: "WebNAS", homepage: null, icon: id === "samba" ? "share-2" : "server", screenshots: [], license: "GPL", supported_distributions: ["debian"], supported_architectures: ["x86_64"], apt_packages: [id], dnf_packages: [id], systemd_services: [id], ports: ["80/tcp"], dependencies: [], conflicts: [], permissions: ["systemd"], config_paths: [`/etc/${id}`], data_paths: [`/var/lib/${id}`], backup_paths: [`/etc/${id}`], proxmox_safe: true, requires_reboot: false, requires_root: true, configurable: true, removable: true, changelog: ["Initial release"] },
    state: { installed: false, installed_version: null, available_version: "1.0.0", update_available: false, requires_reboot: false }, services: { [id]: "inactive" }, status: "available", compatible: true, blocked_by_proxmox: false, distribution: { id: "debian", name: "Debian", architecture: "x86_64", package_manager: "apt-get" }, jobs: [], ...overrides
  };
}

function summary(id: string, overrides: Partial<PackageModule> = {}): ModuleSummary {
  const item = module(id, overrides);
  const activeJob = item.jobs.find((job) => ["queued", "running"].includes(job.status)) || null;
  return {
    ...item,
    module_status: {
      installed: item.state.installed,
      package_version: item.state.installed_version,
      available_version: item.state.available_version,
      update_available: item.state.update_available,
      service_state: Object.values(item.services)[0] || "inactive",
      service_enabled: false,
      services: Object.fromEntries(Object.entries(item.services).map(([name, state]) => [name, { state, enabled: false, required: true }])),
      health: item.status === "error" ? "failed" : item.state.installed ? "healthy" : "not_installed",
      health_message: item.status,
      last_action: "",
      last_action_status: "",
      last_error: item.jobs.find((job) => job.status === "failed")?.error || "",
      metrics: {},
    },
    capabilities: { install: true, update: true, uninstall: true, configure: true, service_control: true, reload: true, logs: true, diagnostics: true, backups: true, import_export: true, healthcheck: true, resources: [], actions: [] },
    active_job: activeJob,
  };
}

const packagePlan: PackagePlan = { module_id: "samba", action: "install", distribution: { id: "debian", name: "Debian", version_id: "12", architecture: "x86_64", package_manager: "apt-get" }, compatible: true, blocked_by_proxmox: false, packages: ["samba", "smbclient", "cifs-utils"], services: ["smbd"], ports: ["445/tcp"], config_paths: ["/etc/samba/smb.conf"], data_paths: ["/var/lib/samba"], permissions: ["systemd"], dependencies: [], conflicts: [], warnings: [], requires_reboot: false, remove_data: false, target_version: "1.0.0", steps: ["apt-get install -y samba smbclient cifs-utils"] };
const queuedInstall: AppJob = { id: "install-1", module_id: "samba", action: "install", status: "queued", progress: 0, created_at: 1, error: "", current_step: "Queued", log_tail: [] };

describe("Package Center", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.apps).mockResolvedValue([module("samba"), module("nginx")]);
    vi.mocked(api.modules).mockResolvedValue([summary("samba"), summary("nginx")]);
    vi.mocked(api.module).mockImplementation((id) => Promise.resolve(summary(id)));
    vi.mocked(api.appCategories).mockResolvedValue(["file_sharing", "web_server"]);
    vi.mocked(api.appJobs).mockResolvedValue([]);
    vi.mocked(api.appHistory).mockResolvedValue([]);
    vi.mocked(api.packageSources).mockResolvedValue([]);
    vi.mocked(api.appPlan).mockResolvedValue(packagePlan);
    vi.mocked(api.appAction).mockResolvedValue({ job: queuedInstall });
  });

  it("renders, searches, filters and opens package details", async () => {
    const configure = vi.fn();
    render(<PackageCenterApp t={(key) => key} toast={vi.fn()} onOpenModule={configure} />);
    expect(await screen.findByText("Samba")).toBeInTheDocument();
    expect(screen.getByText("Nginx")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "action.open" })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("package.search"), { target: { value: "nginx" } });
    expect(screen.queryByText("Samba")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("package.search"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("package.category"), { target: { value: "file_sharing" } });
    expect(screen.queryByText("Nginx")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Samba/ }));
    expect(screen.getByText("samba long description")).toBeInTheDocument();
    expect(screen.getByText("package.changelog")).toBeInTheDocument();
    expect(screen.getByText("package.logs")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "package.configure" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "store.install" }).length).toBeGreaterThan(0);
    expect(configure).not.toHaveBeenCalled();
  });

  it("keeps Samba in the catalog before its runtime status is available", async () => {
    vi.mocked(api.modules).mockResolvedValue([]);

    const { container } = render(<PackageCenterApp t={(key) => key} toast={vi.fn()} />);

    expect(await screen.findByText("Samba")).toBeInTheDocument();
    expect(screen.getByText("samba description")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "store.install" }).length).toBeGreaterThan(0);
    expect(container.querySelector(".package-icon .lucide-share2")).toBeInTheDocument();
    expect(api.apps).toHaveBeenCalledOnce();
  });

  it("shows and confirms a dry-run plan before installation", async () => {
    render(<PackageCenterApp t={(key) => key} toast={vi.fn()} />);
    await screen.findByText("Samba");
    fireEvent.click(screen.getAllByRole("button", { name: "store.install" })[0]);

    expect(await screen.findByText("apt-get install -y samba smbclient cifs-utils")).toBeInTheDocument();
    expect(screen.queryByLabelText("settings.adminPassword")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "package.confirmOperation" }));
    await waitFor(() => expect(api.appAction).toHaveBeenCalledWith("samba", "install", false));
    expect(await screen.findByRole("dialog", { name: "package.liveJobTitle" })).toBeInTheDocument();
    expect(screen.getByText("package.backgroundJobHint")).toBeInTheDocument();
  });

  it("offers opening and service control for an installed module", async () => {
    const installed = summary("samba", { state: { installed: true, installed_version: "1.0.0", available_version: "1.0.0", update_available: false, requires_reboot: false }, services: { smbd: "active" }, status: "running" });
    vi.mocked(api.modules).mockResolvedValue([installed]);
    const open = vi.fn();
    render(<PackageCenterApp t={(key) => key} toast={vi.fn()} onOpenModule={open} />);
    await screen.findByText("Samba");
    const sambaCard = screen.getByText("Samba").closest("article");
    expect(sambaCard).not.toBeNull();
    fireEvent.click(within(sambaCard!).getByRole("button", { name: "action.open" }));
    expect(open).toHaveBeenCalledWith("samba");
    expect(within(sambaCard!).getByRole("button", { name: "store.stop" })).toBeInTheDocument();
    expect(within(sambaCard!).queryByRole("button", { name: "store.reinstall" })).not.toBeInTheDocument();
    expect(within(sambaCard!).queryByRole("button", { name: "store.install" })).not.toBeInTheDocument();

    fireEvent.click(within(sambaCard!).getByRole("button", { name: "package.details" }));
    fireEvent.click(screen.getByRole("button", { name: "store.reinstall" }));
    await waitFor(() => expect(api.appPlan).toHaveBeenCalledWith("samba", "reinstall", false));
  });

  it("disables package actions and shows progress while an operation is active", async () => {
    const running = { id: "job-running", module_id: "samba", action: "install", status: "running" as const, progress: 35, created_at: 1, error: "", current_step: "Install packages", log_tail: [] };
    vi.mocked(api.modules).mockResolvedValue([summary("samba", { jobs: [running] })]);

    render(<PackageCenterApp t={(key) => key} toast={vi.fn()} />);

    expect(await screen.findByText("package.operation.install")).toBeInTheDocument();
    const sambaCard = screen.getByText("Samba").closest("article");
    expect(sambaCard).not.toBeNull();
    expect(within(sambaCard!).getByRole("button", { name: "store.install" })).toBeDisabled();
    expect(within(sambaCard!).getByText("35%")).toBeInTheDocument();
  });

  it("reopens the live status and log dialog from the active reinstall banner", async () => {
    const reinstalling = { id: "job-reinstall", module_id: "samba", action: "reinstall", status: "running" as const, progress: 62, created_at: 1, error: "", current_step: "Installing cifs-utils", log_tail: [{ id: 1, created_at: 2, stream: "stdout", line: "Unpacking cifs-utils" }] };
    const installed = { installed: true, installed_version: "1.0.0", available_version: "1.0.0", update_available: false, requires_reboot: false };
    vi.mocked(api.modules).mockResolvedValue([summary("samba", { state: installed, services: { smbd: "active" }, status: "running", jobs: [reinstalling] })]);

    render(<PackageCenterApp t={(key) => key} toast={vi.fn()} />);

    const banner = await screen.findByRole("button", { name: /package.showLiveJob.*package.operation.reinstall/ });
    fireEvent.click(banner);

    const dialog = await screen.findByRole("dialog", { name: "package.liveJobTitle" });
    expect(within(dialog).getByText("62%")).toBeInTheDocument();
    expect(within(dialog).getByText("Installing cifs-utils")).toBeInTheDocument();
    expect(within(dialog).getByText(/Unpacking cifs-utils/)).toBeInTheDocument();
  });

  it("renders job progress, errors and incompatible modules", async () => {
    const failed = { id: "job-1", module_id: "samba", action: "install", status: "failed" as const, progress: 45, created_at: 1, error: "APT failed", current_step: "Install packages", log_tail: [{ id: 1, created_at: 1, stream: "stderr", line: "Repository unavailable" }] };
    vi.mocked(api.appJobs).mockResolvedValue([failed]);
    vi.mocked(api.modules).mockResolvedValue([summary("samba", { status: "error", jobs: [failed] }), summary("nginx", { status: "incompatible", compatible: false })]);
    render(<PackageCenterApp t={(key) => key} toast={vi.fn()} />);
    expect((await screen.findAllByText("package.status.error")).length).toBeGreaterThan(0);
    expect(screen.queryByText("package.status.incompatible")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /package.tab.jobs/ }));
    expect(screen.getByText("APT failed")).toBeInTheDocument();
    expect(screen.getByText(/Repository unavailable/)).toBeInTheDocument();
  });

  it("keeps all package-center translation keys in Polish and English", () => {
    const keys = Object.keys(pl).filter((key) => key.startsWith("package."));
    expect(keys.length).toBeGreaterThan(50);
    expect(keys.every((key) => key in en)).toBe(true);
    expect(Object.keys(en).filter((key) => key.startsWith("package.")).every((key) => key in pl)).toBe(true);
  });
});
