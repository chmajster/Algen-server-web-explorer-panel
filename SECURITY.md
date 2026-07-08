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

For production, set a strong `security.session_secret`, enable HTTPS at a reverse proxy or through configured TLS, and review whether `/home` is the correct `ReadWritePaths` boundary for your server.
