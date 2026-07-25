# WebNAS Package Center

`hosts-manager` is a regular manifest-driven Package Center module and opens in its own WebNAS window. Uninstall preserves its central registry by default because Ansible Controller and other modules retain logical host-ID references. Full data removal is a separate high-risk, explicitly confirmed operation.

Package Center is the administrator-only package and service manager built into WebNAS. It discovers trusted modules from `backend/app/modules`, validates their YAML manifests, creates a dry-run plan, and executes approved operations as durable SQLite jobs. The browser receives live progress through Server-Sent Events and falls back to polling.

Installed modules now open in the shared module-management framework documented in [MODULES.md](MODULES.md). Package Center remains the catalog/install layer and keeps its original `/api/apps` compatibility routes; `/api/modules` adds provider status, configuration, logs, diagnostics, backups, and transactional module operations.

The catalog includes the native `ansible-controller` module. Searching for Ansible, Tower or AWX finds **Ansible Automation Controller**. Package lifecycle remains in Package Center, while inventory, discovery, credentials, playbooks, templates, executions and schedules use the dedicated typed API described in [ANSIBLE_CONTROLLER.md](ANSIBLE_CONTROLLER.md). Its long operations still use `package_jobs`, redacted logs, retry/cancellation and SSE; only stable domain IDs are placed in durable payloads.

## Architecture

The backend is split into small components under `backend/app/package_center`:

- `router.py` exposes the API and enforces session, granular RBAC, CSRF, and confirmation rules.
- `models.py` defines Pydantic manifest, plan, action, source, and status models.
- `manifests.py` discovers modules and safely resolves module-local files.
- `distro.py` reads `/etc/os-release` and selects `apt-get`, `dnf`, or the `yum` compatibility fallback.
- `service.py` builds filtered package views and operation plans.
- `repository.py` stores jobs, logs, installed state, history, and sources in SQLite.
- `jobs.py` serializes execution, cancellation, retry, recovery, and audit results.
- `executor.py` builds argument arrays and runs only trusted package, systemd, and module-local actions.
- `security.py` checks authenticated sessions, RBAC (with automatic UID 0/`sudo`/`wheel` compatibility), and CSRF.

Only one package job runs at a time. A second operation for the same module cannot be queued. A running command completes before cancellation takes effect at the next safe step. Jobs left in `running` state by a WebNAS restart are marked failed with an interruption message.

## Module layout

Each production module lives in `backend/app/modules/<module_id>/`:

```text
manifest.yaml
install.py or install.sh
update.py or update.sh
uninstall.py or uninstall.sh
health.py or health.sh       # optional
config.py                    # optional, module-owned configuration logic
```

The hidden template in `backend/app/modules/example` is the recommended starting point. Copy it, change the directory and manifest `id`, and remove `ui.hidden: true` only when the module is ready. A module is trusted repository code: review it, test it, and ship it with WebNAS. GitHub sources shown in the UI are metadata only and are never downloaded or executed automatically.

## Manifest format

Example:

```yaml
id: example_service
name: Example Service
description: Short card description.
long_description: Full package detail description.
category: system_tools
version: "1.0.0"
maintainer: WebNAS
homepage: https://example.org/
icon: package
screenshots: []
license: MIT
supported_distributions: [debian, ubuntu, raspbian, fedora, rhel, rocky, almalinux]
supported_architectures: [x86_64, aarch64, armv7l]
apt_packages: [example-service]
dnf_packages: [example-service]
yum_packages: [example-service]
systemd_services: [example-service]
packages:
  apt: [example-service]
  dnf: [example-service]
  yum: [example-service]
services:
  - name: example-service
    required: true
config:
  primary_file: /etc/example-service/config.yaml
  backup_paths: [/etc/example-service]
  validation_command: []
capabilities:
  install: true
  update: true
  uninstall: true
  configure: false
  service_control: true
  reload: false
  logs: true
  diagnostics: true
  backups: false
  import_export: false
  healthcheck: true
ports: [8080/tcp]
dependencies: []
conflicts: []
permissions: [package_management, systemd, network_listen]
config_paths: [/etc/example-service/config.yaml]
data_paths: [/var/lib/example-service]
backup_paths: [/etc/example-service]
proxmox_safe: false
requires_reboot: false
requires_root: true
configurable: false
removable: true
healthcheck: health.py
ui:
  hidden: true
changelog:
  - Initial module.
```

Identifiers, package names, service names, ports, architectures, paths, healthcheck names, and GitHub refs are validated. Manifest paths must be absolute and traversal-free. Hook filenames are fixed and resolved inside the module directory; a manifest cannot point to an arbitrary script. Do not add shell commands, secrets, or user-provided values to a manifest.

## Execution and security

Installation, update, and removal require their dedicated module permission, a valid CSRF token, and explicit plan confirmation. Provider resource/operation routes use their narrower RBAC permissions. The authenticated administrator session is sufficient and the UI neither requests nor retains a second administrator password.

The executor uses `subprocess` argument arrays with `shell=False`, a restricted environment, timeouts, exit-code checks, and redacted output. It never runs `upgrade`, `dist-upgrade`, or implicit `autoremove`. Removal preserves configuration and user data unless the administrator explicitly selects **also remove data** in the confirmation dialog. SQLite transactions provide atomic state updates, and every completed, failed, or cancelled operation is written to history and the audit log.

Network-facing daemons should use a dedicated unprivileged service account. For example, the bundled Syncthing hook creates a hardened `webnas-syncthing.service` running as `webnas`, with its writable area limited to `/var/lib/webnas/syncthing`; it never runs Syncthing as root.

The production service runs as root because PAM impersonation and package managers need it. `ProtectSystem=false` is therefore required in the systemd unit for package database and filesystem writes. The risk is constrained by admin/PAM/CSRF gates, validated manifests, fixed action allowlists, no frontend commands, no `shell=True`, and no execution of external source code.

Configuration changes remain module-specific. The Samba provider creates a private checksummed backup, validates with `testparm`, writes with `fsync` and atomic replacement, reloads and checks the real service/config state, and restores both config files when any later stage fails. New configurable modules must follow the same backup/validate/atomic-replace/verify/rollback pattern. Manifest validation commands select a fixed backend adapter and cannot contain arbitrary shell commands.

## Supported systems and Proxmox

WebNAS recognizes Debian, Ubuntu, Raspberry Pi OS, Fedora, RHEL, Rocky Linux, and AlmaLinux using `/etc/os-release`. The module must list the detected distribution or a matching `ID_LIKE`, the current architecture, and packages for the selected manager. An unsupported system or missing manager is rejected before queueing.

On Proxmox VE hosts, Safe Mode blocks every module whose manifest has `proxmox_safe: false`. This decision is included in list results and the plan. A module may be marked safe only after proving that its packages, services, ports, configuration, and data paths cannot affect the hypervisor, cluster, storage, guests, or host networking.

## Storage, logs, and backup

The default package database is:

```text
/var/lib/webnas/package-center.sqlite3
```

It contains `package_jobs`, `package_job_logs`, `installed_packages`, `package_history`, and `package_sources`. Back up this file while WebNAS is stopped or by using the SQLite online backup mechanism. Job output is available through the jobs/logs API and the Package Center UI. Service-level logs remain in `journalctl -u webnas`.

Module configuration is not stored in the package database. Back up each manifest's `config_paths`, `data_paths`, and `backup_paths` before system migration. Samba module backups are stored under `paths.data_dir/module-backups/samba` with a `0700` directory and `0600` files. They include `smb.conf`, the WebNAS-managed share config, metadata, and a combined checksum, but deliberately exclude Samba password databases. Automatic backup retention is 20.

## API

Read operations require an authenticated session and their view permission. System mutations additionally require CSRF, the concrete operation permission, and plan confirmation.

```text
GET    /api/apps
GET    /api/apps/categories
GET    /api/apps/installed
GET    /api/apps/updates
GET    /api/apps/{module_id}
GET    /api/apps/{module_id}/logs
GET    /api/apps/{module_id}/config
PUT    /api/apps/{module_id}/config
POST   /api/apps/{module_id}/plan?action=install|update|uninstall|start|stop|restart
POST   /api/apps/{module_id}/install
POST   /api/apps/{module_id}/update
POST   /api/apps/{module_id}/uninstall
POST   /api/apps/{module_id}/start
POST   /api/apps/{module_id}/stop
POST   /api/apps/{module_id}/restart

GET    /api/apps/jobs
GET    /api/apps/jobs/{job_id}
GET    /api/apps/jobs/{job_id}/events
POST   /api/apps/jobs/{job_id}/cancel
POST   /api/apps/jobs/{job_id}/retry
GET    /api/apps/history

GET    /api/apps/sources
POST   /api/apps/sources
PUT    /api/apps/sources/{source_id}
DELETE /api/apps/sources/{source_id}
POST   /api/apps/sources/{source_id}/sync
```

`GET /api/apps` accepts `search`, `category`, `status`, `compatible_only`, `installed_only`, and `updates_only`. Existing Samba configuration and legacy StorePlugin endpoints remain available.

The module-management endpoints are listed in [MODULES.md](MODULES.md). Legacy Samba mutation endpoints use the same session, RBAC, CSRF, and confirmation checks and delegate writes/service actions to durable module jobs; they can no longer bypass the provider transaction.

## Manual verification

1. Install WebNAS on a supported disposable VM or container, then log in with a local `sudo`/`wheel` administrator.
2. Open **Centrum pakietów**, search for Nginx, filter by category and open its details.
3. Select **Install**, review packages, services, ports, permissions, and warnings, then confirm the operation.
4. Watch progress and logs in **Jobs**, reload the browser, and verify the job remains visible.
5. Stop, start, and restart the service from the module card. Verify the systemd status shown by WebNAS.
6. Cancel a queued job and retry a failed/cancelled job.
7. Uninstall without data removal and verify configuration/data remain. Test explicit data removal only on disposable data.
8. Restart `webnas` during a disposable job and verify it appears as failed/interrupted in history.
9. Add a GitHub source, edit its branch, refresh metadata, copy its Codex instruction, disable it, and remove it. Confirm no repository code is executed.
10. On a Proxmox host with Safe Mode enabled, verify unsafe modules show as blocked and cannot be planned or queued.
