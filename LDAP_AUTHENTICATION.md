# LDAP authentication

WebNAS supports two authentication methods:

- **PAM** for local Linux accounts defined in `/etc/passwd`;
- **LDAP** for directory identities authenticated against a configured LDAP-compatible directory.

LDAP authentication is disabled by default. Existing and upgraded installations therefore remain PAM-only until an administrator explicitly enables LDAP in **Settings → Administration → LDAP Authentication**.

## Login behaviour

When LDAP is disabled, the login page remains PAM-only and does not show an authentication-method selector.

When LDAP is enabled, the login page offers both **LDAP** and **PAM**. LDAP is selected by default. A user can manually select PAM before submitting the form.

There is **no automatic provider fallback**:

- a failed LDAP login never causes WebNAS to try PAM;
- a failed PAM login never causes WebNAS to try LDAP;
- an LDAP outage leaves LDAP selected and the user may manually choose PAM.

The login API accepts `auth_method: "ldap" | "pam"`. For backward compatibility, requests without `auth_method` use PAM while LDAP is disabled and LDAP while LDAP is enabled.

Public login configuration is available from:

```text
GET /api/auth/config
```

It returns only provider availability and the default provider. LDAP server addresses, DNs, TLS settings and secrets are never exposed by this endpoint.

## POSIX/NSS identity requirement

Successful LDAP credentials must also resolve to a POSIX identity through the host NSS stack, for example through:

- SSSD,
- nslcd/libnss-ldapd,
- winbind,
- another NSS provider that exposes the directory account through `getent passwd USERNAME` / `pwd.getpwnam()`.

This is required because WebNAS file operations execute under the authenticated Unix UID/GID. WebNAS does not create synthetic privileged Unix accounts for LDAP users.

A correctly integrated directory user should therefore return a Unix identity such as:

```bash
getent passwd alice
```

with a non-system UID and an absolute home directory.

LDAP identities mapped to UID `0` or below the configured WebNAS system-UID threshold are rejected.

## PAM and LDAP identity isolation

PAM is intentionally restricted to accounts physically defined in `/etc/passwd`. NSS-only directory accounts do not silently become PAM identities.

LDAP authentication rejects a username that collides with an existing local `/etc/passwd` account. This prevents an LDAP account named, for example, `admin` from inheriting the identity of a local PAM administrator.

After the first successful LDAP authentication, WebNAS records non-secret identity metadata in `ldap-auth.sqlite3`. This record lets RBAC distinguish the LDAP identity from Linux administrator semantics.

An LDAP user does **not** automatically become a WebNAS administrator because NSS reports membership in `sudo` or `wheel`. LDAP authentication starts in normal WebNAS RBAC. Administrators may explicitly assign WebNAS roles/policies after the LDAP identity has been established.

No LDAP group such as `Domain Admins` is automatically mapped to the WebNAS Administrator role.

## LDAP configuration

The LDAP settings page provides:

- Enable LDAP authentication;
- LDAP server / URI;
- port;
- security mode: LDAP, LDAP + StartTLS, or LDAPS;
- TLS certificate verification;
- connection timeout;
- operation/search timeout;
- Base DN;
- User Search Base DN;
- User Search Filter;
- Username Attribute;
- Bind DN;
- Bind Password;
- optional Display Name Attribute;
- optional Email Attribute.

TLS certificate verification is enabled by default. Disabling verification applies only to the configured LDAP connection; WebNAS does not disable TLS verification globally.

The search filter must contain `{username}` exactly once. WebNAS escapes the supplied username according to RFC4515 before inserting it into the filter. Authentication continues only when the search returns exactly one entry and the configured username attribute matches the requested username.

## OpenLDAP example

```text
LDAP server:          ldap.example.com
Port:                 389
Security:             LDAP + StartTLS
Verify TLS:           enabled
Base DN:              dc=example,dc=com
User Search Base:     ou=people,dc=example,dc=com
Username Attribute:  uid
User Search Filter:   (uid={username})
Bind DN:              cn=webnas,ou=services,dc=example,dc=com
```

The corresponding directory users should also be exposed through NSS with POSIX attributes such as `uidNumber`, `gidNumber` and `homeDirectory`, depending on the selected NSS integration.

## FreeIPA example

FreeIPA can use the same LDAP flow. A typical setup uses StartTLS or LDAPS, a dedicated read-only service account for search, `uid` as the username attribute, and SSSD on the WebNAS host for POSIX identity resolution.

## Microsoft Active Directory example

```text
LDAP server:          ad01.example.local
Port:                 636
Security:             LDAPS
Verify TLS:           enabled
Base DN:              DC=example,DC=local
User Search Base:     OU=Users,DC=example,DC=local
Username Attribute:  sAMAccountName
User Search Filter:   (sAMAccountName={username})
Bind DN:              CN=webnas-service,OU=Service Accounts,DC=example,DC=local
```

For filesystem-backed WebNAS features, configure an NSS integration such as SSSD or winbind so the authenticated AD account has a Unix UID, GID and home directory on the WebNAS host.

## Bind Password storage

The LDAP service-account Bind Password is stored through the existing WebNAS **Secrets Manager** encrypted storage. The LDAP settings database stores only the secret identifier.

Settings responses expose only:

```json
{
  "bind_password_configured": true
}
```

They never return the Bind Password or the Secrets Manager identifier. Leaving the password field empty while saving other LDAP settings preserves the existing encrypted secret. The secret can be explicitly removed only while LDAP is disabled.

User passwords supplied on the login screen are used only for the selected authentication operation and are never stored in the database, Activity Center or application logs.

## Authentication flow

LDAP login uses the following sequence:

```text
username + password
        |
        v
service-account bind
        |
        v
escaped user search
        |
        v
exactly one matching entry
        |
        v
bind as discovered user DN
        |
        v
validate PAM/LDAP namespace isolation
        |
        v
resolve POSIX UID/GID/home through NSS
        |
        v
existing WebNAS session + CSRF + RBAC
```

PAM and LDAP use the same session store, HttpOnly/SameSite cookie policy, CSRF protection, login rate limiter and central RBAC implementation. The session records `auth_provider` for identity isolation and auditing.

## Test LDAP Connection

The administrator-only **Test LDAP Connection** action validates the saved configuration by checking:

1. server connection;
2. TLS/StartTLS negotiation when configured;
3. certificate validation;
4. service-account bind;
5. execution of the configured search base/filter.

Returned errors are sanitized into connection, TLS, bind or search failures. Bind passwords, directory entries and library stack traces are not returned to the browser.

## Security notes

- LDAP filter values use RFC4515 escaping.
- More than one search result is an authentication failure; WebNAS never selects the first result.
- TLS verification is enabled by default.
- LDAP and PAM never fall back to one another automatically.
- Login rate limiting uses the same IP + username key regardless of selected provider, so switching providers does not reset the brute-force budget.
- LDAP users do not automatically inherit Linux `sudo`/`wheel` administrator status.
- Local `/etc/passwd` and LDAP namespaces cannot claim the same username through the two login providers.
- Authentication errors do not reveal whether the directory user exists or whether only the password was incorrect.
