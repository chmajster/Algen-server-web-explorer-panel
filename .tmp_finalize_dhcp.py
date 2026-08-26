from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent

TEST = r'''import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type DhcpConfiguration, type DhcpLease, type DhcpReservation, type DhcpStatus, type DhcpSubnet } from "../../../api";
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
const queuedJob = { id: "job-1", module_id: "dhcp", action: "manage", status: "queued", progress: 0, created_at: 1, log_tail: [], error: "" };

function mockApi(nextStatus: DhcpStatus = status) {
  vi.mocked(api.dhcpStatus).mockResolvedValue(nextStatus);
  vi.mocked(api.dhcpSubnets).mockResolvedValue({ items: [subnet], total: 1 });
  vi.mocked(api.dhcpReservations).mockResolvedValue({ items: [reservation], total: 1 });
  vi.mocked(api.dhcpInterfaces).mockResolvedValue({ items: [{ name: "eth0", state: "up", mac_address: "02:00:00:00:00:01", ipv4_addresses: ["10.0.10.1"], subnets: ["10.0.10.0/24"], dhcp_enabled: true }], total: 1 });
  vi.mocked(api.dhcpConfig).mockResolvedValue(configuration);
  vi.mocked(api.dhcpLeases).mockResolvedValue({ items: [lease], total: 1 });
  vi.mocked(api.dhcpDiagnostics).mockResolvedValue({ items: [{ status: "PASS", code: "config", title: "Configuration", detail: "Valid", recommendation: "" }] });
  vi.mocked(api.dhcpBackups).mockResolvedValue({ items: [] });
  vi.mocked(api.dhcpLogs).mockResolvedValue({ source: "journal:kea", sources: [{ id: "journal:kea", label: "Kea" }], lines: ["INFO DHCP service ready"], truncated: false });
  vi.mocked(api.validateDhcpConfig).mockResolvedValue({ ok: true, backend: "kea", issues: [], native_output: "kea-dhcp4 -t: valid", candidate_sha256: "a".repeat(64) });
  vi.mocked(api.planDhcpConfig).mockResolvedValue({ validation: { ok: true, backend: "kea", issues: [], native_output: "", candidate_sha256: "a".repeat(64) }, added_subnets: ["LAN"], removed_subnets: [], changed_subnets: [], added_reservations: [], removed_reservations: [], changed_reservations: [], changed_global_options: ["interfaces"], warnings: [] });
  vi.mocked(api.createDhcpSubnet).mockResolvedValue({ job: queuedJob });
}

describe("DhcpManagerApp", () => {
  beforeEach(() => { vi.clearAllMocks(); mockApi(); });

  it("renders the dashboard and all module navigation sections", async () => {
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

  it("enforces read-only UI and Proxmox Safe Mode without hiding diagnostics", async () => {
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
    expect(screen.getByText("Configuration")).toBeInTheDocument();
  });

  it("validates typed configuration and renders a configuration preview", async () => {
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

  it("loads leases with bounded filters and gates dangerous lease actions by permissions", async () => {
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
'''

DOC = r'''# DHCP Manager

DHCP Manager is the WebNAS infrastructure module for controlled DHCPv4 administration. It is implemented inside the existing module framework: Package Center owns lifecycle, `package_jobs` owns durable mutations and progress, Activity Center records actions, Identity RBAC authorizes requests, and the statically registered DHCP provider is the only system-execution boundary. No second module registry, host inventory, queue, command API, or design system is introduced.

## Architecture

The runtime module lives under `backend/app/modules/dhcp/` and exposes typed Pydantic models, router, service and public integration contracts. The trusted system adapter is `backend/app/modules/providers/dhcp.py` and is explicitly registered in `backend/app/modules/providers/__init__.py`; manifests never name Python classes and no dynamic provider imports are used. The Package Center manifest is `backend/app/modules/dhcp/manifest.yaml`, while the runtime manifest under `backend/app/modules/builtin/dhcp/manifest.yaml` registers the application/router in the existing module loader. The frontend lives under `frontend/src/features/modules/dhcp/` and uses the shared desktop, modal, table, notification, job-progress and theme primitives.

All mutations are serialized through the existing durable `package_jobs` mechanism. Durable payloads contain typed operation data and stable object identifiers only. Browser requests cannot provide executable names, shell fragments, config paths, log paths, systemd units or package-manager commands.

## Supported DHCP backends

DHCP Manager supports Kea DHCPv4 and ISC DHCP Server. Kea DHCP4 is preferred for new installations. Detection is backend-owned and checks only known packages, binaries, configuration locations and systemd units. When both are present, the existing active/configured service is preferred; otherwise Kea is selected according to the provider policy. Unsupported or ambiguous states degrade safely and are reported in status/diagnostics rather than executing guessed commands.

Package installation and removal are delegated to Package Center and its package executor. The frontend never invokes `apt`, `apt-get`, `dnf`, `yum`, `zypper`, `pacman` or `apk` directly.

## Overview and health

The Overview page reports backend/version, service state, autostart, uptime, listening interfaces, active leases, used/available addresses, subnet and reservation counts, last configuration change, configuration validity and recent redacted errors. Health uses `healthy`, `degraded`, `failed`, `unknown` or `not_installed`.

Per-subnet utilization is calculated from the configured dynamic pool. Default thresholds are 70%, 85% and 95% and can be changed through typed configuration. The UI presents used/available totals and a progress indicator without inferring addresses from browser input.

## Subnets and pools

A managed subnet contains a stable ID, name, IPv4 CIDR, router/gateway, mask, pool start/end, DNS servers, domain/search domain, default/max lease time, NTP servers, broadcast address, TFTP/boot/PXE settings, enabled state and description. Create, edit, delete, enable, disable and clone operations are durable jobs.

Validation rejects malformed IPv4/CIDR data, start greater than end, pools outside the subnet, network/broadcast addresses inside a pool, duplicate/overlapping subnets, overlapping pools and reservation conflicts. The backend is authoritative even when the frontend already reports invalid form input.

## Reservations

Reservations contain hostname, normalized MAC, IPv4 address, subnet, optional client identifier, description, enabled state and optional DNS synchronization policy. Duplicate MACs/IPs, addresses outside the selected subnet, addresses inside a dynamic pool and conflicts with active leases are rejected before apply.

An active dynamic lease can be converted to a reservation through the typed lease endpoint. This high-impact mutation requires the dedicated reservation permission, CSRF, PAM and exact lease-ID confirmation.

## Leases

The Leases page reads native backend lease state and provides search, subnet/state filtering, sorting and automatic refresh. Rows include hostname, IP, MAC, client ID, subnet, start/end, remaining time, state and reservation status. Destructive/conversion operations are disabled unless the backend permission and lease state allow them, and the API repeats those checks independently.

## Hosts Manager integration

DHCP Manager does not own a parallel host database. `DHCP Lease -> Add to Hosts Manager` creates or links a record through the Hosts Manager public registry and stores DHCP provider metadata in its controlled variables/integration layer. Hosts Manager can display DHCP IP, MAC, subnet, lease state, reservation state and `source=DHCP` when available.

`Host -> Create DHCP Reservation` is available from Hosts Manager for authorized users. The request carries the existing host ID, selected managed subnet, MAC/hostname and optional DNS flag; the DHCP backend resolves and validates the actual host/address state before queueing. Existing host identity is preserved rather than duplicated.

## Optional DNS integration

Reservations can request `Create/Update DNS record`. DHCP talks only to the public DNS provider contract and currently supports the existing Pi-hole and AdGuard Home integrations. DNS synchronization is optional: DHCP configuration, leases and reservations remain usable without a DNS module. Credentials stay in the existing DNS connection store and are never copied into DHCP state or durable job payloads.

## Configuration transaction

Configuration is edited with typed forms. Applying it follows the fixed transaction:

1. parse the typed request;
2. validate addresses, pools, reservations, interfaces and global options;
3. generate a candidate configuration;
4. run the native Kea/ISC validator with an argument array;
5. return a plan showing added/removed/changed subnets, reservations, global options and warnings;
6. require RBAC, CSRF, exact confirmation and PAM;
7. create an automatic private backup;
8. atomically replace the backend-owned configuration using `fsync` and rename/replace;
9. reload/restart only the allowlisted detected DHCP service;
10. verify service state and validate the applied configuration again;
11. commit module state and audit only after verification.

If a post-write stage fails, the previous configuration is restored from the safety backup, the previous service is reloaded/restarted, the restored configuration is natively validated, and the durable job is marked failed. A failed rollback is surfaced explicitly; WebNAS never treats a partially applied DHCP state as successful.

`Validate Configuration` performs candidate/native validation without changing the host. `Show changes / plan` returns the structured configuration preview used before Apply.

## Kea and ISC configuration

Kea configuration is rendered as controlled JSON and uses Kea-native syntax/testing APIs where available. ISC configuration is generated as a bounded `dhcpd.conf`; arbitrary directives and includes are not accepted. Both parsers normalize discovered state into the same WebNAS DHCP model so the UI/API remain stable across backends.

## Interfaces and service control

Selectable interfaces come from operating-system discovery. A client cannot invent an interface name. The UI displays link state, MAC, IPv4 addresses, subnets and whether DHCP is enabled on that interface.

Service actions are limited to Start, Stop, Restart, Reload, Enable and Disable. The provider maps them to the known service for the detected backend (`kea-dhcp4-server` or `isc-dhcp-server` where present). No service name is accepted from HTTP requests.

## Backups and restore

Backups live under `paths.data_dir/module-backups/dhcp`. Directories are mode `0700` and files are mode `0600`. Metadata includes backend/version, timestamp, actor, description, automatic/manual flag, subnet/reservation counts, file list and SHA-256. The API returns metadata rather than an arbitrary filesystem path.

Apply creates a backup automatically. Restore creates another safety backup before touching the active configuration, verifies checksums/metadata, restores atomically, starts/reloads and validates the service, and rolls back to the pre-restore state if verification fails.

## Logs and diagnostics

Logs are selected by the backend from fixed sources such as the allowlisted Kea or ISC systemd journal. Search, severity, time window and line count are bounded. The client cannot supply a unit or log path. Secret/token/password-like values are redacted before responses and durable logs.

`Run Diagnostics` is read-only and reports PASS/WARNING/FAIL for package/backend/version, native config syntax, service state/autostart, listening interfaces and UDP/67, subnet/pool overlap, duplicate reservations, pool exhaustion/utilization, gateway validity, DNS reachability, interface availability, firewall observation, config ownership and permissions. Diagnostics do not silently change the host.

## RBAC and security

The closed permission registry includes `dhcp.view`, `dhcp.configure`, `dhcp.subnets.manage`, `dhcp.reservations.manage`, `dhcp.leases.view`, `dhcp.service.control`, `dhcp.backup`, `dhcp.restore`, `dhcp.diagnostics`, `dhcp.install` and `dhcp.uninstall`. Administrators receive full access; infrastructure operators receive the configured operational scope; auditors remain read-only. Every endpoint enforces permissions server-side.

Mutations additionally use the existing authentication session, CSRF validation, PAM confirmation policy and Activity Center audit. The implementation uses no `shell=True`, no composed shell command strings and no browser-controlled executable, service, config path or log path. Subprocess calls use fixed executable/argument arrays and bounded output. IPv4, CIDR, MAC, identifiers and enum-like options are validated by Pydantic/domain validators.

## Proxmox Safe Mode

The DHCP manifest is not Proxmox-safe. Central Safe Mode therefore blocks install/uninstall and all DHCP mutations on a Proxmox VE host by default. Read-only status, leases, diagnostics and logs remain available when their permissions allow. DHCP does not bypass or reimplement the central Safe Mode decision.

## API

The dedicated typed API is rooted at `/api/modules/dhcp` and includes status/access, subnets, reservations, leases, system interfaces, config validate/plan/apply, backups, logs, diagnostics and controlled service actions. Representative routes are:

```text
GET    /api/modules/dhcp/status
GET    /api/modules/dhcp/subnets
POST   /api/modules/dhcp/subnets
PUT    /api/modules/dhcp/subnets/{id}
DELETE /api/modules/dhcp/subnets/{id}
GET    /api/modules/dhcp/reservations
POST   /api/modules/dhcp/reservations
PUT    /api/modules/dhcp/reservations/{id}
DELETE /api/modules/dhcp/reservations/{id}
GET    /api/modules/dhcp/leases
POST   /api/modules/dhcp/leases/{id}/reservation
POST   /api/modules/dhcp/leases/{id}/hosts
GET    /api/modules/dhcp/interfaces
GET    /api/modules/dhcp/config
POST   /api/modules/dhcp/config/validate
POST   /api/modules/dhcp/config/plan
POST   /api/modules/dhcp/config/apply
GET    /api/modules/dhcp/backups
POST   /api/modules/dhcp/backups
POST   /api/modules/dhcp/backups/{id}/restore
DELETE /api/modules/dhcp/backups/{id}
GET    /api/modules/dhcp/logs
POST   /api/modules/dhcp/diagnostics
POST   /api/modules/dhcp/service/{start|stop|restart|reload|enable|disable}
POST   /api/modules/dhcp/hosts/{host_id}/reservation
```

Package installation/update/uninstall continues to use Package Center lifecycle endpoints and permissions rather than a duplicate DHCP installer API.

## Limitations

DHCP Manager is IPv4-focused; DHCPv6 is outside the current module contract. ISC DHCP is supported for existing systems but Kea DHCP4 is preferred for new installations. Native lease detail varies by distribution/backend and missing optional fields are shown as unknown rather than fabricated. Firewall diagnostics are observational unless an existing trusted firewall provider exposes a specific safe operation. DNS synchronization requires an already configured supported DNS provider. Real DHCP installation and network changes are intentionally excluded from CI: Linux commands are mocked and tests use temporary files/provider doubles only.
'''

README_SECTION = '''\n## DHCP Manager\n\nWebNAS includes an installable **DHCP Manager** for Kea DHCPv4 and existing ISC DHCP deployments. It provides transactional subnet/pool/reservation configuration, live leases and utilization, controlled service operations, diagnostics, private backup/restore, Proxmox Safe Mode, optional Pi-hole/AdGuard DNS synchronization and shared Hosts Manager identity. See [DHCP_MANAGER.md](DHCP_MANAGER.md).\n'''
MODULES_SECTION = '''\n## DHCP Manager\n\nDHCP Manager follows the dedicated infrastructure-module pattern: typed router/service code in `backend/app/modules/dhcp`, a statically registered trusted provider in `backend/app/modules/providers/dhcp.py`, Package Center lifecycle manifests, and the existing durable `package_jobs` queue. Kea DHCP4 is preferred and ISC DHCP is supported when present. Configuration is candidate-validated, planned, backed up, atomically applied, service-verified and automatically rolled back on failure. It reuses Hosts Manager identity and the public DNS provider contract rather than creating parallel registries. See [DHCP_MANAGER.md](DHCP_MANAGER.md).\n'''
INFRA_SECTION = '''\n## DHCP Manager\n\nDHCP Manager manages Kea DHCPv4 and existing ISC DHCP through the same infrastructure provider/job/RBAC architecture. It exposes typed subnets, pools, reservations, leases, utilization, interfaces, service control, diagnostics, logs and checksummed backup/restore. Apply is validate -> plan -> PAM confirmation -> backup -> atomic write -> reload/restart -> native verification, with verified rollback on failure. The module is `proxmox_safe: false`; central Safe Mode blocks mutations on Proxmox VE. DHCP-discovered systems link to the shared Hosts Manager registry, and reservation DNS synchronization can optionally use the existing Pi-hole/AdGuard public provider contract. See [DHCP_MANAGER.md](DHCP_MANAGER.md).\n'''
PACKAGE_SECTION = '''\n## DHCP Manager lifecycle\n\n`dhcp` is discovered and installed by Package Center like other trusted infrastructure modules. Kea DHCP4 is the preferred package backend for new installations; existing ISC DHCP is detected without replacing it implicitly. Install/update/uninstall use the central package executor and dedicated `dhcp.install`/`dhcp.uninstall` permissions. Runtime configuration mutations reuse `package_jobs` and Activity Center; the browser never executes a package manager. The manifest is intentionally `proxmox_safe: false`. See [DHCP_MANAGER.md](DHCP_MANAGER.md).\n'''
CHANGELOG_LINE = '- Added complete **DHCP Manager** with Kea DHCPv4/ISC detection, Package Center lifecycle, typed subnet/pool/reservation/lease management, configuration preview and native validation, atomic apply with verified backup/rollback, utilization/diagnostics/logs/service controls, granular RBAC/PAM/CSRF/audit, Proxmox Safe Mode, shared Hosts Manager identity and optional Pi-hole/AdGuard DNS synchronization.\n\n'


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def append_once(path: str, marker: str, section: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if marker not in text:
        target.write_text(text.rstrip() + "\n" + section, encoding="utf-8")


write("frontend/src/features/modules/dhcp/DhcpManagerApp.test.tsx", TEST)
write("DHCP_MANAGER.md", DOC)
append_once("README.md", "## DHCP Manager", README_SECTION)
append_once("MODULES.md", "## DHCP Manager", MODULES_SECTION)
append_once("INFRASTRUCTURE_MODULES.md", "## DHCP Manager", INFRA_SECTION)
append_once("PACKAGE_CENTER.md", "## DHCP Manager lifecycle", PACKAGE_SECTION)

changelog = ROOT / "CHANGELOG.md"
text = changelog.read_text(encoding="utf-8")
if "Added complete **DHCP Manager**" not in text:
    needle = "## Unreleased\n\n"
    if needle not in text:
        raise SystemExit("CHANGELOG Unreleased marker missing")
    changelog.write_text(text.replace(needle, needle + CHANGELOG_LINE, 1), encoding="utf-8")

version_paths = [
    "pyproject.toml",
    "backend/app/__init__.py",
    "backend/app/bootstrap.py",
    "backend/tests/test_host_info.py",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/src/features/settings/SettingsApp.tsx",
    "frontend/src/features/settings/SettingsApp.test.tsx",
]
replacements = 0
for relative in version_paths:
    target = ROOT / relative
    if not target.exists():
        continue
    current = target.read_text(encoding="utf-8")
    count = current.count("0.1.14")
    if count:
        target.write_text(current.replace("0.1.14", "0.1.15"), encoding="utf-8")
        replacements += count
if replacements < 4:
    raise SystemExit(f"unexpected version replacement count: {replacements}")
