import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AnsibleControllerApp } from "./AnsibleControllerApp";

const mocks = vi.hoisted(() => ({
  module: vi.fn(), dashboard: vi.fn(), hosts: vi.fn(), groups: vi.fn(), credentials: vi.fn(), scans: vi.fn(), startScan: vi.fn(),
}));

vi.mock("../../../api", async () => {
  const actual = await vi.importActual<typeof import("../../../api")>("../../../api");
  return { ...actual, api: { ...actual.api, module: mocks.module, ansibleDashboard: mocks.dashboard, ansibleHosts: mocks.hosts, ansibleGroups: mocks.groups, ansibleCredentials: mocks.credentials, ansibleScans: mocks.scans, startAnsibleScan: mocks.startScan } };
});

const status = { installed: true, update_available: false, service_state: "ready", service_enabled: false, services: {}, health: "healthy", health_message: "ready", last_action: "", last_action_status: "", last_error: "", metrics: {} };
const permissions = ["ansible-controller.view", "ansible-controller.hosts.view", "ansible-controller.hosts.manage", "ansible-controller.discovery", "ansible-controller.credentials.view"];
const t = (key: string) => key;

describe("AnsibleControllerApp", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocks.module.mockResolvedValue({ module_status: status, manifest: { name: "Ansible" }, capabilities: {}, state: {}, jobs: [] });
    mocks.dashboard.mockResolvedValue({ hosts: 2, hosts_online: 1, hosts_unreachable: 1, host_key_errors: 0, groups: 1, projects: 0, playbooks: 0, templates: 0, active_jobs: 0, failed_jobs: 0, scheduled: 0, ansible_version: "ansible 2.18" });
    mocks.hosts.mockResolvedValue([]); mocks.groups.mockResolvedValue([]); mocks.credentials.mockResolvedValue([]); mocks.scans.mockResolvedValue([]);
    mocks.startScan.mockResolvedValue({ scan: { id: "scan", status: "queued", progress: 0, discovered: 0, request: {}, error: "", created_at: 1 }, job: { id: "job" }, address_count: 254 });
  });

  it("shows a permission state without making controller requests", () => {
    render(<AnsibleControllerApp permissions={[]} t={t} toast={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("ansible.permissionRequired");
    expect(mocks.module).not.toHaveBeenCalled();
  });

  it("renders dashboard metrics with text status labels", async () => {
    render(<AnsibleControllerApp permissions={permissions} t={t} toast={vi.fn()} />);
    expect(await screen.findByText("ansible.dashboard.hosts")).toBeInTheDocument();
    expect(screen.getByText("ansible.status.healthy")).toBeInTheDocument();
    expect(screen.getByText("ansible 2.18")).toBeInTheDocument();
  });

  it("validates and starts discovery through the typed API", async () => {
    render(<AnsibleControllerApp permissions={permissions} t={t} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /module.section.discovery/ }));
    const cidr = await screen.findByLabelText("ansible.discovery.cidr");
    fireEvent.change(cidr, { target: { value: "192.168.50.0/24" } });
    fireEvent.click(screen.getByRole("button", { name: /ansible.discovery.start/ }));
    await waitFor(() => expect(mocks.startScan).toHaveBeenCalledWith(expect.objectContaining({ cidr: "192.168.50.0/24", method: "nmap" })));
  });
});
