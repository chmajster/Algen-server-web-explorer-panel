# Changelog

## Unreleased

## v0.1.30 — 2026-08-30

- Expanded Storage Manager with complete read-only diagnostics and brokered advanced probes.
- Added application-owned Local database authentication as the default, optional PAM/LDAP system authentication, provider-aware sessions, local user administration, POSIX companion mappings, LDAP security controls, and installer bootstrap support.
- Hardened release/update activation so release helpers reliably re-exec inside the candidate virtualenv, including symlinked Python launchers, and added an HTTP-safe clipboard fallback for copying update error details.
- Added Firewall Manager, Security Center and Network Tools with granular RBAC/audit, typed privileged firewall operations, serialized backup/apply/verify/rollback transactions, normalized UFW/firewalld/nftables handling, non-destructive posture scanning, and bounded network diagnostics.
- Added central Job Queue Manager, NTP Manager, Routing Manager, Login History and GitOps Config Manager with privileged-broker integration, safe routing transactions/rollback, authentication-event correlation, secret-safe GitOps workflows, frontend applications, generated OpenAPI contracts and regression coverage.
- Hardened infrastructure manager error boundaries and Job Queue lifecycle: unexpected NTP/routing failures no longer expose exception details, and permanent queue workers are explicitly managed daemon threads so unit/integration processes shut down deterministically.

## v0.1.29 — 2026-08-30

- Added Offline Repository Manager to `os-repositories`: Full/Selected/Delta `.tar.zst` bundles, dependency closure, controlled staging and hardened verification/import, durable offline jobs with SSE/retry/cancel, Air-Gapped Mode enforcement, granular offline RBAC, Hosts Manager group target generation, storage/retention/pinning/freeze/diagnostics, a complete React workflow, generated OpenAPI updates, tests, and operational documentation.

## v0.1.28 — 2026-08-30

- Expanded Proxmox Manager with live node/storage/cluster/VM detail views, central UPID task tracking, snapshots, cloning, migration, hardware and disk growth operations, full locked/backoff inventory auto-sync, a split responsive frontend, create-VM workflow, Host Registry identity preservation, audit integration, tests, and updated documentation without persisting Proxmox secrets or a duplicate VM/LXC inventory.

## v0.1.24 — 2026-08-29

- Added real browser-to-FastAPI E2E coverage and hardened appliance backup/restore validation and recovery workflows.
- Added native Alert Manager and safe read-only Storage Manager, and completed the typed privileged-operation broker so FastAPI can run unprivileged while privileged host mutations remain controlled.
- Reduced idle runtime work with lazy process enumeration, session-resolution caching, gzip compression, request deduplication, shared visibility handling, and event-driven task, job, update, mount, and network-transaction refresh with polling only as fallback.
- Added backend WebSocket health monitoring with reconnect coverage and fixed Credentials refresh rendering so the table no longer flickers during automatic updates.
- Bounded the session cache with LRU eviction and explicit invalidation, removed process scans from base Resource Monitor metrics, and added regression coverage for event fan-out, reconnects, cache invalidation, request deduplication, and recursive transaction invalidation.

## v0.1.23 — 2026-08-29

- Hardened hosted/trusted CI and production deployment so manual production promotion requires a successful hosted test run for the exact `main` revision; authentication diagnostics and baseline HTTP security headers were also strengthened.
- Consolidated persistent jobs, logs, plugins and the application/module-store architecture, and moved Credentials into a standalone application while preserving centralized secret handling and module integrations.
- Improved runtime resilience with watchdog recovery, blue/green service detection, application-log source handling and filtering of unavailable legacy WebNAS systemd units.
- Reduced frontend startup cost through lazy feature/module boundaries and bundle budgets, and improved desktop UX with taskbar-safe dialogs plus horizontal Resource Monitor navigation.
- Improved Proxmox endpoint handling with scheme-less input and automatic API protocol detection, and expanded localized CSRF diagnostics.
- Added ordered multi-server DNS management with dedicated inputs, deduplication and `systemd-resolved` global DNS discovery.
- Prevented durable JobService records from remaining permanently `queued` after a process restart by recovering interrupted queued work into an explicit failed/retryable state.
- Refreshed supported backend/frontend dependencies and kept generated dependency metadata synchronized with the project source of truth.


## v0.1.22 — 2026-08-28
- Reworked the DCST network-security control plane and hardened bulk blocking, live deletion warnings, preview concurrency, inventory permissions, policy-sync timestamps, and raw firewall-log filtering.

- Finished the application UI consistency layer across resource monitoring, settings, activity and transfer centers, network resources, Docker details, and Hosts Manager controls, with container-responsive regression coverage.

- Replaced blocking shared confirmations and prompts with non-blocking, minimizable desktop dialogs; preserved drafts across minimization, isolated concurrent dialogs, cancelled queued actions on logout, suspended hidden legacy-dialog keyboard handlers, and coalesced duplicate privileged Ansible operations.

- Added complete **DHCP Manager** with Kea DHCPv4/ISC detection, Package Center lifecycle, typed subnet/pool/reservation/lease management, configuration preview and native validation, atomic apply with verified backup/rollback, utilization/diagnostics/logs/service controls, granular RBAC/PAM/CSRF/audit, Proxmox Safe Mode, shared Hosts Manager identity and optional Pi-hole/AdGuard DNS synchronization.

- Added native **Proxmox Manager** with Proxmox VE API connections, shared Hosts Manager identity, centralized `proxmox_api` credentials, VM/LXC synchronization, live-node power actions, and direct reuse of the same `host_id` by Hosts Manager and Ansible Automation Controller.

- Added managed Proxmox VM/CT metadata tags for project, environment, location, resource type and Host Registry tags, while preserving administrator-created Proxmox tags and reporting permission/tag-policy failures without blocking host synchronization.

- Added a disposable `--portable` installer mode that runs WebNAS without installing it as a system service and keeps its isolated runtime below the launch directory.

- Fixed portable mode to consistently use `./portable-run/` for source, runtime, configuration, and cleanup, preserving compatibility when launched from an existing repository checkout.

- Added Windows Explorer Drag & Drop uploads to File Manager with a localized drop zone, read-only protection, overwrite confirmation, and reuse of the existing transfer queue.

- Expanded File Manager deletion confirmations with names, types, sizes, full paths, and a bounded summary for large selections.

- Centered the File Manager path bar with symmetric spacing and explicit vertical alignment for breadcrumbs and actions.

- Expanded container creation progress with detailed, secret-safe live logs from validation through final inspection.

- Added typed custom Docker Entrypoint support across container creation, import, duplication, summaries, validation, and tests.

- Expanded container resource controls with presets, host-aware CPU and memory validation, advanced CPU/memory/OOM/I/O settings, allowlisted ulimits, responsive UI, draft and duplication support, and exact safe Docker CLI mapping.

- Redesigned the complete frontend with a compact Synology DSM-inspired visual system shared by the desktop, settings, tables, forms, dialogs, and every module, including dark-mode parity.

- Made the full interface phone-ready with viewport-filling windows and dialogs, touch-sized controls, safe-area support, local table scrolling, module-specific responsive layouts, and stronger modal focus handling.

- Hid Cron Manager from Start until it is installed, and separated NPM dependency updates from WebNAS application updates in Settings.

- Added the native **Cron Manager** module with transactional ownership of `/etc/cron.d/webnas`, read-only external cron discovery, granular RBAC and PAM/CSRF protection, durable audited mutations, server-timezone schedule validation, diagnostics and bounded redacted logs, plus a responsive Polish/English interface, tests, and operations documentation.

- Added administrator-controlled scheduled NPM dependency remediation so automatic update checks can run `npm audit fix`, rebuild, validate, and deploy the frontend even when the WebNAS application version is already current.

- Closed SQLite connections deterministically to prevent file-descriptor exhaustion, bound installer source archives to their recorded immutable revision, and moved every package operation progress view into an independent desktop window that can be moved, stacked, minimized, maximized, and restored.

- Routed Docker Engine installation through the typed Containers Manager API with PAM confirmation, updated vulnerable frontend transitive dependencies, and allowed blue/green backend services to perform authorized host package-manager writes.

- Renamed Package Center to Module Center and hid legacy MariaDB, Redis, and Nginx entries; hardened update runtime paths and scheduler database recovery; and limited backend service failures to three automatic retries spaced 30 seconds apart.

- Improved frontend dependency reporting in the installer with package-level funding and vulnerability details, while ordinary WebNAS updates now skip system repository metadata refreshes.

- Stabilized frontend CI tests, renamed Docker to the localized **Containers Manager** throughout Package Center, and required Docker to be installed before the manager can be opened.

- Added native Linux/WSL installer environment handling and administrator-controlled frontend dependency remediation: `--npm-audit-fix` and the Updates settings can run `npm audit fix`, rebuild, validate, and deploy the frontend even when WebNAS itself is current.

- Clarified interactive prompt defaults, expanded USB automount failure reports with actionable system/udev diagnostics, and made `cifs-utils` a verified installer dependency so SMB/CIFS support cannot silently remain unavailable.

- Improved installer usability with short command-line aliases, visible source-download progress, and richer installation summaries covering the detected OS, kernel, architecture, package manager, environment, and runtimes.

- Fixed installer prompts across interactive shells, piped execution, and consoles with unreliable `/dev/tty`; terminal fallback no longer hides prompts, and fresh installations no longer pause for a redundant initial confirmation.

- Added the installable **Repozytoria systemowe** module: local and mirrored APT/RPM repositories, validated content-addressed uploads, versioned filters, durable sync jobs/schedules/live logs, immutable snapshots and comparisons, atomic Testing/Production promotion and rollback, DEB/RPM building, encrypted GPG keys and signed metadata, generated Hosts Manager configurations, hardened read-only HTTP delivery, granular RBAC, diagnostics, metadata/full backup and verified restore, lifecycle scripts, responsive dedicated UI, tests, and operational documentation.

- Added installable **APMID** with a dedicated desktop app, private versioned
  SQLite registry, Identity-backed members, per-resource allow/deny RBAC,
  Activity Center/local audit, verified backup/restore and safe uninstall.
- Migrated Hosts Manager APMID operations to one authoritative domain while
  retaining old API compatibility, enrollment behavior and existing IDs.

- Expanded **Settings → Network** into transactional Linux network management with NetworkManager, systemd-networkd and Netplan providers; interface/bond/VLAN/bridge, DNS, static-route and traffic-control models; typed plan/apply/confirm/rollback API; granular RBAC/CSRF/audit; independent 90-second systemd rollback; boot restoration; connectivity tests; responsive PL/EN UI; and backend/frontend tests. ifupdown and ambiguous provider configurations remain read-only.

## Hosts Manager

- Added the independent `hosts-manager` module with a private versioned SQLite registry, granular RBAC, enrollment, SSH fingerprints, encrypted credentials, inventory/discovery, repositories, power profiles, operations/SSE, diagnostics and checksummed backup/restore.
- Added transactional, idempotent migration from Ansible Controller preserving host/group IDs, facts, fingerprints, credential encryption and automation references.
- Refactored production Ansible host access through `HostRegistryService` and registered real Ansible host capabilities.
- Added the responsive bilingual Hosts Manager application and backend/frontend tests.

All notable changes to WebNAS are documented in this file.

The format follows the spirit of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses date-based unreleased entries until tagged releases are introduced.

## [Unreleased] - 2026-07-16

### Changed

- Pi-hole, AdGuard Home, and Home Assistant are no longer duplicated in Package Center; they remain available as container applications in Containers Manager.

### Fixed

- Remember-me sessions now persist on HTTP installations while still honoring `security.cookie_secure` when secure cookies are configured.

### Added

- Complete **Logs** system application with structural journald/kernel/service/container sources, controlled classic and rotated log files, backend full-text/field filters, cursor continuation, bounded export, SSE live tail, private saved views, secret redaction, graceful source degradation, granular `logs.*` RBAC, responsive virtualized UI, and an explicit minimal `systemd-journal` installer option.
- Native **Ansible Automation Controller** Package Center module with isolated non-root `ansible-core` execution, private inventory and encrypted credentials, bounded network discovery, explicit SSH fingerprint trust, managed-host onboarding, projects/playbooks and risk validation, job templates, per-host live results, persistent schedules, checksummed backup/restore, granular RBAC, Polish/English UI and optional external AWX integration.
- Container creation now searches locally downloaded images and existing Docker networks, and accepts an editable JSON container configuration or a Docker Compose YAML file; imported Compose projects are validated, saved with revision history, and can be started immediately. Existing containers gain live settings for name, CPU priority, memory limit, automatic restart, and a web portal selected from published TCP ports.
- Complete **Containers Manager** application and typed `/api/modules/docker` API covering the engine dashboard/lifecycle, strict container creation and lifecycle, bounded logs/statistics/processes, local images and Docker Hub search, private registries, Compose validation/history/rollback/scaling, volumes, networks, application templates, checksummed backup artifacts, restore, prune previews, events and diagnostics.
- Official stable Docker repository preparation for apt/dnf/yum hosts, Docker CE/CLI/containerd/Buildx/Compose plugin packages, `hello-world` health verification, version/update visibility, and validated/atomic/backup-first `daemon.json` changes with automatic restart rollback.
- Docker manager schema migration `user_version=3`, automatic removal of legacy registry plaintext into private secret files, private per-container portal preferences, one-time private secret inputs, separate Compose secret environments, seven-day statistics history, granular Docker RBAC and PAM/exact-confirmation gates for high-risk operations.
- Administrator-only **Settings → Network** workspace with a two-second/60-sample interface traffic monitor, packet/error/drop counters, link/IP/gateway/DNS details, current resolver configuration, validated per-server DNS resolution/latency tests, and bounded read-only IPv4/IPv6 routes, policy rules, and active gateways. Routing diagnostics use only fixed server-side `ip -j ... show` commands and expose no user command input.
- OS-level USB filesystem automount using a filesystem-filtered udev rule and device-bound systemd template, stable managed mountpoints below `/media/webnas-usb`, private runtime metadata, safe unplug cleanup, installer/uninstaller integration, and automatic removable-media discovery in File Manager with a dedicated USB section.
- Controlled Docker application catalog with one-click Pi-hole, AdGuard Home, and Home Assistant Container installation, lifecycle controls, image updates with rollback, panel links, persistent private data directories, preserved-data container removal, and reserved-name ownership checks.
- Direct managed-container installers for the previously integration-only Pi-hole and AdGuard Home cards; Pi-hole v6 credentials are stored privately and mounted through `WEBPASSWORD_FILE` instead of entering durable jobs or Docker arguments.
- Debian-compatible Docker installation through the shared `docker-compose` package, with automatic support for either the Compose v2 CLI plugin or the standalone Compose executable.
- Independent per-user desktop, Start, and taskbar application pin lists, with an **All apps** right-click menu and automatic migration of legacy unified pins.
- Expanded existing-installation workflow in `install.sh` with an explicit config-preserving reinstall action, a five-second default-to-update prompt, automatic configuration snapshots, current port/service-owner discovery, and rollback to the previous application after a failed clean reinstall.
- Production Users and groups identity module with a closed granular permission registry, Linux-group and user allow/deny policy, effective permission sources, Linux administrator/last-administrator protection, versioned `identity.sqlite3`, idempotent `rbac.json` migration, compatible legacy APIs, PAM-backed login, session/CSRF-protected mutations, unified responsive UI, and audited policy history.
- Activity Center with a durable structured timeline for sign-ins, file operations, user configuration changes, administrative tasks, network-resource changes, RBAC assignments, and queued/completed/failed module jobs. Regular users are restricted to their own events, while `audit.view` grants global user/category/status/search filters; stored metadata is bounded and recursively redacted for credentials and tokens.
- Granular RBAC layered over PAM/local Linux users, with `administrator`, `operator`, `auditor`, and `user` roles, closed application/operation permissions, atomic private assignments, administrator compatibility for root/sudo/wheel, backend enforcement, and a role-management application.
- Linux Updates module with apt/dnf/yum package and security-update discovery, operation history, restart-required detection, durable metadata/security/full update jobs, session/RBAC/CSRF enforcement, and Proxmox Safe Mode blocking.
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
  - authenticated session, granular RBAC, CSRF, audit, secret redaction, timeout, and argument-array execution controls;
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
  - read-only mount write protection;
  - writable SMB/CIFS, SSHFS, and WebDAV identity mapping to the local resource owner, enabling uploads, editing, rename, copy/move, and file/directory deletion without running Explorer operations as root.
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

- The Samba module now uses a responsive action toolbar, wider overview cards, specific navigation icons, localized service and operation states, a normalized version, a module-specific window title, and no longer leaves completed jobs pinned to the overview.
- Package Center no longer mistakes workload updates reported inside modules such as Linux system updates for an available update of the WebNAS module itself.
- The Linux system updates card now displays its detected package manager instead of the inapplicable systemd service-state field.
- Linux system updates no longer report a fictitious `available` service state; the UI now shows the detected package manager and localizes real service states.
- Opening a module from the Package Center details dialog now closes the modal before creating and focusing the module window, preventing the new window from appearing behind the details overlay.
- Package Center can now install distribution packages containing required SUID/SGID helpers, including Ubuntu's `cifs-utils` `mount.cifs`; older WebNAS service profiles that block the mode receive a precise remediation error instead of an unexplained APT exit code 100.
- Active Package Center operation banners such as “Reinstalling…” are now interactive and reopen the live status, progress, current-step, and log dialog after it has been closed.
- The installer now bootstraps missing `curl`, `wget`, `tar`, and `rsync` packages before downloading, extracting, or synchronizing WebNAS application files, while skipping packages already available on the host.
- Linux Updates now reports package-manager failures instead of presenting them as an empty healthy result, provides retryable resource errors and accurate empty states, runs a real repository metadata refresh from the package toolbar, and reloads the visible list after operations.
- Samba reinstall now recovers from the Ubuntu merged-`/usr` `cifs-utils` self-conflict for `mount.cifs` using a package-scoped repair and then retries the original operation; conflicts owned by any other package remain blocked.
- Linux Updates now launches GNU `screen` with the detached `-dmS` mode, preventing the WebNAS launcher from timing out after ten seconds while package patching continues independently.
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
