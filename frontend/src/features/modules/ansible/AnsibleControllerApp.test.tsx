import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AnsibleControllerApp } from "./AnsibleControllerApp";

const mocks = vi.hoisted(() => ({
  module: vi.fn(), dashboard: vi.fn(), hosts: vi.fn(), groups: vi.fn(), credentials: vi.fn(), saveCredential: vi.fn(), enrollment: vi.fn(), config: vi.fn(), saveManagedAccount: vi.fn(), scans: vi.fn(), startScan: vi.fn(), projects: vi.fn(), playbooks: vi.fn(), validatePlaybook: vi.fn(), savePlaybook: vi.fn(), deletePlaybook: vi.fn(),
}));

vi.mock("../../../api", async () => {
  const actual = await vi.importActual<typeof import("../../../api")>("../../../api");
  return { ...actual, api: { ...actual.api, module: mocks.module, ansibleDashboard: mocks.dashboard, ansibleHosts: mocks.hosts, ansibleGroups: mocks.groups, ansibleCredentials: mocks.credentials, saveAnsibleCredential: mocks.saveCredential, createAnsibleEnrollmentToken: mocks.enrollment, ansibleConfig: mocks.config, saveAnsibleManagedAccount: mocks.saveManagedAccount, ansibleScans: mocks.scans, startAnsibleScan: mocks.startScan, ansibleProjects: mocks.projects, ansiblePlaybooks: mocks.playbooks, validateAnsiblePlaybook: mocks.validatePlaybook, saveAnsiblePlaybook: mocks.savePlaybook, deleteAnsiblePlaybook: mocks.deletePlaybook } };
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
    mocks.enrollment.mockResolvedValue({ id: "enrollment", token: "one-time-token-value", hostname_pattern: "web-*", expires_at: 2_000_000_000 });
    mocks.config.mockResolvedValue({ managed_username: "algen-ansible", managed_sudo_profile: "none", managed_shell: "/bin/bash", managed_comment: "Algen Ansible automation", managed_authorized_keys_mode: "exclusive", managed_key_rotation_days: 90, allowed_networks: [] });
    mocks.saveManagedAccount.mockResolvedValue({ managed_username: "deploy-bot", managed_sudo_profile: "nopasswd", managed_shell: "/bin/sh", managed_comment: "Production automation", managed_authorized_keys_mode: "exclusive", managed_key_rotation_days: 60 });
    mocks.startScan.mockResolvedValue({ scan: { id: "scan", status: "queued", progress: 0, discovered: 0, request: {}, error: "", created_at: 1 }, job: { id: "job" }, address_count: 254 });
    mocks.projects.mockResolvedValue([{ id: "a".repeat(32), name: "Local", source_type: "editor", repository_url: "", revision: "main", credential_id: null, last_commit: "", last_sync_at: null, active: true }]);
    mocks.playbooks.mockResolvedValue([{ id: "b".repeat(32), project_id: "a".repeat(32), name: "Deploy web", filename: "deploy-web.yml", content: "---\n- hosts: web\n  tasks: []\n", current_version: 2, risk_status: "safe", warnings: [], active: true, updated_at: 2 }]);
    mocks.validatePlaybook.mockResolvedValue({ ok: true, task_count: 1, errors: [], blocked: [], warnings: [], runtime: { ok: true, checks: [] } });
    mocks.savePlaybook.mockResolvedValue({ id: "b".repeat(32), project_id: "a".repeat(32), name: "Deploy web", filename: "deploy-web.yml", content: "---\n- hosts: web\n  tasks: []\n", current_version: 3, risk_status: "safe", warnings: [], active: true, updated_at: 3 });
    mocks.deletePlaybook.mockResolvedValue({ ok: true });
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

  it("generates a one-time Bash command constrained by hostname pattern", async () => {
    render(<AnsibleControllerApp permissions={permissions} t={t} toast={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /module.section.hosts/ }));
    const enrollment = (await screen.findByText("ansible.enrollment.title")).closest("details")!;
    enrollment.setAttribute("open", "");
    const fields = enrollment.querySelectorAll("input");
    fireEvent.change(fields[0], { target: { value: "web-*.example.com" } });
    fireEvent.change(fields[3], { target: { value: "production" } });
    fireEvent.change(fields[5], { target: { value: "linux, web" } });
    fireEvent.click(enrollment.querySelector<HTMLButtonElement>('button[type="submit"]')!);

    await waitFor(() => expect(mocks.enrollment).toHaveBeenCalledWith(expect.objectContaining({
      hostname_pattern: "web-*.example.com", environment: "production", tags: ["linux", "web"], expires_minutes: 15,
    })));
    expect(await screen.findByText(/Authorization: Bearer one-time-token-value/)).toBeInTheDocument();
    expect(screen.getByText(/hostname -f/)).toBeInTheDocument();
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
    expect(screen.getByText("Klucze SSH serwerów")).toBeInTheDocument();
    expect(screen.getByText("Brak przygotowanych hostów")).toBeInTheDocument();
    expect(screen.queryByText("ansible.managedAccount.hostKeys")).not.toBeInTheDocument();

    const username = await screen.findByLabelText("ansible.managedAccount.username");
    expect(username).toHaveValue("algen-ansible");
    fireEvent.change(username, { target: { value: "deploy-bot" } });
    fireEvent.change(screen.getByLabelText("ansible.managedAccount.sudoProfile"), { target: { value: "nopasswd" } });
    fireEvent.change(screen.getByLabelText("ansible.managedAccount.shell"), { target: { value: "/bin/sh" } });
    fireEvent.change(screen.getByLabelText("ansible.managedAccount.comment"), { target: { value: "Production automation" } });
    fireEvent.change(screen.getByLabelText("ansible.managedAccount.rotationInterval"), { target: { value: "60" } });
    fireEvent.click(screen.getByRole("button", { name: /ansible.managedAccount.save/ }));

    await waitFor(() => expect(mocks.saveManagedAccount).toHaveBeenCalledWith({ username: "deploy-bot", sudo_profile: "nopasswd", shell: "/bin/sh", comment: "Production automation", authorized_keys_mode: "exclusive", key_rotation_days: 60 }));
  });

  it("lists, opens, edits, and deletes playbooks", async () => {
    const playbookPermissions = [...permissions, "ansible-controller.playbooks.view", "ansible-controller.playbooks.manage"];
    render(<AnsibleControllerApp permissions={playbookPermissions} t={t} toast={vi.fn()} />);
    await screen.findByText("ansible.dashboard.hosts");
    fireEvent.click(screen.getByRole("button", { name: /module.section.playbooks/ }));

    fireEvent.click(await screen.findByRole("button", { name: /^Deploy web/ }));
    const content = screen.getByLabelText("ansible.playbook.content");
    fireEvent.change(content, { target: { value: "---\n- hosts: all\n  tasks: []\n" } });
    fireEvent.click(screen.getByRole("button", { name: /^action.save$/ }));
    await waitFor(() => expect(mocks.savePlaybook).toHaveBeenCalledWith(expect.objectContaining({ name: "Deploy web", filename: "deploy-web.yml", content: expect.stringContaining("hosts: all") }), "b".repeat(32)));

    fireEvent.click(screen.getByRole("button", { name: "action.delete Deploy web" }));
    await waitFor(() => expect(mocks.deletePlaybook).toHaveBeenCalledWith("b".repeat(32)));
  });

  it("opens readable host details in a modal", async () => {
    mocks.hosts.mockResolvedValue([{ id: "c".repeat(32), name: "node-01", address: "192.168.1.58", port: 22, ssh_user: "algen-ansible", credential_id: "credential", python_interpreter: "auto_silent", connection_type: "ssh", environment: "production", location: "rack-1", tags: [], variables: {}, fingerprint_status: "accepted", last_test_at: 2, last_facts_at: 3, last_error: "", managed_user_created: true, active: true, groups: [], facts: { ansible_distribution: "Debian", ansible_kernel: "6.1", ansible_architecture: "x86_64", ansible_processor_vcpus: 4, ansible_memtotal_mb: 8192 }, created_at: 1, updated_at: 4 }]);
    render(<AnsibleControllerApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("ansible.dashboard.hosts");
    fireEvent.click(screen.getByRole("button", { name: /module.section.hosts/ }));
    fireEvent.click(await screen.findByRole("button", { name: "node-01" }));

    const dialog = screen.getByRole("dialog", { name: "ansible.host.details" });
    expect(dialog).toHaveTextContent("192.168.1.58:22");
    expect(dialog).toHaveTextContent("Debian");
    expect(dialog).toHaveTextContent("production");
    fireEvent.click(screen.getAllByRole("button", { name: "action.close" })[0]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
