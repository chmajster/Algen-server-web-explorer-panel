# Users, groups, and application access

WebNAS uses local Linux accounts through PAM by default and can optionally authenticate directory users through LDAP. It does not create an application password database and never reads or returns `/etc/shadow`. UID, GID, home directories, shells, GECOS data, and group membership are changed only through fixed argument arrays passed to standard Linux tools with `shell=False`.

LDAP authentication is an additional authentication provider, not a replacement for PAM. PAM remains the local `/etc/passwd` provider. LDAP users must have a POSIX identity exposed through NSS (for example SSSD, nslcd or winbind) so WebNAS can safely run filesystem operations under their Unix UID/GID.

## Architecture

The implementation lives under `backend/app/identity/`:

- `linux_accounts.py` validates and performs controlled `useradd`, `usermod`, `userdel`, `groupadd`, `groupmod`, `groupdel`, `gpasswd`, `chpasswd`, `chage`, and `setquota` operations;
- `permissions.py` is the closed permission registry, built-in role matrix, compatibility map, and central FastAPI authorization dependency;
- `repository.py` stores versioned user/group application policies and change history in SQLite transactions;
- `migration.py` imports the legacy `rbac.json` once and creates a private backup;
- `service.py` calculates effective access, protects administrators, coordinates Linux changes with policy changes, and records Activity Center events;
- `router.py` serves `/api/identity/*` and compatible `/api/admin/users` and `/api/admin/groups` aliases;
- `backend/app/rbac.py` remains a compatibility façade for existing imports and `/api/rbac/*` clients.

Authentication-provider state is handled by `backend/app/auth_api.py`, `backend/app/security.py` and `backend/app/ldap_auth.py`. The shared session store records `auth_provider=pam|ldap`; LDAP metadata is stored separately in `<data_dir>/ldap-auth.sqlite3`, while the Bind Password is stored through Secrets Manager.

The policy database is `<data_dir>/identity.sqlite3` with mode `0600`. It contains no passwords, PAM secrets, LDAP Bind Password, session cookies, or CSRF tokens. The main tables are `schema_version`, `user_policies`, `group_policies`, and `permission_changes`.

## Authentication identity namespaces

PAM and LDAP are separate authentication namespaces.

PAM is restricted to accounts physically defined in `/etc/passwd`. This prevents an NSS-only LDAP/SSSD account from being treated as a PAM identity merely because `pwd.getpwnam()` can resolve it.

LDAP rejects a username that collides with an existing local `/etc/passwd` account. A first LDAP login also cannot inherit a pre-existing WebNAS user policy with the same username. After the LDAP identity has been successfully established, an administrator may explicitly assign WebNAS RBAC policy to it; that explicit policy remains valid for later LDAP logins.

LDAP authentication requires the directory account to resolve through NSS to a non-system Unix UID, GID and absolute home directory. UID `0` and UIDs below `security.system_uid_threshold` are rejected for LDAP sessions.

## Effective permission calculation

For a normal WebNAS identity, effective permissions are calculated from the built-in role and any explicit WebNAS policies:

```text
role permissions
+ allows from applicable groups
+ individual user allows
- denies from applicable groups
- individual user denies
```

`deny` wins over ordinary allows. The API also returns `permission_sources`, so the UI can distinguish role, group, individual allow, and deny sources. Missing permission means denied.

For PAM/local identities, UID 0 and users whose supplementary or primary group is `sudo` or `wheel` are Linux administrators. They always receive the Administrator role and every registered permission, ignore application denies, and cannot be renamed, locked, deleted, or downgraded through WebNAS.

That Linux-admin shortcut does **not** apply to remembered LDAP identities. An LDAP user does not become a WebNAS Administrator merely because NSS exposes membership in `sudo`, `wheel`, `Domain Admins`, or another directory group. LDAP users begin with normal WebNAS RBAC and require an explicit WebNAS policy to receive elevated application permissions.

UID 0 remains the local PAM break-glass account: it may pass the login eligibility check despite `system_uid_threshold`, but it must still have an interactive shell and successfully authenticate through the configured PAM service. Other local accounts below the threshold remain blocked from sign-in.

## Built-in roles

| Area | Administrator | Operator | Auditor | User |
|---|---|---|---|---|
| Own files/settings/transfers | Full | Full | Read-only where appropriate | Own scope |
| Users and groups | Full | Daily non-destructive operations; no administrator targets | Read-only | None |
| Roles and policy | Full | Read-only | Read-only | None |
| Modules/services/updates | Full | Operate and configure; no Package Center install/uninstall | Status, logs, diagnostics | None unless granted |
| Docker/DNS/databases/Home Assistant | Full | Operate/configure | Read-only | None unless granted |
| Global audit/system logs | Full | Own activity and selected system logs | Read-only global audit | Own activity |

The exact matrix is returned by `GET /api/identity/roles`; each permission includes category, operation, related WebNAS application IDs, risk, mutation flag, and localization keys. Built-in roles are not edited in storage. Administrators customize access through per-user and per-group allow/deny policy.

## API

Principal endpoints:

```text
GET  /api/identity/me
GET  /api/identity/permissions
GET  /api/identity/roles
GET  /api/identity/history
GET/POST/PATCH/DELETE /api/identity/users[/{username}]
POST /api/identity/users/{username}/lock|unlock|password|quota
PUT  /api/identity/users/{username}/policy
GET  /api/identity/users/{username}/effective-permissions
GET/POST/PATCH/DELETE /api/identity/groups[/{groupname}]
POST/DELETE /api/identity/groups/{groupname}/members[/{username}]
PUT  /api/identity/groups/{groupname}/policy
```

Every mutation requires a valid session, CSRF token, a concrete operation permission, and audit logging. The authenticated administrator session is sufficient; identity dialogs do not request or retain a second administrator password. Compatibility routes under `/api/admin/users`, `/api/admin/groups`, and `/api/rbac` call the same identity service. Global transfer review uses the separately protected `GET /api/admin/transfers` endpoint and `transfers.view_all`.

Authentication-specific endpoints are documented in [LDAP_AUTHENTICATION.md](LDAP_AUTHENTICATION.md). In particular, `/api/auth/config` is intentionally public but exposes only provider availability/defaults; administrative LDAP settings remain protected.

Network configuration uses the granular `network.view`, `network.manage_interfaces`, `network.manage_bonds`, `network.manage_vlans`, `network.manage_bridges`, `network.manage_dns`, `network.manage_routes`, `network.manage_traffic`, `network.manage_connections`, `network.confirm`, and `network.rollback` permissions. Administrators receive all of them; built-in operator and auditor roles receive read-only `network.view`; ordinary users receive none by default. Network mutations additionally require a current user-bound plan and CSRF validation.

## Migration

On first identity access, WebNAS creates the SQLite schema and imports `<data_dir>/rbac.json` in one transaction. Old permission names such as `rbac.manage`, `docker.operate`, and `audit.view` are mapped to their current granular identifiers. Unknown legacy values are reported in migration metadata and ignored. Before the transaction, the source is copied to:

```text
<data_dir>/rbac.json.identity-v1.bak
```

The migration marker is stored in SQLite, making startup idempotent. The source JSON is not deleted. Local PAM Linux administrators are calculated live and therefore cannot lose access during migration.

The session database automatically adds `auth_provider` with a default of `pam` when upgrading an existing installation. LDAP itself remains disabled after upgrade until an administrator explicitly configures and enables it.

## Safety and Proxmox

System accounts below `security.system_uid_threshold`, root, administrative groups, `systemd-*`, `pve*`, and other protected local accounts/groups are read-only. A group that remains a primary group cannot be deleted. The current session cannot delete or lock itself, and role/group policy changes are rejected with `409 LAST_ADMIN_PROTECTION` if no effective local PAM administrator would remain.

Existing Proxmox Safe Mode checks remain in the Linux account adapter. When host user/group management is blocked, identity mutations remain blocked even if the caller has an application permission.

## Emergency access recovery

Local PAM access remains available when LDAP is enabled. If the LDAP directory or its network path is unavailable, select **PAM** on the login page and use a permitted local account. WebNAS never performs this fallback automatically.

For RBAC recovery, run recovery locally as `root`; do not edit `/etc/passwd`, `/etc/group`, `/etc/shadow`, or `/etc/sudoers`:

```bash
sudo systemctl stop webnas
sudo cp -a /var/lib/webnas/identity.sqlite3 /var/lib/webnas/identity.sqlite3.recovery-backup
sudo rm -f /var/lib/webnas/identity.sqlite3 /var/lib/webnas/identity.sqlite3-wal /var/lib/webnas/identity.sqlite3-shm
sudo systemctl start webnas
```

Adjust `/var/lib/webnas` to configured `paths.data_dir`. The next access creates a clean policy database and, if `rbac.json` is still present, imports it again. To force clean role defaults, move both `rbac.json` and the identity database out of `data_dir` before restart. Local Linux accounts and passwords are untouched. A local PAM UID 0 or `sudo`/`wheel` user retains full WebNAS access.

## Required tools

The server needs PAM and the standard account tools supplied by `passwd` on Debian-like systems or `shadow-utils` on RHEL-like systems. Disk quotas additionally require `setquota` from the `quota` package. The WebNAS installer installs these dependencies; no shell command strings are evaluated.

LDAP authentication adds the pure-Python `ldap3` dependency. Directory users additionally require a host NSS integration appropriate to the environment (for example SSSD, nslcd or winbind) so `getent passwd USERNAME` resolves their POSIX identity. WebNAS does not automatically install or reconfigure an organization's directory/NSS client.
