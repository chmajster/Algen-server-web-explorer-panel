import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { DockerManagerApp } from "./DockerManagerApp";

vi.mock("../../api", () => ({
  api: {
    dockerDashboard: vi.fn(), dockerEvents: vi.fn(), dockerContainers: vi.fn(), dockerContainer: vi.fn(), dockerContainerStats: vi.fn(),
    dockerContainerLogs: vi.fn(), dockerContainerProcesses: vi.fn(), createDockerContainer: vi.fn(), dockerContainerAction: vi.fn(),
    dockerContainerBackup: vi.fn(), dockerImages: vi.fn(), dockerImageAction: vi.fn(), importDockerImage: vi.fn(), dockerApps: vi.fn(),
    dockerComposeProjects: vi.fn(), dockerVolumes: vi.fn(), dockerNetworks: vi.fn(), dockerRegistries: vi.fn(), dockerBackups: vi.fn(),
    dockerDaemonConfig: vi.fn(), dockerDiagnostics: vi.fn(), dockerEngineAction: vi.fn(), dockerPrune: vi.fn(),
  },
}));
vi.mock("../package-center/PackageJobDialog", () => ({ PackageJobDialog: () => <div>job-dialog</div> }));

const status = { installed: true, package_version: "29.0.0", update_available: false, service_state: "active", service_enabled: true, services: {}, health: "healthy", health_message: "ok", last_action: "", last_action_status: "", last_error: "", metrics: {} };
const dashboard = { status, counts: { containers: 3, running: 2, images: 4, volumes: 5, networks: 3 }, storage: [], security: [], engine: {}, prune_preview: {} };
const t = (key: string) => key;

describe("DockerManagerApp", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.dockerDashboard).mockResolvedValue(dashboard as never);
    vi.mocked(api.dockerEvents).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.dockerContainers).mockResolvedValue({ items: [{ ID: "abc", Names: "web", Image: "nginx:stable", State: "running", Status: "Up" }], total: 1, page: 1, page_size: 50, pages: 1 });
    vi.mocked(api.createDockerContainer).mockResolvedValue({ job: { id: "job-1" } } as never);
  });

  it("renders a dedicated dashboard and all manager sections", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.view_images", "docker.manage_compose", "docker.manage_volumes", "docker.manage_networks", "docker.manage_registries", "docker.export_backup", "docker.diagnostics"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "docker.title" })).toBeInTheDocument();
    expect(screen.getAllByText("3")).toHaveLength(2);
    for (const section of ["containers", "images", "apps", "compose", "volumes", "networks", "registries", "events", "backups", "engine", "diagnostics"]) {
      expect(screen.getByRole("button", { name: `docker.section.${section}` })).toBeInTheDocument();
    }
  });

  it("does not expose inaccessible manager sections", async () => {
    render(<DockerManagerApp permissions={["docker.view"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "docker.section.dashboard" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "docker.section.registries" })).not.toBeInTheDocument();
  });

  it("opens the typed create wizard and submits secrets only in the request body", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.create_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByRole("button", { name: "docker.createContainer" }));
    fireEvent.change(screen.getByLabelText("docker.field.name"), { target: { value: "safe-web" } });
    fireEvent.change(screen.getByLabelText("docker.field.image"), { target: { value: "nginx:stable" } });
    fireEvent.click(screen.getByRole("button", { name: /action.next/ }));
    fireEvent.change(screen.getByLabelText("docker.secretName"), { target: { value: "APP_PASSWORD" } });
    const secretValue = screen.getByLabelText("docker.secretValue");
    expect(secretValue).toHaveAttribute("type", "password");
    fireEvent.change(secretValue, { target: { value: "private" } });
    fireEvent.click(screen.getByRole("button", { name: /action.next/ }));
    expect(screen.getByText("docker.highRiskBlocked")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /action.next/ }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "docker.createContainer" }));
    await waitFor(() => expect(api.createDockerContainer).toHaveBeenCalled());
    expect(vi.mocked(api.createDockerContainer).mock.calls[0][0]).toMatchObject({ name: "safe-web", image: "nginx:stable", secret_environment: { APP_PASSWORD: "private" } });
  });
});
