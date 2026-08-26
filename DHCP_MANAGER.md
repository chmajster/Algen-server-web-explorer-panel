# DHCP Manager

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
