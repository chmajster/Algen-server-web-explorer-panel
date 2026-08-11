# Cron Manager

Cron Manager is the native WebNAS module for administering recurring Linux commands. It is registered in the same backend and frontend module registries as the other WebNAS applications, is activated through Module Center, uses Identity RBAC and PAM sessions, writes Activity Center audit events, and sends changes through the existing durable `package_jobs` queue.

## Architecture

```text
responsive Cron application
        ↓ typed /api/modules/cron API
session + CSRF + cron.* RBAC + PAM confirmation
        ↓ existing package_jobs queue
trusted CronProvider
        ↓
validate → render candidate → backup → atomic replace → verify → audit
        ↓
/etc/cron.d/webnas and the host cron/crond daemon
```

The private metadata database is `paths.data_dir/cron/cron.sqlite3`. It stores stable UUIDs, display metadata, the Linux user, schedule, command, working directory, environment, timeout, enabled state, and configuration history. Sensitive mutation input is staged in a mode-`0600` private file; PAM passwords are authenticated at the API boundary and are never staged, queued, stored, returned, or logged.

The module does not add another scheduler or worker. Cron performs execution, while WebNAS's existing durable package-operation queue serializes configuration mutations and preserves their progress/result across browser disconnects.

## Managed and external jobs

WebNAS owns only `/etc/cron.d/webnas`. Each managed entry has an internal UUID marker, name marker, enabled marker, schedule, validated Linux user, and rendered command. A rename never changes the UUID. Disabling comments the generated entry but retains its complete database definition.

Cron Manager can discover `/etc/crontab`, regular non-symlink files in `/etc/cron.d`, user crontabs returned by fixed `crontab -u USER -l` argument arrays, and periodic scripts in `/etc/cron.hourly`, `cron.daily`, `cron.weekly`, and `cron.monthly`. These records have deterministic display IDs and are always read only. WebNAS never adopts them and skips its own managed file during discovery.

Commands are configuration data. The backend never executes a submitted command. Cron ultimately invokes a shell as required by cron semantics. Working directories, environment values and timeouts are rendered through fixed `/bin/sh`, `/usr/bin/env`, and `/usr/bin/timeout` wrappers with shell quoting, and cron percent characters are escaped. Administrative detection, systemd, crontab and journal calls use fixed executable and service allowlists, argument arrays and `shell=False`.

## Scheduling

The backend parser accepts five-field cron syntax with numeric values, lists, ascending ranges, steps, English month/day abbreviations, Sunday as `0` or `7`, and the standard yearly/monthly/weekly/daily/hourly aliases. `@reboot` is supported explicitly. It rejects missing fields, out-of-range values, descending ranges, zero/oversized steps, whitespace injection and unsupported macros.

The next occurrence is calculated on the backend in the server timezone. Day-of-month/day-of-week use traditional cron OR behavior when both fields are restricted. Calculation walks UTC minutes and converts them to the server zone so daylight-saving transitions are respected. `@reboot` has no predictable timestamp and therefore returns no data.

Cron does not expose reliable exit codes or execution history by itself. The module deliberately shows **No data** instead of inventing last-run, duration or exit status. Configuration audit history is available separately. No execution wrapper is installed, so job semantics remain unchanged.

## Transactional configuration writes

Every managed change follows this sequence:

1. Validate the typed model, expression and Linux username.
2. Render the complete candidate managed file.
3. Parse the candidate and reject invalid or duplicate internal markers.
4. Capture the existing file and create a private retained backup.
5. Write a temporary file in the target directory, set mode `0644` and root ownership, flush it with `fsync`, and replace the target with `os.replace`.
6. Flush the parent directory and verify exact content, markers, owner and mode.
7. Commit the SQLite metadata change and verify that database IDs/states match the file.
8. If any write, verification or database operation fails, atomically restore the previous snapshot (or remove the newly created file).
9. Record the completed operation without command or environment values.

Cron implementations monitor `/etc/cron.d`; a reload/restart is neither required nor performed. This avoids changing daemon state and works with both `cron` and `crond`.

## API

All endpoints require an active WebNAS session. Mutations require CSRF, their granular permission, an exact confirmation value and reauthentication with the current account's PAM password.

```text
GET    /api/modules/cron/access
GET    /api/modules/cron/status
GET    /api/modules/cron/jobs
GET    /api/modules/cron/jobs/{id}
POST   /api/modules/cron/jobs
PUT    /api/modules/cron/jobs/{id}
DELETE /api/modules/cron/jobs/{id}
POST   /api/modules/cron/jobs/{id}/enable
POST   /api/modules/cron/jobs/{id}/disable
POST   /api/modules/cron/jobs/{id}/duplicate
GET    /api/modules/cron/jobs/{id}/history
POST   /api/modules/cron/validate
GET    /api/modules/cron/logs
GET    /api/modules/cron/diagnostics
```

The list supports search, user/status filters and optional external discovery. Log line counts are limited to 1,000. Log source IDs are server-generated; callers cannot submit file paths or systemd units.

## RBAC and audit

| Permission | Purpose | Default roles |
|---|---|---|
| `cron.view` | Dashboard, jobs, details and diagnostics | administrator, operator, auditor |
| `cron.create` | Create and duplicate managed jobs | administrator, operator |
| `cron.edit` | Edit managed jobs and validate a complete definition | administrator, operator |
| `cron.enable` | Enable and disable managed jobs | administrator, operator |
| `cron.delete` | Delete a managed schedule | administrator |
| `cron.logs` | Read controlled cron logs and configuration history | administrator, operator, auditor |
| `cron.admin` | Reserved full Cron Manager administration scope | administrator |

Completed mutations emit `cron.job.created`, `cron.job.updated`, `cron.job.enabled`, `cron.job.disabled`, and `cron.job.deleted`. Events contain only job ID, name, username and schedule. Commands, environment values, passwords and other secrets are excluded. Shared redaction is applied again to journal/classic log output.

## Logs and diagnostics

Logs prefer `journalctl` for the fixed `cron` and `crond` units. Existing regular `/var/log/syslog` and `/var/log/cron` files are offered as controlled alternatives. Responses are size/line bounded and support search, user and job filters.

Diagnostics report `crontab`, cron/crond discovery, service active/enabled state, managed-file consistency, owner/mode, invalid schedules, missing Linux users, unequivocally missing absolute executables, missing working directories, duplicate jobs and Proxmox Safe Mode. Reports are advisory and never repair the host automatically.

## Distributions and Proxmox

The manifest supports Debian, Ubuntu, Raspberry Pi OS (`raspbian`), Fedora, RHEL, Rocky Linux and AlmaLinux. Activation uses the daemon already on the host; it does not install another daemon. Debian-family systems normally expose `cron.service`, while RPM-family systems normally expose `crond.service` and the `cronie` package.

The module is deliberately `proxmox_safe: false`. Read-only discovery and diagnostics remain useful on a Proxmox host, but Safe Mode blocks mutations because a root cron schedule can execute arbitrary future commands even though Cron Manager never touches `/etc/pve`, storage, networking, guests or cluster configuration itself. Use a VM/LXC for scheduled automation or explicitly change the host safety policy only after reviewing that risk.

## Limitations

- Cron itself does not provide authoritative next/last execution or exit-code history; only next times for calendar expressions are calculated.
- Environment values necessarily appear as plain text in the generated cron configuration. The UI warns for secret-like variable names.
- An absent `/usr/bin/timeout` is reported when a job requests a timeout.
- External configuration is informational. Changes made outside WebNAS can appear or disappear at the next refresh and are never rewritten.
- Cron Manager does not delete scripts, working directories or any command target when a job is removed.

## Testing

Backend tests use temporary SQLite and cron files and mock Linux users, systemd, `crontab`, journald and Proxmox state. They cover expression parsing, next-time calculation, CRUD, enable/disable/duplicate, ownership markers, external read-only handling, atomic mode/backup writes, rollback after write/database failures, daemon detection, RBAC/CSRF, Safe Mode, audit redaction and injection-shaped values. No test modifies the CI host crontab.

Frontend tests cover dashboard/list rendering, search and filters, managed versus external actions, create validation and confirmation, enable/disable permissions, loading/error recovery, diagnostics and log filters. The production build runs TypeScript and Vite validation.
