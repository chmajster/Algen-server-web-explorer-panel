# WebNAS infrastructure modules

This document covers the Linux Updates, Docker, Pi-hole, AdGuard Home, PostgreSQL, MariaDB, Redis, Home Assistant, and Cron Manager modules, role-based access control, and desktop widgets. The shared provider and job architecture is described in [MODULES.md](MODULES.md).

Cron Manager stores stable WebNAS job metadata privately, renders only `/etc/cron.d/webnas`, applies backup-first atomic replacement with rollback, and exposes existing host entries as read-only records. It detects both `cron` and `crond`, never executes browser-supplied command text in the API, and blocks mutations under Proxmox Safe Mode. See [CRON_MANAGER.md](CRON_MANAGER.md).

## Roles and permissions

Authentication is unchanged: every session belongs to a real local Linux user authenticated through PAM. RBAC adds an authorization layer and never creates a second user database.

| Role | Default scope |
|---|---|
| `administrator` | Every WebNAS application and operation, including package lifecycle and role assignments. |
| `operator` | Module operation/configuration, Linux updates, Docker/Compose, DNS controls, database backups/restores, and Home Assistant. No role assignment or Package Center install/uninstall. |
| `auditor` | Read-only modules, updates, Docker, DNS, databases, Home Assistant, monitoring, and audit logs. |
| `user` | Files, transfers, personal settings, monitor, and personal widgets. |

Assignments are stored atomically in `paths.data_dir/rbac.json` with mode `0600`. A record can add or deny individual permissions from the closed backend list. UID 0 and members of `sudo` or `wheel` always resolve to `administrator`; an assignment cannot downgrade them. State-changing routes require session authentication, CSRF and the current user's rate-limited PAM password. Permissions are enforced in backend dependencies; hidden controls are only a usability layer.

## Linux system updates

The module supports `apt-get`, `dnf`, and `yum`. It lists candidate packages, marks security advisories, exposes apt/dnf history, and reports `/var/run/reboot-required` or `needs-restarting -r`. Metadata refresh, security-only upgrade, and full upgrade run as durable jobs. Package names are parsed by the provider and revalidated before they become arguments.

Security and full upgrades start a fixed Python worker in a server-named detached GNU `screen` session. Closing or crashing the browser cannot terminate patching. The worker keeps private `0700` session directories with `0600` output and atomically replaced state files under `paths.data_dir/linux-update-sessions`; on a WebNAS process restart, the SQLite job reconnects to the same worker instead of starting a second package manager. Running package transactions cannot be cancelled from the UI because interrupting `apt`, `dnf`, or `yum` mid-transaction is unsafe. The installer includes `screen`; existing installations that predate this feature must install that package or rerun the installer.

The manifest is not Proxmox-safe. Safe Mode rejects refresh and upgrade jobs on a detected Proxmox VE host. WebNAS never queues an automatic host restart.

## Docker and Compose

Docker uses the local Docker CLI with fixed argument arrays. It exposes containers, images, networks, volumes, one-shot statistics, bounded container logs, image pulls, and start/stop/restart operations.

The **Apps** resource is a closed catalog of official Pi-hole, AdGuard Home, and Home Assistant images. Install/update/remove operations delegate to their typed providers; a client can select only an application identifier and timezone, never an image, container name, mount, port, label, or Docker flag. Catalog containers carry an `io.webnas.app` ownership label, and a reserved name already used by an unrelated container is reported but never adopted. Removing a catalog container preserves its private data under `paths.data_dir/container-apps` (or `paths.data_dir/home-assistant`).

Pi-hole v6 receives its panel/API password through a private `0600` file mounted read-only and `WEBPASSWORD_FILE`; the password is saved through the existing private connection store and never enters the durable job payload or Docker command arguments. AdGuard Home exposes port 3000 for its first-run wizard and persistent work/config volumes. Both DNS templates bind host port 53 and therefore conflict with each other and with `systemd-resolved` or another local DNS server already using that port. Home Assistant retains the existing fixed host-network container setup.

Compose projects live under `paths.data_dir/compose/<project>/compose.yaml` with `0700` directories and `0600` files. The accepted schema intentionally excludes `build`, `privileged`, host PID/IPC, capabilities, devices, arbitrary extensions, and Docker socket mounting. Host bind mounts are restricted to `/srv`, `/mnt`, `/media`, or `paths.data_dir`; named volumes are allowed. Compose content is returned only to callers with `docker.compose`, never in the general resource list or a durable job. Jobs carry only the validated project identifier.

On apt systems the Docker module installs the distribution-common `docker.io` and `docker-compose` packages. At runtime it prefers the Compose v2 `docker compose` plugin and falls back to the standalone `docker-compose` executable, which keeps Docker installation functional on both Debian and Ubuntu repositories.

## Pi-hole and AdGuard Home

API connections accept only HTTP(S) origins resolving exclusively to private or loopback addresses. Credentials are stored in `paths.data_dir/module-config/<module>.json` with mode `0600`; read APIs return only `secret_configured`.

Pi-hole uses v6 session authentication (`POST /api/auth`) and the `X-FTL-SID` header. It reads summary statistics, domains, clients, lists and version information, and enables/disables blocking through `/api/dns/blocking`. Sessions are explicitly closed after requests.

AdGuard Home uses its `/control` API with HTTP Basic authentication. It exposes DNS statistics, clients, filters, upstreams and bounded query logs. Operators can toggle protection, refresh filters, replace bounded rule lists, update upstreams and invoke the built-in updater. Local AdGuard YAML backups are private and checksummed; restore parses YAML, stops the service, atomically replaces the file, restarts the service, and restores the previous file if restart fails.

## PostgreSQL, MariaDB and Redis

PostgreSQL uses fixed read-only queries over the local socket for databases, roles and active connection metadata. Query text is deliberately excluded. `pg_dumpall` and `psql` stream private cluster backups and restores without putting SQL, password hashes, or credentials in logs.

MariaDB uses the local socket to list schemas, users without authentication hashes, schema privileges, and a redacted replication summary. `mariadb-dump`/`mysqldump` and the local client stream all-database backups and restores.

Redis exposes INFO sections for memory, persistence, clients and statistics; bounded memory/eviction and append-only settings use `CONFIG SET`. Security status reports only whether authentication is configured, never `requirepass`. RDB backup waits for `BGSAVE` completion. Restore is limited to standard Redis/Valkey data directories, preserves ownership/mode, restarts the service, and rolls the previous RDB back if startup fails.

Database backups are stored under `paths.data_dir/module-backups/<module>`, with `0700` directories, `0600` data/metadata, SHA-256 verification and retention of the newest 20 automatic safety copies. Restore always creates a safety backup first.

## Home Assistant Container

The module uses the official stable container image and a fixed `homeassistant` container name. Configuration is stored under `paths.data_dir/home-assistant/config`. Installation does not request privileged mode, devices, D-Bus, or a Docker socket mount. Start, stop, restart and update are durable jobs. Update pulls the stable image and recreates the controlled container; if recreation fails, WebNAS starts the previous image.

Configuration backups are tar archives that contain only regular files/directories and skip links/devices. Restore validates every archive entry, stages extraction, swaps directories, and restores the previous configuration if the container cannot restart. Panel access is a direct URL: WebNAS does not proxy, bypass or retain Home Assistant authentication. HTTPS or loopback URLs are marked secure; plain non-loopback HTTP produces a diagnostic warning.

## Desktop widgets

CPU, RAM, disk, transfer, module-service and recent-alert widgets use existing authenticated resource/task/module APIs. Each user can pin/hide, move and resize them on a validated 12-column grid. Pointer controls have keyboard movement buttons. `widgets_enabled` and the six-item `desktop_widgets` layout are saved through the existing per-user settings endpoint, validated by Pydantic, and synchronized across browsers.

## Distribution limitations

- Package and systemd unit names vary across distributions; optional units degrade to unavailable rather than being invented.
- Pi-hole v6 is required for the session API. The API URL should point to the locally served version-matched API.
- AdGuard Home backup requires a recognized local configuration path.
- Database tools must be installed and local socket authentication must permit the WebNAS root service to use the administrative local account.
- Docker Engine and the Compose v2 plugin must be available; Docker Desktop is not supported on the Linux server.
- Every new infrastructure manifest has `proxmox_safe: false`, so host mutations are blocked on Proxmox VE by default.

## DHCP Manager

DHCP Manager manages Kea DHCPv4 and existing ISC DHCP through the same infrastructure provider/job/RBAC architecture. It exposes typed subnets, pools, reservations, leases, utilization, interfaces, service control, diagnostics, logs and checksummed backup/restore. Apply is validate -> plan -> PAM confirmation -> backup -> atomic write -> reload/restart -> native verification, with verified rollback on failure. The module is `proxmox_safe: false`; central Safe Mode blocks mutations on Proxmox VE. DHCP-discovered systems link to the shared Hosts Manager registry, and reservation DNS synchronization can optionally use the existing Pi-hole/AdGuard public provider contract. See [DHCP_MANAGER.md](DHCP_MANAGER.md).
