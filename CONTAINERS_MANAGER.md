# Containers Manager

Containers Manager is the typed Docker administration workspace built into WebNAS. It replaces Docker's generic Package Center action dialog with a dedicated responsive application and a closed API under `/api/modules/docker`. The browser never submits an executable, Docker flag list, shell command, entrypoint, privileged mode, host/PID/IPC namespace, device, capability, or Docker socket mount.

## Installation and engine lifecycle

Docker Engine is installed from Docker's official stable repository on supported Debian/Ubuntu/Raspberry Pi OS and Fedora/RHEL-family systems. The trusted repository-owned `prepare.py` hook removes only Docker's documented conflicting package names when they are installed, writes the official HTTPS repository/key configuration atomically, and then lets the existing Package Center executor install `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-buildx-plugin`, and `docker-compose-plugin`.

Install, reinstall, update, stop, restart, disable, and daemon configuration changes require their granular permission, CSRF, exact confirmation and PAM re-authentication. A health hook verifies `docker version`, `docker compose version`, and `docker run --rm hello-world`. `daemon.json` is JSON/policy checked, validated with `dockerd --validate`, backed up, written atomically, followed by service restart and post-check; a failure restores the previous file and restarts Docker again.

Docker mutations remain disabled when Proxmox Safe Mode blocks the module. The manager requires a systemd-based Linux host and a root-run WebNAS service. It is not a remote Docker/TCP client and does not enable a daemon TCP listener.

## Workspace

The desktop application is split into independently maintained views:

- dashboard with engine/Compose/package versions, service state and uptime, container/image/volume/network counts, CPU/RAM/storage summaries, update availability, security information and prune preview;
- containers list, details, bounded logs, SSE log delivery, live/current statistics plus seven-day sampled history, processes, typed creation wizard, live name/resource/restart/web-portal settings, and lifecycle/update/duplicate/recreate/export/backup actions;
- local images, Docker Hub search, pull/update/remove/prune, checksummed save artifacts and bounded tar upload/load;
- registries with password/token files outside SQLite, TLS/custom-CA metadata, login tests, logout and `docker login --password-stdin`;
- Compose projects with static allowlist checks plus mandatory `docker compose config`, separate public and secret `.env` values, service status/logs, revision history, rollback, lifecycle actions and typed service scaling;
- volumes and networks with consumers, protected system networks, subnet-conflict checks, volume backup/restore/clone and destructive previews;
- a dedicated bridge-network editor with automatic or manual IPv4, optional manual IPv6, contained allocation ranges, gateways, internal mode, labels and an explicit IP-masquerade override; the same screen can safely configure Docker's default `bridge` through the existing validated, backed-up and rollback-capable `daemon.json` workflow;
- typed container pickers for connecting and disconnecting networks, exact-confirmation/PAM removal that refuses networks with attached containers, and a prune preview listing every unused custom network before deletion;
- versioned one-click templates for Pi-hole, AdGuard Home, Home Assistant, Uptime Kuma, Nginx Proxy Manager, Jellyfin, Syncthing, Nextcloud, MariaDB, PostgreSQL and Redis;
- container creation from the typed wizard, an editable JSON container configuration, or an imported Compose YAML file that is validated before it is saved and optionally started;
- WebNAS container/volume/image backup artifacts and restore to a new container name;
- engine settings, diagnostics and Docker event history.

Container and Compose updates pull the new image first, retain the old container under a private rollback name, recreate using the supported inspected configuration, verify running/health state and automatically restore the previous container if verification fails.

## API families

All routes are under `/api/modules/docker`:

| Family | Main routes |
| --- | --- |
| Dashboard/engine | `GET /dashboard`, `GET /engine`, `POST /engine/actions`, `GET/PUT /daemon-config` |
| Containers | `GET/POST /containers`, `POST /containers/import`, `GET /containers/{name}`, `GET/PUT /containers/{name}/settings`, `POST /containers/{name}/actions`, `/logs`, `/logs/stream`, `/stats`, `/processes`, `/compose`, `/export`, `/backup` |
| Images/registries | `GET /images`, `GET /images/search`, `POST /images/actions`, `POST /images/import`, registry CRUD/test routes |
| Volumes/networks | list/detail/create routes, `GET/PUT /networks/default-bridge`, `GET /networks/{name}/containers`, and typed `POST .../{name}/actions` |
| Compose | list/get/save/validate/action/status/log/history/rollback routes below `/compose` |
| Catalog/events | `GET /apps`, app install/action routes, `GET /events` |
| Cleanup/backups | `GET /prune/plan`, `POST /prune`, `GET /backups`, restore and checksummed artifact download routes |
| Diagnostics | `GET /diagnostics` |

Long operations use the existing durable `package_jobs` queue and expose its normal progress, redacted logs, audit history, retry and safe-step cancellation behavior. Only one mutation for Docker can be queued/running at a time. If WebNAS itself restarts during a non-detached Docker subprocess, repository recovery marks that job failed as interrupted; it is never reported as successful and can be retried after state inspection.

## Storage and migration

No manual migration command is needed. On first access, `DockerManagerStore` creates `/var/lib/webnas/docker-manager/manager.sqlite3` and applies `PRAGMA user_version=3`, adding registry metadata/TLS state, seven-day statistics, artifact metadata/checksums and per-container web-portal preferences. Version 2 moves any version-1 plaintext registry password into a dedicated `0600` secret file, clears the legacy database column, checkpoints WAL and vacuums the database; version 3 adds non-secret portal preferences. The manager and secret/artifact/input directories are mode `0700`; databases, Compose files, environment files, staged inputs and registry secret files are mode `0600`. The existing `/var/lib/webnas/package-center.sqlite3` continues to own jobs and job history.

Compose projects live below `/var/lib/webnas/compose/<project>`. Secrets use a separate `.env.secrets`, are never returned, and are preserved when an edit does not submit replacements. Temporary create/restore/catalog secrets use one-time random references; the private input is consumed and deleted before execution. Registry passwords are returned only as `secret_configured`, live outside SQLite, and are sent to Docker through standard input rather than arguments. Optional CA files are installed only as `webnas-ca.crt` below the validated registry directory. Container inspection returns environment key names only. Logs, activity details and diagnostics pass through secret redaction.

Backups and exports are registered as private artifacts with SHA-256 checksums and are verified before download or restore. Container backups deliberately omit environment values; restore requires the operator to re-enter every omitted value through masked, one-time private fields. Container filesystem export/import, image save/load and WebNAS configuration/volume backup remain distinct operations. Volume filesystem backup/restore needs the classic rootful Docker local-volume layout below `/var/lib/docker/volumes`; unsupported/rootless layouts fail closed. Bind mounts are limited to configured data roots plus `/srv`, `/mnt`, `/media` and the WebNAS data directory.

Home Assistant is installed on the safer bridge network with port 8123 published. Integrations that depend on host-network multicast discovery may need manual device addresses; Containers Manager does not silently grant host networking. The Pi-hole wizard supports hostname, IANA timezone, DNS/panel ports, a named bridge network and a password file; active `systemd-resolved` fails closed with corrective guidance. Pi-hole and AdGuard Home both use host DNS ports, so only one can own port 53 on the same host at a time.

The ordinary container wizard intentionally does not accept `command`, `entrypoint`, executable names or free-form Docker arguments. This is the enforcement of the closed API requirement; use a repository-owned catalog template or an allowlisted Compose field when an image needs behavior beyond its declared default command. Privileged mode, host/PID/IPC namespaces, devices, capabilities and Docker socket mounts are not enabled by an administrator toggle in this release and therefore cannot bypass the default prohibition.

## Authorization

Administrators retain all Docker permissions. Operators receive normal container/image/Compose/registry/volume/network lifecycle permissions but not prune, restore or `docker.high_risk`. Auditors receive read-only container/image/log/statistics/diagnostic access. Important permissions include:

```text
docker.install_engine       docker.update_engine       docker.start_service
docker.stop_service         docker.view_containers     docker.create_container
docker.start_container      docker.stop_container      docker.restart_container
docker.remove_container     docker.inspect_container   docker.view_logs
docker.view_stats           docker.view_images         docker.pull_image
docker.remove_image         docker.manage_registries   docker.manage_volumes
docker.manage_networks      docker.manage_compose      docker.export_backup
docker.restore_backup       docker.prune                docker.diagnostics
docker.high_risk
```

The backend is the enforcement boundary. The responsive PL/EN interface also hides or disables controls based on effective permissions, but a direct request still goes through session, CSRF, RBAC, typed-model, confirmation, PAM, Proxmox and provider allowlist checks.

## Verification

Backend coverage uses mocked subprocess/HTTP/filesystem boundaries and checks strict models, socket/namespace rejection, registry-secret migration/non-disclosure, one-time inputs, the closed catalog and Pi-hole/Home Assistant arguments, Compose policy/runtime validation, daemon allowlists, fixed Docker argument arrays, RBAC, trusted install hooks and route registration. Frontend component tests cover manager navigation, permission hiding and masked secret-bearing create requests. Normal validation commands are:

```bash
cd backend
../.venv/bin/python -m pytest tests/test_docker_manager.py tests/test_modules_framework.py tests/test_package_center.py

cd ../frontend
npm test -- --run
npm run build
```

Run the real install/update/rollback and volume restore checks on a disposable supported Linux VM. Windows development can validate contracts and UI, but cannot exercise systemd, PAM, Docker's Linux volume layout, POSIX file modes or the official Linux package repositories.
