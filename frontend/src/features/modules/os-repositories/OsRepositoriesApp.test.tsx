import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../../api";
import { OsRepositoriesApp } from "./OsRepositoriesApp";

vi.mock("../../../api", async () => {
  const actual = await vi.importActual<typeof import("../../../api")>("../../../api");
  return { ...actual, api: { ...actual.api, module: vi.fn(), osRepositoriesDashboard: vi.fn(), osRepositories: vi.fn(), osRepository: vi.fn(), osRepositoryPackages: vi.fn(), osRepositorySnapshots: vi.fn(), osRepositoryChannels: vi.fn(), osRepositoryJobs: vi.fn(), osRepositoryKeys: vi.fn(), osRepositoryAssignments: vi.fn(), osRepositoryHistory: vi.fn(), osRepositorySettings: vi.fn(), planOsRepository: vi.fn(), saveOsRepository: vi.fn(), previewOsRepositoryFilter: vi.fn(), saveOsRepositoryFilter: vi.fn() } };
});

const t = (key: string) => key;
const permissions = ["os-repositories.view", "os-repositories.manage", "os-repositories.sync", "os-repositories.packages.upload", "os-repositories.snapshots.manage", "os-repositories.configure"];

describe("OsRepositoriesApp", () => {
  beforeEach(() => {
    vi.mocked(api.module).mockResolvedValue({ module_status: { installed: true, package_version: "1.0.0", update_available: false, service_state: "active", service_enabled: true, services: {}, health: "healthy", health_message: "", last_action: "", last_action_status: "", last_error: "", metrics: {} } } as never);
    vi.mocked(api.osRepositoriesDashboard).mockResolvedValue({ repositories: 1, packages: 2, snapshots: 1, published_channels: 1, hosts: 0, pending_packages: 0, running_jobs: 0, errors: 0, size_bytes: 1024, recent_jobs: [], expiring_keys: [] });
    vi.mocked(api.osRepositories).mockResolvedValue({ items: [{ id: "a".repeat(32), name: "Ubuntu", description: "Production packages", kind: "local", format: "apt", distribution: "ubuntu", distribution_version: "24.04", architectures: ["amd64"], source_url: "", active: true, schedule: "", retention_count: 10, allow_private_network: false, allow_private_http: false, auth_type: "none", auth_username: "", auth_secret_configured: false, last_sync_status: "completed", package_count: 2, size_bytes: 1024 }], page: 1, page_size: 50, total: 1 });
    vi.mocked(api.osRepository).mockResolvedValue({ id: "a".repeat(32), name: "Ubuntu", description: "Production packages", kind: "local", format: "apt", distribution: "ubuntu", distribution_version: "24.04", architectures: ["amd64"], source_url: "", active: true, schedule: "", retention_count: 10, allow_private_network: false, allow_private_http: false, auth_type: "none", auth_username: "", auth_secret_configured: false, last_sync_status: "completed", package_count: 2, size_bytes: 1024, filters: [] });
    vi.mocked(api.osRepositoryPackages).mockResolvedValue({ items: [], page: 1, page_size: 50, total: 0 });
    vi.mocked(api.osRepositorySnapshots).mockResolvedValue({ items: [], page: 1, page_size: 50, total: 0 });
    vi.mocked(api.osRepositoryChannels).mockResolvedValue([]);
    vi.mocked(api.osRepositoryJobs).mockResolvedValue({ items: [], page: 1, page_size: 50, total: 0 });
    vi.mocked(api.osRepositoryKeys).mockResolvedValue([]);
    vi.mocked(api.osRepositoryAssignments).mockResolvedValue([]);
    vi.mocked(api.osRepositoryHistory).mockResolvedValue([]);
    vi.mocked(api.osRepositorySettings).mockResolvedValue({ listen_address: "0.0.0.0", port: 8088, public_base_url: "", upload_limit_mb: 2048, max_parallel_syncs: 1 });
    vi.mocked(api.planOsRepository).mockResolvedValue({ action: "create", requires_confirmation: true });
    vi.mocked(api.saveOsRepository).mockResolvedValue({} as never);
    vi.mocked(api.previewOsRepositoryFilter).mockResolvedValue({ included: 2, rejected: 0, estimated_size: 1024 });
    vi.mocked(api.saveOsRepositoryFilter).mockResolvedValue({ version: 1 });
  });

  it("renders dashboard and the dedicated repository navigation", async () => {
    render(<OsRepositoriesApp permissions={permissions} t={t} toast={vi.fn()} />);
    expect(await screen.findByText("osRepositories.dashboard.repositories")).toBeInTheDocument();
    expect(screen.getAllByText("1").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /module.section.packages/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /module.section.channels/ })).toBeInTheDocument();
  });

  it("opens the repository creator and saves a typed local repository", async () => {
    render(<OsRepositoriesApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("osRepositories.dashboard.repositories");
    fireEvent.click(screen.getByRole("button", { name: /module.section.repositories/ }));
    fireEvent.click(screen.getByRole("button", { name: "osRepositories.addRepository" }));
    fireEvent.change(screen.getByLabelText("common.name"), { target: { value: "Rocky" } });
    fireEvent.change(screen.getByLabelText("osRepositories.distribution"), { target: { value: "rocky" } });
    fireEvent.change(screen.getByLabelText("osRepositories.distributionVersion"), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "osRepositories.showPlan" }));
    await screen.findByText(/requires_confirmation/);
    fireEvent.click(screen.getByRole("button", { name: "action.confirm" }));
    await waitFor(() => expect(api.saveOsRepository).toHaveBeenCalledWith(expect.objectContaining({ name: "Rocky", kind: "local", architectures: ["amd64"] }), undefined));
  });

  it("configures a bearer-authenticated mirror without putting the token in its URL", async () => {
    render(<OsRepositoriesApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("osRepositories.dashboard.repositories");
    fireEvent.click(screen.getByRole("button", { name: /module.section.repositories/ }));
    fireEvent.click(screen.getByRole("button", { name: "osRepositories.addRepository" }));
    fireEvent.change(screen.getByLabelText("common.name"), { target: { value: "Private mirror" } });
    fireEvent.change(screen.getByLabelText("osRepositories.kind"), { target: { value: "mirror" } });
    fireEvent.change(screen.getByLabelText("osRepositories.sourceUrl"), { target: { value: "https://packages.example/repo" } });
    fireEvent.change(screen.getByLabelText("osRepositories.authType"), { target: { value: "bearer" } });
    fireEvent.change(screen.getByLabelText("osRepositories.authSecret"), { target: { value: "private-token" } });
    fireEvent.click(screen.getByRole("button", { name: "osRepositories.showPlan" }));
    await screen.findByText(/requires_confirmation/);
    fireEvent.click(screen.getByRole("button", { name: "action.confirm" }));
    await waitFor(() => expect(api.saveOsRepository).toHaveBeenCalledWith(expect.objectContaining({ auth_type: "bearer", auth_secret: "private-token", source_url: "https://packages.example/repo" }), undefined));
  });

  it("previews and activates package filters for a repository", async () => {
    render(<OsRepositoriesApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("osRepositories.dashboard.repositories");
    fireEvent.click(screen.getByRole("button", { name: /module.section.repositories/ }));
    fireEvent.click(screen.getByRole("button", { name: "osRepositories.filters" }));
    await screen.findByText("osRepositories.filterSnapshotHint");
    fireEvent.change(screen.getByLabelText("osRepositories.includeGlobs"), { target: { value: "webnas-*, nginx*" } });
    fireEvent.change(screen.getByLabelText("osRepositories.latestVersions"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "osRepositories.filterPreview" }));
    await screen.findByText("osRepositories.includedPackages");
    expect(api.previewOsRepositoryFilter).toHaveBeenCalledWith("a".repeat(32), expect.objectContaining({ include_globs: ["webnas-*", "nginx*"], latest_versions: 2 }));
    fireEvent.click(screen.getByRole("button", { name: "osRepositories.saveFilter" }));
    await waitFor(() => expect(api.saveOsRepositoryFilter).toHaveBeenCalledWith("a".repeat(32), expect.objectContaining({ include_globs: ["webnas-*", "nginx*"], latest_versions: 2 })));
  });
});
