# LDAP Authentication

LDAP Authentication is the WebNAS login provider configured under **Settings → Authentication → LDAP Authentication**. It is not an installable module and it is completely independent from [LDAP Manager](LDAP_MANAGER.md).

```text
WebNAS user
  -> LDAP Authentication
  -> WebNAS identity
  -> existing WebNAS RBAC
  -> WebNAS session
```

LDAP Manager instead lets an administrator manage remote directories. Its connections, database and credentials are never used by LDAP Authentication.

## Authentication modes

WebNAS exposes explicit `local`, `pam` and `ldap` login providers according to the active global authentication mode. In System authentication mode PAM is available and LDAP can be enabled independently. When LDAP is enabled the login page lets the user select LDAP or PAM.

There is no automatic provider fallback. An LDAP credential failure never invokes PAM, and a PAM credential failure never invokes LDAP. LDAP failover is limited to alternative servers belonging to the same LDAP Authentication configuration.

## Configuration

LDAP Authentication supports:

- enabled/disabled state;
- directory type: generic LDAP, Active Directory or FreeIPA-aware identity handling;
- multiple LDAP servers with host, port, priority and enabled state;
- failover strategy: priority or round robin;
- optional DNS SRV discovery;
- LDAP, LDAP + StartTLS and LDAPS;
- TLS certificate verification, enabled by default;
- optional custom CA certificate;
- connection and operation timeouts;
- Base DN and User Search Base;
- User Search Filter and Username Attribute;
- configurable immutable identity attribute;
- Bind DN and dedicated Bind Password;
- Display Name and Email attributes;
- Group Search Base, Group Search Filter and membership attribute;
- controlled group-cache TTL;
- LDAP-group-to-WebNAS-role/permission mappings;
- access allow/deny policy;
- diagnostics and explicit identity-policy refresh.

The primary API is rooted at:

```text
/api/settings/authentication/ldap
```

Subresources include `/servers`, `/group-mappings`, `/access-policy`, `/diagnostics`, `/test` and `/refresh`.

## Multiple servers and failover

Example:

```text
dc01.company.local:636 priority 10
dc02.company.local:636 priority 20
dc03.company.local:636 priority 30
```

With `priority`, WebNAS tries servers in priority order when connection/TLS/service-bind failures make the preferred server unavailable. With `round_robin`, the first candidate rotates while preserving failover across the complete set.

DNS SRV discovery can supplement configured endpoints, for example `_ldap._tcp.dc._msdcs.company.local` for Active Directory.

Invalid user credentials do not trigger authentication against PAM or another WebNAS provider.

## Dedicated service credential

LDAP Authentication owns a read-oriented service credential, typically:

```text
CN=webnas-auth,OU=Service Accounts,DC=company,DC=local
```

Its Bind Password is stored only through the existing Secrets Manager as `auth-ldap-bind-password`. The authentication settings database stores only the secret identifier. API responses expose only:

```json
{
  "bind_password_configured": true
}
```

The Bind Password and secret identifier are never returned to the browser.

LDAP Manager connections own different Secrets Manager entries such as `ldap-manager-connection-<id>-bind-password`. Credentials are never copied between these subsystems.

## User lookup and injection protection

The User Search Filter must contain `{username}` exactly once. Usernames are escaped as LDAP filter values according to RFC4515 before substitution. Authentication requires exactly one matching entry and verifies the configured username attribute against the requested username.

Group-search templates similarly escape `{username}` and `{dn}` as LDAP filter values. Directory-management DN/RDN construction belongs to LDAP Manager and uses DN parsing/escaping separately.

## Stable LDAP identity

LDAP identity is not keyed only by username. WebNAS stores a stable immutable identifier:

- Active Directory: `objectGUID` by default;
- OpenLDAP: `entryUUID`;
- FreeIPA: `ipaUniqueID`/`entryUUID` where available;
- or a configured immutable-ID attribute.

Stored identity metadata includes provider, immutable ID, username, canonical username, DN, display name, email, POSIX UID/GID/home, first-seen, last-seen and last-login timestamps plus controlled group-cache metadata.

A username or DN rename for the same immutable identity therefore does not create a new WebNAS identity or intentionally discard its RBAC history.

Local/PAM/LDAP namespaces remain isolated. A local account and an LDAP account with the same username are not automatically merged.

## POSIX/NSS requirement

LDAP credentials establish directory identity, but WebNAS filesystem operations still need a Unix execution identity. The authenticated account must therefore resolve through NSS, for example SSSD, nslcd/libnss-ldapd or winbind:

```bash
getent passwd alice
```

UID `0`, configured system-service UID ranges and invalid/non-absolute home mappings are rejected.

## LDAP group → WebNAS RBAC

Mappings reuse the existing Identity/RBAC system. They do not create a second authorization engine.

Example:

```text
CN=WebNAS-Admins,OU=Groups,DC=company,DC=local
  -> role: admin

CN=Storage-Team,OU=Groups,DC=company,DC=local
  -> role: user
  -> allow: storage.read, storage.manage, files.read
  -> deny: users.manage
```

When multiple mappings apply, explicit deny permissions remove matching allows. LDAP-derived policy is written through the existing WebNAS Identity repository.

## Access policy

Supported modes:

- allow all matched LDAP users;
- allow only users matching configured LDAP-group mappings.

Optional allow-group and deny-group sets further restrict access. Deny takes precedence over allow.

Changing group mappings or access policy invalidates active LDAP sessions. Session validation also refreshes LDAP group membership according to the configured TTL; a manual refresh endpoint is available. If membership no longer permits access, the LDAP identity's sessions are revoked.

## Session model

Every WebNAS session records at least username, `auth_provider` and `identity_id`. LDAP sessions use `auth_provider=ldap` and the immutable LDAP identity ID. This prevents provider collisions and enables targeted revocation.

The existing HttpOnly/SameSite cookie policy, CSRF protection, persistent session store and login rate limiter are reused unchanged.

## Preflight and break-glass behavior

Enabling LDAP Authentication first persists the candidate configuration disabled, validates it, and only then activates it. An evidently unreachable/broken LDAP configuration remains disabled. A mapped-groups-only policy additionally requires at least one configured mapping.

The global Local database authentication mode remains the break-glass path. Switching authentication modes uses the existing last-administrator protection and session invalidation rules documented in [AUTHENTICATION.md](AUTHENTICATION.md).

## Diagnostics

LDAP Authentication diagnostics report sanitized steps such as:

```text
DNS resolution
TCP connection
TLS handshake
Certificate verification
Service bind
Base DN search
User search
Group lookup
NSS user resolution
POSIX UID/GID
Home
RBAC mapping
Overall health
```

Diagnostics never return Bind Passwords, user passwords, Secrets Manager identifiers or raw stack traces.

## OpenLDAP example

```text
Servers:             ldap01.example.com:636, ldap02.example.com:636
Security:            LDAPS
Verify TLS:          enabled
Base DN:             dc=example,dc=com
User Search Base:    ou=People,dc=example,dc=com
Username Attribute: uid
Immutable ID:        entryUUID
User Search Filter:  (uid={username})
Bind DN:             cn=webnas-auth,ou=Services,dc=example,dc=com
```

Typical POSIX attributes include `uidNumber`, `gidNumber` and `homeDirectory`.

## Active Directory example

```text
Servers:             dc01.company.local:636, dc02.company.local:636
Security:            LDAPS
Verify TLS:          enabled
Base DN:             DC=company,DC=local
User Search Base:    OU=Users,DC=company,DC=local
Username Attribute: sAMAccountName
Immutable ID:        objectGUID
User Search Filter:  (sAMAccountName={username})
Bind DN:             CN=webnas-auth,OU=Service Accounts,DC=company,DC=local
```

SSSD or winbind can provide the POSIX identity required by filesystem features.

## FreeIPA example

Use StartTLS or LDAPS with a dedicated read-only service identity, `uid` for login lookup, `ipaUniqueID`/`entryUUID` for immutable identity where available, and SSSD for NSS/POSIX mapping.

## Security properties

- TLS certificate verification defaults to enabled and is scoped per LDAP configuration.
- RFC4515 escaping is mandatory for values inserted into LDAP filters.
- More than one user-search result is an authentication failure.
- The service Bind Password is stored only in Secrets Manager.
- User passwords are transient and never written to SQLite, Activity, Audit or logs.
- Source-IP + username rate limiting is shared across login providers, so switching providers does not reset the brute-force budget.
- LDAP users never inherit WebNAS administrator status merely because Linux NSS reports `sudo`/`wheel` membership.
- Changing LDAP policy can invalidate active LDAP sessions.
- LDAP Authentication does not depend on LDAP Manager being installed or enabled.