import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type ModuleSummary } from "../../api";
import { ManagedModuleApp } from "./ManagedModuleApp";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, api: { ...actual.api, module: vi.fn(), moduleResource: vi.fn(), moduleAction: vi.fn(), moduleService: vi.fn() } };
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
  module_status: { ...summary.module_status, package_version: null, update_available: true, service_state: "available", metrics: { updates: 2, security_updates: 1, reboot_required: false } },
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
    expect(screen.queryByLabelText("settings.adminPassword")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));

    await waitFor(() => expect(api.moduleAction).toHaveBeenCalledWith("linux-updates", "upgrade_security", {}));
  });
});
