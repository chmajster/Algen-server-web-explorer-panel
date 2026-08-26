import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type AppJob, type DhcpConfiguration, type DhcpLease, type DhcpReservation, type DhcpStatus, type DhcpSubnet } from "../../../api";
import { DhcpManagerApp } from "./DhcpManagerApp";

vi.mock("../../../api", async () => {
  const actual = await vi.importActual<typeof import("../../../api")>("../../../api");
  return {
    ...actual,
    api: {
      ...actual.api,
      dhcpStatus: vi.fn(), dhcpSubnets: vi.fn(), dhcpReservations: vi.fn(), dhcpInterfaces: vi.fn(), dhcpConfig: vi.fn(),
      dhcpLeases: vi.fn(), dhcpDiagnostics: vi.fn(), dhcpBackups: vi.fn(), dhcpLogs: vi.fn(), validateDhcpConfig: vi.fn(),
      planDhcpConfig: vi.fn(), applyDhcpConfig: vi.fn(), createDhcpSubnet: vi.fn(), updateDhcpSubnet: vi.fn(), deleteDhcpSubnet: vi.fn(),
      setDhcpSubnetEnabled: vi.fn(), cloneDhcpSubnet: vi.fn(), createDhcpReservation: vi.fn(), updateDhcpReservation: vi.fn(),
      deleteDhcpReservation: vi.fn(), setDhcpReservationEnabled: vi.fn(), convertDhcpLease: vi.fn(), addDhcpLeaseToHosts: vi.fn(),
      createDhcpBackup: vi.fn(), restoreDhcpBackup: vi.fn(), deleteDhcpBackup: vi.fn(), controlDhcpService: vi.fn(), appJob: vi.fn(),
    },
  };
});

vi.mock("../../package-center/PackageJobDialog", () => ({
  PackageJobDialog: ({ initialJob }: { initialJob: { progress: number } }) => <div data-testid="dhcp-job-progress">Job progress {initialJob.progress}%</div>,
}));

const t = (key: string) => key;
const subnet: DhcpSubnet = {
  id: "subnet-lan", name: "LAN", cidr: "10.0.10.0/24", gateway: "10.0.10.1", subnet_mask: "255.255.255.0",
  pool_start: "10.0.10.100", pool_end: "10.0.10.200", dns_servers: ["10.0.10.2"], domain_name: "lab.local", search_domain: "lab.local",
  lease_time: 3600, max_lease_time: 7200, ntp_servers: [], broadcast_address: "10.0.10.255", tftp_server: "", boot_filename: "",
  pxe_enabled: false, enabled: true, description: "LAN pool",
  utilization: { subnet_id: "subnet-lan", subnet: "10.0.10.0/24", pool_start: "10.0.10.100", pool_end: "10.0.10.200", used: 54, available: 47, total: 101, usage_percent: 53.5, level: "normal" },
};
const reservation: DhcpReservation = { id: "reservation-printer", hostname: "printer", mac_address: "02:00:00:00:00:10", ipv4_address: "10.0.10.20", subnet_id: subnet.id, description: "", client_identifier: "", enabled: true, create_dns_record: true, dns_provider: "auto" };
const lease: DhcpLease = { id: "lease-1", hostname: "laptop", ipv4_address: "10.0.10.110", mac_address: "02:00:00:00:00:20", client_identifier: "client-1", subnet_id: subnet.id, subnet: subnet.cidr, lease_start: 1_700_000_000, lease_end: 2_000_000_000, remaining_seconds: 1200, state: "active", reserved: false };
const configuration: DhcpConfiguration = { interfaces: ["eth0"], authoritative: true, default_lease_time: 3600, max_lease_time: 7200, thresholds: { warning: 70, critical: 85, emergency: 95 }, subnets: [subnet], reservations: [reservation] };
const status: DhcpStatus = { installed: true, backend: "kea", version: "2.6.1", service: "kea-dhcp4-server", service_state: "active", service_enabled: true, uptime_seconds: 7200, interfaces: ["eth0"], active_leases: 54, available_addresses: 47, used_addresses: 54, subnet_count: 1, reservation_count: 1, last_errors: [], last_config_change: 1_700_000_000, configuration_valid: true, health: "healthy", blocked_by_proxmox: false };
const queuedJob: AppJob = { id: "job-1", module_id: "dhcp", action: "manage", status: "queued", progress: 0, created_at: 1, log_tail: [], error: "" };

function mockApi(nextStatus: DhcpStatus = status) {
  vi.mocked(api.dhcpStatus).mockResolvedValue(nextStatus);
  vi.mocked(api.dhcpSubnets).mockResolvedValue({ items: [subnet], total: 1 });
  vi.mocked(api.dhcpReservations).mockResolvedValue({ items: [reservation], total: 1 });
  vi.mocked(api.dhcpInterfaces).mockResolvedValue({ items: [{ name: "eth0", state: "up", mac_address: "02:00:00:00:00:01", ipv4_addresses: ["10.0.10.1"], subnets: ["10.0.10.0/24"], dhcp_enabled: true }], total: 1 });
  vi.mocked(api.dhcpConfig).mockResolvedValue(configuration);
  vi.mocked(api.dhcpLeases).mockResolvedValue({ items: [lease], total: 1 });
  vi.mocked(api.dhcpDiagnostics).mockResolvedValue({ items: [{ status: "PASS", code: "config", title: "DHCP configuration diagnostic", detail: "Valid", recommendation: "" }] });
  vi.mocked(api.dhcpBackups).mockResolvedValue({ items: [] });
  vi.mocked(api.dhcpLogs).mockResolvedValue({ source: "journal:kea", sources: [{ id: "journal:kea", label: "Kea" }], lines: ["INFO DHCP service ready"], truncated: false });
  vi.mocked(api.validateDhcpConfig).mockResolvedValue({ ok: true, backend: "kea", issues: [], native_output: "kea-dhcp4 -t: valid", candidate_sha256: "a".repeat(64) });
  vi.mocked(api.planDhcpConfig).mockResolvedValue({ validation: { ok: true, backend: "kea", issues: [], native_output: "", candidate_sha256: "a".repeat(64) }, added_subnets: ["LAN"], removed_subnets: [], changed_subnets: [], added_reservations: [], removed_reservations: [], changed_reservations: [], changed_global_options: ["interfaces"], warnings: [] });
  vi.mocked(api.createDhcpSubnet).mockResolvedValue({ job: queuedJob });
}

describe("DhcpManagerApp", () => {
  beforeEach(() => { vi.clearAllMocks(); mockApi(); });

  it("renders dashboard, utilization and all module sections", async () => {
    render(<DhcpManagerApp permissions={["dhcp.view", "dhcp.leases.view"]} t={t} toast={vi.fn()} />);
    expect(await screen.findByText("KEA")).toBeInTheDocument();
    expect(screen.getByText("54 used · 47 available")).toBeInTheDocument();
    for (const label of ["Overview", "Subnets", "Reservations", "Leases", "Interfaces", "Configuration", "Diagnostics", "Logs", "Backups"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("button", { name: "Subnets" }));
    expect(screen.getByText("LAN")).toBeInTheDocument();
    expect(screen.getByText("53.5%")).toBeInTheDocument();
  });

  it("enforces read-only UI and Proxmox Safe Mode while retaining diagnostics", async () => {
    mockApi({ ...status, blocked_by_proxmox: true });
    render(<DhcpManagerApp permissions={["dhcp.view", "dhcp.configure", "dhcp.subnets.manage", "dhcp.diagnostics"]} t={t} toast={vi.fn()} />);
    expect(await screen.findByRole("status")).toHaveTextContent("Proxmox Safe Mode blocks DHCP mutations");
    fireEvent.click(screen.getByRole("button", { name: "Subnets" }));
    expect(screen.queryByRole("button", { name: "Create subnet" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Disable" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Configuration" }));
    expect(screen.getByRole("button", { name: /Apply/ })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /eth0/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Diagnostics" }));
    await waitFor(() => expect(api.dhcpDiagnostics).toHaveBeenCalled());
    expect(screen.getByText("DHCP configuration diagnostic")).toBeInTheDocument();
  });

  it("validates typed configuration and renders the configuration preview", async () => {
    render(<DhcpManagerApp permissions={["dhcp.view", "dhcp.configure"]} t={t} toast={vi.fn()} />);
    await screen.findByText("KEA");
    fireEvent.click(screen.getByRole("button", { name: "Configuration" }));
    fireEvent.click(screen.getByRole("button", { name: /Validate Configuration/ }));
    expect(await screen.findByText("Configuration valid")).toBeInTheDocument();
    expect(api.validateDhcpConfig).toHaveBeenCalledWith(expect.objectContaining({ interfaces: ["eth0"] }));
    fireEvent.click(screen.getByRole("button", { name: /Show changes \/ plan/ }));
    expect(await screen.findByText("Configuration preview")).toBeInTheDocument();
    expect(screen.getByText("Added subnets")).toBeInTheDocument();
    expect(screen.getByText("LAN")).toBeInTheDocument();
  });

  it("requires exact confirmation and PAM before queueing a subnet mutation and shows job progress", async () => {
    render(<DhcpManagerApp permissions={["dhcp.view", "dhcp.subnets.manage"]} t={t} toast={vi.fn()} />);
    await screen.findByText("KEA");
    fireEvent.click(screen.getByRole("button", { name: "Subnets" }));
    fireEvent.click(screen.getByRole("button", { name: "Create subnet" }));
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.change(dialog.getByLabelText("Name"), { target: { value: "Lab" } });
    const save = dialog.getByRole("button", { name: /Save and Apply/ });
    expect(save).toBeDisabled();
    fireEvent.change(dialog.getByLabelText(/Type exactly dhcp:subnet:create/), { target: { value: "dhcp:subnet:create" } });
    fireEvent.change(dialog.getByLabelText("PAM password"), { target: { value: "secret" } });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(api.createDhcpSubnet).toHaveBeenCalledWith(expect.objectContaining({ name: "Lab" }), { confirmation: "dhcp:subnet:create", pam_password: "secret" }));
    expect(await screen.findByTestId("dhcp-job-progress")).toHaveTextContent("Job progress 0%");
  });

  it("loads leases with filters and gates lease actions by permissions", async () => {
    render(<DhcpManagerApp permissions={["dhcp.view", "dhcp.leases.view"]} t={t} toast={vi.fn()} />);
    await screen.findByText("KEA");
    fireEvent.click(screen.getByRole("button", { name: "Leases" }));
    expect(await screen.findByText("laptop")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reserve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add to Hosts" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Search leases"), { target: { value: "laptop" } });
    fireEvent.keyDown(screen.getByLabelText("Search leases"), { key: "Enter" });
    await waitFor(() => expect(api.dhcpLeases).toHaveBeenCalledWith(expect.objectContaining({ search: "laptop" })));
    fireEvent.change(screen.getByLabelText("Lease state"), { target: { value: "active" } });
    await waitFor(() => expect(api.dhcpLeases).toHaveBeenCalledWith(expect.objectContaining({ state: "active" })));
  });
});
