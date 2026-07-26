# Users, groups, and application access

WebNAS uses local Linux accounts and PAM as its only identity and password source. It does not create an application password database and never reads or returns `/etc/shadow`. UID, GID, home directories, shells, GECOS data, and group membership are changed only through fixed argument arrays passed to standard Linux tools with `shell=False`.

## Architecture

The implementation lives under `backend/app/identity/`:

- `linux_accounts.py` validates and performs controlled `useradd`, `usermod`, `userdel`, `groupadd`, `groupmod`, `groupdel`, `gpasswd`, `chpasswd`, `chage`, and `setquota` operations;
- `permissions.py` is the closed permission registry, built-in role matrix, compatibility map, and central FastAPI authorization dependency;
- `repository.py` stores versioned user/group application policies and change history in SQLite transactions;
- `migration.py` imports the legacy `rbac.json` once and creates a private backup;
- `service.py` calculates effective access, protects administrators, coordinates Linux changes with policy changes, and records Activity Center events;
- `router.py` serves `/api/identity/*` and compatible `/api/admin/users` and `/api/admin/groups` aliases;
- `backend/app/rbac.py` remains a compatibility façade for existing imports and `/api/rbac/*` clients.

The policy database is `<data_dir>/identity.sqlite3` with mode `0600`. It contains no passwords, PAM secrets, session cookies, or CSRF tokens. The main tables are `schema_version`, `user_policies`, `group_policies`, and `permission_changes`.

## Effective permission calculation

For a normal Linux user, WebNAS calculates:

```text
role permissions
+ allows from every Linux group
+ individual user allows
- denies from every Linux group
- individual user denies
```

`deny` wins over ordinary allows. The API also returns `permission_sources`, so the UI can distinguish role, group, individual allow, and deny sources. Missing permission means denied.

UID 0 and users whose supplementary or primary group is `sudo` or `wheel` are Linux administrators. They always receive the Administrator role and every registered permission, ignore application denies, and cannot be renamed, locked, deleted, or downgraded through WebNAS.

UID 0 is also the local break-glass account: it may pass the login eligibility check despite `system_uid_threshold`, but it must still have an interactive shell and successfully authenticate through the configured PAM service. Other accounts below the threshold remain blocked from sign-in.

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

Network configuration uses the granular `network.view`, `network.manage_interfaces`, `network.manage_bonds`, `network.manage_vlans`, `network.manage_bridges`, `network.manage_dns`, `network.manage_routes`, `network.manage_traffic`, `network.manage_connections`, `network.confirm`, and `network.rollback` permissions. Administrators receive all of them; built-in operator and auditor roles receive read-only `network.view`; ordinary users receive none by default. Network mutations additionally require a current user-bound plan and CSRF validation.

## Migration

On first identity access, WebNAS creates the SQLite schema and imports `<data_dir>/rbac.json` in one transaction. Old permission names such as `rbac.manage`, `docker.operate`, and `audit.view` are mapped to their current granular identifiers. Unknown legacy values are reported in migration metadata and ignored. Before the transaction, the source is copied to:

```text
<data_dir>/rbac.json.identity-v1.bak
```

The migration marker is stored in SQLite, making startup idempotent. The source JSON is not deleted. Linux administrators are calculated live and therefore cannot lose access during migration.

## Safety and Proxmox

System accounts below `security.system_uid_threshold`, `root`, administrative groups, `systemd-*`, `pve*`, and other protected accounts/groups are read-only. A group that remains a primary group cannot be deleted. The current session cannot delete or lock itself, and role/group policy changes are rejected with `409 LAST_ADMIN_PROTECTION` if no effective administrator would remain.

Existing Proxmox Safe Mode checks remain in the Linux account adapter. When host user/group management is blocked, identity mutations remain blocked even if the caller has an application permission.

## Emergency access recovery

Run recovery locally as `root`; do not edit `/etc/passwd`, `/etc/group`, `/etc/shadow`, or `/etc/sudoers`:

```bash
sudo systemctl stop webnas
sudo cp -a /var/lib/webnas/identity.sqlite3 /var/lib/webnas/identity.sqlite3.recovery-backup
sudo rm -f /var/lib/webnas/identity.sqlite3 /var/lib/webnas/identity.sqlite3-wal /var/lib/webnas/identity.sqlite3-shm
sudo systemctl start webnas
```

Adjust `/var/lib/webnas` to configured `paths.data_dir`. The next access creates a clean policy database and, if `rbac.json` is still present, imports it again. To force clean role defaults, move both `rbac.json` and the identity database out of `data_dir` before restart. Local Linux accounts and passwords are untouched. A UID 0 or `sudo`/`wheel` user retains full WebNAS access.

## Required tools

The server needs PAM and the standard account tools supplied by `passwd` on Debian-like systems or `shadow-utils` on RHEL-like systems. Disk quotas additionally require `setquota` from the `quota` package. The WebNAS installer installs these dependencies; no shell command strings are evaluated.
