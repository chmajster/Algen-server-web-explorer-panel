# WebNAS

WebNAS includes a central [Hosts Manager](HOSTS_MANAGER.md) for secure enrollment, shared inventory, SSH trust, connection credentials, power profiles, repositories and cross-module host actions. Ansible Controller consumes this registry instead of maintaining an independent editable host database.

WebNAS is a web NAS administration panel for Linux, similar in spirit to Synology-style file management while using its own interface and assets. It gives a server a clean browser panel for local Linux users, PAM login, systemd startup, and rsync-powered file operations.

See [CHANGELOG.md](CHANGELOG.md) for the project change history.

## Features

- Web file explorer for browsing a logged-in Linux user's home directory.
- Copy and move operations through `rsync`.
- Real-time transfer tracking with progress, speed, ETA, current file, exit code, and log tail.
- Transfer cancellation from the UI and API.
- PAM authentication with local Linux accounts.
- FastAPI backend and React + TypeScript + Vite frontend.
- Default port `5000`.
- One-command installer with systemd/autostart support, a five-second automatic update for detected installations, config-preserving reinstall, safety backups, and failed-reinstall rollback.
- Optional firewall setup for `ufw` or `firewalld`.
- Modular NAS-style Package Center with validated YAML manifests, dry-run plans, durable jobs, live logs, service control, history, and GitHub source metadata.
- Shared module-management applications with health, service controls, configuration plans, diagnostics, bounded/redacted logs, private backups, verified restore, and safe uninstall workflows.
- Administrator-managed SMB/CIFS, NFS, SSHFS, and WebDAV network resources integrated with Settings and File Explorer.
- Read-only network diagnostics in Settings with per-interface traffic history, errors, link/IP/gateway/DNS details, DNS resolution latency tests, and kernel routing tables/rules.
- OS-level USB filesystem automount through udev and a device-bound systemd service, with removable media shown automatically in File Manager.
- Windows 11-inspired (but independently branded) WebNAS desktop with one bottom taskbar, Start menu search, pinned/running app indicators, notification and transfer flyouts, and responsive application windows.
- Per-user personalization synchronized by the backend: theme, accent, wallpaper, taskbar alignment, accessibility, notifications, transfer behavior, and File Manager defaults.
- Role-based authorization for local Linux users with administrator, operator, auditor, and user roles plus closed per-operation grants/denials; existing root/sudo/wheel administrators retain full access.
- Infrastructure modules for Linux security/system updates, Docker with a controlled Pi-hole/AdGuard Home/Home Assistant application catalog and safe Compose projects, PostgreSQL, MariaDB, Redis, and Home Assistant Container.
- Complete **Containers Manager** for official Docker Engine installation/update, local images, an Applications view backed by the Docker Hub/Registry V2 image catalog with tag-aware pulls, registry connections, Compose projects/history/scaling, volumes, networks, backups, diagnostics, granular RBAC and high-risk PAM confirmations.
- One permission-aware **Users and groups** application for local Linux account/group management, built-in roles, per-user and Linux-group allow/deny policy, effective-access sources, and an audited SQLite policy store. PAM and Linux accounts remain the source of truth.
- Per-user CPU, RAM, disk, transfer, service, and alert widgets that can be pinned, hidden, moved, and resized on the desktop.
- Persistent Activity Center for sign-ins, file operations, configuration changes, administrative tasks, and module events, with private per-user history and permission-controlled global audit access.
- Native Logs application for bounded journal, kernel, service, detected file, WebNAS, Activity Center, and Docker-container logs with combined server-side filters, live tail, export, saved views, and granular RBAC.

## Desktop and personalization

The WebNAS workspace uses one bottom taskbar for the Start menu, pinned and running applications, active-window state, transfers, notifications, theme, session identity, clock/date, and sign-out. The Start menu opens above the taskbar, searches all apps, distinguishes administrator tools, and closes after launching an app, clicking outside, or pressing `Escape`. Right-clicking an entry under **All apps** can independently add or remove it from the desktop, the pinned Start section, or the taskbar. Each destination is synchronized per user by the backend, while legacy unified pin lists are migrated automatically. Saved window state remains compatible with previous releases and can be restored after sign-in or disabled in **Settings → System**.

Desktop shortcuts flow down from the upper-left corner and can be hidden or resized. A user can configure an HTTP(S) or supported image data URL as wallpaper and choose `cover`, `contain`, stretch, or centered display. Window transparency and short animations can be disabled. The responsive layout maximizes app windows on narrow screens, keeps taskbar flyouts inside the viewport, converts Settings to mobile navigation, and preserves controlled scrolling for file tables.

**Settings** is organized into System, Personalization, File Manager, Transfers, Notifications, Accessibility, Language & region, Account, and About. Administrators additionally receive Network and Administration. Settings search opens the category containing a matching control. Changes are applied optimistically and saved automatically; text input uses a short debounce and exposes saving, saved, and error states.

File Manager preferences are active rather than cosmetic. They control list/grid/large-icon view, compact rows, hidden files, delete/overwrite confirmation, 25/50/100/200 item pages, initial sorting and direction, and whether the last directory is remembered. The explorer keeps the existing path validation and operation security model.

## Activity Center

**Activity Center** presents a searchable, paginated timeline of sign-ins, file operations, user configuration changes, administrative actions, and module jobs. Every user can inspect their own activity. Administrators and auditors with `audit.view` can inspect the global timeline and filter it by user, category, status, and text. Status labels and icons distinguish queued, completed, failed, informational, and cancelled operations without relying on color alone.

Events are stored in `paths.data_dir/activity.sqlite3` with a bounded history and private data-directory permissions. Only structured operation metadata is retained: file contents, passwords, cookies, authorization headers, tokens, credentials, and private keys are never intentionally stored. Nested details and free-form error text pass through the same secret-redaction layer used by module logs. Activity recording is failure-isolated, so an unavailable activity database cannot weaken or interrupt PAM authentication, CSRF validation, path policy, Proxmox Safe Mode, or the operation being audited.

## Logs

**Logs** is a permission-aware Linux log browser available from the desktop, Start menu, search, taskbar pinning, and restored windows. It reads structured `journalctl --output=json` records, kernel entries, dynamically detected systemd services, controlled classic files and rotations, WebNAS/Activity Center adapters, and Docker containers when Docker is available. A missing program, file, permission, or individual source is reported locally without disabling the remaining sources.

Search, priority, time, boot, service, PID/UID, identifier, transport, container, phrase, case, negation, and bounded regular-expression filters execute on the backend. Responses default to 200 and never exceed 1,000 records; continuation tokens replace unbounded offset pagination. The frontend caps retained live entries and virtualizes the visible list. TXT, JSON, JSONL, and CSV exports are UTF-8, filter-aware, bounded to 5,000 entries, and report truncation.

Log messages and structured fields pass through the existing credential/token/private-key redaction layer. The API accepts neither paths nor command strings, runs only server-generated argument arrays without `shell=True`, validates units/containers/ranges/limits, bounds subprocess output and time, and audits access without recording queries or log contents. Saved views are validated, private, atomically replaced under `paths.data_dir/settings/log_views`, and protected by CSRF for mutations. See [Logs API and operations](docs/LOGS_API.md).

User preferences are stored by the backend in `paths.data_dir/settings/<username>.json`. Every value is validated against an enum, length limit, or numeric range, files are replaced atomically with owner-only permissions, and missing fields from older files receive safe defaults automatically. Passwords and other secrets are never part of this settings store; password changes continue to require the current password through the dedicated authenticated endpoint.

## Network diagnostics and resources

**Settings → Network** contains four tabs. **Network monitor** samples Linux interface counters every two seconds and keeps a 60-sample browser history for receive/transmit rates; it also shows packets, errors, dropped packets, carrier state, negotiated speed/duplex, MTU, MAC and IP addresses, active gateways, and effective per-link/global DNS servers. **DNS** presents `/etc/resolv.conf` and `systemd-resolved` state and can send bounded direct DNS queries for one validated domain to configured DNS servers, reporting each server's latency and response code. **Routing table** is a read-only view of IPv4/IPv6 routes, policy rules, and default gateways.

The diagnostic API accepts no command or routing expressions. Route and rule collection uses fixed server-side `ip -j ... show` argument lists, response sizes and item counts are bounded, and the DNS test accepts only a validated IDNA hostname and contacts only servers already present in the system resolver configuration.

Administrators manage SMB/CIFS, NFS, SSHFS, and WebDAV definitions under **Settings → Network → Network resources**. The previous `mounts` application id is still restored from saved window state, but redirects to this single settings section. Each definition can be created, edited, tested, mounted, unmounted, remounted, migrated, inspected through redacted logs, and removed. Mutating operations require an authenticated session, their concrete permission, and CSRF.

WebNAS always calculates the local path as `/mnt/webnas/mnt/<name>`; neither the UI nor the API accepts an arbitrary `mount_point`. Names are single 1–63 character path components made from letters, numbers, dots, dashes, and underscores. Separators, `..`, control characters, trailing dots/spaces, duplicates after Unicode normalization, nested paths, and symlinks escaping the base are rejected.

Only resources verified as mounted by the operating system and allowed for the current user are published under **Network resources** in File Explorer. Visibility can be granted to users or real primary/supplementary groups. To preserve the existing WebNAS policy, empty user and group lists grant access to every authenticated local user; the owner and administrators retain access. Read-only definitions are enforced in both the UI and every backend write path. Explorer refreshes automatically after mount state changes and returns to the home directory if its active resource disappears.

Read/write resources support the regular File Explorer operations, including uploads, text editing, creating files and directories, renaming, copying, moving, and recursive deletion. SMB/CIFS, SSHFS, and WebDAV mounts automatically use the local UID and primary GID of the resource owner when no explicit mapping was configured; explicit UID/GID values remain authoritative. SSHFS uses FUSE permission checks while allowing the mapped local identity to reach the root-created mount. Existing mounts must be remounted once after upgrading to apply the effective identity options. NFS continues to honor the UID/GID and export permissions configured by the NFS server.

Protocol dependencies are `cifs-utils` (SMB), `nfs-common` (NFS), `sshfs` plus `fuse3` (SSHFS), and `davfs2` (WebDAV). HTTPS is strongly preferred for WebDAV. SSHFS password authentication is intentionally disabled because it cannot be passed safely without exposing the secret; configure key authentication instead. An empty SMB/WebDAV password during editing preserves the current managed secret, while deletion requires the explicit **remove stored secret** option.

Persistent definitions use path-escaped `.mount`/`.automount` unit names matching `Where=`. Existing definitions outside the managed base are marked for migration and are never published until the administrator completes a conflict-free migration. Local directory contents are not moved or overwritten automatically.

## USB automount

The installer registers `99-webnas-usb-automount.rules` and the `webnas-usb-mount@.service` template. A USB disk or partition containing a supported filesystem is mounted by the operating system below `/media/webnas-usb/<label>-<id>` and unmounted when its device unit disappears. USB filesystems that were already connected during installation are also queued for mounting.

File Manager polls the authenticated local-disk endpoint while the page is visible and publishes managed media under a separate **USB devices** section without requiring a page reload. If the currently open device is disconnected, the explorer returns to the user's home directory. The same path policy, Linux-user permission checks, read-only enforcement, and Proxmox Safe Mode restrictions used for other local disks remain in force.

Supported filesystems are ext2/3/4, XFS, Btrfs, F2FS, VFAT, exFAT, NTFS, and NTFS3. Mounts always use `nosuid,nodev,noexec`; filesystems without Unix permission bits receive broad file access so authenticated local users can use them, while native Linux filesystems keep their existing ownership and modes. Encrypted volumes, swap, LVM members, unknown filesystems, symlink mountpoints, and non-USB block devices are rejected. Runtime mount metadata is private under `/run/webnas/usb-mounts`, and uninstall only removes the integration and empty mount directories—it never deletes files from a USB device.

## Package Center

**Package Center** manages trusted WebNAS modules through a permission-controlled UI with search, categories, status filters, installed/updates views, jobs, history, and sources. The catalog includes Samba, Ansible Automation Controller, Squid Proxy, Nginx, Syncthing, Linux Updates, Docker, PostgreSQL, MariaDB, and Redis. Container-only applications such as Pi-hole, AdGuard Home, and Home Assistant are available from Containers Manager instead of being duplicated here. Install, update, uninstall, and systemd actions require an authenticated session, a concrete RBAC permission, CSRF, and plan confirmation; progress and redacted logs survive browser and service restarts in SQLite. Linux security/full patching additionally runs in a detached GNU `screen` worker, so closing the browser does not stop the package manager and WebNAS can reconnect to the operation after its own process restarts.

Modules support Debian, Ubuntu, Raspberry Pi OS, Fedora, RHEL, Rocky Linux, and AlmaLinux when their manifest provides packages for the detected `apt-get`, `dnf`, or `yum` manager. Proxmox Safe Mode rejects modules not explicitly marked safe. External GitHub repositories are stored and refreshed only as untrusted metadata—they are never downloaded or executed automatically.

Installed modules open as regular WebNAS windows from Package Center. A shared shell provides Overview, Configuration (when supported), Service, Logs, Diagnostics, Backups, and Information; providers expose only manifest-declared capabilities. Module jobs extend the existing SQLite queue with durable stages, warnings, results, SSE updates, interruption recovery, and real post-operation status checks.

The [Ansible Automation Controller](ANSIBLE_CONTROLLER.md) is a local, isolated `ansible-core` controller inspired by Tower/AWX. It adds safe network discovery, verified SSH fingerprints, inventory and facts, encrypted credentials, projects/playbooks, job templates, live per-host results, persistent schedules and optional external AWX integration without deploying Kubernetes or running playbooks as the WebNAS root process.

The Docker entry opens the dedicated **Containers Manager** instead of the generic package dialog. Its network workspace supports typed dual-stack bridge creation, IPAM validation, default-bridge configuration, container connection pickers, protected system networks, exact-confirmation removal and unused-network previews. Its closed application catalog includes Pi-hole, AdGuard Home, Home Assistant, Uptime Kuma, Nginx Proxy Manager, Jellyfin, Syncthing, Nextcloud, MariaDB, PostgreSQL, and Redis. See [CONTAINERS_MANAGER.md](CONTAINERS_MANAGER.md) for installation, API, storage migration, permissions, safety boundaries and verification.

Samba is the complete reference provider. Its application adds Shares, SMB users, and Sessions; typed global/share configuration; controlled VFS options; `smbstatus` parsing; UFW/firewalld status; fixed-source redacted logs; comprehensive diagnostics; checksummed `0600` backups; and transactional `testparm`/atomic-write/reload/verify/rollback behavior. File Manager labels shared directories with their Samba name/read-only state and can open, create, or remove the share definition without deleting the directory.

Module mutations require an active session, CSRF, the concrete operation permission, a structured plan, and audit logging. Package installation and uninstall remain restricted to callers with their dedicated high-risk permissions. Administrative dialogs use the active authenticated session and never request or retain a second administrator password. SMB passwords never enter settings, local storage, plans, jobs, command lines, or logs.

See [PACKAGE_CENTER.md](PACKAGE_CENTER.md) for the package layer, [MODULES.md](MODULES.md) for provider architecture and Samba, [CONTAINERS_MANAGER.md](CONTAINERS_MANAGER.md) for Docker, [INFRASTRUCTURE_MODULES.md](INFRASTRUCTURE_MODULES.md) for infrastructure modules, and [IDENTITY.md](IDENTITY.md) for roles, granular permissions, Linux account safety, migration, API, and access recovery.

## Szybki start

Requirements: Debian, Ubuntu, Raspberry Pi OS, Fedora, or RHEL-like Linux with systemd and root/sudo access.

One-command installation:

```bash
curl -fsSL https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash
```

Default address after installation:

```text
http://IP_SERWERA:5000
```

Login uses local Linux accounts through PAM. Check service status with:

```bash
sudo systemctl status webnas
```

Update by running the installer again. It detects an existing `/opt/webnas` installation and asks whether to update, create a backup, or abort.

Uninstall:

```bash
sudo /opt/webnas/uninstall.sh
```

## Instalacja

Install with `curl`:

```bash
curl -fsSL https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash
```

Install with `wget`:

```bash
wget -qO- https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash
```

Safer download-review-run flow:

```bash
curl -fsSL -o install.sh https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh
chmod +x install.sh
sudo ./install.sh
```

Custom port example:

```bash
curl -fsSL https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash -s -- --port 5000
```

Useful installer options:

```bash
sudo ./install.sh --port 8080 --install-dir /opt/webnas --user webnas --yes
sudo ./install.sh --skip-build
sudo ./install.sh --no-firewall
```

## Pobieranie instalatora

Direct installer URL:

```text
https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh
```

## Service Commands

```bash
sudo systemctl status webnas
sudo systemctl restart webnas
sudo journalctl -u webnas -f
```

Healthcheck:

```text
GET /api/health
```

## Proxmox VE Host Safety

Direct installation on a Proxmox VE host is intentionally restricted. The safer production setup is to run WebNAS inside a VM or LXC container. If the installer detects Proxmox VE through `/etc/pve`, `pveversion`, or Proxmox services, it aborts unless you pass:

```bash
sudo ./install.sh --allow-proxmox-host-install
```

With that flag, WebNAS runs in Proxmox Safe Mode. The backend blocks file operations, chmod/chown, delete, move, rsync, user/group administration, and service management that could touch Proxmox cluster, storage, VM/LXC, network, boot, runtime, or system paths. Protected examples include `/etc/pve`, `/var/lib/vz`, `/var/lib/lxc`, `/mnt/pve`, `/etc/network`, `/boot`, `/root`, `/dev`, `/proc`, `/sys`, `/run`, and `/rpool`.

On Proxmox, effective roots are limited to the authenticated user's home directory or `/srv/webnas-shares/{username}`. Admin diagnostics are available at:

```text
GET /api/admin/system/proxmox-safety
```

The Settings panel shows a Proxmox Safe Mode banner when the backend reports that Safe Mode is active.

## Development

Start backend and frontend without systemd:

```bash
./dev-start.sh
```

Manual backend:

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=$PWD uvicorn app.main:app --reload --host 0.0.0.0 --port 5000
```

Manual frontend:

```bash
cd frontend
npm install
npm run dev
```

For full per-user file access, run the backend on Linux with sufficient privileges for PAM and user file operations.

## File Transfers

`/api/files/copy` and `/api/files/move` enqueue durable `rsync` transfer tasks. Tasks are stored in SQLite at `paths.data_dir/transfers.sqlite3`, so completed, failed, and cancelled transfer history remains visible after a service restart. Move is implemented as rsync first and source removal only after a successful transfer, so a failed, paused, or cancelled move keeps the source intact.

The transfer manager supports:

- priority queueing,
- global and per-user parallel limits,
- pause and resume using rsync partial transfers,
- cancellation with `.webnas-partial` cleanup,
- retry after failure,
- history filters for active, completed, failed, and cancelled transfers,
- detail view with command preview, exit code, stderr/log tail, file counts, average speed, and start/end time,
- protection against moving a directory into itself or one of its children.

Task endpoints:

```text
GET  /api/files/tasks
GET  /api/files/tasks?status=active|finished|failed|cancelled
GET  /api/files/tasks/{task_id}
GET  /api/files/tasks/{task_id}/events
POST /api/files/tasks/{task_id}/cancel
POST /api/files/tasks/{task_id}/pause
POST /api/files/tasks/{task_id}/resume
POST /api/files/tasks/{task_id}/retry
PATCH /api/files/tasks/{task_id}/priority
```

The frontend uses Server-Sent Events for live updates when available and falls back to polling. To debug transfer failures, inspect `error_message`, `stderr_tail`, `log_tail`, `rsync_exit_code`, and the service log.
