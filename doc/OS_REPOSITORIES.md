# Repozytoria systemowe

`os-repositories` is an installable WebNAS infrastructure module for storing,
mirroring, validating, snapshotting, signing, and publishing APT and RPM
repositories for managed hosts. It does not manage Git repositories and does
not replace `linux-updates`, which remains responsible for the local WebNAS
host's package state.

## Architecture

The module uses the existing WebNAS boundaries instead of creating parallel
infrastructure:

- Package Center discovers `backend/app/modules/os-repositories/manifest.yaml`
  and runs its trusted lifecycle scripts through durable Package Center jobs.
- `backend/app/modules/os_repositories` owns typed Pydantic contracts, an
  idempotent SQLite store, format adapters, durable synchronization jobs, the
  repository HTTP service, and the dedicated FastAPI router.
- the normal identity middleware supplies sessions, CSRF, granular RBAC, and
  Activity Center records;
- Hosts Manager integration uses `HostCapabilityProvider` and public registry
  methods. The module never opens the Hosts Manager database;
- the React application uses the shared module shell and opens from Package
  Center, Start, desktop search, saved windows, and normal application pins.

APT and RPM publication adapters are deliberately separate. APT produces
`dists/<suite>/main/binary-<architecture>/Packages{,.gz}`, a checksummed
`Release`, optional `InRelease`/`Release.gpg`, and a content-addressed `pool/`.
RPM creates one architecture root with `Packages/`, `repodata/`, and a signed
`repomd.xml.asc` when a signing key is assigned. This boundary is intended for
future Zypper, Pacman, APK, Chocolatey, or Winget adapters; unsupported formats
are not exposed in the current UI or API.

## Installation and lifecycle

Install **Repozytoria systemowe** from Package Center. Proxmox Safe Mode blocks
the plan because the manifest intentionally declares `proxmox_safe: false`:
the module installs package tools, listens on a network port, and can consume
substantial storage.

On Debian-family hosts the installer uses `apt-get` and installs `aptly`,
`dpkg-dev`, GnuPG, `createrepo-c`, and RPM tooling. On Fedora/RHEL-family hosts
it uses the detected `dnf` or `yum` and installs DNF reposync plugins,
`createrepo_c`, RPM build/sign tools, GnuPG, and Debian package inspection
support. Every command is a fixed argument array with `shell=False`, a bounded
environment, and a timeout.

Installation creates:

```text
/var/lib/webnas/os-repositories/
  repositories.sqlite3
  content/ incoming/ mirrors/ published/ snapshots/
  builds/ temporary/ gnupg/ backups/ logs/ config/
/etc/webnas/os-repositories.yaml
/etc/systemd/system/webnas-repository-server.service
```

The private data root is mode `0700`; SQLite, secrets, builds, temporary data,
and backups stay behind that boundary. Only `published/` is exposed read-only
to the unprivileged `webnas-repository` service through a systemd bind mount at
`/srv/webnas-repositories`. The service uses `NoNewPrivileges`, a strict
filesystem view, private devices/tmp, kernel protections, syscall architecture
restriction, and file-descriptor limits.

An update creates online SQLite and configuration/unit backups, reruns the
idempotent installer/migrations, verifies service health, and restores the
previous database/configuration/unit on a critical failure. Normal uninstall
stops and removes only the service integration and preserves all authoritative
data. Full deletion is a separate API/UI operation requiring
`os-repositories.full-remove`, the exact text `Repozytoria systemowe`, and an
extra force choice when host assignments still exist.

## Data and transactions

SQLite uses WAL, foreign keys, a busy timeout, explicit transactions, indexes,
and `schema_migrations`. It stores repository/source/architecture/filter
metadata, jobs and bounded log lines, package metadata, immutable snapshot
membership, channels/publications, signing-key envelopes, builds/files, host
assignments, schedules, settings, and audit metadata. Package payloads are
never SQLite BLOBs.

Uploads stream through a private temporary file, enforce the configured byte
limit, compute SHA-256, verify DEB/RPM magic, inspect metadata with `dpkg-deb`
or `rpm`, check signatures when the platform tool is available, and only then
atomically move the content into a SHA-256-addressed directory. Repeated
content is deduplicated.

Snapshots are immutable lists of content objects. Active, versioned filters
are applied before snapshot creation. Publishing builds a complete private
generation, links package content where possible, validates/generates all
metadata, signs it, and atomically switches the public channel pointer. A
failure removes the incomplete generation and leaves the last publication
active. Each channel retains its previous snapshot for atomic rollback.

## Repositories, filters, and synchronization

Create a `local` repository for uploaded/built packages or a `mirror` for an
external source. Supported distributions are Debian, Ubuntu, Raspberry Pi OS,
Fedora, RHEL, Rocky Linux, and AlmaLinux. Mirror URLs:

- must use HTTPS unless private HTTP is explicitly approved;
- cannot contain credentials or a fragment;
- are DNS-resolved and reject loopback, link-local, multicast, unspecified,
  reserved, and unapproved private addresses;
- are resolved again immediately before a synchronization tool starts.

Synchronization is a durable database job. It records stage, percentage,
current item, package/byte counters, warnings, error, actor, timestamps, and
bounded redacted log lines. SSE drives the live UI and three-second polling is
the fallback. Jobs can be cancelled and failed/cancelled jobs retried. Queued
jobs resume after WebNAS starts; jobs interrupted while running are marked
failed rather than treated as successful. Temporary RPM downloads are removed
after ingestion; APT mirror storage remains private and content is ingested
into the shared content-addressed store. No incomplete mirror is published.

Schedules accept `@hourly`, `@daily`, `@weekly`, or a bounded five-field cron
expression. A single scheduler thread checks installed active mirrors every 30
seconds and the job manager prevents duplicate concurrent synchronization of
the same repository.

Filters support exact allow/deny names, glob patterns, restricted regular
expressions, architecture, min/max version and date, newest N versions, source,
debug and development exclusions, and maximum size. Preview returns included
and rejected counts, examples, estimated size, and whether the 5,000-package
preview bound was reached. Regex constructs associated with catastrophic
backtracking, lookarounds, and backreferences are rejected.

## Channels and release flow

Every repository receives `incoming`, `testing`, `production`, and `archive`.
The normal flow is:

```text
local or mirror -> incoming packages -> immutable snapshot
                -> testing -> production -> optional archive
```

The UI requests a publication plan with the current/target snapshots and a
structured diff before applying it. Production publication and rollback
require `os-repositories.channels.promote` and exact `Production`
confirmation. Other channels require snapshot-management permission. Every
switch and rollback is recorded in `channel_publications` and Activity Center.

## Package builder

The package builder creates DEB with `dpkg-deb` and RPM with `rpmbuild` inside
a private per-build root. The typed definition includes name, version, release,
architecture, description, maintainer/vendor/license/homepage, dependencies,
conflicts, source files, validated absolute target paths, owner/group/mode,
configuration-file flags, and maintainer scripts. Inputs are capped at 200
files/200 MiB and cannot escape the build root.

Maintainer scripts require an explicit high-risk checkbox. They are embedded
as DEB `preinst/postinst/prerm/postrm` or RPM `%pre/%post/%preun/%postun` and
are never executed by WebNAS while building. The finished package is passed
through the same validation, signature, SHA-256, and content-addressed upload
path as a browser upload. Build output and failure state are durable.

## GPG keys

Administrators can import public/private ASCII-armored material or generate an
RSA signing key with GnuPG. The supplied fingerprint is verified against the
public key when GPG is available. Private material and passphrases are stored
only as authenticated encrypted envelopes using a root-only key outside
SQLite. API responses return `secret_configured`, never a private key.

Signing runs in a temporary mode-`0700` GNUPG home, verifies the secret-key
fingerprint before use, and supplies passphrases over stdin rather than command
arguments. Only public keys are exported below `/keys/<fingerprint>.asc`.
Assigned keys cannot be deleted.

## Repository HTTP service

The default endpoint is `0.0.0.0:8088`; change it under module Settings. Saving
performs a bind test before writing the controlled YAML file and restarting the
service. A public base URL can be configured for generated host files.

The standalone read-only server serves regular files only. It does not list
directories or expose dot paths/generations, follows resolved paths only inside
the published root, rejects traversal and backslashes, and supports GET, HEAD,
single byte ranges, MIME types, connection/range limits, socket timeouts, and
security headers. It has no route to SQLite, backups, temporary data, logs, or
private keys.

## Hosts Manager

Assignments target either one host or one Hosts Manager group and one published
channel. The `os-repositories.generate-config` capability checks the host's
distribution and architecture, returns a plan, requires confirmation, and only
generates configuration. It never automatically changes a host.

APT example:

```text
deb [signed-by=/usr/share/keyrings/webnas-repository.gpg] http://server:8088/<repository-id>/production 24.04 main
```

DNF/YUM example:

```ini
[webnas-rocky-production]
name=Rocky packages production
baseurl=http://server:8088/<repository-id>/production/$basearch/
enabled=1
gpgcheck=1
gpgkey=http://server:8088/keys/<fingerprint>.asc
```

Unsigned repositories generate explicit `gpgcheck=0` for RPM and omit the APT
`signed-by` option rather than pointing to a nonexistent key.

## API and RBAC

The typed API is rooted at `/api/modules/os-repositories` and groups dashboard,
repositories/plans/filters/sync, packages/upload/download, snapshots/compare,
channels/plans/promote/rollback, builds, keys, assignments/configuration, jobs
and SSE, history, settings, backups/restore, diagnostics, and full removal.
Lists are paginated or explicitly bounded.

Permissions are:

```text
os-repositories.view                 os-repositories.manage
os-repositories.sync                 os-repositories.packages.upload
os-repositories.packages.delete      os-repositories.packages.build
os-repositories.snapshots.manage     os-repositories.channels.promote
os-repositories.keys.view            os-repositories.keys.manage
os-repositories.hosts.assign         os-repositories.jobs.cancel
os-repositories.backup               os-repositories.restore
os-repositories.configure            os-repositories.full-remove
```

Administrators receive all permissions. Operators can operate repositories,
sync/upload/build, manage snapshots and host assignments, cancel jobs, back up,
and configure, but cannot manage keys, delete package data, publish Production,
restore, or fully remove. Auditors receive read-only module/key visibility.
Users receive no module access by default. Backend checks remain authoritative;
the UI also hides actions that are outside the effective permission set.

## Backup and restore

Metadata backup uses SQLite online backup and creates a mode-`0600` tar.gz with
a versioned manifest and SHA-256 checksums. Full backup additionally includes
content without following symlinks. By default private-key columns are removed
from the staged database. Optional private keys are decrypted only in memory
and written as a passphrase-derived scrypt + encrypt-then-MAC envelope; the
archive never contains plaintext private material.

Restore verifies the outer checksum, archive paths/types/sizes, manifest and
schema version, internal file checksums, SQLite integrity, and the optional
private-key envelope. It first creates a safety backup, prepares the restored
database privately, then atomically replaces the active database. Unsafe,
linked, oversized, or traversing members are rejected.

## Diagnostics

Diagnostics report tool paths/versions, SQLite/schema integrity, private root
permissions, free space, package presence and SHA-256 integrity, snapshot
foreign-key consistency, expired keys, configured listen address/port, and
HTTP socket status. Responses never include private key material, passphrases,
or command output beyond bounded version/check messages.

## Manual verification

1. Install the module in Package Center and verify
   `systemctl status webnas-repository-server` as well as the module Diagnostics.
2. Create a local Ubuntu/`apt` repository for `amd64`, upload a real `.deb`, and
   confirm its SHA-256 and metadata in Packages.
3. Create a snapshot, inspect the Testing publication plan, publish it, and run
   `curl -I http://server:8088/<id>/testing/dists/24.04/Release`.
4. On a disposable APT client, install the generated public key/configuration,
   run `apt-get update`, and download the uploaded package.
5. Repeat with a Rocky/`rpm` repository and run `dnf makecache` against the
   generated `.repo` file.
6. Publish a second snapshot to Production, then use rollback and verify that
   the previous package index becomes active as one generation.
7. Configure a small approved mirror and schedule, follow its SSE log, cancel
   and retry it, then restart WebNAS during a test job to verify interruption
   recovery.
8. Assign Testing to a disposable Hosts Manager host/group, preview the plan,
   generate its APT/DNF configuration, and verify no host was modified.
9. Create metadata and full backups, restore into a disposable installation,
   verify diagnostics, and confirm a normal uninstall preserved the data root.
