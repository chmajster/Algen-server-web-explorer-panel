import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type ModuleSummary } from "../../api";
import { ManagedModuleApp } from "./ManagedModuleApp";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, api: { ...actual.api, module: vi.fn(), moduleResource: vi.fn(), moduleAction: vi.fn(), moduleService: vi.fn(), saveModuleConnection: vi.fn() } };
});

const summary = {
  id: "docker", manifest: { id: "docker", name: "Docker", description: "Containers", long_description: "", category: "containers", version: "1", maintainer: "WebNAS", icon: "boxes", screenshots: [], license: "Apache", supported_distributions: ["debian"], supported_architectures: ["x86_64"], apt_packages: ["docker.io"], dnf_packages: ["docker"], systemd_services: ["docker"], ports: [], dependencies: [], conflicts: [], permissions: [], config_paths: [], data_paths: [], backup_paths: [], proxmox_safe: false, requires_reboot: false, requires_root: true, configurable: true, removable: true, changelog: [] },
  state: { installed: true, installed_version: "26", available_version: "26", update_available: false, requires_reboot: false }, services: { docker: "active" }, status: "running", compatible: true, blocked_by_proxmox: false, distribution: { id: "debian", name: "Debian", architecture: "x86_64", package_manager: "apt-get" }, jobs: [],
  module_status: { installed: true, package_version: "26", update_available: false, service_state: "active", service_enabled: true, services: {}, health: "healthy", health_message: "Available", last_action: "", last_action_status: "", last_error: "", metrics: {} },
  capabilities: { install: true, update: true, uninstall: true, configure: true, service_control: true, reload: true, logs: true, diagnostics: true, backups: false, import_export: false, healthcheck: true, resources: ["containers"], actions: ["container_start"] }, active_job: null,
} satisfies ModuleSummary;

const linuxSummary = {
  ...summary,
  id: "linux-updates",
  manifest: { ...summary.manifest, id: "linux-updates", name: "Linux system updates", description: "Updates", category: "system_tools", apt_packages: ["apt"], dnf_packages: ["dnf"], systemd_services: [], configurable: false },
  services: {},
  module_status: { ...summary.module_status, package_version: null, update_available: true, service_state: "not_applicable", metrics: { updates: 2, security_updates: 1, reboot_required: false, package_manager: "apt-get" } },
  capabilities: { ...summary.capabilities, configure: false, service_control: false, reload: false, logs: false, resources: ["packages", "security", "history", "reboot"], actions: ["refresh", "upgrade_all", "upgrade_security"] },
} satisfies ModuleSummary;

const queuedUpdate = { id: "update-1", module_id: "linux-updates", action: "manage", operation: "upgrade_security", status: "queued" as const, progress: 0, created_at: 1, log_tail: [], error: "", current_step: "Queued" };

describe("ManagedModuleApp", () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.module).mockResolvedValue(summary); vi.mocked(api.moduleResource).mockResolvedValue({ resource: "containers", items: [{ ID: "abc", Names: "web", State: "exited" }], total: 1 }); vi.mocked(api.moduleAction).mockResolvedValue({ job: queuedUpdate }); vi.mocked(api.moduleService).mockResolvedValue({ job: queuedUpdate }); });

  it("keeps mutating controls hidden from auditors", async () => {
    render(<ManagedModuleApp moduleId="docker" permissions={["modules.view", "docker.view"]} t={(key) => key} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /managed.containers/ }));
    await screen.findByText("web");
    expect(screen.queryByTitle("module.start")).not.toBeInTheDocument();
  });

  it("uses the authenticated session for an authorized container action", async () => {
    render(<ManagedModuleApp moduleId="docker" permissions={["modules.view", "docker.view", "docker.manage_containers"]} t={(key) => key} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /managed.containers/ }));
    await screen.findByText("web");
    fireEvent.click(screen.getByTitle("module.start"));
    expect(screen.queryByLabelText("settings.adminPassword")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));
    await waitFor(() => expect(api.moduleAction).toHaveBeenCalledWith("docker", "container_start", { target: "abc" }));
    expect(await screen.findByRole("dialog", { name: "package.liveJobTitle" })).toBeInTheDocument();
  });

  it("installs Pi-hole from the controlled Docker application catalog without placing its password in the job", async () => {
    vi.mocked(api.module).mockResolvedValue({ ...summary, capabilities: { ...summary.capabilities, resources: ["apps", "containers"], actions: ["app_install", "app_start", "app_stop", "app_update", "app_remove"] } });
    vi.mocked(api.moduleResource).mockResolvedValue({ resource: "apps", items: [{ id: "pihole", name: "Pi-hole", description: "DNS filtering", category: "dns", image: "pihole/pihole:latest", ports: ["53/tcp", "53/udp", "8080/tcp"], panel_port: 8080, installed: false, running: false, managed: false, status: "not_installed" }], total: 1 });
    vi.mocked(api.saveModuleConnection).mockResolvedValue({ base_url: "http://127.0.0.1:8080", username: "", secret_configured: true });

    render(<ManagedModuleApp moduleId="docker" permissions={["modules.view", "docker.view", "docker.manage_containers"]} t={(key) => key} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /managed.apps/ }));
    fireEvent.click(await screen.findByRole("button", { name: "store.install" }));
    fireEvent.change(screen.getByLabelText("managed.piholePassword"), { target: { value: "private-password" } });
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));

    await waitFor(() => expect(api.saveModuleConnection).toHaveBeenCalledWith("pihole", { base_url: "http://127.0.0.1:8080", username: "", secret: "private-password" }));
    expect(api.moduleAction).toHaveBeenCalledWith("docker", "app_install", { app_id: "pihole", timezone: "Europe/Warsaw" });
    expect(JSON.stringify(vi.mocked(api.moduleAction).mock.calls)).not.toContain("private-password");
  });

  it("uses the authenticated admin session for routine module service controls", async () => {
    render(<ManagedModuleApp moduleId="docker" permissions={["modules.view", "docker.view", "docker.manage_containers"]} t={(key) => key} toast={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: /managed.service/ }));
    fireEvent.click(screen.getByRole("button", { name: "module.restart" }));

    expect(screen.queryByLabelText("settings.adminPassword")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));

    await waitFor(() => expect(api.moduleService).toHaveBeenCalledWith("docker", "restart"));
  });

  it("starts security patching from the update button through the durable module action", async () => {
    vi.mocked(api.module).mockResolvedValue(linuxSummary);
    vi.mocked(api.moduleResource).mockResolvedValue({ resource: "security", items: [{ name: "openssl", available_version: "3.0.2", security: true }], total: 1 });
    render(<ManagedModuleApp moduleId="linux-updates" permissions={["modules.view", "updates.view", "updates.apply"]} t={(key) => key} toast={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: /managed.securityUpdates/ }));
    await screen.findByText("openssl");
    expect(screen.getByText("managed.detachedUpdateHint")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "managed.updateNow" }));
    expect(screen.getByText("managed.confirm.securityTitle")).toBeInTheDocument();
    expect(screen.getByText("managed.confirm.scopeSecurity")).toBeInTheDocument();
    expect(screen.getByText("managed.confirm.background")).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getByText("1")).toBeInTheDocument();
    expect(screen.queryByLabelText("settings.adminPassword")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "managed.confirm.installSecurity" }));

    await waitFor(() => expect(api.moduleAction).toHaveBeenCalledWith("linux-updates", "upgrade_security", {}));
  });

  it("shows the package manager instead of a fictitious service state for Linux updates", async () => {
    vi.mocked(api.module).mockResolvedValue(linuxSummary);

    render(<ManagedModuleApp moduleId="linux-updates" permissions={["modules.view", "updates.view"]} t={(key) => key} toast={vi.fn()} />);

    expect(await screen.findByText("managed.field.package_manager: apt-get")).toBeInTheDocument();
    expect(screen.getByText("managed.field.package_manager")).toBeInTheDocument();
    expect(screen.queryByText("module.serviceState: available")).not.toBeInTheDocument();
  });

  it("shows a healthy empty security state and disables an unnecessary update", async () => {
    vi.mocked(api.module).mockResolvedValue({ ...linuxSummary, module_status: { ...linuxSummary.module_status, update_available: true, metrics: { updates: 2, security_updates: 0, reboot_required: false } } });
    vi.mocked(api.moduleResource).mockResolvedValue({ resource: "security", items: [], total: 0 });

    render(<ManagedModuleApp moduleId="linux-updates" permissions={["modules.view", "updates.view", "updates.apply"]} t={(key) => key} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /managed.securityUpdates/ }));

    expect(await screen.findByText("managed.noSecurityUpdates")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "managed.updateNow" })).toBeDisabled();
  });

  it("does not reload the visible resource during periodic status polling", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(api.module).mockResolvedValue(linuxSummary);
      vi.mocked(api.moduleResource).mockResolvedValue({ resource: "packages", items: [{ name: "curl", available_version: "8.1" }], total: 1 });

      render(<ManagedModuleApp moduleId="linux-updates" permissions={["modules.view", "updates.view"]} t={(key) => key} toast={vi.fn()} />);
      await act(async () => { await Promise.resolve(); });
      fireEvent.click(screen.getByRole("button", { name: /managed.packages/ }));
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(screen.getByText("curl")).toBeInTheDocument();
      expect(api.moduleResource).toHaveBeenCalledTimes(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
      expect(api.module).toHaveBeenCalledTimes(2);
      expect(api.moduleResource).toHaveBeenCalledTimes(1);
      expect(screen.getByText("curl")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("exposes resource failures with a retry instead of leaving the module loading forever", async () => {
    vi.mocked(api.module).mockResolvedValue(linuxSummary);
    vi.mocked(api.moduleResource).mockRejectedValue(new Error("APT metadata unavailable"));

    render(<ManagedModuleApp moduleId="linux-updates" permissions={["modules.view", "updates.view"]} t={(key) => key} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /managed.packages/ }));

    expect(await screen.findByText("managed.resourceLoadFailed")).toBeInTheDocument();
    expect(screen.getByText("APT metadata unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "action.retry" })).toBeInTheDocument();
  });

  it("runs a real repository metadata refresh from the package toolbar", async () => {
    vi.mocked(api.module).mockResolvedValue(linuxSummary);
    vi.mocked(api.moduleResource).mockResolvedValue({ resource: "packages", items: [{ name: "curl", available_version: "8.1" }], total: 1 });

    render(<ManagedModuleApp moduleId="linux-updates" permissions={["modules.view", "updates.view", "updates.apply"]} t={(key) => key} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /managed.packages/ }));
    await screen.findByText("curl");
    fireEvent.click(screen.getByRole("button", { name: "managed.refreshMetadata" }));
    expect(screen.getByText("managed.confirm.refreshIntro")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "managed.confirm.checkRepositories" }));

    await waitFor(() => expect(api.moduleAction).toHaveBeenCalledWith("linux-updates", "refresh", {}));
  });
});
