# Ansible Automation Controller

> Host ownership changed: hosts, groups, SSH connection credentials, fingerprints and facts now live in [Hosts Manager](HOSTS_MANAGER.md). Ansible Controller retains automation projects, playbooks, templates, schedules, executions/results and logical host locks. Its idempotent migration preserves existing host IDs and references.

The `ansible-controller` package is WebNAS's native `ansible-core` automation controller. It follows Tower/AWX concepts (inventory, projects, playbooks, job templates, schedules and per-host results) without installing the retired Ansible Tower product or deploying AWX/Kubernetes. An existing AWX or Red Hat Automation Controller can be connected optionally.

## Architecture

Package installation, update and uninstall use the existing Package Center manifest, provider and durable job manager. Domain data is kept separately in the versioned SQLite database `/var/lib/webnas/ansible-controller/controller.sqlite3`. Long operations are Package Center `manage` jobs; their durable payloads contain stable object IDs and policy metadata, never credentials. Progress, bounded redacted logs, cancellation, retry and SSE therefore use the same mechanisms as other modules.

The typed module API is mounted at `/api/modules/ansible-controller`. The React application is registered in the common module shell and provides Dashboard, Hosts, Inventory, Discovery, Credentials, Projects, Playbooks, Templates, Jobs, Schedules, Facts, Settings, Diagnostics and Backups sections.

## Requirements and installation

Supported systems and architectures are declared in `backend/app/modules/ansible-controller/manifest.yaml`. Package Center installs system packages rather than running a global `pip install`:

- Debian, Ubuntu and Raspberry Pi OS: `ansible-core`, `openssh-client`, `nmap`, `git`, `python3`, `python3-venv`;
- Fedora, RHEL, Rocky and AlmaLinux: `ansible-core`, `openssh-clients`, `nmap`, `git`, `python3`.

Open Package Center, search for `Ansible`, `Tower` or `AWX`, review the plan and install **Ansible Automation Controller**. The install hook creates the non-login system account `webnas-ansible`, private directories and an Ed25519 controller key. No network port or separate service is opened.

All `ansible`, `ansible-playbook` and `ansible-inventory` processes run after supplementary groups, GID and UID have been dropped to that account. The account is not added to `sudo` or `wheel`. Directories are mode `0700`, private keys and transient credential files are mode `0600`, host-key verification is enabled, and execution directories are removed after success, error, timeout or cancellation.

## Security model

The backend owns executable names, command arguments, inventory paths and project paths. Subprocesses receive argument arrays with `shell=False`. Playbooks are rejected by default when they request controller-local execution (`connection: local`, local delegation, `local_action`), pipe lookups or user-supplied local action/callback/connection/lookup plugins. The isolated Ansible environment points plugin paths at system locations only.

Static analysis also warns about command-oriented modules, `become`, `all`, destructive-looking operations, firewall/network/user/sudoers changes and secret-like variables. This analysis is advisory and is not a security proof. Every saved or launched playbook is parsed with limits and is checked using fixed `ansible-playbook --syntax-check`, `--list-hosts`, `--list-tasks` and `--list-tags` invocations.

Mutations require an authenticated session, CSRF token, the exact granular permission and an explicit confirmation where the operation is sensitive. Package install/restore flows retain the framework's PAM gate. Domain changes are written to the controller audit table with actor, correlation ID, object, result and timestamp; central activity/audit records are created for queued operations. Redaction is applied recursively to passwords, passphrases, tokens, secrets, vault data and private keys.

## Credentials

Supported types are SSH private key, initial SSH password, become password, Git private key, AWX token and Ansible Vault secret. Secret material is encrypted before entering SQLite with an authenticated envelope. The master key is outside the database and mode `0600`. Credential read APIs return only ID, name, type, username, description and `secret_configured`; they never return the encrypted envelope or plaintext.

Secrets are not put in durable jobs, URL query strings, process arguments, logs, SSE, audit details or browser storage. Temporary files are private and deleted with the run directory. Initial passwords are transient unless an administrator deliberately creates a credential.

## Discovery and SSH fingerprints

The Discovery wizard accepts a CIDR/range, TCP SSH port, timeout, concurrency limit, optional group name and reverse-DNS preference. `ipaddress` validation permits RFC1918/local ranges and explicitly configured administrator ranges, caps a scan at 4096 addresses and rejects `/0`, public Internet sweeps, UDP, vulnerability or login scanning. `nmap` receives a fixed server-side argument list. Results are reviewed and selected hosts are imported; discovery never logs in or imports everything automatically.

Before SSH or Ansible is allowed, use **Scan key**, compare the displayed SHA-256 fingerprint through a trusted channel and explicitly accept it. The key is written to the module's private `known_hosts`. A changed key marks the host as changed and blocks connection until the replacement fingerprint is independently verified and explicitly accepted. `StrictHostKeyChecking=yes` remains active.

## Host onboarding and managed users

Onboarding records the target, initial user and credential, verifies the accepted host key, performs controlled SSH/Ansible probes and gathers facts. It can optionally create `algen-ansible` on the remote Linux host. The managed username has strict Linux-name validation.

The remote script is fixed by the backend. It creates the home and `.ssh`, installs the public key with `0700`/`0600` permissions and correct ownership, optionally writes `/etc/sudoers.d/<user>`, validates it with `visudo -cf`, and rolls back a newly created account or incomplete sudoers file after an error. Profiles are no sudo, password sudo, passwordless sudo and custom validated policy. `NOPASSWD: ALL` requires explicit confirmation and typing the host address. The initial account is never deleted.

## Inventory and facts

Hosts contain address, port, SSH user, credential reference, Python interpreter, connection type, environment, location, tags, variables, activity state and last-result metadata. Groups have variables, parent/child relationships and host membership. Generated inventory is placed only in a private backend-owned run directory.

YAML and INI imports are limited to 2 MiB and 5000 hosts, validate group names and reject plaintext secret keys. `ansible-inventory --list` and `--graph` run under `webnas-ansible` before import. Export returns generated YAML. Facts are collected with controlled `ansible.builtin.setup`, stored separately, redacted before API delivery and shown in the host/Facts views.

## Projects and playbooks

Projects support editor-managed content and controlled Git synchronization. Git URLs accept HTTPS or SSH forms without embedded passwords/tokens; branch/tag revisions are strictly validated. Commands contain no frontend-provided options. Submodules are blocked unless enabled, and symlinks escaping the managed project root are rejected. Sync history and the last commit are retained.

The editor provides line numbers, search, fullscreen mode, YAML errors, risk warnings and version history. Each save creates an immutable content version and checksum. Runtime files are snapshots; the frontend cannot submit a filesystem path. Restore an older version by loading it as a new current version so history remains append-only.

## Job templates, execution and schedules

A template selects a project/playbook, hosts/groups, SSH/become/Vault credential references, limit, tags, skipped tags, check/diff mode, verbosity, forks, timeout, validated extra variables, synchronization preference, confirmation and a concurrency policy. Plaintext secret-like extra-variable keys are rejected.

The launch plan shows the version/commit, targets, host count, modes, tags, credential requirements and risk warnings. Launch requires explicit confirmation. Each execution retains its actor, template snapshot metadata, host IDs, credential IDs, timestamps, stage, status, bounded redacted output, exit code, recap and separate host results. Live events use `/jobs/{job_id}/events`. Cancellation sends interrupt, then terminate and kill after bounded grace periods, preserves partial output/results and always removes transient files. Retry creates a linked execution.

Host locks implement the default **block overlapping hosts** policy. Templates can instead allow parallel jobs, block the template or request a single controller job. Stale locks are cleaned when execution finishes.

Schedules are persistent SQLite records and survive application restarts. One-time, hourly, daily, weekly, monthly and strictly validated five-field cron expressions are supported with IANA time zones, active state, next/last run and missed-run policy. The scheduler submits the same durable launch job used by an interactive launch.

## External AWX / Automation Controller

Settings accept an HTTPS URL, encrypted AWX-token credential, TLS verification flag, optional CA certificate and bounded timeout. TLS verification is enabled by default. The `/awx` API can test connectivity/version, list organizations, inventories, projects and job templates, launch a selected template, poll status and retrieve bounded redacted stdout. WebNAS does not deploy AWX or Kubernetes.

## Diagnostics

Diagnostics report availability/version of Ansible, ansible-playbook, OpenSSH and nmap; the controller account and UID/GID; directory/key modes; SQLite integrity/migration state; managed config and known-hosts state; process isolation; temporary directories; scheduler state; recent failures; plaintext-secret indicators and external AWX configuration. Reports contain metadata and redacted messages only.

## Backup and restore

Backups are private, versioned `tar.gz` artifacts with an online SQLite snapshot, controller-managed project/config data, metadata, accepted fingerprints and SHA-256 checksum. Credential metadata is always represented; encrypted credential envelopes are optional and are never decrypted into an archive. Validation checks the manifest, checksum, schema version, member paths and sizes before restore.

Restore requires the `ansible-controller.restore` permission, checksum and confirmation. It first creates a safety backup, replaces the database atomically and preserves the failed/pre-restore artifact for recovery. Backup download is an authenticated API response rather than a public static URL.

## Uninstall

The default removes module packages/executables while preserving inventory, playbooks, projects, history, keys and credentials. The wizard can additionally remove local configuration, or configuration plus all local module data. Full removal requires typing `Ansible`. It lists hosts where the managed user was created. No uninstall mode connects to remote hosts or removes `algen-ansible` accounts.

## API overview

All routes are below `/api/modules/ansible-controller`:

```text
GET/PUT dashboard, config
GET/POST/PUT/DELETE hosts, groups, credentials, projects, playbooks, templates, schedules
GET/POST inventory; POST inventory/validate, inventory/import
GET/POST scans; POST scans/{id}/import
POST hosts/{id}/keyscan, fingerprint, test, facts; POST onboarding
POST projects/{id}/sync; POST playbooks/validate
POST templates/{id}/plan, templates/{id}/launch
GET jobs, jobs/{id}, jobs/{id}/events; POST jobs/{id}/cancel, jobs/{id}/retry
GET facts, audit, diagnostics, backups; POST backups, backups/{id}/validate, backups/{id}/restore
DELETE/GET backups/{id}, backups/{id}/download
GET/POST awx resources and launches
```

See the generated OpenAPI document for exact strict Pydantic schemas and response fields.

## Permissions

The closed registry contains `ansible-controller.view`, `install`, `configure`, `hosts.view`, `hosts.manage`, `discovery`, `credentials.view`, `credentials.manage`, `projects.view`, `projects.manage`, `playbooks.view`, `playbooks.manage`, `jobs.launch`, `jobs.cancel`, `schedules.manage`, `audit.view`, `backup` and `restore`. Built-in administrator/operator/viewer assignments follow least privilege; custom roles can select individual entries.

## Troubleshooting

- `ANSIBLE_NOT_AVAILABLE`: install/update the module and run Diagnostics; do not install Ansible globally with pip.
- `HOST_KEY_NOT_ACCEPTED` or a changed-key alert: verify the fingerprint out of band and explicitly accept it. Never disable host-key checking.
- unreachable host: check TCP port/firewall, SSH user, credential type, Python path and the per-host stderr/recap.
- validation failure: inspect the YAML line and all four Ansible pre-flight results; controller-local actions remain intentionally blocked.
- Git sync failure: confirm URL/revision, host trust and credential, then inspect the redacted durable job log.
- restore failure: validate the checksum/schema, keep the automatic safety backup and inspect database diagnostics.

## Limitations

This is a local `ansible-core` controller, not a full AWX replacement. It does not deploy execution-environment containers, Galaxy content servers, Kubernetes or remote account removal. Static risk analysis cannot prove that an automation is harmless. Git SSH hosts must already be trusted by the controller account. Network discovery finds SSH endpoints only and does not identify vulnerabilities or attempt authentication.

## Manual verification

Use disposable Linux VMs and test networks only:

1. Install the module from Package Center; verify `webnas-ansible` is non-root, non-login and not in sudo/wheel, and inspect directory/key modes.
2. Open the module dashboard and run Diagnostics.
3. Scan a small RFC1918 CIDR, observe SSE progress, cancel one scan, then import only selected results.
4. Add a key credential, add a test host, scan and independently verify its fingerprint, accept it, run ping and collect facts.
5. Onboard a disposable host with and without the managed-user option; test every sudo profile and force a failure to verify rollback.
6. Import YAML and INI inventory, including rejected oversize/plaintext-secret cases.
7. Save a safe playbook; verify YAML, four Ansible checks, risk analysis, versions and blocked local-execution samples.
8. Create a template, review its plan, confirm launch, watch live redacted output/per-host recap, cancel and retry it.
9. Create each schedule type, restart WebNAS and verify next/last-run persistence.
10. Create/validate/download a backup, alter disposable data, restore it and verify the safety backup.
11. Test external AWX with a least-privilege token and a valid/custom CA; confirm TLS is not disabled by default.
12. Uninstall in each mode and verify remote accounts are untouched and full data removal requires `Ansible`.
