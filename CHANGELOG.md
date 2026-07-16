# Changelog

All notable changes to WebNAS are documented in this file.

The format follows the spirit of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses date-based unreleased entries until tagged releases are introduced.

## [Unreleased] - 2026-07-16

### Added

- Activity Center with a durable structured timeline for sign-ins, file operations, user configuration changes, administrative tasks, network-resource changes, RBAC assignments, and queued/completed/failed module jobs. Regular users are restricted to their own events, while `audit.view` grants global user/category/status/search filters; stored metadata is bounded and recursively redacted for credentials and tokens.
- Granular RBAC layered over PAM/local Linux users, with `administrator`, `operator`, `auditor`, and `user` roles, closed application/operation permissions, atomic private assignments, administrator compatibility for root/sudo/wheel, backend enforcement, and a role-management application.
- Linux Updates module with apt/dnf/yum package and security-update discovery, operation history, restart-required detection, durable metadata/security/full update jobs, PAM/CSRF enforcement, and Proxmox Safe Mode blocking.
- Linux Updates `Update` action backed by a server-generated detached GNU `screen` session, private atomic worker state/log files, safe reconnection after a WebNAS process restart, and continued patching when the browser is closed or disconnected.
- Docker module with containers, images, networks, volumes, logs, one-shot statistics, lifecycle actions, image updates, and a restricted private Docker Compose store/editor that rejects privileged/host-control configuration.
- Pi-hole v6 API module with session authentication, statistics, domains, clients, lists, version data and blocking control; and AdGuard Home with DNS dashboard, clients, filters, upstreams, query log, API operations, updates and transactional configuration backups.
- PostgreSQL and MariaDB modules with database/user/connection-or-privilege views, streamed private backups/restores, logs, service controls, replication summary and diagnostics without credential logging.
- Redis module with memory, persistence, limits, clients, statistics, RDB backups/restores, bounded configuration controls and secret-free security diagnostics.
- Home Assistant Container module with controlled non-privileged installation, lifecycle, logs, stable-image update rollback, safe configuration archives and direct authenticated panel access.
- Per-user desktop widgets for CPU, RAM, disks, active transfers, module services and recent alerts, including pin/hide, pointer and keyboard movement, resizing, responsive display, and server-synchronized validated layouts.
- Backend/frontend coverage and `INFRASTRUCTURE_MODULES.md` for the new providers, RBAC, secret handling, safe Compose schema, backup/restore behavior, widgets, Proxmox policy and distribution limitations.

- Shared provider-based module-management framework extending the existing Package Center:
  - structured `packages`, required/optional `services`, controlled `config`, and `capabilities` manifest sections with automatic mapping of legacy manifests;
  - unified module status/health contracts and administrator-only `/api/modules` routes for lifecycle, service actions, config validation/apply, logs, diagnostics, backups, restore, and SSE job events;
  - durable job warnings/results and idempotent SQLite column migration without replacing existing jobs/history;
  - common module application shell, headers, health cards, service controls, job progress, structured apply plans, logs, diagnostics, backups, danger zone, and uninstall wizard;
  - installed-module windows and enhanced Package Center cards showing versions, service/health/update state, active jobs, and last errors.
- Complete Samba reference provider and application:
  - overview, shares, SMB users, active sessions, global configuration, services, fixed-source logs, diagnostics, private backups, firewall adapter, and module information;
  - safe share editor with access/permission groups, users/groups, masks, force modes, controlled VFS objects, recycle/versioning, path tests, duplication, enable/disable, and File Manager opening;
  - JSON and text `smbstatus` parsers, controlled `smbpasswd` account actions, closed global option validation, SMB1 acknowledgement, and UFW/firewalld plans;
  - combined checksummed backups for main and managed config, `0600` storage, retention of 20 automatic copies, verified restore, and automatic safety backup;
  - transactional candidate validation, atomic writes, reload/state/post-validation checks, and automatic rollback of both config files;
  - File Manager share name/read-only badges plus create/open/remove-share actions that never delete the local directory;
  - deduplicated actionable module notifications for jobs, updates, invalid config, service failure, diagnostics, restore failure, and rollback.
- `MODULES.md` provider/API/Samba architecture guide with a minimal provider and author security checklist.
- Backend and frontend coverage for manifest compatibility/command rejection, auth rate limiting, parsers, validation, log redaction, backup checksum/retention, rollback, repository migration, real post-state checks, common module UI, share editing, plan confirmation, jobs, diagnostics, backups, admin visibility, and dirty-window close confirmation.

- Complete WebNAS desktop modernization with an independently branded Windows 11-inspired visual language:
  - one bottom taskbar replacing the separate top system bar and old taskbar;
  - searchable Start menu with pinned/all-app sections, administrator badges, user identity, and sign-out;
  - pinned/running/active app states, transfer and notification indicators, theme control, session menu, and localized clock/date;
  - column-flow desktop shortcuts, optional welcome widget, per-user wallpaper and four fit modes;
  - active/inactive window styling, title-bar controls, optional transparency/animations, viewport clamping, resize handling, and narrow-screen fullscreen behavior.
- Full Settings application with category sidebar, mobile category selector, settings search, optimistic automatic saves, debounced wallpaper input, save status, and rollback on errors.
- Server-validated per-user preferences for system startup, personalization, File Manager, transfers, notifications, accessibility, language/region, and desktop behavior. Legacy partial JSON files receive safe defaults without manual migration and writes remain atomic.
- Account details and current-password-protected password change in Settings, plus administrator-only Network resources, service/update/Proxmox information, automatic update control, and links to dedicated administration apps.
- Modular frontend style system under `frontend/src/styles/` for tokens, base/accessibility, desktop, windows, taskbar, Settings, File Manager, and responsive rules.
- Tests for user-setting defaults, legacy file compatibility, validation, atomic per-user persistence, hidden-file listing, Settings search, theme/taskbar changes, wallpaper rendering, File Manager preferences, hidden shortcuts, disabled animations, Start menu behavior, and administrator-only sections.

- Modern NAS-style desktop UI with app icons, draggable/resizable windows, taskbar, notification center, light/dark mode, responsive layout, keyboard shortcuts, and context menus.
- File Manager window with an expanded explorer experience:
  - lazy-loaded directory tree;
  - resizable tree panel;
  - backend-driven table sorting;
  - backend-driven pagination configurable at 25, 50, 100, or 200 items per page;
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
- Near-real-time Linux resource monitor with lock-protected `/proc` deltas, per-core CPU, RAM/swap, filesystem and disk I/O, network interfaces, temperature, alerts, 60-sample SVG histories, configurable polling, and admin-only mount/process details. Filesystems are grouped by device identity and regular users only receive metrics for allowed roots.
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

### Fixed

- Accessibility interface scale and larger-text settings now resize typography consistently across the desktop. Scale options submit numeric values instead of percent-suffixed strings, fixed pixel font sizes use scalable `rem` units, and taskbar/title-bar dimensions receive browser-compatible precomputed values.
- Modal forms now retain the active input, cursor position, and entered value while parent views refresh; Escape handling still uses the latest close callback without restarting the focus trap.
- Dialogs are portaled to the desktop overlay layer, preventing small application windows and their overflow rules from clipping forms, footers, or scrolling content.
- Primary and dangerous action buttons now keep complete semantic foreground/background colors with sufficient cascade priority, preventing invisible white labels on light component surfaces, including Package Center cards and modal footers.

### Changed

- File listing API now supports:
  - `sort`;
  - `direction`;
  - `page`;
  - `page_size`;
  - `folders_first`;
  - `filter`.
- File listing now supports validated `show_hidden` filtering and page sizes up to 200 so per-user File Manager preferences are enforced by the backend.
- File Manager command bar, navigation/path/search areas, location sidebar, detail/icon views, selection, context menu, and status bar now share the desktop visual system.
- File listing responses now include pagination metadata, current/parent paths, directory permissions, item capability flags, symlink metadata, MIME/type fields, and modification timestamps.
- File operations now check read-only network mounts before write operations.
- Allowed roots can include user-visible WebNAS network mount points.
- The legacy Network Mounts `AppId` is retained only for saved-window compatibility and redirects to Settings; its separate launcher shortcut was removed.
- Installer, update, uninstall, packaging, and service files were expanded for safer install/update flows and systemd operation.
- The systemd service now explicitly runs as root with a writable system tree so validated package-manager operations can complete; other process hardening remains enabled.
- Authenticated file workers now retain writable access to allowed home directories; directory capability flags are calculated after dropping to the logged-in user's UID instead of from the root service process.
- README, install, security, and example configuration documentation were expanded for the new operational surface.

### Security

- Closed the legacy Samba configuration/service paths so they use rate-limited PAM and durable provider jobs rather than bypassing the module transaction.
- Module operations accept only provider-owned services, commands, log sources, config paths, firewall adapters, Samba options, and VFS objects; subprocesses continue to use argument arrays with `shell=False`.
- Samba log responses are redacted, limited to 1,000 lines and 512 KiB, and never accept a client path. Backups are private metadata-only resources and exclude password databases.
- Destructive Samba uninstall distinguishes package/config/internal-state removal, creates an optional backup, requires typing `Samba` for internal data removal, verifies package removal, and excludes every share path.

- Added stricter mount path validation and blocked critical system paths such as `/`, `/etc`, `/boot`, `/usr`, `/var/lib/vz`, `/etc/pve`, `/proc`, `/sys`, `/dev`, `/run`, and `/tmp`.
- Added audit logging for denied path-policy attempts outside `allowed_roots`.
- Added validation for Samba share names, users, comments, masks, mount options, mount names, hosts, and remote paths.
- Blocked unsafe mount options such as `suid`, `dev`, `exec`, `allow_other`, and inline credentials.
- Avoided `shell=True` for mount/app-management command execution.
- Package Center accepts no command strings from the frontend, validates package/service/path identifiers, confines hooks to module directories, restricts subprocess environments, uses timeouts, and redacts secrets from persisted output.
- Prevented plaintext mount secrets from being stored in SQLite, logs, dry-run previews, or command-line arguments.

### Notes

- Local backend test execution on the current Windows workspace requires a real Python installation. The existing `python` command resolves to the Microsoft Store alias in this environment.
