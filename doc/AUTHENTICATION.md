# Authentication

WebNAS authentication is intentionally separated from remote directory administration. Authentication establishes a WebNAS identity; the existing Identity/RBAC subsystem authorizes that identity.

## Global modes

WebNAS has two mutually exclusive global authentication modes.

### Local database

`Local database` is the default mode. Only application-owned local accounts are accepted. Their credentials are stored as salted password hashes in WebNAS and are not PAM or LDAP identities.

A fresh installation creates the configured bootstrap administrator and preserves existing local accounts during upgrades. Last-administrator protections prevent an administrator from accidentally removing the final usable local break-glass account.

### System authentication

System mode exposes PAM and, when configured, LDAP Authentication.

```text
System authentication
  ├── PAM
  └── LDAP Authentication (optional)
```

The login API distinguishes `local`, `pam` and `ldap`. A selected provider is authoritative for that login attempt. There is no automatic LDAP → PAM, PAM → LDAP or system-provider → local fallback after a credential failure.

When LDAP Authentication is enabled, the login screen exposes both LDAP and PAM so the user can explicitly choose a method. LDAP server failover occurs only among servers configured inside the LDAP provider.

See [LDAP_AUTHENTICATION.md](LDAP_AUTHENTICATION.md).

## PAM

PAM is a separate authentication provider. WebNAS uses the dedicated PAM service:

```text
/etc/pam.d/webnas
```

There is no fallback to `/etc/pam.d/login`. A missing WebNAS PAM policy is treated as a configuration/service error rather than silently changing authentication semantics.

The standard installer creates `/etc/pam.d/webnas` from the distribution's supported PAM base policy (`common-*` on Debian/Ubuntu/SUSE-style systems or `system-auth` on RHEL-family systems where present).

PAM passwords are passed only to PAM for the selected operation and are never stored by WebNAS.

## LDAP Authentication

LDAP Authentication belongs only to **Settings → Authentication**. It performs LDAP bind/search login, establishes a stable WebNAS LDAP identity, maps LDAP groups into the existing WebNAS RBAC system, evaluates login access policy and creates an ordinary WebNAS session.

It owns its own database and Secrets Manager service credential. It does not consume LDAP Manager connections or credentials.

## LDAP Manager is not authentication

[LDAP Manager](LDAP_MANAGER.md) is an optional Module Center module for remote LDAP/Active Directory/FreeIPA administration: directory browsing, users, groups, OUs, schema, import/export, diagnostics and bulk operations.

Installing, disabling or removing LDAP Manager must not change whether LDAP users can log in to WebNAS. Likewise, configuring LDAP Authentication must not implicitly create an LDAP Manager connection.

## Public login configuration

The browser obtains nonsensitive provider availability from:

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

System mode with LDAP enabled:

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

The public endpoint never returns LDAP hosts, DNs, TLS configuration, password hashes, Bind Passwords, secret IDs or session tokens.

## Login API

`POST /api/auth/login` accepts the selected provider explicitly:

```json
{
  "username": "alice",
  "password": "secret",
  "auth_method": "ldap"
}
```

The backend validates the active global mode and provider availability. Invalid provider/mode combinations are rejected rather than redirected to another provider.

## Identity namespaces

Local, PAM and LDAP identities do not collapse into one namespace merely because their usernames match.

Sessions store:

```text
username
auth_provider
identity_id
```

Local and PAM identities receive provider-qualified IDs. LDAP identities use a stable immutable directory identifier such as `objectGUID`, `entryUUID`, `ipaUniqueID` or a configured immutable-ID attribute.

This provider context is also used for targeted session revocation and prevents an LDAP user from inheriting Linux/PAM administrator semantics merely through a matching username.

## Sessions, CSRF and rate limiting

All providers reuse the same hardened WebNAS session subsystem, HttpOnly/SameSite cookie policy, CSRF protection and login rate limiter. Switching authentication mode invalidates existing sessions so a session from one identity namespace cannot remain active after changing namespaces.

LDAP access-policy/group changes can invalidate LDAP sessions independently. LDAP session validation refreshes directory group state according to the configured cache TTL.

The brute-force limiter is keyed by source IP and username, not provider, so switching between LDAP and PAM does not reset the failure budget.

## Authorization

Authentication providers do not create independent authorization systems.

- Local database establishes a local WebNAS identity and its WebNAS role.
- PAM establishes a Linux-backed system identity.
- LDAP Authentication establishes an LDAP identity and can derive WebNAS RBAC assignments from LDAP groups.
- WebNAS Identity/RBAC remains authoritative for permissions.
- LDAP Manager endpoints use the same WebNAS RBAC engine with granular `ldap.*` permissions.

## Break-glass and lockout protection

Local database authentication remains the application-controlled break-glass path. Mode changes reuse existing administrator-continuity protections. LDAP Authentication performs preflight validation before activation and saves a failing candidate disabled rather than activating an obviously unusable configuration.

## Password and secret handling

- Local database passwords are stored only as salted hashes.
- PAM passwords are transient and passed only to PAM.
- LDAP user passwords are transient and used only for the selected user bind.
- LDAP Authentication Bind Password is stored only by Secrets Manager.
- LDAP Manager connection Bind Passwords are separate Secrets Manager entries.
- Passwords and credentials are excluded from API responses, Activity/Audit details and exception text.