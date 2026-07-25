import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { ImagesManager } from "./ImagesManager";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, api: { ...actual.api, dockerImages: vi.fn(), dockerImageAction: vi.fn(), importDockerImage: vi.fn() } };
});

describe("ImagesManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.dockerImages).mockResolvedValue({
      items: [{ ID: "sha256:one", Repository: "nginx", Tag: "stable", Digest: "sha256:digest", Size: "50MB" }],
      total: 1,
      page: 1,
      page_size: 200,
      pages: 1,
    });
  });

  it("shows only local images while preserving manual pull and local actions", async () => {
    render(<ImagesManager permissions={["docker.pull_image", "docker.export_backup", "docker.remove_image"]} t={(key) => key} toast={vi.fn()} onJob={vi.fn()} />);

    expect(await screen.findByText("nginx")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "docker.pullImage" })).toBeInTheDocument();
    expect(screen.getByTitle("docker.saveImage")).toBeInTheDocument();
    expect(screen.getByTitle("action.delete")).toBeInTheDocument();
    expect(screen.queryByText("docker.searchRegistry")).not.toBeInTheDocument();
  });
});
