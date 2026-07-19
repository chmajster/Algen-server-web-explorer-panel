import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AnsibleControllerApp } from "./AnsibleControllerApp";

const mocks = vi.hoisted(() => ({
  module: vi.fn(), dashboard: vi.fn(), hosts: vi.fn(), groups: vi.fn(), credentials: vi.fn(), saveCredential: vi.fn(), config: vi.fn(), saveManagedAccount: vi.fn(), scans: vi.fn(), startScan: vi.fn(),
}));

vi.mock("../../../api", async () => {
  const actual = await vi.importActual<typeof import("../../../api")>("../../../api");
  return { ...actual, api: { ...actual.api, module: mocks.module, ansibleDashboard: mocks.dashboard, ansibleHosts: mocks.hosts, ansibleGroups: mocks.groups, ansibleCredentials: mocks.credentials, saveAnsibleCredential: mocks.saveCredential, ansibleConfig: mocks.config, saveAnsibleManagedAccount: mocks.saveManagedAccount, ansibleScans: mocks.scans, startAnsibleScan: mocks.startScan } };
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
    mocks.saveCredential.mockResolvedValue({ id: "credential" });
    mocks.config.mockResolvedValue({ managed_username: "algen-ansible", managed_sudo_profile: "none", managed_shell: "/bin/bash", managed_comment: "Algen Ansible automation", managed_authorized_keys_mode: "exclusive", allowed_networks: [] });
    mocks.saveManagedAccount.mockResolvedValue({ managed_username: "deploy-bot", managed_sudo_profile: "nopasswd", managed_shell: "/bin/sh", managed_comment: "Production automation", managed_authorized_keys_mode: "append" });
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

  it("shows credential fields appropriate for the selected type", async () => {
    const credentialPermissions = [...permissions, "ansible-controller.credentials.manage"];
    render(<AnsibleControllerApp permissions={credentialPermissions} t={t} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /module.section.credentials/ }));
    fireEvent.click(await screen.findByRole("button", { name: /ansible.credential.add/ }));

    const type = screen.getByLabelText("ansible.credential.type");
    fireEvent.change(type, { target: { value: "ssh_password" } });
    expect(screen.getByLabelText("ansible.credential.localUsername")).toBeRequired();
    expect(screen.getByLabelText("ansible.credential.secret.ssh_password")).toHaveAttribute("type", "password");

    fireEvent.change(type, { target: { value: "awx_token" } });
    expect(screen.queryByLabelText("ansible.credential.localUsername")).not.toBeInTheDocument();
    expect(screen.getByLabelText("ansible.credential.secret.awx_token")).toHaveAttribute("type", "password");
  });

  it("changes the default managed account used for host onboarding", async () => {
    const credentialPermissions = [...permissions, "ansible-controller.credentials.manage", "ansible-controller.configure"];
    render(<AnsibleControllerApp permissions={credentialPermissions} t={t} toast={vi.fn()} />);
    await screen.findByText("ansible.dashboard.hosts");
    const accountTab = screen.getByRole("button", { name: /module.section.automation-account/ });
    fireEvent.click(accountTab);
    expect(accountTab).toHaveAttribute("aria-current", "page");
    await screen.findByText("ansible.managedAccount.pageTitle");

    const username = await screen.findByLabelText("ansible.managedAccount.username");
    expect(username).toHaveValue("algen-ansible");
    fireEvent.change(username, { target: { value: "deploy-bot" } });
    fireEvent.change(screen.getByLabelText("ansible.managedAccount.sudoProfile"), { target: { value: "nopasswd" } });
    fireEvent.change(screen.getByLabelText("ansible.managedAccount.shell"), { target: { value: "/bin/sh" } });
    fireEvent.change(screen.getByLabelText("ansible.managedAccount.comment"), { target: { value: "Production automation" } });
    fireEvent.change(screen.getByLabelText("ansible.managedAccount.keysMode"), { target: { value: "append" } });
    fireEvent.click(screen.getByRole("button", { name: /ansible.managedAccount.save/ }));

    await waitFor(() => expect(mocks.saveManagedAccount).toHaveBeenCalledWith({ username: "deploy-bot", sudo_profile: "nopasswd", shell: "/bin/sh", comment: "Production automation", authorized_keys_mode: "append" }));
  });
});
