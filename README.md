# WebNAS

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
- One-command installer with systemd/autostart support.
- Optional firewall setup for `ufw` or `firewalld`.
- Modular NAS-style Package Center with validated YAML manifests, dry-run plans, durable jobs, live logs, service control, history, and GitHub source metadata.
- Administrator-managed SMB/CIFS, NFS, SSHFS, and WebDAV network resources integrated with Settings and File Explorer.

## Network resources

Administrators manage network resources in **Settings → Network resources**. The previous `mounts` application id is still restored from saved window state, but redirects to this single settings section. Each definition can be created, edited, tested, mounted, unmounted, remounted, migrated, inspected through redacted logs, and removed. Mutating operations require an administrator session, CSRF, and fresh PAM reauthentication.

WebNAS always calculates the local path as `/mnt/webnas/mnt/<name>`; neither the UI nor the API accepts an arbitrary `mount_point`. Names are single 1–63 character path components made from letters, numbers, dots, dashes, and underscores. Separators, `..`, control characters, trailing dots/spaces, duplicates after Unicode normalization, nested paths, and symlinks escaping the base are rejected.

Only resources verified as mounted by the operating system and allowed for the current user are published under **Network resources** in File Explorer. Visibility can be granted to users or real primary/supplementary groups. To preserve the existing WebNAS policy, empty user and group lists grant access to every authenticated local user; the owner and administrators retain access. Read-only definitions are enforced in both the UI and every backend write path. Explorer refreshes automatically after mount state changes and returns to the home directory if its active resource disappears.

Protocol dependencies are `cifs-utils` (SMB), `nfs-common` (NFS), `sshfs` plus `fuse3` (SSHFS), and `davfs2` (WebDAV). HTTPS is strongly preferred for WebDAV. SSHFS password authentication is intentionally disabled because it cannot be passed safely without exposing the secret; configure key authentication instead. An empty SMB/WebDAV password during editing preserves the current managed secret, while deletion requires the explicit **remove stored secret** option.

Persistent definitions use path-escaped `.mount`/`.automount` unit names matching `Where=`. Existing definitions outside the managed base are marked for migration and are never published until the administrator completes a conflict-free migration. Local directory contents are not moved or overwritten automatically.

## Package Center

**Centrum pakietów** manages trusted WebNAS modules through an administrator-only UI with search, categories, status filters, installed/updates views, jobs, history, and sources. The initial catalog contains Samba, Squid Proxy, Nginx, and Syncthing. Install, update, uninstall, and systemd actions require plan confirmation and PAM reauthentication; progress and redacted logs survive browser and service restarts in SQLite.

Modules support Debian, Ubuntu, Raspberry Pi OS, Fedora, RHEL, Rocky Linux, and AlmaLinux when their manifest provides packages for the detected `apt-get`, `dnf`, or `yum` manager. Proxmox Safe Mode rejects modules not explicitly marked safe. External GitHub repositories are stored and refreshed only as untrusted metadata—they are never downloaded or executed automatically.

See [PACKAGE_CENTER.md](PACKAGE_CENTER.md) for architecture, manifest fields, module authoring, security, API endpoints, storage, backups, and a manual test checklist.

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
