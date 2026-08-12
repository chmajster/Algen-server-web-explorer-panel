import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type DockerDashboard } from "../../api";
import { DockerManagerApp } from "./DockerManagerApp";

vi.mock("../../api", () => ({
  api: {
    dockerDashboard: vi.fn(), dockerEvents: vi.fn(), dockerContainers: vi.fn(), dockerContainer: vi.fn(), dockerContainerStats: vi.fn(),
    dockerContainerLogs: vi.fn(), dockerContainerProcesses: vi.fn(), dockerContainerSettings: vi.fn(), updateDockerContainerSettings: vi.fn(), dockerContainerDefaultsPolicy: vi.fn(), saveDockerContainerDefaultsPolicy: vi.fn(), createDockerContainer: vi.fn(), dockerContainerAction: vi.fn(), dockerContainerCompose: vi.fn(),
    dockerContainerBackup: vi.fn(), dockerImages: vi.fn(), dockerImageAction: vi.fn(), importDockerImage: vi.fn(), dockerApps: vi.fn(),
    dockerComposeProjects: vi.fn(), validateDockerCompose: vi.fn(), saveDockerComposeProject: vi.fn(), dockerComposeAction: vi.fn(),
    dockerVolumes: vi.fn(), dockerNetworks: vi.fn(), dockerNetworkContainers: vi.fn(), dockerDefaultBridge: vi.fn(), saveDockerDefaultBridge: vi.fn(), createDockerNetwork: vi.fn(), dockerNetworkAction: vi.fn(), dockerPrunePlan: vi.fn(), dockerRegistries: vi.fn(), dockerRegistrySources: vi.fn(), dockerRegistryCatalog: vi.fn(), dockerRegistryTags: vi.fn(), dockerBackups: vi.fn(),
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
    vi.mocked(api.dockerContainerCompose).mockResolvedValue({ content: "services:\n  web:\n    image: nginx:stable\n", secrets_omitted: false, environment_keys: [] });
    vi.mocked(api.dockerContainerSettings).mockResolvedValue({ name: "web", resource_limits_enabled: false, cpu_priority: "medium", memory_mb: null, auto_restart: false, restart_policy: "no", portal_enabled: false, portal_port: null, portal_published_port: null, portal_protocol: "http", compose_managed: false, available_ports: [{ target: 8096, published: 8096, protocol: "tcp" }] });
    vi.mocked(api.updateDockerContainerSettings).mockResolvedValue({ job: { id: "settings-job" } } as never);
    vi.mocked(api.dockerContainerDefaultsPolicy).mockResolvedValue({ resource_limits_enabled: true, memory_mb: 512, memory_swap_mb: 1024, cpus: 1, pids: 128 });
    vi.mocked(api.dockerImages).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50, pages: 1 });
    vi.mocked(api.dockerNetworks).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50, pages: 1 });
    vi.mocked(api.dockerRegistries).mockResolvedValue({ items: [{ id: "docker-hub-public", name: "Docker Hub", provider: "docker_hub", server: "docker.io", username: "", tls: true, ca_certificate_configured: false, secret_configured: false, built_in: true, public_access: true, created_at: 0, updated_at: 0 }] });
    vi.mocked(api.dockerRegistrySources).mockResolvedValue([{ id: "docker-hub-public", name: "Docker Hub", provider: "docker_hub", server: "docker.io", built_in: true, public_access: true }]);
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

  it("renders the container list with metrics and expandable quick details", async () => {
    vi.mocked(api.dockerContainers).mockResolvedValue({ items: [{
      ID: "abc", Names: "web", Image: "nginx:stable", Digest: "sha256:full-digest",
      State: "running", Status: "Up 2 hours", Health: "healthy", Ports: "80/tcp, 443/tcp, 8080/tcp", Networks: "bridge", CpuPercent: 1.234, MemoryBytes: 88_080_384,
    }], total: 1, page: 1, page_size: 50, pages: 1 });
    render(<DockerManagerApp permissions={[
      "docker.view", "docker.view_containers", "docker.inspect_container", "docker.start_container",
      "docker.stop_container", "docker.restart_container", "docker.export_backup", "docker.remove_container",
    ]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));

    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
      "docker.container", "docker.field.status", "docker.cpu", "docker.memory", "docker.field.ports", "docker.field.actions",
    ]);
    expect(within(table).getByText("web")).toBeInTheDocument();
    expect(within(table).getByText("nginx:stable")).toBeInTheDocument();
    expect(within(table).getByText(/1[,.]23%/)).toBeInTheDocument();
    expect(within(table).getByText("84 MiB")).toBeInTheDocument();
    expect(within(table).getByText("+1")).toBeInTheDocument();
    expect(within(table).queryByText("sha256:full-digest")).not.toBeInTheDocument();

    const more = within(table).getByRole("button", { name: "docker.showTechnicalDetails" });
    expect(more).toHaveAttribute("type", "button");
    expect(more).toHaveAttribute("aria-expanded", "false");
    const detailsId = more.getAttribute("aria-controls")!;
    fireEvent.click(more);

    expect(within(table).getByRole("button", { name: "docker.hideTechnicalDetails" })).toHaveAttribute("aria-expanded", "true");
    const details = document.getElementById(detailsId)!;
    expect(details).toBeInTheDocument();
    expect(within(details).getByText("sha256:full-digest")).toBeInTheDocument();
    expect(details.querySelector("td")).toHaveAttribute("colspan", "6");
    expect(within(details).getByText("docker.field.image")).toBeInTheDocument();
    expect(within(details).getByText("nginx:stable")).toBeInTheDocument();
    expect(details.querySelector(".docker-container-detail-grid")).toBeInTheDocument();

    fireEvent.click(within(table).getByRole("button", { name: "docker.hideTechnicalDetails" }));
    expect(document.getElementById(detailsId)).not.toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "docker.showTechnicalDetails" })).toHaveAttribute("aria-expanded", "false");
  });

  it("shows page-scoped summaries and a permission-aware context menu", async () => {
    vi.mocked(api.dockerContainers).mockResolvedValue({ items: [
      { ID: "run", Names: "web", Image: "nginx", State: "running", Health: "healthy" },
      { ID: "bad", Names: "db", Image: "postgres", State: "running", Health: "unhealthy" },
      { ID: "off", Names: "worker", Image: "app", State: "exited" },
    ], total: 8, page: 1, page_size: 3, pages: 3 });
    render(<DockerManagerApp permissions={[
      "docker.view", "docker.view_containers", "docker.inspect_container", "docker.start_container", "docker.stop_container",
      "docker.restart_container", "docker.create_container", "docker.pull_image", "docker.export_backup", "docker.remove_container",
    ]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));

    expect(await screen.findByText("docker.currentResults")).toBeInTheDocument();
    const problems = screen.getByRole("button", { name: /docker.summary.problems/ });
    await waitFor(() => expect(problems).toHaveTextContent("1"));
    fireEvent.click(screen.getAllByRole("button", { name: "docker.moreActions" })[0]);
    expect(screen.queryByRole("combobox", { name: "docker.moreActions" })).not.toBeInTheDocument();
    expect(await screen.findByRole("menuitem", { name: "docker.details" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "docker.detail.logs" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "docker.console" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "docker.kill" })).toHaveClass("danger");
    expect(screen.getByRole("menuitem", { name: "action.delete" })).toHaveClass("danger");
  });

  it("expands several containers independently and renders missing detail values as None", async () => {
    vi.mocked(api.dockerContainers).mockResolvedValue({ items: [
      { ID: "abc", Names: "web", Image: "nginx:stable", State: "running", Status: "Up" },
      { ID: "def", Names: "worker", Image: "", State: "exited", Status: "Exited" },
    ], total: 2, page: 1, page_size: 50, pages: 1 });
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.inspect_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));

    const toggles = await screen.findAllByRole("button", { name: "docker.showTechnicalDetails" });
    const detailIds = toggles.map((button) => button.getAttribute("aria-controls")!);
    fireEvent.click(toggles[0]);
    fireEvent.click(toggles[1]);

    expect(screen.getAllByRole("button", { name: "docker.hideTechnicalDetails" })).toHaveLength(2);
    expect(document.getElementById(detailIds[0])).toBeInTheDocument();
    const secondDetails = document.getElementById(detailIds[1])!;
    expect(secondDetails).toBeInTheDocument();
    expect(within(secondDetails).getAllByText("common.none").length).toBeGreaterThan(0);
    expect(secondDetails.querySelector(".docker-container-detail-grid")).toBeInTheDocument();
  });

  it("keeps dashboard elements visible while data refreshes in the background", async () => {
    let finishRefresh: ((value: DockerDashboard) => void) | undefined;
    vi.mocked(api.dockerDashboard)
      .mockResolvedValueOnce(dashboard as never)
      .mockImplementationOnce(() => new Promise<DockerDashboard>((resolve) => { finishRefresh = resolve; }));
    const { container } = render(<DockerManagerApp permissions={["docker.view"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);

    expect(await screen.findByRole("button", { name: "docker.section.dashboard" })).toBeInTheDocument();
    expect(container.querySelector(".docker-dashboard")).toBeInTheDocument();
    const refresh = container.querySelector<HTMLButtonElement>(".docker-manager-header button")!;
    fireEvent.click(refresh);

    expect(container.querySelector(".docker-dashboard")).toBeInTheDocument();
    expect(refresh).toHaveAttribute("aria-busy", "true");
    await act(async () => { finishRefresh?.(dashboard as unknown as DockerDashboard); });
    expect(refresh).toHaveAttribute("aria-busy", "false");
  });

  it("shows public Docker Hub as the built-in default registry", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.view_images", "docker.manage_registries"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.registries" }));
    expect(await screen.findByText("Docker Hub")).toBeInTheDocument();
    expect(screen.getByText("docker.publicAnonymous")).toBeInTheDocument();
    expect(screen.getByText("docker.defaultRegistry")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "docker.registry.chooseRegistry" })).not.toBeInTheDocument();
  });

  it("opens the registry image search in Applications without preset cards", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.view_images"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.apps" }));

    expect(await screen.findByRole("textbox", { name: "docker.registry.searchImages" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "docker.registry.chooseRegistry" })).toBeInTheDocument();
    expect(api.dockerApps).not.toHaveBeenCalled();
  });

  it("opens the typed create wizard and submits secrets only in the request body", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.create_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByRole("button", { name: "docker.createContainer" }));
    fireEvent.change(screen.getByLabelText("docker.field.name"), { target: { value: "safe-web" } });
    fireEvent.change(screen.getByLabelText("docker.field.image"), { target: { value: "nginx:stable" } });
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.section.process" }));
    fireEvent.change(screen.getByLabelText("docker.field.entrypoint"), { target: { value: "/usr/local/bin/start" } });
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.section.secrets" }));
    fireEvent.change(screen.getByLabelText("docker.secretName"), { target: { value: "APP_PASSWORD" } });
    const secretValue = screen.getByLabelText("docker.secretValue");
    expect(secretValue).toHaveAttribute("type", "password");
    fireEvent.change(secretValue, { target: { value: "private" } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "docker.createContainer" }));
    await waitFor(() => expect(api.createDockerContainer).toHaveBeenCalled());
    expect(vi.mocked(api.createDockerContainer).mock.calls[0][0]).toMatchObject({ name: "safe-web", image: "nginx:stable", entrypoint: "/usr/local/bin/start", secret_environment: { APP_PASSWORD: "private" } });
  });

  it("preserves a custom Entrypoint when duplicating a container", async () => {
    sessionStorage.removeItem("docker:create-container");
    vi.mocked(api.dockerContainer).mockResolvedValue({
      id: "abc", name: "web", image: "nginx:stable", entrypoint: "/docker-entrypoint.sh",
      state: { Running: true }, networks: { bridge: {} }, ports: {}, mounts: [], labels: {}, limits: {}, read_only: false,
    });
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.inspect_container", "docker.create_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click((await screen.findAllByRole("button", { name: "docker.moreActions" }))[0]);
    fireEvent.click(await screen.findByRole("menuitem", { name: "docker.duplicate" }));

    expect(await screen.findByLabelText("docker.field.name")).toHaveValue("web-copy");
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.section.process" }));
    expect(screen.getByLabelText("docker.field.entrypoint")).toHaveValue("/docker-entrypoint.sh");
  });

  it("opens and closes compact configuration sections with aria-expanded", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.create_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByRole("button", { name: "docker.createContainer" }));

    const dialog = screen.getByRole("dialog", { name: "docker.createContainer" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog.querySelector(".docker-compact-form")).toBeInTheDocument();
    expect(dialog.querySelector(".docker-compact-footer")).toBeInTheDocument();
    const general = within(dialog).getByRole("button", { name: "docker.wizard.section.general" });
    const secrets = within(dialog).getByRole("button", { name: "docker.wizard.section.secrets" });
    expect(general).toHaveAttribute("aria-expanded", "true");
    expect(secrets).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByLabelText("docker.field.name")).toHaveAttribute("aria-invalid", "true");
    fireEvent.click(general);
    expect(general).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("docker.field.name")).not.toBeInTheDocument();
    fireEvent.click(secrets);
    expect(secrets).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("docker.secretValue")).toHaveAttribute("type", "password");
  });

  it("adds, validates, and removes editable port rows", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.create_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByRole("button", { name: "docker.createContainer" }));
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.addPort" }));
    fireEvent.change(screen.getByLabelText("docker.wizard.hostPort"), { target: { value: "70000" } });
    fireEvent.change(screen.getByLabelText("docker.wizard.containerPort"), { target: { value: "80" } });
    expect(screen.getByRole("alert")).toHaveTextContent("docker.wizard.validation.portRange");
    fireEvent.change(screen.getByLabelText("docker.wizard.hostPort"), { target: { value: "8080" } });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.removePort" }));
    expect(screen.queryByLabelText("docker.wizard.hostPort")).not.toBeInTheDocument();
  });

  it("edits environment variables as rows and text without losing data", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.create_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByRole("button", { name: "docker.createContainer" }));
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.addVariable" }));
    fireEvent.change(screen.getByLabelText("docker.wizard.variableName"), { target: { value: "TZ" } });
    fireEvent.change(screen.getByLabelText("docker.wizard.variableValue"), { target: { value: "Europe/Warsaw" } });
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.editAsText" }));
    expect(screen.getByLabelText("docker.field.environment")).toHaveValue("TZ=Europe/Warsaw");
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.editAsRows" }));
    expect(screen.getByLabelText("docker.wizard.variableName")).toHaveValue("TZ");
    expect(screen.getByLabelText("docker.wizard.variableValue")).toHaveValue("Europe/Warsaw");
  });

  it("loads resource defaults from policy and reveals conditional healthcheck fields", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.create_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByRole("button", { name: "docker.createContainer" }));
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.section.resources" }));
    await waitFor(() => expect(screen.getByLabelText("docker.field.memoryMb")).toHaveValue(512));
    expect(screen.getByLabelText("docker.field.memorySwapMb")).toHaveValue(1024);
    expect(screen.getByLabelText("docker.field.cpus")).toHaveValue(1);
    expect(screen.getByLabelText("docker.field.pids")).toHaveValue(128);
    expect(screen.getByLabelText("docker.wizard.enableLimits")).toBeChecked();

    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.section.health" }));
    fireEvent.change(screen.getByLabelText("docker.field.healthcheck"), { target: { value: "http" } });
    expect(screen.getByLabelText("docker.field.healthPort")).toBeInTheDocument();
    expect(screen.getByLabelText("docker.field.healthPath")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("docker.field.healthcheck"), { target: { value: "tcp" } });
    expect(screen.queryByLabelText("docker.field.healthPath")).not.toBeInTheDocument();
  });

  it("restores a create-container draft after reload without persisting secret fields", async () => {
    const draftKey = "test-window:create-container";
    sessionStorage.removeItem(draftKey);
    sessionStorage.removeItem("test-window:section");
    const permissions = ["docker.view", "docker.view_containers", "docker.create_container"];
    const first = render(<DockerManagerApp draftKey="test-window" permissions={permissions} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByRole("button", { name: "docker.createContainer" }));
    fireEvent.change(screen.getByLabelText("docker.field.name"), { target: { value: "restored-media" } });
    fireEvent.change(screen.getByLabelText("docker.field.image"), { target: { value: "jellyfin:latest" } });
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.section.process" }));
    fireEvent.change(screen.getByLabelText("docker.field.entrypoint"), { target: { value: "/init" } });
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.addPort" }));
    fireEvent.change(screen.getByLabelText("docker.wizard.hostPort"), { target: { value: "8096" } });
    fireEvent.change(screen.getByLabelText("docker.wizard.containerPort"), { target: { value: "8096" } });
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.section.secrets" }));
    fireEvent.change(screen.getByLabelText("docker.secretName"), { target: { value: "API_TOKEN" } });
    fireEvent.change(screen.getByLabelText("docker.secretValue"), { target: { value: "do-not-store" } });
    expect(sessionStorage.getItem(draftKey)).not.toContain("do-not-store");

    first.unmount();
    render(<DockerManagerApp draftKey="test-window" permissions={permissions} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "docker.createContainer" })).toBeInTheDocument();
    expect(screen.getByLabelText("docker.wizard.hostPort")).toHaveValue("8096");
    expect(screen.getByLabelText("docker.wizard.containerPort")).toHaveValue("8096");
    expect(screen.getByLabelText("docker.field.name")).toHaveValue("restored-media");
    expect(screen.getByLabelText("docker.field.image")).toHaveValue("jellyfin:latest");
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.section.process" }));
    expect(screen.getByLabelText("docker.field.entrypoint")).toHaveValue("/init");
    sessionStorage.removeItem(draftKey);
    sessionStorage.removeItem("test-window:section");
  });

  it("imports a JSON container definition into the editable create wizard", async () => {
    render(<DockerManagerApp permissions={["docker.view", "docker.view_containers", "docker.create_container"]} t={t} toast={vi.fn()} onDirtyChange={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.section.containers" }));
    fireEvent.click(await screen.findByRole("button", { name: "docker.createContainer" }));
    expect(screen.getByRole("dialog").parentElement).toHaveClass("modal-backdrop", "docker-wizard-backdrop");
    const file = new File([JSON.stringify({ name: "imported-web", image: "nginx:stable", entrypoint: "/docker-entrypoint.sh", environment: { TZ: "Europe/Warsaw" }, ports: [{ published: 8080, target: 80, protocol: "tcp" }] })], "container.json", { type: "application/json" });
    const input = document.querySelector('input[accept=".json,application/json"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(screen.getByLabelText("docker.field.name")).toHaveValue("imported-web"));
    expect(screen.getByLabelText("docker.field.image")).toHaveValue("nginx:stable");
    expect(screen.getByLabelText("docker.wizard.variableName")).toHaveValue("TZ");
    expect(screen.getByLabelText("docker.wizard.variableValue")).toHaveValue("Europe/Warsaw");
    expect(screen.getByLabelText("docker.wizard.hostPort")).toHaveValue("8080");
    expect(screen.getByLabelText("docker.wizard.containerPort")).toHaveValue("80");
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.section.process" }));
    expect(screen.getByLabelText("docker.field.entrypoint")).toHaveValue("/docker-entrypoint.sh");
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
    expect(screen.queryByRole("textbox", { name: "docker.field.mounts" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "docker.wizard.addVolume" }));
    fireEvent.click(screen.getByRole("button", { name: "docker.chooseHostPath" }));
    expect(await screen.findByRole("heading", { name: "docker.chooseHostPath" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "docker.chooseCurrentFolder" }));
    expect(screen.getByLabelText("docker.mountSource")).toHaveValue("/srv/media");
    fireEvent.change(screen.getByLabelText("docker.mountTarget"), { target: { value: "/media" } });
    fireEvent.change(screen.getByLabelText("docker.wizard.accessMode"), { target: { value: "ro" } });
    expect(screen.getByLabelText("docker.wizard.accessMode")).toHaveValue("ro");
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
    fireEvent.click(await screen.findByRole("button", { name: "web" }));
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
