import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type ModuleSummary } from "../../api";
import { ManagedModuleApp } from "./ManagedModuleApp";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, api: { ...actual.api, module: vi.fn(), moduleResource: vi.fn(), moduleAction: vi.fn() } };
});

const summary = {
  id: "docker", manifest: { id: "docker", name: "Docker", description: "Containers", long_description: "", category: "containers", version: "1", maintainer: "WebNAS", icon: "boxes", screenshots: [], license: "Apache", supported_distributions: ["debian"], supported_architectures: ["x86_64"], apt_packages: ["docker.io"], dnf_packages: ["docker"], systemd_services: ["docker"], ports: [], dependencies: [], conflicts: [], permissions: [], config_paths: [], data_paths: [], backup_paths: [], proxmox_safe: false, requires_reboot: false, requires_root: true, configurable: true, removable: true, changelog: [] },
  state: { installed: true, installed_version: "26", available_version: "26", update_available: false, requires_reboot: false }, services: { docker: "active" }, status: "running", compatible: true, blocked_by_proxmox: false, distribution: { id: "debian", name: "Debian", architecture: "x86_64", package_manager: "apt-get" }, jobs: [],
  module_status: { installed: true, package_version: "26", update_available: false, service_state: "active", service_enabled: true, services: {}, health: "healthy", health_message: "Available", last_action: "", last_action_status: "", last_error: "", metrics: {} },
  capabilities: { install: true, update: true, uninstall: true, configure: true, service_control: true, reload: true, logs: true, diagnostics: true, backups: false, import_export: false, healthcheck: true, resources: ["containers"], actions: ["container_start"] }, active_job: null,
} satisfies ModuleSummary;

describe("ManagedModuleApp", () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.module).mockResolvedValue(summary); vi.mocked(api.moduleResource).mockResolvedValue({ resource: "containers", items: [{ ID: "abc", Names: "web", State: "exited" }], total: 1 }); });

  it("keeps mutating controls hidden from auditors", async () => {
    render(<ManagedModuleApp moduleId="docker" permissions={["modules.view", "docker.view"]} t={(key) => key} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /managed.containers/ }));
    await screen.findByText("web");
    expect(screen.queryByTitle("module.start")).not.toBeInTheDocument();
  });

  it("opens PAM confirmation for an operator container action", async () => {
    render(<ManagedModuleApp moduleId="docker" permissions={["modules.view", "docker.view", "docker.operate"]} t={(key) => key} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /managed.containers/ }));
    await screen.findByText("web");
    fireEvent.click(screen.getByTitle("module.start"));
    await waitFor(() => expect(screen.getByLabelText("settings.adminPassword")).toBeInTheDocument());
  });
});
