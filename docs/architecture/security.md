# Security boundaries

The modular composition preserves PAM authentication, server-side sessions, CSRF, RBAC, audit logging, path policy and Proxmox Safe Mode.

Rules for system adapters:

- commands are argument arrays and never use `shell=True`;
- programs, services and actions come from closed enums or allowlists;
- user paths pass through the central path policy;
- writes are atomic where state or configuration integrity matters;
- logs and job errors redact credentials, cookies, tokens and authorization headers;
- downloaded manifests are data only and cannot declare executable code;
- secrets are passed through explicit secret DTOs and are never durable job payloads.

The module catalog endpoint requires an authenticated session. Diagnostics must not expose secrets or arbitrary host paths.
