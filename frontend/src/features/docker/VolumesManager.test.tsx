import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../api";
import { VolumesManager } from "./VolumesManager";

vi.mock("../../api", () => ({
  api: {
    dockerVolumes: vi.fn(),
    createDockerVolume: vi.fn(),
    dockerVolumeAction: vi.fn(),
  },
}));

const t = (key: string) => key;

describe("VolumesManager name validation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.dockerVolumes).mockResolvedValue({
      items: [{ Name: "existing-data", Driver: "local", Scope: "local", consumers: [] }],
      total: 1,
      page: 1,
      page_size: 50,
      pages: 1,
    });
    vi.mocked(api.createDockerVolume).mockResolvedValue({ job: { id: "volume-job" } } as never);
  });

  it("rejects a one-character volume name before enqueueing a job", async () => {
    render(<VolumesManager permissions={["docker.manage_volumes"]} t={t} toast={vi.fn()} onJob={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.createVolume" }));
    fireEvent.change(screen.getByLabelText("docker.field.name"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));

    expect(await screen.findByText("docker.volumeValidation.nameInvalid")).toBeInTheDocument();
    expect(api.createDockerVolume).not.toHaveBeenCalled();
  });

  it("trims and submits a valid Docker volume name", async () => {
    const onJob = vi.fn();
    render(<VolumesManager permissions={["docker.manage_volumes"]} t={t} toast={vi.fn()} onJob={onJob} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.createVolume" }));
    fireEvent.change(screen.getByLabelText("docker.field.name"), { target: { value: " data-01 " } });
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));

    await waitFor(() => expect(api.createDockerVolume).toHaveBeenCalledWith({ name: "data-01", labels: {} }));
    expect(onJob).toHaveBeenCalledWith(expect.objectContaining({ id: "volume-job" }));
  });
});
