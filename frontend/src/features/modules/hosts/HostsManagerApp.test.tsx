import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, type HostsManagerSettings } from "../../../api";
import { HostsManagerApp } from "./HostsManagerApp";

vi.mock("../../../api", async () => {
  const actual = await vi.importActual<typeof import("../../../api")>("../../../api");
  return { ...actual, api: { ...actual.api, hostsManagerDashboard: vi.fn(), hostsManagerSettings: vi.fn(), saveHostsManagerSettings: vi.fn(), hostsManagerHosts: vi.fn(), hostsManagerGroups: vi.fn(), hostsManagerEnvironments: vi.fn(), hostsManagerApmids: vi.fn(), hostsManagerHostnamePatterns: vi.fn(), hostsManagerEnrollmentTokens: vi.fn(), hostsManagerOperations: vi.fn(), hostsManagerCredentials: vi.fn(), hostsManagerRepositories: vi.fn(), hostsManagerPowerProfiles: vi.fn(), hostsManagerDiagnostics: vi.fn(), hostsManagerBackups: vi.fn(), hostsManagerCapabilities: vi.fn(), saveHostsManagerHost: vi.fn(), createHostsManagerEnrollmentToken: vi.fn(), downloadHostsManagerEnrollmentScript: vi.fn() } };
});

const t = (key: string) => key;
const permissions = ["hosts-manager.view", "hosts-manager.hosts.view", "hosts-manager.hosts.manage", "hosts-manager.hosts.approve", "hosts-manager.audit.view"];
const baseSettings: HostsManagerSettings = {
  hostname_template: "SCL000XXX",
  next_hostname: "SCL000001",
  sequence_width: 3,
  preview_hostnames: ["SCL000001", "SCL000002", "SCL000003"],
  bootstrap_default_os: "linux",
  bootstrap_apply_hostname: true,
  default_hostname_pattern_id: "default",
  agent_default_port: 8443,
  server_url: "https://panel.example.test",
  agent_protocol: "https",
  connection_timeout_seconds: 15,
  report_interval_seconds: 300,
  heartbeat_interval_seconds: 60,
  max_connection_retries: 3,
  ssh_default_port: 22,
  ssh_timeout_seconds: 10,
  ssh_max_concurrency: 16,
  ssh_verify_fingerprint: true,
  ssh_new_host_key_policy: "ask",
  agent_min_version: "1.0.0",
  agent_auto_update: true,
  agent_update_channel: "stable",
  agent_repository_url: "https://panel.example.test/api/modules/hosts-manager/agent/source",
  agent_enforce_tls: true,
  agent_log_level: "INFO",
  token_ttl_minutes: 15,
  allowed_registration_networks: ["10.0.0.0/8", "192.168.0.0/16"],
  max_auth_failures: 5,
  updated_at: 0,
  updated_by: "",
};

describe("HostsManagerApp", () => {
  beforeEach(() => {
    vi.mocked(api.hostsManagerDashboard).mockResolvedValue({ total: 1, online: 1, offline: 0, unverified: 1, fingerprint_errors: 0, pending_approval: 1, ansible_available: 0, power_managed: 0, recent_operations: [], recent_errors: [] });
    vi.mocked(api.hostsManagerSettings).mockResolvedValue(baseSettings);
    vi.mocked(api.hostsManagerHosts).mockResolvedValue([{ id: "a".repeat(32), name: "node-01", hostname: "node-01", fqdn: "", address: "192.168.1.10", management_address: "", port: 22, ssh_user: "ops", credential_id: null, python_interpreter: "auto_silent", connection_type: "ssh", environment: "prod", location: "rack-1", description: "", tags: ["linux"], variables: {}, group_ids: [], approved: false, registration_status: "pending_approval", connection_status: "online", power_status: "unknown", enrollment_source: "manual", fingerprint_status: "unverified", last_error: "", managed_user_created: false, active: true, groups: [], facts: {}, created_at: 1, updated_at: 1 }]);
    vi.mocked(api.hostsManagerGroups).mockResolvedValue([]);
    vi.mocked(api.hostsManagerEnvironments).mockResolvedValue([{
      id: "default", name: "Default", slug: "default", description: "", color: "#187eb1",
      default_hostname_pattern_id: null, default_credential_id: null, default_agent_port: 9443,
      report_interval_seconds: 600, active: true, host_count: 0, created_at: 1, updated_at: 1,
    }]);
    vi.mocked(api.hostsManagerApmids).mockResolvedValue([{
      id: "apmid-app", code: "APP", description: "", active: true, created_at: 1, updated_at: 1,
      created_by: "admin", updated_by: "admin", environment_groups: [],
    }]);
    vi.mocked(api.hostsManagerHostnamePatterns).mockResolvedValue([]);
    vi.mocked(api.hostsManagerEnrollmentTokens).mockResolvedValue([]);
    vi.mocked(api.hostsManagerOperations).mockResolvedValue([]);
    vi.mocked(api.hostsManagerCredentials).mockResolvedValue([]);
    vi.mocked(api.hostsManagerRepositories).mockResolvedValue([]);
    vi.mocked(api.hostsManagerPowerProfiles).mockResolvedValue([]);
    vi.mocked(api.hostsManagerDiagnostics).mockResolvedValue({ schema_version: 5, checks: [] });
    vi.mocked(api.hostsManagerBackups).mockResolvedValue([]);
    vi.mocked(api.hostsManagerCapabilities).mockResolvedValue([]);
  });

  it("renders dashboard, filters hosts, and gates management controls", async () => {
    render(<HostsManagerApp permissions={permissions} t={t} toast={vi.fn()} />);
    expect(await screen.findByText("hosts.dashboard.total")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /module.section.hosts/ }));
    expect((await screen.findAllByText("node-01")).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText("action.search"), { target: { value: "missing" } });
    expect(screen.getByText("hosts.list.empty")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "hosts.host.add" })).toBeInTheDocument();
    const addressSort = screen.getByRole("button", { name: "hosts.host.address" });
    fireEvent.click(addressSort);
    expect(addressSort.closest("th")).toHaveAttribute("aria-sort", "ascending");
  });

  it("keeps APMID selectors for enrollment without duplicating the management form", async () => {
    render(<HostsManagerApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");

    expect(screen.queryByRole("button", { name: "module.section.apmid" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "module.section.installer" }));
    expect(await screen.findByText("hosts.installer.wizard")).toBeInTheDocument();
    expect(screen.queryByText("hosts.apmid.title")).not.toBeInTheDocument();
  });

  it("filters host groups by the related APMID code", async () => {
    vi.mocked(api.hostsManagerGroups).mockResolvedValue([{
      id: "group-default",
      name: "managed-default",
      description: "Generated environment group",
      parent_id: null,
      variables: {},
      host_ids: [],
      active: true,
      created_at: 1,
      updated_at: 1,
      managed: true,
      managed_by: { apmid_id: "apmid-app", environment_id: "default" },
    }]);
    render(<HostsManagerApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");

    fireEvent.click(screen.getByRole("button", { name: /module.section.settings/ }));
    fireEvent.click(await screen.findByRole("button", { name: "hosts.settings.view.groups" }));
    const search = screen.getByLabelText("hosts.groups.searchApmid");
    fireEvent.change(search, { target: { value: "APP" } });

    expect(screen.getByText("managed-default")).toBeInTheDocument();
    expect(screen.getByText("APP")).toBeInTheDocument();
    fireEvent.change(search, { target: { value: "OTHER" } });
    expect(screen.getByText("hosts.records.empty")).toBeInTheDocument();
  });

  it("uses the global interface scale without resetting the section or fetching again", async () => {
    const toast = vi.fn();
    const originalFontSize = document.documentElement.style.fontSize;
    const { container, rerender } = render(<HostsManagerApp permissions={permissions} t={t} toast={toast} />);
    await screen.findByText("hosts.dashboard.total");
    const root = container.querySelector(".module-app");
    expect(root).toHaveClass("hosts-manager-app");
    expect((root as HTMLElement).style.zoom).toBe("");
    expect((root as HTMLElement).style.transform).toBe("");
    expect((root as HTMLElement).style.getPropertyValue("--ui-scale")).toBe("");

    fireEvent.click(screen.getByRole("button", { name: /module.section.installer/ }));
    expect(screen.getByRole("button", { name: /module.section.installer/ })).toHaveAttribute("aria-current", "page");
    const dashboardCalls = vi.mocked(api.hostsManagerDashboard).mock.calls.length;

    document.documentElement.style.fontSize = "20px";
    rerender(<HostsManagerApp permissions={permissions} t={t} toast={toast} />);

    expect(screen.getByRole("button", { name: /module.section.installer/ })).toHaveAttribute("aria-current", "page");
    expect(api.hostsManagerDashboard).toHaveBeenCalledTimes(dashboardCalls);
    document.documentElement.style.fontSize = originalFontSize;
  });

  it("submits the manual host form through the central API", async () => {
    vi.mocked(api.saveHostsManagerHost).mockResolvedValue({} as never);
    render(<HostsManagerApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: /module.section.hosts/ }));
    fireEvent.click(await screen.findByRole("button", { name: "hosts.host.add" }));
    fireEvent.change(screen.getByLabelText("common.name"), { target: { value: "new-node" } });
    fireEvent.change(screen.getByLabelText("hosts.host.address"), { target: { value: "192.168.1.20" } });
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));
    await waitFor(() => expect(api.saveHostsManagerHost).toHaveBeenCalledWith(expect.objectContaining({ name: "new-node", address: "192.168.1.20" }), undefined));
  });

  it("shows the next hostname and saves the central hostname template", async () => {
    vi.mocked(api.saveHostsManagerSettings).mockResolvedValue({ ...baseSettings, hostname_template: "SRV-XXXX", next_hostname: "SRV-0001", sequence_width: 4, preview_hostnames: ["SRV-0001", "SRV-0002", "SRV-0003"], bootstrap_default_os: "windows", updated_at: 2, updated_by: "admin" });
    render(<HostsManagerApp permissions={[...permissions, "hosts-manager.configure"]} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: /module.section.settings/ }));
    expect((await screen.findAllByText("SCL000001")).length).toBeGreaterThan(0);
    fireEvent.change(await screen.findByDisplayValue("SCL000XXX"), { target: { value: "SRV-XXXX" } });
    fireEvent.change(screen.getByLabelText("hosts.enrollment.os"), { target: { value: "windows" } });
    fireEvent.click(screen.getByRole("button", { name: "action.save" }));
    await waitFor(() => expect(api.saveHostsManagerSettings).toHaveBeenCalledWith(expect.objectContaining({ hostname_template: "SRV-XXXX", bootstrap_default_os: "windows" })));
  });

  it("creates a Windows bootstrap for the reserved hostname", async () => {
    vi.mocked(api.createHostsManagerEnrollmentToken).mockResolvedValue({ id: "token", hostname_pattern: "SCL000001", assigned_hostname: "SCL000001", bootstrap_os: "windows", apply_hostname: true, expires_at: 100, used: false, token: "raw-once", script_url: "/api/modules/hosts-manager/enrollment-script", command: "powershell command", filename: "webnas-enroll-SCL000001.ps1" });
    render(<HostsManagerApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: /module.section.installer/ }));
    fireEvent.click(screen.getByRole("button", { name: /hosts.installer.script/ }));
    fireEvent.click(await screen.findByRole("button", { name: /hosts.enrollment.generate/ }));
    expect(screen.getByText("SCL000001")).toBeInTheDocument();
    expect(screen.getByText("hosts.enrollment.basic")).toBeInTheDocument();
    expect(screen.getByText("hosts.enrollment.advanced")).toBeInTheDocument();
    expect(screen.queryByLabelText("hosts.host.user")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("hosts.host.port")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("hosts.enrollment.os"), { target: { value: "windows" } });
    const generateButtons = screen.getAllByRole("button", { name: "hosts.enrollment.generate" });
    fireEvent.click(generateButtons[generateButtons.length - 1]);
    await waitFor(() => expect(api.createHostsManagerEnrollmentToken).toHaveBeenCalledWith(expect.objectContaining({
      bootstrap_os: "windows", apply_hostname: true, apmid_id: "apmid-app", environment_id: "default",
      agent_port: 9443, report_interval_seconds: 600,
    })));
    const payload = vi.mocked(api.createHostsManagerEnrollmentToken).mock.calls[0][0] as Record<string, unknown>;
    expect(payload).not.toHaveProperty("ssh_user");
    expect(payload).not.toHaveProperty("port");
    expect(await screen.findByText("powershell command")).toBeInTheDocument();
    vi.mocked(api.downloadHostsManagerEnrollmentScript).mockResolvedValue(new Blob(["script"]));
    fireEvent.click(screen.getByRole("button", { name: /hosts.enrollment.download/ }));
    await waitFor(() => expect(api.downloadHostsManagerEnrollmentScript).toHaveBeenCalledWith("/api/modules/hosts-manager/enrollment-script", "raw-once"));
  });

  it("hides validity for permanent tokens and restores it for one-time tokens", async () => {
    render(<HostsManagerApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: /module.section.installer/ }));
    fireEvent.click(screen.getByRole("button", { name: /hosts.installer.script/ }));
    fireEvent.click(await screen.findByRole("button", { name: /hosts.enrollment.generate/ }));
    expect(screen.getByLabelText("hosts.enrollment.minutes")).toBeRequired();
    fireEvent.change(screen.getByLabelText("hosts.enrollment.mode"), { target: { value: "permanent" } });
    expect(screen.queryByLabelText("hosts.enrollment.minutes")).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("hosts.enrollment.mode"), { target: { value: "one_time" } });
    expect(screen.getByLabelText("hosts.enrollment.minutes")).toBeInTheDocument();
  });

  it("sends no expiration for a permanent token", async () => {
    vi.mocked(api.createHostsManagerEnrollmentToken).mockResolvedValue({
      id: "permanent", hostname_pattern: "SCL000XXX", assigned_hostname: "", bootstrap_os: "linux",
      apply_hostname: true, expires_at: 0, used: false, mode: "permanent", command: "curl command",
    });
    render(<HostsManagerApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: /module.section.installer/ }));
    fireEvent.click(screen.getByRole("button", { name: /hosts.installer.script/ }));
    fireEvent.click(await screen.findByRole("button", { name: /hosts.enrollment.generate/ }));
    fireEvent.change(screen.getByLabelText("hosts.enrollment.mode"), { target: { value: "permanent" } });
    const generateButtons = screen.getAllByRole("button", { name: "hosts.enrollment.generate" });
    fireEvent.click(generateButtons[generateButtons.length - 1]);
    await waitFor(() => expect(api.createHostsManagerEnrollmentToken).toHaveBeenCalledWith(expect.objectContaining({
      mode: "permanent", expires_minutes: null, apmid_id: "apmid-app", environment_id: "default",
    })));
  });

  it("sends a positive numeric expiration for a one-time token", async () => {
    vi.mocked(api.createHostsManagerEnrollmentToken).mockResolvedValue({
      id: "once", hostname_pattern: "SCL000001", assigned_hostname: "SCL000001", bootstrap_os: "linux",
      apply_hostname: true, expires_at: 100, used: false, mode: "one_time", command: "curl command",
    });
    render(<HostsManagerApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: /module.section.installer/ }));
    fireEvent.click(screen.getByRole("button", { name: /hosts.installer.script/ }));
    fireEvent.click(await screen.findByRole("button", { name: /hosts.enrollment.generate/ }));
    fireEvent.change(screen.getByLabelText("hosts.enrollment.minutes"), { target: { value: "30" } });
    const generateButtons = screen.getAllByRole("button", { name: "hosts.enrollment.generate" });
    fireEvent.click(generateButtons[generateButtons.length - 1]);
    await waitFor(() => expect(api.createHostsManagerEnrollmentToken).toHaveBeenCalledWith(expect.objectContaining({
      mode: "one_time", expires_minutes: 30, apmid_id: "apmid-app", environment_id: "default",
      hostname_pattern_id: null,
    })));
    expect(typeof vi.mocked(api.createHostsManagerEnrollmentToken).mock.calls[0][0].expires_minutes).toBe("number");
  });

  it("shows the field name from a controlled enrollment API error", async () => {
    const toast = vi.fn();
    vi.mocked(api.createHostsManagerEnrollmentToken).mockRejectedValue(
      new ApiError("The selected APMID does not exist or is inactive", 422, "APMID_INACTIVE", "apmid_id"),
    );
    render(<HostsManagerApp permissions={permissions} t={t} toast={toast} />);
    await screen.findByText("hosts.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: /module.section.installer/ }));
    fireEvent.click(screen.getByRole("button", { name: /hosts.installer.script/ }));
    fireEvent.click(await screen.findByRole("button", { name: /hosts.enrollment.generate/ }));
    const generateButtons = screen.getAllByRole("button", { name: "hosts.enrollment.generate" });
    fireEvent.click(generateButtons[generateButtons.length - 1]);
    await waitFor(() => expect(toast).toHaveBeenCalledWith("apmid_id: hosts.apmid.inactive", "error"));
  });

  it("blocks generation when no active APMID exists", async () => {
    vi.mocked(api.hostsManagerApmids).mockResolvedValue([]);
    render(<HostsManagerApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: /module.section.installer/ }));
    fireEvent.click(screen.getByRole("button", { name: /hosts.installer.script/ }));
    expect(await screen.findByText("hosts.enrollment.noActiveApmid")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "hosts.enrollment.generate" })).toBeDisabled();
  });

  it("clears a hostname pattern that disappeared after refresh", async () => {
    vi.mocked(api.hostsManagerHostnamePatterns).mockResolvedValue([{
      id: "pattern-1", name: "Production", description: "", template: "PRD-XXX", prefix: "PRD-", suffix: "", digits: 3,
      start_value: 1, next_value: 1, step: 1, last_value: null, preview_hostnames: ["PRD-001"],
      next_hostname: "PRD-001", active: true, created_at: 1, updated_at: 1,
    }]);
    const view = render(<HostsManagerApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: /module.section.installer/ }));
    fireEvent.click(screen.getByRole("button", { name: /hosts.installer.script/ }));
    fireEvent.click(await screen.findByRole("button", { name: /hosts.enrollment.generate/ }));
    fireEvent.change(screen.getByLabelText("hosts.environment.pattern"), { target: { value: "pattern-1" } });

    vi.mocked(api.hostsManagerHostnamePatterns).mockResolvedValue([]);
    const refreshButton = Array.from(view.container.querySelectorAll("button")).find((button) => button.querySelector(".lucide-refresh-cw"));
    expect(refreshButton).toBeDefined();
    fireEvent.click(refreshButton!);
    await waitFor(() => expect(screen.getByLabelText("hosts.environment.pattern")).toHaveValue(""));
  });

  it("blocks generation when no active environment exists", async () => {
    vi.mocked(api.hostsManagerEnvironments).mockResolvedValue([]);
    render(<HostsManagerApp permissions={permissions} t={t} toast={vi.fn()} />);
    await screen.findByText("hosts.dashboard.total");
    fireEvent.click(screen.getByRole("button", { name: /module.section.installer/ }));
    fireEvent.click(screen.getByRole("button", { name: /hosts.installer.script/ }));
    expect(await screen.findByText("hosts.enrollment.noActiveEnvironment")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "hosts.enrollment.generate" })).toBeDisabled();
  });
});
