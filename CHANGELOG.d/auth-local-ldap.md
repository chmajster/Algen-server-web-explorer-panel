# Authentication

- Add an application-owned local user database as the default WebNAS authentication mode, with salted scrypt password hashes, a random one-time bootstrap administrator credential, local user/role management, and locked POSIX execution mappings.
- Add a mutually exclusive PAM + optional LDAP system authentication mode. When LDAP is enabled, LDAP and PAM are both available on the login page, LDAP is selected by default, and there is no automatic provider fallback.
- Add LDAP/StartTLS/LDAPS configuration, encrypted Secrets Manager storage for the Bind Password, Test LDAP Connection, RFC4515 filter escaping, NSS/POSIX identity validation, provider-aware sessions and identity-collision protections.
- Invalidate active sessions when the global authentication mode changes.
