# Offline Repository Manager

Offline Repository Manager extends the existing `os-repositories` module with portable repository bundles for disconnected and air-gapped environments. It deliberately reuses the authoritative repository database, content-addressed package store, APT/RPM adapters, immutable snapshots, channels, GPG keys, audit integration and host-facing configuration model instead of introducing a second repository subsystem.

## Scope

The current implementation provides the backend foundation for:

- reusable offline repository targets;
- full, selected-package and delta bundle planning;
- recursive dependency-closure calculation from snapshot metadata;
- deterministic JSON metadata and normalized tar/gzip archives;
- controlled server-side staging and browser upload staging;
- archive inspection and integrity verification before import;
- import into the existing content-addressed package store;
- creation of a new immutable snapshot for each import;
- optional publication through the existing Testing/Production channel mechanism;
- bundle pinning and retention;
- snapshot freeze metadata;
- storage accounting;
- an enforceable Air-Gapped Mode that blocks repository synchronization in the backend.

The API is rooted at `/api/modules/os-repositories/offline`.

## Architecture

```text
os-repositories
  |
  +-- repositories / mirrors
  +-- content-addressed package store
  +-- APT / RPM adapters
  +-- snapshots
  +-- channels
  +-- signing keys
  +-- repository jobs
  |
  +-- offline
      +-- targets
      +-- bundle planning
      +-- dependency closure
      +-- export
      +-- verification
      +-- import
      +-- delta calculation
      +-- retention
      +-- air-gap policy
```

Offline metadata is stored in the same SQLite database as the normal repository module. Package payloads are never stored as SQLite BLOBs.

The extension creates idempotent tables for targets, bundle records, import history, imported-snapshot lineage, snapshot freeze state and offline settings. Existing repository/snapshot/package/channel tables remain authoritative.

## Online to offline workflow

```text
Internet
   |
   v
WebNAS online
   |
   +--> mirror/sync
   +--> package filtering
   +--> snapshot
   +--> dependency closure
   +--> offline bundle
             |
             +--> controlled transfer
                      |
                      v
                WebNAS offline
                      |
                      +--> stage
                      +--> inspect
                      +--> verify
                      +--> import
                      +--> immutable snapshot
                      +--> optional publish
                              |
                              v
                         Linux clients
```

The offline instance does not need access to the source WebNAS database. The bundle contains the repository metadata and package descriptors needed to verify and ingest the payload.

## Bundle format

The implemented portable format uses `.tar.gz` archives. The manifest version is currently `1`.

Example:

```text
manifest.json
manifest.json.asc             # optional
repository/
  dists/...                   # APT
  pool/...                    # APT
  <arch>/Packages/...         # RPM
  <arch>/repodata/...         # RPM
keys/
  repository.asc              # public key only
metadata/
  repository.json
  snapshot.json
  packages.json
```

`manifest.json` records the bundle ID, repository identity, format, distribution/version, source snapshot, optional base snapshot, channel, architecture, bundle type, package metadata, target package set, removed packages for delta bundles, creation time, compression, signing fingerprint and a SHA-256/size manifest for every non-manifest file.

Private GPG material is never exported.

## Full bundles

A full bundle contains every package in the selected snapshot that matches the requested architecture plus architecture-independent packages (`all` for DEB and `noarch` for RPM).

Before creation the backend returns a plan containing package counts, estimated bundle size, available disk space and dependency-closure state.

## Selected package bundles

A selected bundle starts from an explicit package list. The resolver walks dependency metadata recursively and selects the highest available version that satisfies the recorded version constraint.

Currently handled dependency syntax includes common package names, alternatives and the comparison operators `=`, `>=`, `>`, `>>`, `<=`, `<` and `<<`.

The planner reports missing dependencies and conflicts. Export is rejected if the dependency closure is incomplete.

The resolver operates exclusively on package metadata already ingested into the selected snapshot. It does not execute frontend-provided shell commands and does not silently fetch missing dependencies.

## Delta bundles

A delta plan compares a base snapshot with a target snapshot by `(package name, architecture)` and package SHA-256.

It reports:

- added packages;
- updated packages;
- removed packages;
- unchanged packages;
- target full size;
- delta payload size.

The bundle contains changed payloads plus a complete target package descriptor set. Import creates a new snapshot; the source/base snapshot is never mutated.

For a delta import, the offline destination must already contain an imported snapshot whose recorded source snapshot matches the delta's base snapshot. Missing unchanged package content causes the import to fail rather than producing an incomplete snapshot.

## Staging and import

Server-side staging is restricted to:

```text
/var/lib/webnas/os-repositories/incoming/offline-bundles/
```

The API addresses staged artifacts by derived IDs. It does not accept arbitrary filesystem paths.

Browser uploads stream into this directory with the module's configured upload limit and an atomic final rename.

The import flow is:

```text
stage
  -> archive validation
  -> safe extraction
  -> manifest validation
  -> SHA-256 verification
  -> package inspection
  -> optional GPG verification
  -> destination compatibility check
  -> content-addressed ingestion
  -> immutable snapshot creation
  -> optional channel publication
```

## Security model

Offline archives are untrusted input.

The extractor rejects:

- absolute paths;
- `..` path traversal;
- backslash path ambiguity;
- symlinks;
- hardlinks;
- devices;
- FIFOs;
- unsupported tar member types;
- duplicate paths;
- case-colliding paths;
- excessive archive member counts;
- excessive declared extracted size.

Extraction is manual rather than `extractall()`. Every destination is resolved through the module's managed-path guard before data is written.

Files are streamed in bounded chunks. The implementation does not load an entire multi-gigabyte archive or package into memory.

Before import, every declared file is checked for exact byte size and SHA-256. Unexpected files are reported. Package payloads are hashed independently and inspected by the existing DEB/RPM package inspector before ingestion.

External tools continue to use fixed argument arrays, `shell=False`, a restricted environment and bounded timeouts.

## GPG verification

A signed bundle contains an armored detached signature for `manifest.json` and the corresponding public key.

Verification occurs in a private temporary GnuPG home. If the cryptographic signature is correct but the fingerprint is not present in the local signing-key registry, the result is `verified` with trust `unknown`; it is not silently promoted to trusted.

Unsigned bundles are explicitly reported as unsigned. Repository-level package/signature policy remains controlled by the existing repository module.

## Air-Gapped Mode

Air-Gapped Mode is persisted in the offline settings table.

When enabled, the backend rejects new repository synchronization requests before they are queued. A synchronization job that was queued before Air-Gapped Mode was enabled is failed before DNS resolution, authenticated proxy setup or repository tooling can run.

Offline operations that use local content remain available: package browsing, bundle staging/verification/import, snapshots, channels, retention and storage inspection.

This is a backend policy, not merely a hidden frontend control.

## Retention and pinning

Default policy:

- keep the latest 5 bundles;
- remove eligible bundles older than 90 days;
- keep Production bundles;
- keep signed bundles;
- always keep pinned bundles.

Deleting a generated archive changes only the offline bundle artifact record. It does not delete packages from the shared content-addressed store, snapshots or published channels.

## Storage

The storage endpoint reports:

- logical package bytes;
- generated offline bundle bytes;
- staging/temporary bytes;
- logical snapshot bytes;
- physical content-store bytes;
- estimated bytes saved through deduplication;
- filesystem free space.

The authoritative package store remains SHA-256-addressed, so importing a package that already exists does not create another permanent payload copy.

## API

Current endpoints:

```text
GET    /api/modules/os-repositories/offline/dashboard
GET    /api/modules/os-repositories/offline/settings
PUT    /api/modules/os-repositories/offline/settings

GET    /api/modules/os-repositories/offline/targets
POST   /api/modules/os-repositories/offline/targets
GET    /api/modules/os-repositories/offline/targets/{id}
PUT    /api/modules/os-repositories/offline/targets/{id}
DELETE /api/modules/os-repositories/offline/targets/{id}

POST   /api/modules/os-repositories/offline/exports/plan
POST   /api/modules/os-repositories/offline/exports

GET    /api/modules/os-repositories/offline/bundles
GET    /api/modules/os-repositories/offline/bundles/{id}
GET    /api/modules/os-repositories/offline/bundles/{id}/download
PUT    /api/modules/os-repositories/offline/bundles/{id}/pin
DELETE /api/modules/os-repositories/offline/bundles/{id}

GET    /api/modules/os-repositories/offline/imports/staged
POST   /api/modules/os-repositories/offline/imports/upload
GET    /api/modules/os-repositories/offline/imports/{staged_id}/inspect
POST   /api/modules/os-repositories/offline/imports/{staged_id}/verify
POST   /api/modules/os-repositories/offline/imports/{staged_id}

GET    /api/modules/os-repositories/offline/delta/plan
POST   /api/modules/os-repositories/offline/snapshots/{snapshot_id}/freeze
GET    /api/modules/os-repositories/offline/storage
```

All routes are mounted through the existing module manifest and use the normal WebNAS session/CSRF/RBAC dependencies. Production publication additionally requires the existing `os-repositories.channels.promote` permission and exact `Production` confirmation.

## Database additions

The extension uses idempotent `CREATE TABLE IF NOT EXISTS` migrations for:

```text
offline_targets
offline_bundles
offline_imports
offline_snapshot_origins
snapshot_freezes
offline_settings
```

Indexes cover repository/time and status/time bundle queries plus imported snapshot lineage.

## Testing

Dedicated tests cover:

- offline schema/settings/targets;
- Air-Gapped Mode synchronization blocking;
- recursive dependency closure;
- missing dependencies;
- full bundle export and verification round trip;
- tar traversal rejection;
- delta calculation;
- idempotent snapshot freeze.

Repository CI additionally executes Ruff, mypy, Bandit, backend tests, integration tests, frontend validation/build, dependency review and CodeQL.

## Manual verification

1. Install `os-repositories` and create a disposable local APT repository.
2. Upload valid `.deb` packages and create a snapshot.
3. Request `/offline/exports/plan` for the snapshot and verify disk-space/dependency output.
4. Create a confirmed full bundle and download it.
5. Copy the archive into the controlled staging directory of another disposable WebNAS instance.
6. Inspect and verify the staged bundle.
7. Import it into a compatible repository and verify that a new snapshot is created.
8. Publish the imported snapshot to Testing and confirm the normal repository HTTP service serves its metadata.
9. Enable Air-Gapped Mode and confirm `/repositories/{id}/sync` is rejected without DNS or HTTP activity.
10. Generate a second source snapshot, create a delta plan/bundle and verify the offline destination requires the matching imported base snapshot.

## Current limitations

The backend foundation is implemented, but the following items remain outside the current PR scope or require additional hardening before they should be considered complete production features:

- archive compression is currently deterministic gzip/tar rather than `.tar.zst`;
- bundle export/import/verification currently execute synchronously instead of using dedicated durable offline jobs/SSE;
- the existing generic `os-repositories.*` permissions are reused; dedicated `os-repositories.offline.*` RBAC permissions are not yet registered;
- the dedicated Offline Repository Manager frontend workflow is not yet wired into `OsRepositoriesApp`;
- Hosts Manager group-to-target generation is not yet implemented;
- offline metadata is not yet included in the module backup/restore manifest;
- diagnostics do not yet expose offline-specific checks;
- snapshot freeze state is recorded but normal snapshot-deletion code does not yet consult it;
- dependency closure is based on the metadata currently stored by WebNAS and does not yet implement virtual `Provides`/RPM `Obsoletes` semantics;
- large exports are streamed to disk, but dedicated progress/cancellation/restart recovery for offline operations still requires durable-job integration.

These limitations are intentionally explicit so the current PR is reviewable as a real backend increment rather than presenting unimplemented UI or job behavior as complete.
