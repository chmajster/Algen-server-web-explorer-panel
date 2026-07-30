# Hosts Manager

Hosts Manager (`hosts-manager`) is the central WebNAS registry for remote servers. Its source of truth is the private, versioned SQLite database at `/var/lib/webnas/hosts-manager/hosts.sqlite3`. Other modules use `HostRegistryService`; they must not open this database directly.

## Architecture and migration

The registry owns hosts, environments, APMIDs, groups/memberships, connection credentials, accepted SSH keys, sanitized facts, enrollment tokens, hostname patterns and reservations, agent identities/reports/version history, Git repository assignments, power profiles and host-correlated operations. Schema version 5 adds APMID records, durable APMID–environment–group relations and APMID/environment/managed-group references on new enrollment tokens. Startup migrations use additive, idempotent DDL and retain every existing row; historical tokens without those references remain valid.

At first initialization the service detects the Ansible database, creates a mode-`0600` SQLite backup, and transactionally copies central records. Host/group IDs are unchanged, so templates, `host_ids_json`, schedules, history and per-host results remain valid. Credential envelopes are re-encrypted with `/var/lib/webnas/secrets/hosts-manager.key`. A migration marker makes the operation idempotent. Legacy tables remain as a rollback artifact, but the production Ansible adapter no longer writes registry data there.

## Security

The data directory is `0700`; databases, backups, keys and secret-bearing artifacts are `0600`. Credential APIs return metadata and `secret_configured`, never plaintext or an envelope. Backend consumers supply a module and purpose to `verified_credential`. Variables and agent reports reject secret-like keys. Facts use an allowlist and hash `machine-id`. Agent tokens are stored only as salted hashes; each identity rotation invalidates the previous salt and returns the new raw token once.

Remote addresses reject loopback, unspecified and multicast targets. Discovery accepts bounded private networks. SSH uses fixed argument arrays, timeouts and `StrictHostKeyChecking=yes`. Enrollment never grants SSH trust: a host cannot connect until its SHA-256 fingerprint is scanned, compared out of band and explicitly accepted. A changed key blocks trust.

## Enrollment and inventory

An APMID identifies the team or application that owns an agent. Codes are trimmed, normalized to uppercase and restricted to letters, digits, `_` and `-`. For every active APMID and active environment, Hosts Manager transactionally maintains one uppercase group named `<APMID>.<ENVIRONMENT_SLUG>`. The `apmid_environment_groups` table is the source of the relation; group names are not parsed to recover ownership. Creating or renaming either side synchronizes the related groups, conflicts roll the transaction back, repeated synchronization is idempotent, and managed groups cannot be renamed or deleted through the manual group API.

The script generator requires an active environment and APMID. The backend derives the managed group from those two IDs, stores all three references on the token, and rejects attempts to submit another APMID-managed group as a manual group. Enrollment assigns the host to the selected environment, the derived managed group and any additional active manual groups. SSH user, SSH port and SSH credential are intentionally not part of script enrollment; the historical database columns remain only for migration compatibility. Manual hosts, discovery, Ansible and agent installation over SSH keep their SSH settings.

One-time token creation atomically reserves the next hostname from the selected pattern with `BEGIN IMMEDIATE`. Multiple patterns can define independent prefix, suffix, digit width, start and step values. Reservations are case-insensitive, monotonic and never released after use, expiry, revocation or host deletion. Administrators can explicitly skip values, but cannot rewind a sequence.

Tokens are cryptographically random and stored only as SHA-256 hashes. One-time tokens require a lifetime from 1 to 525600 minutes and reserve an exact hostname. Permanent tokens ignore any submitted lifetime, store `expires_at = 0`, can enroll multiple hosts and can be bound to one private IP address; they remain explicitly revocable. The raw value is returned once. Linux `.sh` and Windows PowerShell `.ps1` scripts are downloaded without an administrator cookie from `/enrollment-script`, using the active token only in the `Authorization: Bearer` header. Responses are `no-store`; inactive tokens fail closed, including after a WebNAS restart.

Both scripts require HTTPS/TLS 1.2, support `WEBNAS_ENROLL_ADDRESS`, collect bounded system metadata and do not configure SSH or modify the firewall. Optional hostname changes use `hostnamectl` with a non-systemd fallback on Linux and `Rename-Computer` without an automatic reboot on Windows. `/enroll` atomically consumes one-time tokens, requires the reserved hostname and retains glob matching only for migrated legacy tokens. Every enrolled host remains unapproved with an unverified SSH fingerprint.

Before generating a script or starting SSH onboarding, configure the public HTTPS Hosts Manager URL in Settings. The backend refuses to derive installer URLs from an untrusted request host header or to generate an HTTP installer.

## Linux agent

The dependency-free Python agent supports Debian/Ubuntu/Raspberry Pi OS, Fedora/RHEL/Rocky/Alma/CentOS, openSUSE/SLES, Arch/Manjaro, Alpine and Proxmox. The Linux installer downloads the agent, writes a private JSON document compatible with YAML 1.2 to `/etc/hosts-manager-agent/config.yaml`, stores the one-time returned identity under `/var/lib/hosts-manager-agent/state.json` and starts a systemd or OpenRC service. A cron/nohup fallback is available where neither init system is present.

The agent sends heartbeats and bounded inventory reports over HTTPS. Reports cover OS/DMI identity, CPU, memory, disks, filesystems, network interfaces, services, package-manager metadata, repositories and update counts. It uses fixed subprocess argument arrays, command timeouts, retries with backoff and rotating logs. It never reports credential values. Reinstalling or rotating an identity invalidates its old salt and token; manual invalidation moves the host to `authentication_required`.

Configuration, installation, removal and troubleshooting are documented in [docs/HOSTS_MANAGER_AGENT.md](docs/HOSTS_MANAGER_AGENT.md).
The repository also includes `.env.example` for selecting the WebNAS YAML configuration and for the optional standalone agent installer variables; enrollment token values must remain empty until generated for a specific installation.

Inventory endpoints validate/preview YAML, JSON and Ansible YAML/INI before confirmed import. Export is generated from active central hosts/groups and rejects plaintext secrets.

## Repositories, power and capabilities

Git repositories accept validated HTTPS/SSH URLs without embedded credentials and safe revisions. Fixed Git argument lists disable submodules and write only under the managed repository directory.

Power profiles model `none`, Wake-on-LAN, Redfish, IPMI and Proxmox. Wake-on-LAN uses a UDP socket and reports `request_sent`, not a false boot confirmation. Shutdown/reboot require granular permissions, a plan, explicit confirmation and the exact host name. Unavailable provider clients fail closed.

External modules register `HostCapabilityProvider` entries with an ID, permission, availability predicate, plan and durable execution callback. Hosts Manager lists only real, available capabilities and re-checks the provider permission. Ansible registers connection test, facts, managed-key rotation and playbook launch; job payloads contain stable IDs, not credentials.

## API and permissions

The `/api/modules/hosts-manager` API covers dashboard/host CRUD and CSV export, environments, APMID CRUD and group synchronization, hostname patterns/skips, approval, fingerprints, test/facts, agent heartbeat/report/history/identity rotation, capability plan/execute, groups, inventory, one-time and permanent enrollment, discovery, credentials, repositories, power, operations/SSE, diagnostics and checksummed backups. APMID endpoints are `/apmids` and `/apmids/sync-groups`; reads use the view permission and mutations use host-management permission. `GET /settings` requires `hosts-manager.view`; `PUT /settings` requires `hosts-manager.configure`. Agent and installer endpoints use scoped Bearer tokens and do not require a browser session.

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
2. Create two hostname patterns, skip one value and confirm each sequence remains monotonic.
3. Create an APMID, verify its uppercase groups for every active environment, then generate a one-time Linux script and confirm the new host receives the selected environment and managed group.
4. Generate an IP-bound permanent token, enroll two hosts and then revoke it.
5. Verify the Linux agent service, heartbeat, inventory report, rotating identity and invalidation flow.
6. Approve it; scan, independently compare and accept its SSH fingerprint.
7. Test SSH and gather facts, then verify Ansible Controller shows the same host ID.
8. Select the host in a template and launch a playbook from both applications.
9. Review and launch managed-key rotation.
10. Configure Wake-on-LAN and verify the result says only that a request was sent.
11. Assign/sync a Git repository and inspect its recorded commit.
12. Create/validate/restore a backup and verify operator/auditor RBAC restrictions.
