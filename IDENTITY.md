# Users, groups, and application access

WebNAS uses an application-owned local user database as its default authentication mode. Administrators can alternatively switch the application to **PAM + LDAP system authentication**. The two global modes are mutually exclusive and active sessions are invalidated when the mode changes.

Local WebNAS passwords are stored only as salted `scrypt` hashes. PAM passwords and LDAP user passwords are never stored by WebNAS. The LDAP service Bind Password is stored through encrypted Secrets Manager storage.

See [AUTHENTICATION.md](AUTHENTICATION.md) for the global mode model and [LDAP_AUTHENTICATION.md](LDAP_AUTHENTICATION.md) for LDAP configuration.

## Architecture

The authorization implementation lives under `backend/app/identity/`:

- `linux_accounts.py` validates and performs controlled `useradd`, `usermod`, `userdel`, `groupadd`, `groupmod`, `groupdel`, `gpasswd`, `chpasswd`, `chage`, and `setquota` operations;
- `permissions.py` is the closed permission registry, built-in role matrix, compatibility map, and central FastAPI authorization dependency;
- `repository.py` stores versioned system-mode user/group application policies and change history in SQLite transactions;
- `migration.py` imports the legacy `rbac.json` once and creates a private backup;
- `service.py` calculates effective access and separates Local database identities from PAM/Linux and LDAP identity semantics;
- `router.py` serves `/api/identity/*` and compatible `/api/admin/users` and `/api/admin/groups` aliases;
- `backend/app/rbac.py` remains a compatibility façade for existing imports and `/api/rbac/*` clients.

Authentication state is handled by:

- `backend/app/local_auth.py` — local WebNAS users, salted password hashes, roles, global auth mode and POSIX companion mapping;
- `backend/app/auth.py` — PAM/local-Linux authentication;
- `backend/app/ldap_auth.py` — LDAP authentication and LDAP identity metadata;
- `backend/app/auth_api.py` — login provider selection and common session creation;
- `backend/app/auth_settings.py` — authentication mode and local-user administration;
- `backend/app/security.py` — shared persistent sessions, CSRF and login rate limiting.

The shared session store records `auth_provider=local|pam|ldap`.

## Authentication identity namespaces

### Local database

Local mode uses users stored in `<data_dir>/local-auth.sqlite3`. Their WebNAS role is stored with the application identity and does not inherit a system-mode policy merely because the same username exists elsewhere.

A standard deployment creates or reuses a safe POSIX mapping for a local WebNAS user so file operations can run under a Unix UID/GID. WebNAS-created companion accounts have a locked system password and `nologin`; the WebNAS password is never copied to `/etc/shadow`.

A local user's application role is authoritative in Local mode. Linux `sudo`/`wheel` membership does not replace that role with the Linux-admin compatibility shortcut.

### PAM

PAM is available only in System authentication mode. PAM is restricted to accounts physically defined in `/etc/passwd`. An NSS-only LDAP/SSSD account therefore does not silently become a PAM identity merely because `pwd.getpwnam()` can resolve it.

### LDAP

LDAP is optional inside System authentication mode. LDAP rejects a username that collides with an existing local `/etc/passwd` account. A first LDAP login also cannot inherit a pre-existing system-mode WebNAS user policy with the same username.

After a successful LDAP authentication, WebNAS records non-secret identity metadata in `ldap-auth.sqlite3`. An administrator may then explicitly assign WebNAS RBAC policy to that LDAP identity.

LDAP authentication requires the directory account to resolve through NSS to a non-system Unix UID, GID and absolute home directory. UID `0` and UIDs below `security.system_uid_threshold` are rejected for LDAP sessions.

## Effective permission calculation

### Local mode

Local database identities use the built-in role stored with the local WebNAS user:

```text
local WebNAS role
        |
        v
ROLE_PERMISSIONS
```

The current implementation intentionally does not reuse a PAM/LDAP user policy or Linux group policy solely because a local database account has the same username.

If a valid local session somehow lacks a safe POSIX mapping, file/transfer permissions are denied rather than allowing operations under an incorrect Unix identity. Normal standard deployments provision the mapping before completing local login.

### System mode

For a normal PAM/LDAP system identity, effective permissions are calculated from the built-in role and explicit WebNAS policies:

```text
role permissions
+ allows from applicable groups
+ individual user allows
- denies from applicable groups
- individual user denies
```

`deny` wins over ordinary allows. The API also returns `permission_sources`, so the UI can distinguish role, group, individual allow, and deny sources. Missing permission means denied.

For genuine PAM/local Linux identities, UID 0 and users whose supplementary or primary group is `sudo` or `wheel` are Linux administrators. They receive the Administrator role and every registered permission.

That Linux-admin shortcut does **not** apply to remembered LDAP identities or Local database identities. An LDAP user does not become a WebNAS Administrator merely because NSS exposes membership in `sudo`, `wheel`, `Domain Admins`, or another directory group.

UID 0 remains the PAM break-glass account in System mode: it must still have an interactive shell and successfully authenticate through the configured PAM service.

## Built-in roles

| Area | Administrator | Operator | Auditor | User |
|---|---|---|---|---|
| Own files/settings/transfers | Full | Full | Read-only where appropriate | Own scope |
| Users and groups | Full | Daily non-destructive operations; no administrator targets | Read-only | None |
| Roles and policy | Full | Read-only | Read-only | None |
| Modules/services/updates | Full | Operate and configure; no Package Center install/uninstall | Status, logs, diagnostics | None unless granted |
| Docker/DNS/databases/Home Assistant | Full | Operate/configure | Read-only | None unless granted |
| Global audit/system logs | Full | Own activity and selected system logs | Read-only global audit | Own activity |

The exact matrix is returned by `GET /api/identity/roles`; each permission includes category, operation, related WebNAS application IDs, risk, mutation flag, and localization keys.

Local database accounts select one of these built-in roles directly. System-mode accounts continue to use the existing user/group policy machinery where applicable.

## Local user administration API

Authentication administration is available under:

```text
GET  /api/settings/authentication
PUT  /api/settings/authentication
GET  /api/settings/authentication/local-users
POST /api/settings/authentication/local-users
PATCH /api/settings/authentication/local-users/{username}
DELETE /api/settings/authentication/local-users/{username}
POST /api/settings/authentication/local-password
```

Only administrators can create/delete/change roles for local users. A local signed-in user can use the local-password endpoint for its own password after the current password has been verified.

The last enabled local administrator cannot be disabled, downgraded or deleted. Switching into Local database mode is rejected if no enabled local administrator exists.

## System identity API

Principal existing identity endpoints remain available for Linux/system administration:

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

Every mutation requires a valid session, CSRF token, a concrete operation permission, and audit logging.

## Migration and storage

The existing policy database remains `<data_dir>/identity.sqlite3` with mode `0600`. It does not contain authentication passwords.

The Local database authentication store is `<data_dir>/local-auth.sqlite3` and defaults to `auth_mode=local`. Local password values are salted `scrypt` hashes.

The session database automatically adds `auth_provider` when upgrading an older schema. Historical sessions without the field receive the compatibility value `pam`.

LDAP settings remain stored separately in `<data_dir>/ldap-auth.sqlite3`; the service Bind Password itself lives in Secrets Manager.

Changing global authentication mode revokes all active sessions so a session created in one namespace cannot cross into the other mode.

## Initial local administrator

On an empty Local database, WebNAS creates an `admin` application account with a random password. The one-time credential is written with filesystem mode `0600` to:

```text
<data_dir>/initial-local-admin.txt
```

The file is removed after the first successful local admin login or after the password is changed. There is no static default password.

## Safety and Proxmox

System accounts below `security.system_uid_threshold`, root, administrative groups, `systemd-*`, `pve*`, and other protected Linux accounts/groups remain protected by the existing Linux-account and privileged-broker policies.

Local WebNAS user passwords are never passed to `useradd`, `usermod`, `chpasswd` or PAM. WebNAS-created POSIX companion accounts exist solely to provide a bounded UID/GID/home and are locked against system login.

Existing Proxmox Safe Mode checks remain in the Linux account adapter. When host user/group management is blocked, system identity mutations remain blocked even if the caller has an application permission.

## Emergency access recovery

### Local mode

Retrieve the initial credential before its first use with:

```bash
sudo cat /var/lib/webnas/initial-local-admin.txt
```

adjusting the path if `paths.data_dir` was changed.

If a local administrator still exists, its password can be reset through another local administrator in Settings. The last-admin protection prevents ordinary UI actions from removing all local administrators.

### System mode

When LDAP is enabled, PAM remains manually selectable. If LDAP is unavailable, select PAM on the login page; WebNAS never performs the fallback automatically.

Changing the global authentication mode requires administrator access and invalidates current sessions.

## Required tools

The standard server needs PAM and the account tools supplied by `passwd` on Debian-like systems or `shadow-utils` on RHEL-like systems. The privileged broker is used for locked POSIX companion identities and other controlled host mutations. Disk quotas additionally require `setquota` from the `quota` package.

LDAP authentication adds the pure-Python `ldap3` dependency. Directory users additionally require a host NSS integration appropriate to the environment (for example SSSD, nslcd or winbind) so `getent passwd USERNAME` resolves their POSIX identity.
