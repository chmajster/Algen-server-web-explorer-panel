# Authentication modes

WebNAS has two mutually exclusive global authentication modes.

## 1. Local database — default

`Local database` is the default mode. The login page accepts only users stored in WebNAS' application-owned `local-auth.sqlite3` database. PAM and LDAP are not offered while this mode is active.

Local-user records contain the username, enabled state, display name, WebNAS role, home metadata and timestamps. Passwords are stored only as salted `scrypt` hashes. Plaintext passwords are never written to the user database, application logs, audit events or browser-readable APIs.

### Initial administrator

A fresh standard installation creates this Local database administrator:

```text
username: chris
password: 1
role: admin
```

The password is stored in `local-auth.sqlite3` only as a salted `scrypt` hash; plaintext `1` is not stored in SQLite. The installer supplies this short bootstrap password through a dedicated first-user path that is available only while the Local database is empty. Normal local-user creation and password changes still require 12–1024 characters.

The installer prints the default account and warns that the password must be changed immediately after the first login. Updates and reinstalls preserve an already initialized Local user database instead of recreating or resetting `chris`.

### Local user management

Administrators can manage local accounts from **Settings → Administration → Authentication**:

- create users;
- assign `admin`, `operator`, `auditor` or `user` roles;
- enable/disable accounts;
- reset passwords;
- delete accounts;
- inspect whether a POSIX mapping is available.

The last enabled local administrator cannot be disabled, downgraded or deleted. A signed-in local account cannot delete itself.

Local users can change their own password through the standard account settings flow. The current password is verified against the local WebNAS hash before the new hash is written.

### POSIX mapping

WebNAS performs filesystem operations under a Unix UID/GID. A standard installation therefore creates or reuses a safe POSIX mapping for each local WebNAS user.

When no suitable account already exists and the privileged broker is enabled, WebNAS creates a Linux companion account using a dedicated UID/GID, home directory, a `nologin` shell and a locked system password. The WebNAS password is never copied to `/etc/shadow`.

The companion account is an execution identity, not an authentication source. In Local database mode authentication is performed only by WebNAS.

If a safe POSIX mapping cannot be obtained after valid local credentials are supplied, WebNAS fails the login rather than creating a session that would later break the filesystem security boundary.

Deleting a WebNAS local user does not automatically delete an existing POSIX identity because that operating-system account may predate WebNAS or be used by another service.

## 2. PAM + LDAP system authentication

`PAM + LDAP` is the alternative global mode. When enabled, Local database users are not accepted by the login API.

PAM is always available in this mode. LDAP is independently configurable and disabled by default.

### LDAP disabled

The login screen is effectively the historical PAM form:

```text
Username
Password
Log in
```

No provider selector is displayed.

### LDAP enabled

The login screen exposes:

```text
Authentication method
[ LDAP ] [ PAM ]

Username
Password
Log in
```

LDAP is selected by default for every new visit to the login page. Users can manually select PAM without reloading the page.

There is no automatic fallback:

- LDAP failure never invokes PAM;
- PAM failure never invokes LDAP;
- the selected provider remains selected after an error.

Both providers use the same session store, CSRF controls, central RBAC and login rate limiter.

See [LDAP_AUTHENTICATION.md](LDAP_AUTHENTICATION.md) for directory configuration and security details.

## Switching modes

The authentication mode is changed from **Settings → Administration → Authentication**.

The modes are mutually exclusive:

```text
Local database
OR
PAM + optional LDAP
```

Switching modes invalidates all active WebNAS sessions. This is intentional: a session authenticated under one identity namespace cannot remain active after the application moves to another namespace.

Switching back to Local database is rejected unless at least one enabled local administrator exists.

## Public login configuration

The login page obtains only nonsensitive authentication state from:

```text
GET /api/auth/config
```

Local mode example:

```json
{
  "mode": "local",
  "local_enabled": true,
  "pam_enabled": false,
  "ldap_enabled": false,
  "available_providers": ["local"],
  "default_provider": "local"
}
```

System mode with LDAP example:

```json
{
  "mode": "system",
  "local_enabled": false,
  "pam_enabled": true,
  "ldap_enabled": true,
  "available_providers": ["ldap", "pam"],
  "default_provider": "ldap"
}
```

This endpoint never returns password hashes, LDAP hosts, DNs, TLS configuration, Bind Passwords, session tokens or other secrets.

## Login API

The existing login endpoint remains authoritative:

```text
POST /api/auth/login
```

The browser explicitly includes the selected provider:

```json
{
  "username": "alice",
  "password": "secret",
  "auth_method": "local"
}
```

or, in system mode:

```json
{
  "username": "alice",
  "password": "secret",
  "auth_method": "ldap"
}
```

The backend validates the global mode and provider availability. Supplying `pam`/`ldap` in Local mode, or `local` in System mode, is rejected rather than silently redirected to another provider.

When `auth_method` is omitted, the backend follows the current UI default:

- Local mode → `local`;
- System mode, LDAP disabled → `pam`;
- System mode, LDAP enabled → `ldap`.

## Session and rate-limit isolation

Sessions record the actual `auth_provider` (`local`, `pam` or `ldap`) for auditing and identity handling. Old session database schemas are migrated with `pam` as the compatibility value for pre-feature sessions.

The brute-force limiter is keyed by source IP and username rather than provider. Switching between LDAP and PAM does not reset the failure budget.

## Authorization

Authentication and authorization remain separate.

- Local database, PAM and LDAP establish identity.
- WebNAS RBAC decides what that identity can do.
- Local users use their WebNAS database role.
- PAM/Linux administrator compatibility applies only to the system identity namespace.
- LDAP identities do not automatically inherit WebNAS Administrator from `sudo`, `wheel`, `Domain Admins` or another directory group.

Authentication mode changes do not create a second authorization subsystem.

## Password handling

### Local database

- salted `scrypt` hashes;
- random per-password salts;
- minimum 12-character password at the API boundary;
- constant-style dummy verification for unknown usernames;
- plaintext exists only in process memory while credentials are being created, submitted or verified;
- the fresh-install bootstrap account is `chris` with default password `1`; SQLite stores only its salted `scrypt` hash;
- the short password is accepted only by the empty-database installer bootstrap path; normal password APIs retain the 12-character minimum;
- password changes replace the hash and never expose it through an API.

### PAM

Passwords are passed only to the configured PAM authentication operation and are not stored by WebNAS.

### LDAP

User passwords are used only for the user-DN bind. The service Bind Password is stored in encrypted Secrets Manager storage. See [LDAP_AUTHENTICATION.md](LDAP_AUTHENTICATION.md).