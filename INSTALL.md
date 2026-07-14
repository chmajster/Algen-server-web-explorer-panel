# WebNAS Installation Guide

This document covers automatic installation, manual installation, updates, uninstalling, logs, debugging, packages, and common errors.

## Automatic Installation

Recommended:

```bash
curl -fsSL https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash
```

With a custom port:

```bash
curl -fsSL https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh | sudo bash -s -- --port 8080
```

Safer flow:

```bash
curl -fsSL -o install.sh https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh
chmod +x install.sh
sudo ./install.sh
```

Useful options:

```bash
sudo ./install.sh --port 5000
sudo ./install.sh --install-dir /opt/webnas
sudo ./install.sh --user webnas
sudo ./install.sh --yes
sudo ./install.sh --no-firewall
sudo ./install.sh --skip-build
```

The installer supports `apt`, `dnf`, and `yum`.

## Proxmox VE Host Safety

Installing directly on a Proxmox VE host is not the recommended production layout. Prefer a VM or LXC container so WebNAS cannot affect the hypervisor, cluster, storage, VM disks, container data, or host networking.

If the installer detects Proxmox VE through `/etc/pve`, `pveversion`, or Proxmox services, it stops before installation unless the operator explicitly confirms host installation:

```bash
sudo ./install.sh --allow-proxmox-host-install
```

With that flag, the generated config keeps:

```yaml
proxmox:
  safe_mode: true
```

The installer does not remove packages, run `apt autoremove`, change Proxmox repositories, edit `/etc/pve`, edit `/etc/network/interfaces`, restart Proxmox services, reboot the host, or change Proxmox storage. WebNAS then blocks protected file/admin operations at runtime.

## Required Packages

The installer installs the packages actually used by WebNAS:

- Python 3, pip, venv, Python development headers.
- Build tools for Python packages.
- Node.js and npm for the React frontend build.
- `rsync` for copy and move transfers.
- `sudo`, PAM development/runtime packages, and local account tools.
- `curl`, `tar`, `gzip`, `iproute2`/`iproute`, and system utilities.

## Manual Installation

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv python3-dev build-essential libpam0g-dev rsync sudo nodejs npm
sudo mkdir -p /opt/webnas /etc/webnas /var/lib/webnas/tmp /var/log/webnas
sudo rsync -a --delete ./ /opt/webnas/
sudo python3 -m venv /opt/webnas/backend/.venv
sudo /opt/webnas/backend/.venv/bin/pip install -r /opt/webnas/backend/requirements.txt
cd /opt/webnas/frontend
sudo npm install
sudo npm run build
```

Create `/etc/webnas/config.yaml` from `config.example.yaml`, set `server.port`, and replace `security.session_secret`.

Create `/etc/systemd/system/webnas.service`:

```ini
[Unit]
Description=WebNAS web administration panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/webnas/backend
Environment=PYTHONPATH=/opt/webnas/backend
Environment=WEBNAS_CONFIG=/etc/webnas/config.yaml
ExecStart=/opt/webnas/backend/.venv/bin/python -m app.run
Restart=on-failure
RestartSec=3
User=root
Group=root
NoNewPrivileges=false
PrivateTmp=true
# Package Center needs package-manager writes below /etc, /usr and /var.
ProtectSystem=false
ProtectHome=false
ReadWritePaths=/var/lib/webnas /var/log/webnas /home /opt/webnas

[Install]
WantedBy=multi-user.target
```

Then enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now webnas
```

The root service context is intentional: WebNAS uses PAM and authenticated user contexts for file operations, while Package Center performs validated package-manager and systemd actions. `ProtectHome=false` is also intentional: workers drop to the authenticated UID and the path policy confines them to configured roots, while a read-only systemd home mount would prevent users from creating their own files. Do not expose WebNAS directly to the public internet. Keep the session secret private, restrict network access, and use TLS through a trusted reverse proxy. Package Center never accepts command strings from the browser and still requires an administrator session, CSRF token, confirmed plan, and fresh PAM password.

## Package Center installation notes

No separate package-center daemon is required. Its SQLite database is created automatically at:

```text
/var/lib/webnas/package-center.sqlite3
```

Supported hosts are Debian, Ubuntu, Raspberry Pi OS, Fedora, RHEL, Rocky Linux, and AlmaLinux with systemd. Modules select `apt-get`, `dnf`, or `yum` from `/etc/os-release` and their validated manifest. A module is rejected before execution when its distribution, architecture, package manager, or Proxmox safety declaration is incompatible.

The package catalog ships with Samba, Squid Proxy, Nginx, and Syncthing. Before the first real operation, use a disposable VM/container and review the dry-run plan in the UI. The production systemd profile must retain `User=root`, `Group=root`, `NoNewPrivileges=false`, and `ProtectSystem=false`; changing those values makes package installation fail with a clear permission or read-only-filesystem error.

Back up package metadata and module configuration before an OS migration:

```bash
sudo systemctl stop webnas
sudo cp -a /var/lib/webnas/package-center.sqlite3 /var/lib/webnas/package-center.sqlite3.backup
sudo tar -czf /root/webnas-package-configs.tgz /etc/samba /etc/squid /etc/nginx 2>/dev/null || true
sudo systemctl start webnas
```

The bundled Syncthing module runs as the unprivileged `webnas` account through `webnas-syncthing.service` and stores its configuration/data in `/var/lib/webnas/syncthing`; include that path in backups. Uninstall preserves declared configuration and data by default. The **also remove data** option is deliberately separate and irreversible.

For module creation, manifest validation rules, endpoints, job recovery, GitHub source handling, and the complete security model, see [PACKAGE_CENTER.md](PACKAGE_CENTER.md).

## Update

Run the installer again:

```bash
sudo ./install.sh
```

If `/opt/webnas` already exists, the installer asks whether to update, create a backup and update, or abort. In `--yes` mode it updates and backs up the existing config automatically.

## Uninstall

```bash
sudo /opt/webnas/uninstall.sh
```

The uninstaller first checks and unmounts WebNAS-managed network resources, disables/removes their path-derived systemd units, and runs `daemon-reload`. It then stops WebNAS, removes `/etc/systemd/system/webnas.service`, validates every deletion path, and asks for the text confirmation `REMOVE WEBNAS`. Config, data, and logs are not removed without confirmation. `/mnt/webnas/mnt` is never deleted recursively: non-empty mount-point directories are retained, and removal of an empty base directory requires a separate confirmation.

## Network mount prerequisites

The installer creates `/mnt/webnas/mnt` as a root-owned traversal-only base so ordinary users cannot create arbitrary mount points. Updates preserve this directory, the SQLite definitions, managed credential files, and any local directory contents.

Install the tools required by the protocols you use:

```bash
sudo apt-get install cifs-utils nfs-common sshfs fuse3 davfs2
```

On RPM-based systems, use the distribution equivalents. Missing tools are shown in **Settings → Network resources** and block mounting instead of recording a false success. Persistent mounts require systemd. WebDAV should use HTTPS. SSHFS supports key authentication only; password mode is rejected because exposing it through arguments, environment, logs, or units is unsafe.

Old definitions using paths outside `/mnt/webnas/mnt/<name>` appear as requiring migration. Migration never overwrites a destination, moves local data, or publishes a stale directory in File Explorer. Resolve directory/name conflicts manually before retrying.

## Logs and Debugging

Service status:

```bash
sudo systemctl status webnas
```

Live logs:

```bash
sudo journalctl -u webnas -f
```

Recent logs:

```bash
sudo journalctl -u webnas -n 100 --no-pager
```

Package job output is also available in **Centrum pakietów → Zadania**, `GET /api/apps/jobs/{job_id}`, and the SSE stream at `GET /api/apps/jobs/{job_id}/events`. Failed jobs expose the current step, exit code, error, and redacted log tail. Common package-center codes include `MODULE_INCOMPATIBLE`, `MODULE_BLOCKED_BY_PROXMOX`, `PACKAGE_MANAGER_UNAVAILABLE`, `JOB_ALREADY_RUNNING`, `INVALID_MANIFEST`, and `AUTHENTICATION_FAILED`.

Healthcheck:

```bash
curl http://127.0.0.1:5000/api/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "webnas"
}
```

Proxmox Safe Mode diagnostics:

```bash
curl --cookie webnas_session=... http://127.0.0.1:5000/api/admin/system/proxmox-safety
```

The endpoint returns whether Proxmox was detected, whether Safe Mode is active, protected paths, blocked admin features, effective roots, service user, and warnings.

## Common Errors

`Port 5000 is not listening`: another service may be using the port, or WebNAS failed to start. Check `journalctl -u webnas -n 100 --no-pager`.

`PAM authentication failed`: verify that the Linux account exists and that PAM packages are installed. Some distributions require the service to run with enough privilege for PAM checks.

`rsync is missing`: install `rsync` manually or rerun the installer.

`Frontend build failed`: check Node.js/npm availability, then rerun without `--skip-build`.

`systemctl not found`: WebNAS production installation requires a systemd-based Linux system.

`Operation blocked by Proxmox Safe Mode`: the requested action touches a protected Proxmox/system path, system account, protected group, or service outside the WebNAS allowlist.

## Transfer Queue Storage

Transfer jobs are persisted in SQLite:

```text
/var/lib/webnas/transfers.sqlite3
```

The file stores queued, running, paused, completed, failed, and cancelled task metadata. If the service restarts while a transfer is running, WebNAS marks that task as failed with a clear interruption message while keeping the history visible. Retry creates a new queued task with the same source, destination, operation, and priority.

Tune concurrency in `/etc/webnas/config.yaml`:

```yaml
file_tasks:
  max_parallel: 2
  max_parallel_per_user: 1
```
