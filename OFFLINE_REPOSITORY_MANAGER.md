# Offline Repository Manager

Offline Repository Manager is an extension of the existing `os-repositories` module for building, transferring, verifying, importing and publishing Linux package repositories in disconnected and air-gapped environments.

It does not create a second package-management subsystem. The implementation reuses the existing WebNAS repository database, content-addressed package store, APT/RPM adapters, immutable snapshots, channels, signing keys, audit trail, repository job tables and Hosts Manager public API.

## Supported workflow

```text
Internet / upstream repositories
            |
            v
      WebNAS online
            |
       mirror / sync
            |
         snapshot
            |
  dependency closure + plan
            |
   Full / Selected / Delta
       .tar.zst bundle
            |
      controlled transfer
            |
            v
      WebNAS offline
            |
     stage -> inspect
            |
       verify integrity
            |
          import
            |
    immutable snapshot
            |
      optional publish
       Testing / Production
            |
         Linux hosts
```

## User interface

The `os-repositories` application exposes two modes:

- **Online repositories** — the existing repository manager;
- **Offline Repository Manager** — the disconnected-repository workflow.

The offline UI contains:

- Dashboard;
- Targets;
- Bundles;
- Host Groups;
- Import;
- Delta & Freeze;
- Jobs;
- Storage;
- Diagnostics;
- Settings / Air-Gapped Mode.

The UI hides destructive actions when the current user does not have the corresponding permission. Backend RBAC remains authoritative.

## Reusable targets

A target stores a reusable export definition:

- repository;
- snapshot or channel;
- distribution and version;
- architecture;
- optional package allow-list;
- dependency-closure policy;
- signing key;
- optional Hosts Manager group association.

Targets can be created manually or generated from a Hosts Manager group. Group generation reads hosts exclusively through the supported Hosts Manager public registry. The offline module does not open the Hosts Manager SQLite database directly.

For host-group generation, host distribution, release and architecture are compared with candidate repositories. Common architecture aliases are normalized, including `x86_64` -> `amd64` for APT and `amd64` -> `x86_64` for RPM.

## Bundle types

### Full

Contains every package from the selected snapshot for the requested architecture, including architecture-independent packages (`all` for DEB and `noarch` for RPM).

### Selected

Starts from an explicit package list and recursively resolves dependencies from package metadata already stored by WebNAS. Missing dependencies and conflicts are reported before export.

### Delta

Compares a base snapshot with a target snapshot and exports only changed package payloads while carrying a complete target package descriptor set.

The delta plan reports:

- added packages;
- updated packages;
- removed packages;
- unchanged packages;
- full target size;
- delta payload size.

A delta import requires the destination to have the matching imported base snapshot. The source snapshot is never mutated.

## Dependency closure

The resolver understands common DEB/RPM dependency expressions, alternatives and version operators such as `=`, `>=`, `>`, `>>`, `<=`, `<` and `<<`.

Resolution uses only metadata already present in the selected WebNAS snapshot. It never executes user-provided shell commands and never silently downloads missing packages.

## Bundle format

New exports use Zstandard-compressed tar archives:

```text
webnas-offline-<distribution>-<version>-<architecture>-<id>.tar.zst
```

Legacy `.tar.gz` and `.tgz` bundles remain accepted for import compatibility.

Typical archive layout:

```text
manifest.json
manifest.json.asc             # optional detached GPG signature
repository/
  dists/...                   # APT metadata
  pool/...                    # APT payloads
  <arch>/Packages/...         # RPM payloads
  <arch>/repodata/...         # RPM metadata
keys/
  repository.asc              # public key only
metadata/
  repository.json
  snapshot.json
  packages.json
```

Private GPG material is never exported.

The manifest contains repository identity, source/base snapshot identity, architecture, bundle type, package descriptors, removed packages for delta bundles, compression metadata and a SHA-256/size entry for every declared non-manifest file.

Tar metadata is normalized before compression to improve reproducibility. Payload hashing is streamed in bounded chunks.

## Controlled staging

Browser uploads are written only to the managed staging directory:

```text
/var/lib/webnas/os-repositories/incoming/offline-bundles/
```

The API addresses staged artifacts through derived IDs. It never accepts an arbitrary server filesystem path from the frontend.

Uploads are streamed, bounded by the configured repository upload limit and atomically renamed into place after completion.

## Verification and import security

Offline archives are treated as hostile input.

The safe extractor rejects:

- absolute paths;
- `..` traversal;
- backslash path ambiguity;
- symlinks;
- hardlinks;
- devices;
- FIFOs;
- unsupported tar entry types;
- duplicate paths;
- case-colliding paths;
- excessive member counts;
- excessive declared extracted size.

Extraction is manual; `extractall()` is not used.

Before import WebNAS verifies:

1. bundle format version;
2. manifest structure;
3. declared file presence;
4. exact file size;
5. SHA-256 for every declared file;
6. absence of unexpected files;
7. package payload SHA-256;
8. DEB/RPM metadata using the existing package inspector;
9. optional GPG manifest signature;
10. destination repository compatibility;
11. delta base availability when applicable.

Import then ingests package payloads through the existing content-addressed repository service and creates a new immutable snapshot.

## GPG trust model

A signed bundle carries an armored detached signature and the public key needed for cryptographic verification.

Verification runs in a private temporary GnuPG home. A cryptographically valid signature whose fingerprint is not known to the local WebNAS key registry is reported as **verified with unknown trust**; it is not silently promoted to trusted.

Unsigned bundles are explicitly reported as unsigned.

## Durable jobs

Export, verify and import operations use the existing `repository_sync_jobs` and `repository_sync_logs` infrastructure instead of a parallel job database.

Offline operations are identified as:

```text
offline_export
offline_verify
offline_import
```

The API provides:

- queued/running/completed/failed/cancelled state;
- stages and progress;
- current item;
- persistent logs;
- retry;
- cancellation request;
- SSE job updates;
- restart handling through the existing durable repository store.

The normal repository sync manager filters its own jobs to `operation='sync'`, so it does not consume offline work after restart.

## Air-Gapped Mode

Air-Gapped Mode is a persisted backend policy, not a frontend-only switch.

When enabled:

- new mirror synchronization requests are rejected before queueing;
- a sync queued before the mode was enabled is failed before DNS resolution, HTTP proxy setup or repository tooling can run;
- local package browsing, staging, verification, import, snapshots, channels, bundles, retention and diagnostics remain available.

Changing Air-Gapped Mode requires the dedicated critical permission `os-repositories.offline.airgap.manage`.

## RBAC

Offline Repository Manager registers dedicated permissions in the existing permission registry:

```text
os-repositories.offline.view
os-repositories.offline.export
os-repositories.offline.import
os-repositories.offline.verify
os-repositories.offline.delete
os-repositories.offline.targets.manage
os-repositories.offline.freeze
os-repositories.offline.delta
os-repositories.offline.configure
os-repositories.offline.airgap.manage
```

Default role policy:

- **Administrator** — all offline permissions;
- **Operator** — operational offline permissions except destructive bundle deletion and Air-Gapped Mode switching;
- **Auditor** — read-only offline view.

Publishing an imported snapshot to Production additionally requires the existing `os-repositories.channels.promote` permission and Production confirmation.

Deleting a pinned bundle requires the critical delete permission plus `force=true` and the exact confirmation text `DELETE`.

## Retention and pinning

Default retention settings are:

- keep the latest 5 bundles;
- delete eligible artifacts older than 90 days;
- retain Production bundles;
- retain signed bundles;
- always retain pinned bundles.

Deleting a bundle removes the portable artifact record/file only. It does not delete shared package content, source snapshots or published channels.

## Storage and deduplication

Offline storage reporting includes:

- logical package bytes;
- generated bundle bytes;
- staging/temporary bytes;
- logical snapshot bytes;
- physical content-store bytes;
- estimated bytes saved by deduplication;
- filesystem free space.

Imported packages continue to use the existing SHA-256-addressed package store. Re-importing content already present does not create another permanent payload copy.

## Diagnostics

Offline diagnostics report:

- bundle directory availability;
- staging directory availability;
- temporary directory availability;
- free space;
- missing generated bundle artifacts;
- orphaned offline job payloads;
- active offline jobs;
- Air-Gapped Mode state;
- availability of GPG, DEB and RPM tooling;
- current offline storage statistics.

## Backup and restore

Offline metadata lives in the same `repositories.sqlite3` database as the normal `os-repositories` module. The existing repository backup performs an SQLite backup of that database, therefore target, bundle, import, lineage, freeze, settings and offline-job metadata participate in the same backup/restore transaction model.

Package payload storage remains governed by the normal repository backup/content-store policy.

## API

The extension is mounted under:

```text
/api/modules/os-repositories/offline
```

Main endpoint groups:

```text
GET/PUT  /settings
GET      /dashboard

GET/POST /targets
GET/PUT/DELETE /targets/{id}
POST     /targets/from-host-group
GET      /hosts/groups/{group_id}/compatibility

POST     /exports/plan
POST     /exports
GET      /bundles
GET      /bundles/{id}
GET      /bundles/{id}/download
PUT      /bundles/{id}/pin
DELETE   /bundles/{id}

GET      /imports/staged
POST     /imports/upload
GET      /imports/{staged_id}/inspect
POST     /imports/{staged_id}/verify
POST     /imports/{staged_id}

GET      /delta/plan
POST     /snapshots/{snapshot_id}/freeze

GET      /jobs
GET      /jobs/{id}
GET      /jobs/{id}/events
POST     /jobs/{id}/cancel
POST     /jobs/{id}/retry

GET      /storage
GET      /diagnostics
```

## Database additions

The extension creates its schema idempotently with `CREATE TABLE IF NOT EXISTS` and does not destructively replace the existing repository schema.

Offline tables include:

```text
offline_targets
offline_bundles
offline_imports
offline_snapshot_origins
snapshot_freezes
offline_settings
offline_job_payloads
```

## Tests

Dedicated automated coverage includes:

- schema/settings/targets;
- Air-Gapped Mode sync blocking;
- recursive dependency closure;
- missing dependencies;
- bundle export and verification round trip;
- malicious tar traversal;
- delta calculation;
- snapshot freeze idempotency;
- durable offline jobs sharing the repository job store;
- offline role permissions;
- Hosts Manager group compatibility and target generation.

The repository CI additionally runs Ruff, mypy, Bandit, backend unit/integration tests, frontend lint/typecheck/tests/build, generated OpenAPI consistency, dependency audits, Playwright, real-stack E2E and CodeQL.

## Operational verification

A representative acceptance test is:

1. Create an APT or RPM repository on an online WebNAS instance.
2. Synchronize/upload packages and create a snapshot.
3. Run export plan and confirm dependency closure and free-space checks.
4. Create a Full bundle and download the `.tar.zst` artifact.
5. Transfer it to an offline WebNAS instance through the approved medium.
6. Stage and inspect the archive.
7. Run verification and review checksum/signature status.
8. Import into a compatible destination repository.
9. Confirm a new immutable snapshot is created.
10. Publish to Testing and validate a disposable Linux client.
11. Promote to Production only after normal repository approval.
12. Create a second source snapshot and repeat with a Delta bundle.
13. Enable Air-Gapped Mode and verify online synchronization is rejected before outbound network activity.

## Compatibility note

Dependency closure is intentionally based on package dependency metadata currently modeled by WebNAS. Advanced virtual-provider semantics such as every RPM `Provides`/`Obsoletes` edge are not synthesized when those relationships were not present in the ingested metadata. Missing closure is reported and export is rejected rather than guessing a package set.
