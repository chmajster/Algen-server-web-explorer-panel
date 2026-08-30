# Authentication

- Add an application-owned local user database as the default WebNAS authentication mode, with salted scrypt password hashes, a random one-time bootstrap administrator credential delivered by the standard installer, local user/role management, and locked POSIX execution mappings. The temporary recoverable bootstrap copy is encrypted in Secrets Manager and deleted after retrieval; no plaintext password file is created.
- Add a mutually exclusive PAM + optional LDAP system authentication mode. When LDAP is enabled, LDAP and PAM are both available on the login page, LDAP is selected by default, and there is no automatic provider fallback.
- Add LDAP/StartTLS/LDAPS configuration, encrypted Secrets Manager storage for the Bind Password, Test LDAP Connection, RFC4515 filter escaping, NSS/POSIX identity validation, provider-aware sessions and identity-collision protections.
- Invalidate active sessions when the global authentication mode changes.
- Update standard installation for Local database bootstrap and keep portable mode explicitly on System/PAM because portable mode does not install the privileged broker required for Local POSIX companion provisioning.