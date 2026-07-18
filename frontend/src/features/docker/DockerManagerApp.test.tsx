import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { DockerManagerApp } from "./DockerManagerApp";

vi.mock("../../api", () => ({
  api: {
    dockerDashboard: vi.fn(), dockerEvents: vi.fn(), dockerContainers: vi.fn(), dockerContainer: vi.fn(), dockerContainerStats: vi.fn(),
    dockerContainerLogs: vi.fn(), dockerContainerProcesses: vi.fn(), dockerContainerSettings: vi.fn(), updateDockerContainerSettings: vi.fn(), createDockerContainer: vi.fn(), dockerContainerAction: vi.fn(),
    dockerContainerBackup: vi.fn(), dockerImages: vi.fn(), dockerImageAction: vi.fn(), importDockerImage: vi.fn(), dockerApps: vi.fn(),
    dockerComposeProjects: vi.fn(), validateDockerCompose: vi.fn(), saveDockerComposeProject: vi.fn(), dockerComposeAction: vi.fn(),
    dockerVolumes: vi.fn(), dockerNetworks: vi.fn(), dockerRegistries: vi.fn(), dockerBackups: vi.fn(),
    list: vi.fn(), localDisks: vi.fn(), mountRoots: vi.fn(),
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
    vi.mocked(api.dockerContainer).mockResolvedValue({ name: "web", state: { Status: "running" } });
    vi.mocked(api.dockerContainerSettings).mockResolvedValue({ name: "web", resource_limits_enabled: false, cpu_priority: "medium", memory_mb: null, auto_restart: false, restart_policy: "no", portal_enabled: false, portal_port: null, portal_published_port: null, portal_protocol: "http", compose_managed: false, available_ports: [{ target: 8096, published: 8096, protocol: "tcp" }] });
    vi.mocked(api.updateDockerContainerSettings).mockResolvedValue({ job: { id: "settings-job" } } as never);
    vi.mocked(api.dockerImages).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50, pages: 1 });
    vi.mocked(api.dockerNetworks).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50, pages: 1 });
    vi.mocked(api.dockerRegistries).mockResolvedValue({ items: [{ id: "docker-hub-public", name: "Docker Hub", provider: "docker_hub", server: "docker.io", username: "", tls: true, ca_certificate_configured: false, secret_configured: false, built_in: true, public_access: true, created_at: 0, updated_at: 0 }] });
    vi.mocked(api.localDisks).mockResolvedValue([]);
    vi.mocked(api.mountRoots).mockResolvedValue([]);
    vi.mocked(api.list).mockResolvedValue({ current_path: "/srv/media", parent_path: "/srv", items: [], page: 1, page_size: 200, total_items: 0, total_pages: 1 } as never);
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

  it("shows public Docker Hub as the built-in default registry", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.manage_registries"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.registries" }));
    expect(await screen.findByText("Docker Hub")).toBeInTheDocument();
    expect(screen.getByText("docker.publicAnonymous")).toBeInTheDocument();
    expect(screen.getByText("docker.defaultRegistry")).toBeInTheDocument();
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

  it("imports a JSON container definition into the editable create wizard", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.create_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByRole("button", { name: "docker.createContainer" }));
    expect(screen.getByRole("dialog").parentElement).toHaveClass("modal-backdrop", "docker-wizard-backdrop");
    const file = new File([JSON.stringify({ name: "imported-web", image: "nginx:stable", environment: { TZ: "Europe/Warsaw" }, ports: [{ published: 8080, target: 80, protocol: "tcp" }] })], "container.json", { type: "application/json" });
    const input = document.querySelector('input[accept=".json,application/json"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(screen.getByLabelText("docker.field.name")).toHaveValue("imported-web"));
    expect(screen.getByLabelText("docker.field.image")).toHaveValue("nginx:stable");
    fireEvent.click(screen.getByRole("button", { name: /action.next/ }));
    expect(screen.getByLabelText("docker.field.environment")).toHaveValue("TZ=Europe/Warsaw");
    expect(screen.getByLabelText("docker.field.ports")).toHaveValue("8080:80/tcp");
  });

  it("searches and selects an image already downloaded to Docker", async () => {
    vi.mocked(api.dockerImages).mockResolvedValue({ items: [
      { Repository: "nginx", Tag: "stable", ID: "sha256:one" },
      { Repository: "postgres", Tag: "17", ID: "sha256:two" },
    ], total: 2, page: 1, page_size: 50, pages: 1 });
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.view_images", "docker.create_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByRole("button", { name: "docker.createContainer" }));
    const imageInput = screen.getByRole("combobox", { name: "docker.field.image" });
    fireEvent.focus(imageInput);
    fireEvent.change(imageInput, { target: { value: "post" } });

    const option = await screen.findByRole("option", { name: "postgres:17" });
    expect(api.dockerImages).toHaveBeenLastCalledWith(expect.objectContaining({ search: "post" }));
    fireEvent.mouseDown(option);
    fireEvent.click(option);
    expect(imageInput).toHaveValue("postgres:17");
  });

  it("searches and selects an existing Docker network", async () => {
    vi.mocked(api.dockerNetworks).mockResolvedValue({ items: [
      { Name: "bridge", Driver: "bridge" },
      { Name: "app-network", Driver: "bridge" },
      { Name: "host", Driver: "host" },
      { Name: "none", Driver: "null" },
    ], total: 4, page: 1, page_size: 50, pages: 1 });
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.create_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByRole("button", { name: "docker.createContainer" }));
    const networkInput = screen.getByRole("combobox", { name: "docker.field.network" });
    fireEvent.focus(networkInput);
    expect(await screen.findByRole("option", { name: "app-network" })).toBeInTheDocument();
    fireEvent.change(networkInput, { target: { value: "app" } });

    const option = await screen.findByRole("option", { name: "app-network" });
    expect(api.dockerNetworks).toHaveBeenCalledWith("");
    expect(screen.queryByRole("option", { name: "host" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "none" })).not.toBeInTheDocument();
    fireEvent.mouseDown(option);
    fireEvent.click(option);
    expect(networkInput).toHaveValue("app-network");
  });

  it("adds structured mounts and chooses a bind path in the graphical explorer", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.create_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByRole("button", { name: "docker.createContainer" }));
    fireEvent.change(screen.getByLabelText("docker.field.name"), { target: { value: "media" } });
    fireEvent.change(screen.getByLabelText("docker.field.image"), { target: { value: "jellyfin:latest" } });
    fireEvent.click(screen.getByRole("button", { name: /action.next/ }));
    expect(screen.queryByRole("textbox", { name: "docker.field.mounts" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "docker.addMount" }));
    fireEvent.click(screen.getByRole("button", { name: "docker.chooseHostPath" }));
    expect(await screen.findByRole("heading", { name: "docker.chooseHostPath" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "docker.chooseCurrentFolder" }));
    expect(screen.getByLabelText("docker.mountSource")).toHaveValue("/srv/media");
    fireEvent.change(screen.getByLabelText("docker.mountTarget"), { target: { value: "/media" } });
    fireEvent.click(screen.getByRole("button", { name: "docker.removeMount" }));
    expect(screen.getByText("docker.noMounts")).toBeInTheDocument();
  });

  it("validates, saves, and starts an imported Compose file", async () => {
    vi.mocked(api.validateDockerCompose).mockResolvedValue({} as never);
    vi.mocked(api.saveDockerComposeProject).mockResolvedValue({} as never);
    vi.mocked(api.dockerComposeAction).mockResolvedValue({ job: { id: "compose-job" } } as never);
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.create_container", "docker.manage_compose"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByRole("button", { name: "docker.createContainer" }));
    const file = new File(["services:\n  web:\n    image: nginx:stable\n"], "my-stack.yaml", { type: "application/yaml" });
    const input = document.querySelector('input[accept^=".yaml"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByRole("heading", { name: "docker.importComposeAndRun" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "docker.importAndRun" }));
    await waitFor(() => expect(api.validateDockerCompose).toHaveBeenCalled());
    expect(api.saveDockerComposeProject).toHaveBeenCalledWith("my-stack", expect.objectContaining({ content: expect.stringContaining("nginx:stable") }));
    expect(api.dockerComposeAction).toHaveBeenCalledWith("my-stack", expect.objectContaining({ action: "up" }));
  });

  it("modifies live container resources, restart policy, name, and web portal", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.inspect_container", "docker.create_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByTitle("docker.inspect"));
    fireEvent.click(await screen.findByRole("button", { name: "docker.detail.settings" }));
    expect(await screen.findByLabelText("docker.containerName")).toHaveValue("web");
    fireEvent.change(screen.getByLabelText("docker.containerName"), { target: { value: "jellyfin" } });
    fireEvent.click(screen.getByLabelText("docker.enableResourceLimits"));
    fireEvent.change(screen.getByLabelText("docker.cpuPriority"), { target: { value: "high" } });
    fireEvent.change(screen.getByLabelText("docker.memoryLimit"), { target: { value: "4096" } });
    fireEvent.click(screen.getByLabelText("docker.enableAutoRestart"));
    fireEvent.click(screen.getByLabelText("docker.configureWebPortal"));
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));

    await waitFor(() => expect(api.updateDockerContainerSettings).toHaveBeenCalledWith("abc", expect.objectContaining({
      name: "jellyfin", resource_limits_enabled: true, cpu_priority: "high", memory_mb: 4096,
      auto_restart: true, portal_enabled: true, portal_port: 8096, portal_protocol: "http", confirmation: "abc",
    })));
  });
});
