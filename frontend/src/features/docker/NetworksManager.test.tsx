import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type DockerNetwork } from "../../api";
import { NetworksManager } from "./NetworksManager";

vi.mock("../../api", () => ({
  api: {
    dockerNetworks: vi.fn(),
    createDockerNetwork: vi.fn(),
    dockerNetworkContainers: vi.fn(),
    dockerNetworkAction: vi.fn(),
    dockerPrunePlan: vi.fn(),
    dockerDefaultBridge: vi.fn(),
    saveDockerDefaultBridge: vi.fn(),
  },
}));

const t = (key: string) => key;
const custom: DockerNetwork = {
  Name: "app-network",
  ID: "network-id",
  Driver: "bridge",
  Scope: "local",
  IPv6: true,
  subnets: ["172.20.0.0/16", "fd42:20::/64"],
  gateways: ["172.20.0.1", "fd42:20::1"],
  ip_ranges: ["172.20.10.0/24"],
  container_count: 1,
  containers: [{ id: "container-id", name: "web" }],
  internal: false,
  attachable: false,
  system: false,
  options: {},
  labels: {},
};
const system: DockerNetwork = { ...custom, Name: "bridge", ID: "bridge-id", IPv6: false, container_count: 0, containers: [], system: true };

describe("NetworksManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.dockerNetworks).mockResolvedValue({ items: [custom, system], total: 2, page: 1, page_size: 200, pages: 1 });
    vi.mocked(api.createDockerNetwork).mockResolvedValue({ job: { id: "create-job" } } as never);
    vi.mocked(api.dockerNetworkAction).mockResolvedValue({ job: { id: "action-job" } } as never);
    vi.mocked(api.dockerNetworkContainers).mockResolvedValue({
      network: custom.Name,
      total: 2,
      items: [
        { id: "one", name: "web", state: "running", connected: true },
        { id: "two", name: "worker", state: "exited", connected: false },
      ],
    });
  });

  it("renders enriched IPAM data and protects system network actions", async () => {
    render(<NetworksManager permissions={["docker.manage_networks", "docker.high_risk"]} t={t} toast={vi.fn()} onJob={vi.fn()} />);
    expect((await screen.findAllByText("172.20.0.0/16")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("fd42:20::/64").length).toBeGreaterThan(0);
    expect(screen.getByText("docker.systemNetwork")).toBeInTheDocument();
    const protectedActions = screen.getAllByTitle("docker.systemNetworkProtected").filter((item) => item.tagName === "BUTTON");
    expect(protectedActions).toHaveLength(3);
    protectedActions.forEach((button) => expect(button).toBeDisabled());
  });

  it("submits the typed dual-stack create contract", async () => {
    const onJob = vi.fn();
    render(<NetworksManager permissions={["docker.manage_networks"]} t={t} toast={vi.fn()} onJob={onJob} />);
    fireEvent.click(await screen.findByRole("button", { name: "docker.createNetwork" }));
    fireEvent.change(screen.getByLabelText("docker.field.name"), { target: { value: " private-net " } });
    const manualModes = screen.getAllByLabelText("docker.ipMode.manual");
    fireEvent.click(manualModes[0]);
    fireEvent.change(screen.getByPlaceholderText("172.20.0.0/16"), { target: { value: "172.20.0.0/16" } });
    fireEvent.change(screen.getByPlaceholderText("172.20.10.0/24"), { target: { value: "172.20.10.0/24" } });
    fireEvent.change(screen.getByPlaceholderText("172.20.0.1"), { target: { value: "172.20.0.1" } });
    fireEvent.click(manualModes[1]);
    fireEvent.change(screen.getByPlaceholderText("fd42:20::/64"), { target: { value: "fd42:20::/64" } });
    fireEvent.change(screen.getByPlaceholderText("fd42:20:0:0:10::/80"), { target: { value: "fd42:20:0:0:10::/80" } });
    fireEvent.change(screen.getByPlaceholderText("fd42:20::1"), { target: { value: "fd42:20::1" } });
    fireEvent.click(screen.getByLabelText("docker.disableIpMasquerade"));
    fireEvent.click(screen.getByRole("button", { name: "action.add" }));

    await waitFor(() => expect(api.createDockerNetwork).toHaveBeenCalled());
    expect(api.createDockerNetwork).toHaveBeenCalledWith(expect.objectContaining({
      name: "private-net",
      driver: "bridge",
      ipv4_mode: "manual",
      ipv4_ip_range: "172.20.10.0/24",
      ipv6_mode: "manual",
      ipv6_subnet: "fd42:20::/64",
      disable_ip_masquerade: true,
    }));
    expect(onJob).toHaveBeenCalledWith(expect.objectContaining({ id: "create-job" }));
  });

  it("connects a container selected from eligible candidates", async () => {
    render(<NetworksManager permissions={["docker.manage_networks"]} t={t} toast={vi.fn()} onJob={vi.fn()} />);
    fireEvent.click(await screen.findByTitle("docker.connectContainer"));
    const select = await screen.findByLabelText("docker.field.container");
    expect(screen.queryByRole("option", { name: /web/ })).not.toBeInTheDocument();
    fireEvent.change(select, { target: { value: "worker" } });
    fireEvent.click(screen.getByRole("button", { name: "action.apply" }));
    await waitFor(() => expect(api.dockerNetworkAction).toHaveBeenCalledWith("app-network", expect.objectContaining({
      action: "connect",
      container: "worker",
    })));
  });
});
