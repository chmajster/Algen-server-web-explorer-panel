import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type DockerRegistryCatalogResult } from "../../api";
import { RegistryCatalog } from "./RegistryCatalog";
import { RegistryManager } from "./RegistryManager";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return {
    ...actual,
    api: {
      ...actual.api,
      dockerRegistrySources: vi.fn(),
      dockerRegistryCatalog: vi.fn(),
      dockerRegistryTags: vi.fn(),
      dockerImageAction: vi.fn(),
      dockerRegistries: vi.fn(),
    },
  };
});

const t = (key: string) => key;
const sources = [
  { id: "docker-hub-public", name: "Docker Hub", provider: "docker_hub" as const, server: "docker.io", built_in: true, public_access: true },
  { id: "a".repeat(24), name: "Private", provider: "custom" as const, server: "registry.example.test", built_in: false, public_access: false },
];
const catalog: DockerRegistryCatalogResult = {
  items: [{
    registry_id: "docker-hub-public",
    registry: "Docker Hub",
    provider: "docker_hub",
    repository: "library/nginx",
    pull_reference: "library/nginx",
    description: "Official web server",
    stars: 100,
    official: true,
    automated: false,
  }],
  pagination: { page: 1, page_size: 25, total: 1, pages: 1, has_next: false, truncated: false },
  source: sources[0],
};

describe("RegistryManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.dockerRegistrySources).mockResolvedValue(sources);
    vi.mocked(api.dockerRegistryCatalog).mockResolvedValue(catalog);
    vi.mocked(api.dockerRegistryTags).mockResolvedValue({
      repository: "library/nginx",
      pull_reference: "library/nginx",
      tags: ["stable", "latest"],
      pagination: { page: 1, page_size: 100, total: 2, pages: 1, has_next: false, truncated: false },
      source: sources[0],
    });
    vi.mocked(api.dockerImageAction).mockResolvedValue({ job: { id: "pull-job" } } as never);
    vi.mocked(api.dockerRegistries).mockResolvedValue({ items: [{
      id: "docker-hub-public", name: "Docker Hub", provider: "docker_hub", server: "docker.io", username: "", tls: true,
      ca_certificate_configured: false, secret_configured: false, built_in: true, public_access: true, created_at: 0, updated_at: 0,
    }] });
  });

  it("shows registry connections without the image catalog", async () => {
    render(<RegistryManager t={t} toast={vi.fn()} onJob={vi.fn()} />);
    expect(await screen.findByText("docker.publicAnonymous")).toBeInTheDocument();
    expect(api.dockerRegistries).toHaveBeenCalledOnce();
    expect(screen.queryByRole("combobox", { name: "docker.registry.chooseRegistry" })).not.toBeInTheDocument();
  });

  it("searches with Enter and the search button using selected filters", async () => {
    render(<RegistryCatalog permissions={["docker.view_images"]} t={t} toast={vi.fn()} onJob={vi.fn()} />);
    await waitFor(() => expect(api.dockerRegistryCatalog).toHaveBeenCalledWith(expect.objectContaining({
      registry_id: "docker-hub-public",
      query: "server",
      page_size: 10,
    })));
    const search = await screen.findByRole("textbox", { name: "docker.registry.searchImages" });
    fireEvent.change(search, { target: { value: "nginx" } });
    fireEvent.keyDown(search, { key: "Enter" });

    await waitFor(() => expect(api.dockerRegistryCatalog).toHaveBeenCalledWith(expect.objectContaining({ registry_id: "docker-hub-public", query: "nginx" })));
    expect(await screen.findByText("library/nginx")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "docker.registry.chooseRegistry" }), { target: { value: "a".repeat(24) } });
    await waitFor(() => expect(api.dockerRegistryCatalog).toHaveBeenLastCalledWith(expect.objectContaining({
      registry_id: "a".repeat(24),
      query: "nginx",
    })));
    await waitFor(() => expect(screen.getByRole("button", { name: "action.search" })).not.toBeDisabled());
    fireEvent.change(screen.getByRole("combobox", { name: "docker.registry.imageFilter" }), { target: { value: "official" } });
    fireEvent.change(screen.getByRole("combobox", { name: "docker.registry.sort" }), { target: { value: "name" } });
    fireEvent.change(screen.getByRole("combobox", { name: "docker.registry.pageSize" }), { target: { value: "50" } });
    fireEvent.click(screen.getByRole("button", { name: "action.search" }));

    await waitFor(() => expect(api.dockerRegistryCatalog).toHaveBeenLastCalledWith({
      registry_id: "a".repeat(24),
      query: "nginx",
      page: 1,
      page_size: 50,
      official: "official",
      sort: "name",
      direction: "asc",
    }));
  });

  it("opens image details, selects a tag and platform, and starts the existing pull job", async () => {
    const onJob = vi.fn();
    render(<RegistryCatalog permissions={["docker.view_images", "docker.pull_image"]} t={t} toast={vi.fn()} onJob={onJob} />);
    const search = await screen.findByRole("textbox", { name: "docker.registry.searchImages" });
    fireEvent.change(search, { target: { value: "nginx" } });
    fireEvent.click(screen.getByRole("button", { name: "action.search" }));
    fireEvent.click(await screen.findByTitle("docker.registry.imageDetails"));

    const dialog = await screen.findByRole("dialog", { name: "docker.registry.imageDetails" });
    const tags = await within(dialog).findByRole("combobox", { name: "docker.registry.availableTags" });
    expect(tags).toHaveValue("latest");
    fireEvent.change(tags, { target: { value: "stable" } });
    fireEvent.change(within(dialog).getByRole("combobox", { name: "docker.field.platform" }), { target: { value: "linux/arm64" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "docker.pullImage" }));

    await waitFor(() => expect(api.dockerImageAction).toHaveBeenCalledWith({ action: "pull", image: "library/nginx:stable", platform: "linux/arm64" }));
    expect(onJob).toHaveBeenCalledWith({ id: "pull-job" });
  });

  it("does not expose pulling without docker.pull_image", async () => {
    render(<RegistryCatalog permissions={["docker.view_images"]} t={t} toast={vi.fn()} onJob={vi.fn()} />);
    const search = await screen.findByRole("textbox", { name: "docker.registry.searchImages" });
    fireEvent.change(search, { target: { value: "nginx" } });
    fireEvent.click(screen.getByRole("button", { name: "action.search" }));
    fireEvent.click(await screen.findByTitle("docker.registry.imageDetails"));

    const dialog = await screen.findByRole("dialog", { name: "docker.registry.imageDetails" });
    expect(within(dialog).getByText("docker.registry.noPullPermission")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "docker.pullImage" })).not.toBeInTheDocument();
  });

  it("shows short-query, empty, and unsupported-catalog states", async () => {
    render(<RegistryCatalog permissions={["docker.view_images"]} t={t} toast={vi.fn()} onJob={vi.fn()} />);
    const search = await screen.findByRole("textbox", { name: "docker.registry.searchImages" });
    await waitFor(() => expect(api.dockerRegistryCatalog).toHaveBeenCalled());
    vi.mocked(api.dockerRegistryCatalog).mockClear();
    fireEvent.change(search, { target: { value: "n" } });
    fireEvent.click(screen.getByRole("button", { name: "action.search" }));
    expect(screen.getByRole("alert")).toHaveTextContent("docker.registrySearchTooShort");
    expect(api.dockerRegistryCatalog).not.toHaveBeenCalled();

    vi.mocked(api.dockerRegistryCatalog).mockResolvedValueOnce({ ...catalog, items: [], pagination: { ...catalog.pagination, total: 0, pages: 0 } });
    fireEvent.change(search, { target: { value: "missing" } });
    fireEvent.click(screen.getByRole("button", { name: "action.search" }));
    expect(await screen.findByText("docker.registry.catalogEmpty")).toBeInTheDocument();

    vi.mocked(api.dockerRegistryCatalog).mockRejectedValueOnce(new ApiError("raw", 409, "REGISTRY_CATALOG_UNSUPPORTED"));
    fireEvent.change(search, { target: { value: "private/repository" } });
    fireEvent.click(screen.getByRole("button", { name: "action.search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("docker.registry.catalogUnsupported");
  });
});
