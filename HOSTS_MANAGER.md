# Hosts Manager

Hosts Manager (`hosts-manager`) is the central WebNAS registry for remote servers. Its source of truth is the private, versioned SQLite database at `/var/lib/webnas/hosts-manager/hosts.sqlite3`. Other modules use `HostRegistryService`; they must not open this database directly.

## Architecture and migration

The registry owns hosts, groups/memberships, connection credentials, accepted SSH keys, sanitized facts, enrollment tokens, hostname settings and reservations, Git repository assignments, power profiles and host-correlated operations. Schema version 2 adds the settings, monotonic sequence and permanent reservation tables plus the Linux/Windows bootstrap fields on existing enrollment tokens. Startup migrations use additive, idempotent DDL and retain every existing row.

At first initialization the service detects the Ansible database, creates a mode-`0600` SQLite backup, and transactionally copies central records. Host/group IDs are unchanged, so templates, `host_ids_json`, schedules, history and per-host results remain valid. Credential envelopes are re-encrypted with `/var/lib/webnas/secrets/hosts-manager.key`. A migration marker makes the operation idempotent. Legacy tables remain as a rollback artifact, but the production Ansible adapter no longer writes registry data there.

## Security

The data directory is `0700`; databases, backups, keys and secret-bearing artifacts are `0600`. Credential APIs return metadata and `secret_configured`, never plaintext or an envelope. Backend consumers supply a module and purpose to `verified_credential`. Variables reject secret-like keys. Facts use an allowlist and hash `machine-id`.

Remote addresses reject loopback, unspecified and multicast targets. Discovery accepts bounded private networks. SSH uses fixed argument arrays, timeouts and `StrictHostKeyChecking=yes`. Enrollment never grants SSH trust: a host cannot connect until its SHA-256 fingerprint is scanned, compared out of band and explicitly accepted. A changed key blocks trust.

## Enrollment and inventory

Token creation atomically reserves the next hostname from the configured template (default `SCL000XXX`) with `BEGIN IMMEDIATE`. Reservations are case-insensitive, monotonic and never released after use, expiry, revocation or host deletion. Existing hosts and reservations determine the next number whenever a template is saved.

Each token is cryptographically random, single-use and valid for at most 60 minutes; only its SHA-256 hash is stored. The raw value is returned once and is never kept in process memory. Linux `.sh` and Windows PowerShell `.ps1` scripts are downloaded without an administrator cookie from `/enrollment-script`, using the active token only in the `Authorization: Bearer` header. Responses are `no-store`; expired, used and revoked tokens fail closed, including after a WebNAS restart.

Both scripts require HTTPS/TLS 1.2, support `WEBNAS_ENROLL_ADDRESS`, collect bounded system metadata and do not install packages, configure SSH or modify the firewall. Optional hostname changes use `hostnamectl` on Linux and `Rename-Computer` without an automatic reboot on Windows. `/enroll` atomically consumes the bearer token, requires an exact match for newly assigned hostnames and retains glob matching only for migrated legacy tokens. Every enrolled host remains unapproved with an unverified SSH fingerprint.

Inventory endpoints validate/preview YAML, JSON and Ansible YAML/INI before confirmed import. Export is generated from active central hosts/groups and rejects plaintext secrets.

## Repositories, power and capabilities

Git repositories accept validated HTTPS/SSH URLs without embedded credentials and safe revisions. Fixed Git argument lists disable submodules and write only under the managed repository directory.

Power profiles model `none`, Wake-on-LAN, Redfish, IPMI and Proxmox. Wake-on-LAN uses a UDP socket and reports `request_sent`, not a false boot confirmation. Shutdown/reboot require granular permissions, a plan, explicit confirmation and the exact host name. Unavailable provider clients fail closed.

External modules register `HostCapabilityProvider` entries with an ID, permission, availability predicate, plan and durable execution callback. Hosts Manager lists only real, available capabilities and re-checks the provider permission. Ansible registers connection test, facts, managed-key rotation and playbook launch; job payloads contain stable IDs, not credentials.

## API and permissions

The `/api/modules/hosts-manager` API covers dashboard/host CRUD, approval, fingerprints, test/facts, capability plan/execute, groups, inventory, enrollment, discovery, credentials, repositories, power, operations/SSE, diagnostics and checksummed backups. `GET /settings` requires `hosts-manager.view`; `PUT /settings` requires `hosts-manager.configure`. The public script download endpoint accepts an enrollment Bearer token but no browser session.

Permissions are:

- `hosts-manager.view`, `hosts-manager.hosts.view`, `hosts-manager.hosts.manage`, `hosts-manager.hosts.approve`
- `hosts-manager.discovery`, `hosts-manager.inventory.manage`
- `hosts-manager.credentials.view`, `hosts-manager.credentials.manage`
- `hosts-manager.repositories.view`, `hosts-manager.repositories.manage`
- `hosts-manager.power.view`, `hosts-manager.power.on`, `hosts-manager.power.shutdown`, `hosts-manager.power.reboot`
- `hosts-manager.actions.execute`, `hosts-manager.passwords.rotate`, `hosts-manager.audit.view`
- `hosts-manager.backup`, `hosts-manager.restore`, `hosts-manager.configure`

Administrators receive all permissions. Operators manage hosts and safe actions without credential/restore access. Auditors read hosts and audit data. Users have no access by default.

## Backup, restore and uninstall

Backup creates a consistent SQLite snapshot and versioned manifest in a checksummed archive. Restore validates checksum, member paths/sizes and SQLite integrity, creates a safety backup, then atomically replaces the database. Uninstall preserves registry data by default. Full removal is a separate high-risk operation requiring the exact text `Hosts Manager`; it never changes remote accounts or keys.

## Manual verification

1. Install/open Hosts Manager and add a private-network host.
2. Configure `SCL000XXX`, generate Linux and Windows scripts, confirm consecutive reserved names, enroll the exact assigned hostname and verify token reuse fails.
3. Approve it; scan, independently compare and accept its SSH fingerprint.
4. Test SSH and gather facts, then verify Ansible Controller shows the same host ID.
5. Select the host in a template and launch a playbook from both applications.
6. Review and launch managed-key rotation.
7. Configure Wake-on-LAN and verify the result says only that a request was sent.
8. Assign/sync a Git repository and inspect its recorded commit.
9. Create/validate/restore a backup.
10. Verify operator/auditor RBAC restrictions.
