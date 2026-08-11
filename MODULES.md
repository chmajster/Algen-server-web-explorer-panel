# WebNAS module-management framework

The `apmid` module is a zero-package, Proxmox-safe administration module with a
dedicated application and private SQLite domain. Manifest installation state
and `/api/modules/apmid/access` jointly control launcher visibility, including
access granted by per-APMID membership. See [APMID.md](APMID.md).

WebNAS modules extend the existing Package Center. A module is discovered from a validated repository-owned manifest, installed by the existing package executor, and tracked in the existing SQLite database. The module-management layer adds a controlled provider, a common API, and a shared application shell. It does not load executable providers from uploaded manifests or third-party metadata.

Cron Manager is the native scheduled-task module. It uses a dedicated typed router and provider, the shared durable package-operation queue for mutations, Identity RBAC/CSRF/PAM and Activity Center audit. It owns only `/etc/cron.d/webnas`; system and user cron entries are discovered as read only. See [CRON_MANAGER.md](CRON_MANAGER.md).

Samba is the reference infrastructure implementation. Ansible Automation Controller is the reference complex application module with a dedicated versioned domain database, typed router and app-shell sections; see [ANSIBLE_CONTROLLER.md](ANSIBLE_CONTROLLER.md). **Repozytoria systemowe** follows the same dedicated-domain pattern for APT/RPM content, immutable publications, its hardened HTTP service, and a Hosts Manager capability; see [OS_REPOSITORIES.md](OS_REPOSITORIES.md). Nginx, Squid Proxy, and Syncthing use the generic shell for the capabilities their manifests declare and can gain dedicated providers without changing Package Center, window persistence, or the job schema.

The Ansible provider is registered explicitly like every trusted provider. Its install/update/uninstall operations use the standard plan and job paths. Domain operations enqueue the existing `manage` action with object identifiers only, and `/api/modules/ansible-controller` enforces the closed granular RBAC registry. This pattern is preferred when a module needs substantial domain APIs without growing the generic `modules/router.py`.

## Architecture

```text
backend/app/modules/<id>/manifest.yaml
             │
             ▼
package_center.manifests + Pydantic validation
             │
             ├── package_center.service/executor  install/update/uninstall
             ├── package_center.jobs/repository  durable queue, logs, result
             └── modules.providers               status/config/log/diagnostic/backup adapters
                              │
                              ▼
                     /api/modules endpoints
                              │
                              ▼
frontend/features/modules/common + module-specific application
```

`ModuleProvider` is the controlled adapter boundary. The base provider implements status, declared systemd service actions, journal logs, generic diagnostics, capability checks, typed resource names and typed management actions. It accepts only services declared by the manifest and only fixed action enums. `SambaProvider` adds typed Samba configuration, while the infrastructure providers add controlled package, Docker, private HTTP API, database-socket and container adapters.

Long operations reuse `package_jobs`; no second queue exists. The repository automatically adds `warnings_json` and `result_json` to older databases. Existing rows, history, installed-module records, and `/api/apps` endpoints remain valid.

Docker is intentionally routed through the stricter dedicated API and split frontend described in [CONTAINERS_MANAGER.md](CONTAINERS_MANAGER.md). Generic module actions cannot be used to bypass Docker's typed contracts, granular permissions, exact confirmations or PAM gates.

## Manifest

New manifests can use the structured fields below. Legacy `apt_packages`, `dnf_packages`, `systemd_services`, `config_paths`, and `backup_paths` are mapped automatically.

```yaml
id: samba
name: Samba / Windows File Sharing
version: "1.0.0"
category: file_sharing
description: SMB/CIFS file sharing
icon: share-2
homepage: https://www.samba.org/
license: GPL-3.0-or-later
proxmox_safe: true

packages:
  apt: [samba, smbclient]
  dnf: [samba, samba-client]
  yum: [samba, samba-client]

services:
  - name: smbd
    required: true
  - name: nmbd
    required: false

config:
  primary_file: /etc/samba/smb.conf
  backup_paths: [/etc/samba/smb.conf, /etc/samba/algen-shares.conf]
  validation_command: [testparm, -s]

capabilities:
  install: true
  update: true
  uninstall: true
  configure: true
  service_control: true
  reload: true
  logs: true
  diagnostics: true
  backups: true
  import_export: true
  healthcheck: true
  resources: [shares, sessions]
  actions: [refresh]
```

Package names, service names, ports, identifiers, architectures, and absolute paths are validated. `validation_command` is not a shell command facility: it must match a backend-supported adapter exactly. The current adapters are `testparm -s`, `nginx -t`, `squid -k parse`, and the non-mutating Syncthing version check. Unknown commands are rejected while loading the manifest.

Capabilities are enforced by both routing and providers. A hidden button is not a security boundary; calling an unsupported operation directly returns `CAPABILITY_NOT_SUPPORTED`.

## Unified data contracts

Every provider returns a `ModuleStatus` containing installation and available versions, update state, service state/autostart, per-service details, configuration validity, health, the latest action/time/error, and module metrics. Health is one of:

```text
healthy  degraded  failed  unknown  not_installed
```

Jobs expose the old fields and the module aliases `operation`, `stage`, and `requested_by`, plus durable warnings and a structured result. Status is `queued`, `running`, `completed`, `failed`, or `cancelled`. SSE sends complete job snapshots; polling remains a fallback.

## API

Read routes require the module-specific view permission. Mutations require an authenticated session, their granular operation/configuration/install/backup/restore permission, CSRF, and explicit confirmation where applicable. Existing root/sudo/wheel users always resolve to administrator.

```text
GET    /api/modules
GET    /api/modules/{module_id}
GET    /api/modules/{module_id}/status
GET    /api/modules/{module_id}/resources/{resource}
GET    /api/modules/{module_id}/connection
GET    /api/modules/{module_id}/config
GET    /api/modules/{module_id}/logs
GET    /api/modules/{module_id}/diagnostics
GET    /api/modules/{module_id}/backups

POST   /api/modules/{module_id}/install
POST   /api/modules/{module_id}/update
POST   /api/modules/{module_id}/uninstall
POST   /api/modules/{module_id}/validate
POST   /api/modules/{module_id}/apply
POST   /api/modules/{module_id}/diagnostics
POST   /api/modules/{module_id}/service/{start|stop|restart|reload|enable|disable}
POST   /api/modules/{module_id}/actions/{operation}
PUT    /api/modules/{module_id}/connection
POST   /api/modules/{module_id}/backups
POST   /api/modules/{module_id}/backups/{backup_id}/restore
DELETE /api/modules/{module_id}/backups/{backup_id}
GET    /api/modules/{module_id}/jobs/{job_id}/events
GET    /api/modules/docker/compose/{project}
PUT    /api/modules/docker/compose/{project}
```

Samba-specific controlled routes:

```text
GET    /api/modules/samba/users
POST   /api/modules/samba/users/{username}/{add|password|enable|disable|remove}
GET    /api/modules/samba/sessions
GET    /api/modules/samba/shares/{share_name}/test
DELETE /api/modules/samba/shares/{share_name}
POST   /api/modules/samba/import/validate
GET    /api/modules/samba/firewall
POST   /api/modules/samba/firewall/open
```

The firewall adapter supports only `ufw allow Samba` or firewalld's predefined Samba service plus reload. An unknown firewall produces instructions/status and no command. The API never accepts a service name, command, executable, or config path from the browser.

## Samba configuration transaction

The source of truth for WebNAS-managed shares remains the compatible Samba state JSON and `/etc/samba/algen-shares.conf`, included from `/etc/samba/smb.conf`. Existing share definitions load with defaults for newly added fields.

Applying configuration follows this sequence:

1. Parse the typed global/share model and enforce path policy, protected roots, Proxmox Safe Mode, masks, users/groups, conflicts, and closed option/VFS allowlists.
2. Render a candidate and run `testparm -s` through the controlled adapter.
3. Return added/changed/removed shares, global changes, directory/permission changes, warnings, and validator output for review.
4. Require CSRF, plan confirmation, PAM, and a separate SMB1 risk acknowledgement when `NT1` is selected.
5. Create a private automatic backup.
6. Prepare explicitly requested directories/permissions, update the managed include atomically, and atomically replace the managed config with `fsync` plus `os.replace`.
7. Reload `smbd`, verify `systemctl is-active`, and rerun `testparm` against the applied file.
8. Write compatible state and audit history only after verification.
9. On any write/reload/post-validation failure, restore both backed-up files, reload again, mark the durable job failed, and retain the rollback message in its redacted log.

SMB1 is off by default. `wide links`, `follow symlinks`, anonymous write, and missing interface restrictions produce visible warnings. Arbitrary Samba lines, includes, pre/post-exec commands, paths, and VFS modules are not accepted.

## Samba shares and accounts

The share model covers visibility, guest/read-only access, users, groups, write/admin lists, inherited permissions, masks, force user/group/modes, controlled VFS objects, recycle bin/versioning, veto patterns, and optional directory preparation. Protected roots include `/`, `/etc`, `/boot`, `/dev`, `/proc`, `/sys`, `/run`, `/root`, `/etc/pve`, `/var/lib/vz`, and `/mnt/pve`; the normal allowed-root and Proxmox policies still apply after symlink resolution.

Removing sharing deletes only the share definition through a validated apply job. It never deletes the directory. File Manager shows the share name and read-only state, opens the matching editor, creates a prefilled share for an unshared directory, and offers confirmed removal for an existing share.

SMB account actions call `smbpasswd` with argument arrays and stdin, never `shell=True`. Passwords are neither returned nor put in command lines, plans, logs, SQLite, settings, or local storage. Removing an SMB user uses `smbpasswd -x`; it never removes the Linux account.

Sessions prefer `smbstatus --json` and use a tested text parser when JSON is unavailable. Session termination is deliberately not exposed.

## Logs, diagnostics, and firewall

The log provider has a fixed source list for `journalctl -u smbd/nmbd/winbind` and existing standard files under `/var/log/samba`. It caps line count at 1,000 and response content at 512 KiB, supports search/level filters, and redacts password/token/secret patterns. A client cannot submit a log path.

Diagnostics are durable jobs. Samba checks packages/version, `testparm`, generated config, service state/autostart, ports 139/445, interface restriction, firewall adapter, share paths/modes/free space/symlinks, SMB1, anonymous write, duplicate names, and stale Samba accounts. Reports are advisory; WebNAS does not silently repair the host.

## Backups and uninstall

Samba backups live under `paths.data_dir/module-backups/samba`, outside user roots. Directories are mode `0700`; config and metadata files are mode `0600`. A backup contains the main and WebNAS-managed config, version, timestamp, actor, description, file list, size, and a combined SHA-256 checksum. Password databases under `/var/lib/samba/private` are intentionally excluded. The API returns metadata, never a static file URL. The newest 20 automatic backups are retained; manual backups are not removed by that policy.

The uninstall wizard shows active shares/sessions, packages, services, config paths, warnings, and the backup option. It offers packages only, packages plus WebNAS config, or packages/config/internal module data. The last choice requires typing `Samba`. Shared directories are not manifest data paths and are never removed. Package removal is verified with `dpkg-query` or `rpm` when available instead of trusting only the package command's exit code.

## Adding a provider

A minimal provider can use the safe base implementation:

```python
from app.modules.providers.base import ModuleProvider


class ExampleProvider(ModuleProvider):
    def __init__(self, actor: str = "root") -> None:
        super().__init__("example")
        self.actor = actor

    # Override only declared capabilities. Parse into typed data, build
    # structured validation feedback, and keep all commands/paths backend-owned.
```

Register the provider in `backend/app/modules/providers/__init__.py`, add its validated manifest, expose only required typed frontend sections, and add parser/provider/API/component tests. Do not dynamically import a class named by a manifest.

## Author security checklist

- [ ] All module, package, service, path, option, and action values are enums/allowlists or validated typed fields.
- [ ] No provider uses `shell=True`, concatenated shell commands, client-supplied executables, client-supplied service names, or client-supplied config/log paths.
- [ ] Every mutation enforces session, administrator, CSRF, rate-limited PAM, confirmation, and audit.
- [ ] Passwords/tokens are never persisted or echoed; logs and errors are redacted and bounded.
- [ ] Proxmox Safe Mode and the central path policy are called rather than reproduced or bypassed.
- [ ] Apply is validate → backup → atomic write → service action → real state check → rollback on failure.
- [ ] Backups are checksummed, private, metadata-only through the API, and exclude unnecessary secret stores.
- [ ] Uninstall does not include user-created/shared paths and verifies actual package/service state.
- [ ] Jobs survive browser/backend restarts and expose meaningful stages/results.
- [ ] Linux commands are mocked in tests; CI never installs packages or changes the test host.
- [ ] Polish and English keys, responsive layout, keyboard operation, focus, and ARIA state are covered.

## Distribution notes

Package names differ between apt and RPM families, optional services such as `nmbd`/`winbind` may be absent, systemd unit naming can vary, and Samba versions differ in `smbstatus --json` support. The manifest carries apt/dnf/yum mappings and required/optional services; providers must degrade cleanly when optional tools are unavailable. Firewall automation is limited to UFW and firewalld. WebNAS does not attempt to manage an unknown firewall.
