# Changelog

All notable changes to WebNAS are documented in this file.

The format follows the spirit of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses date-based unreleased entries until tagged releases are introduced.

## [Unreleased] - 2026-07-14

### Added

- Modern NAS-style desktop UI with app icons, draggable/resizable windows, taskbar, notification center, light/dark mode, responsive layout, keyboard shortcuts, and context menus.
- File Manager window with an expanded explorer experience:
  - lazy-loaded directory tree;
  - resizable tree panel;
  - backend-driven table sorting;
  - backend-driven pagination capped at 20 items per page;
  - backend-driven quick filtering;
  - breadcrumbs, selection bar, skeleton loading, empty states, and persisted view settings.
- Persistent rsync transfer manager backed by SQLite:
  - queueing and priorities;
  - pause/resume where possible;
  - cancellation;
  - retry;
  - history;
  - filters;
  - detailed status, command preview, exit code, stderr tail, average speed, file counts, and timestamps.
- Server resource dashboard with CPU, RAM, swap, disk, allowed root usage, uptime, load average, service status, warnings, and admin/user scoping.
- Safe local user management panel for admins, including user creation, lock/unlock, password reset, group membership, home directory creation, quota support, and audit logging.
- App Store/module system with manifests, admin-only actions, background jobs, dry-run support, logs, configuration API, and persistent state.
- Complete modular Package Center replacing Samba-only package actions:
  - Pydantic-validated YAML manifests and safe module-local hooks;
  - Debian/Ubuntu/Raspberry Pi OS/Fedora/RHEL/Rocky/Alma detection with `apt-get`, `dnf`, and `yum` fallback;
  - dry-run plans covering packages, services, ports, paths, permissions, conflicts, reboot needs, and Proxmox compatibility;
  - durable SQLite jobs, log streaming over SSE, polling fallback, cancellation, retry, interruption recovery, history, and a global execution limit;
  - administrator, CSRF, PAM reauthentication, audit, secret redaction, timeout, and argument-array execution controls;
  - package catalog, detail view, filters, installed/updates/jobs/history/source tabs, progress UI, responsive light/dark styling, and Polish/English translations;
  - GitHub source metadata management without downloading or executing untrusted repository code.
- Initial validated Package Center modules for Samba, Squid Proxy, Nginx, and Syncthing, plus a hidden authoring template.
- Package Center architecture and authoring guide in `PACKAGE_CENTER.md`.
- Samba module for the App Store:
  - `samba` and `smbclient` installation without `apt upgrade`;
  - `smb.conf` backup before changes;
  - share configuration with validation;
  - `testparm` validation before applying config;
  - `smbd`/`nmbd` service control;
  - `smbpasswd` support without exposing passwords in logs or command previews.
- Network Mounts module:
  - SMB/CIFS, NFS, SSHFS, and WebDAV mount definitions;
  - SQLite-backed configuration;
  - credentials stored outside the database in `0600` files;
  - mount/unmount/remount/test background jobs;
  - persistent systemd mount and automount unit generation;
  - safe dry-run previews;
  - File Manager integration;
  - read-only mount write protection.
  - a single administrator-only **Settings → Network resources** interface with dynamic SMB/NFS/SSHFS/WebDAV create and edit forms;
  - fixed mount locations under `/mnt/webnas/mnt/<name>`, normalized-name uniqueness, traversal/symlink protection, and client `mount_point` rejection;
  - real operating-system status reconciliation, filesystem capacity only for active mounts, and a minimal user-filtered `/api/mounts/roots` endpoint;
  - user, owner, primary-group, and supplementary-group access checks plus automatic shared Explorer refresh;
  - path-derived systemd mount/automount unit names, legacy definition migration, rename rollback, per-definition operation locks, and safe uninstall cleanup;
  - atomic secret updates, blank-password preservation, explicit secret removal, stricter option allowlisting, missing-package reporting, and disabled unsafe SSHFS password mode.
- Full GitHub Actions pipeline for backend, frontend, security scans, shell scripts, and packaging checks.
- Proxmox Safe Mode guards for protected paths, services, users/groups, storage paths, and admin operations.
- Additional backend and frontend tests covering transfers, path policy, security/session/CSRF, file operations, resource dashboard, Proxmox guards, app store, network mounts, and file listing.

### Changed

- File listing API now supports:
  - `sort`;
  - `direction`;
  - `page`;
  - `page_size`;
  - `folders_first`;
  - `filter`.
- File listing responses now include pagination metadata, current/parent paths, directory permissions, item capability flags, symlink metadata, MIME/type fields, and modification timestamps.
- File operations now check read-only network mounts before write operations.
- Allowed roots can include user-visible WebNAS network mount points.
- The legacy Network Mounts `AppId` is retained only for saved-window compatibility and redirects to Settings; its separate launcher shortcut was removed.
- Installer, update, uninstall, packaging, and service files were expanded for safer install/update flows and systemd operation.
- The systemd service now explicitly runs as root with a writable system tree so validated package-manager operations can complete; other process hardening remains enabled.
- Authenticated file workers now retain writable access to allowed home directories; directory capability flags are calculated after dropping to the logged-in user's UID instead of from the root service process.
- README, install, security, and example configuration documentation were expanded for the new operational surface.

### Security

- Added stricter mount path validation and blocked critical system paths such as `/`, `/etc`, `/boot`, `/usr`, `/var/lib/vz`, `/etc/pve`, `/proc`, `/sys`, `/dev`, `/run`, and `/tmp`.
- Added audit logging for denied path-policy attempts outside `allowed_roots`.
- Added validation for Samba share names, users, comments, masks, mount options, mount names, hosts, and remote paths.
- Blocked unsafe mount options such as `suid`, `dev`, `exec`, `allow_other`, and inline credentials.
- Avoided `shell=True` for mount/app-management command execution.
- Package Center accepts no command strings from the frontend, validates package/service/path identifiers, confines hooks to module directories, restricts subprocess environments, uses timeouts, and redacts secrets from persisted output.
- Prevented plaintext mount secrets from being stored in SQLite, logs, dry-run previews, or command-line arguments.

### Notes

- Local backend test execution on the current Windows workspace requires a real Python installation. The existing `python` command resolves to the Microsoft Store alias in this environment.
