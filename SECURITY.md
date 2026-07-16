# Security Notes

- Authentication uses PAM and local Linux accounts.
- Passwords are sent only to PAM verification and are not stored.
- Session cookies are signed and HTTP-only.
- Mutating API requests require an `x-csrf-token` header.
- Login attempts are rate-limited per client/user key.
- Paths are resolved against configured roots before each operation.
- Path traversal outside the configured roots is rejected.
- User input is not interpolated into shell commands.
- File operations run in a worker process that drops privileges to the authenticated user.
- Network resources are confined to direct, non-symlink children of `/mnt/webnas/mnt`, and actual mount state is reconciled from `/proc/self/mountinfo`/`mountpoint` before publication.
- Mount options use an allowlist; `suid`, `dev`, `exec`, `allow_other`, inline credentials, authentication fields, and argument-injection syntax are rejected.
- SMB/WebDAV secrets are atomically stored in backend-generated `0600` files inside a `0700` directory. Passwords and credentials are redacted from API responses, logs, previews, process arguments, and systemd units.
- Administrative mount APIs require an authenticated session, the concrete RBAC permission, and CSRF for mutations. The user-facing `/api/mounts/roots` response contains only verified roots and basic filesystem data.

For production, set a strong `security.session_secret`, enable HTTPS at a reverse proxy or through configured TLS, and review whether `/home` is the correct `ReadWritePaths` boundary for your server.

Network mount definitions with empty access lists follow the documented compatibility policy and are visible to every authenticated local user. Configure `allowed_users` or `allowed_groups` when a resource must be restricted. Proxmox Safe Mode additionally rejects managed paths colliding with configured Proxmox storage; WebNAS never registers a mount as Proxmox storage.

## Proxmox VE Host Safety

Running WebNAS directly on a Proxmox VE host is supported only in a restricted Safe Mode. The recommended production deployment is a VM or LXC container.

When Proxmox is detected, WebNAS protects host-critical paths such as `/etc/pve`, `/var/lib/pve-cluster`, `/var/lib/vz`, `/var/lib/lxc`, `/mnt/pve`, `/etc/network`, `/boot`, `/root`, `/dev`, `/proc`, `/sys`, `/run`, and `/rpool`. Safe Mode blocks delete, trash, move, rename, upload, create, mkdir, chmod, chown, and rsync operations on those paths or their parents.

Safe Mode also blocks system user/group management, protected group membership changes, root password changes through the panel, and service management outside `webnas.service`. The UI shows a banner in Settings, and admins can inspect `GET /api/admin/system/proxmox-safety`.

The installer refuses direct Proxmox host installation unless `--allow-proxmox-host-install` is provided. Even then it must not modify Proxmox cluster configuration, storage, network configuration, Proxmox repositories, or Proxmox services.
