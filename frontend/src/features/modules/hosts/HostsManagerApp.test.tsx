import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../../../api";
import { HostsManagerApp } from "./HostsManagerApp";

vi.mock("../../../api", async () => {
  const actual = await vi.importActual<typeof import("../../../api")>("../../../api");
  return { ...actual, api: { ...actual.api, hostsManagerDashboard: vi.fn(), hostsManagerHosts: vi.fn(), hostsManagerGroups: vi.fn(), hostsManagerEnrollmentTokens: vi.fn(), hostsManagerOperations: vi.fn(), hostsManagerCredentials: vi.fn(), hostsManagerRepositories: vi.fn(), hostsManagerPowerProfiles: vi.fn(), hostsManagerDiagnostics: vi.fn(), hostsManagerBackups: vi.fn(), hostsManagerCapabilities: vi.fn(), saveHostsManagerHost: vi.fn(), createHostsManagerEnrollmentToken: vi.fn() } };
});

const t = (key: string) => key;
const permissions = ["hosts-manager.view", "hosts-manager.hosts.view", "hosts-manager.hosts.manage", "hosts-manager.hosts.approve", "hosts-manager.audit.view"];

describe("HostsManagerApp", () => {
  beforeEach(() => {
    vi.mocked(api.hostsManagerDashboard).mockResolvedValue({ total: 1, online: 1, offline: 0, unverified: 1, fingerprint_errors: 0, pending_approval: 1, ansible_available: 0, power_managed: 0, recent_operations: [], recent_errors: [] });
    vi.mocked(api.hostsManagerHosts).mockResolvedValue([{ id: "a".repeat(32), name: "node-01", hostname: "node-01", fqdn: "", address: "192.168.1.10", management_address: "", port: 22, ssh_user: "ops", credential_id: null, python_interpreter: "auto_silent", connection_type: "ssh", environment: "prod", location: "rack-1", description: "", tags: ["linux"], variables: {}, group_ids: [], approved: false, registration_status: "pending_approval", connection_status: "online", power_status: "unknown", enrollment_source: "manual", fingerprint_status: "unverified", last_error: "", managed_user_created: false, active: true, groups: [], facts: {}, created_at: 1, updated_at: 1 }]);
    vi.mocked(api.hostsManagerGroups).mockResolvedValue([]);
    vi.mocked(api.hostsManagerEnrollmentTokens).mockResolvedValue([]);
    vi.mocked(api.hostsManagerOperations).mockResolvedValue([]);
    vi.mocked(api.hostsManagerCapabilities).mockResolvedValue([]);
  });

  it("renders dashboard, filters hosts, and gates management controls", async () => {
    render(<HostsManagerApp permissions={permissions} t={t} toast={vi.fn()} />);
    expect(await screen.findByText("hosts.dashboard.total")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /module.section.hosts/ }));
    expect(await screen.findByText("node-01")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("action.search"), { target: { value: "missing" } });
    expect(screen.getByText("hosts.list.empty")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /hosts.host.add/ })).toBeInTheDocument();
  });

  it("submits the manual host form through the central API", async () => {
    vi.mocked(api.saveHostsManagerHost).mockResolvedValue({} as never);
    render(<HostsManagerApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: /module.section.hosts/ }));
    fireEvent.click(await screen.findByRole("button", { name: /hosts.host.add/ }));
    fireEvent.change(screen.getByLabelText("common.name"), { target: { value: "new-node" } });
    fireEvent.change(screen.getByLabelText("hosts.host.address"), { target: { value: "192.168.1.20" } });
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));
    await waitFor(() => expect(api.saveHostsManagerHost).toHaveBeenCalledWith(expect.objectContaining({ name: "new-node", address: "192.168.1.20" }), undefined));
  });
});
