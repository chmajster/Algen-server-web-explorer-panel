# WebNAS appliance backup and restore

WebNAS appliance backup coordinates configuration, persistent domain state and credential key material into one checksummed recovery artifact. It is intentionally separate from module-specific convenience backups.

## What is included

By default a backup contains:

- the active WebNAS configuration file as `config/config.yaml`;
- SQLite databases below `paths.data_dir`, captured with SQLite's online backup API rather than copying live WAL files;
- small configuration/metadata files below the data directory;
- the Hosts Manager credential key and other files under the `secrets` directory;
- a versioned JSON manifest with SHA-256, byte size, file mode, source WebNAS version and minimum restore version for every payload member.

The authentication session database `sessions.sqlite3` is deliberately excluded. Restoring server sessions after a migration or host replacement would preserve browser bearer state across recovery boundaries and is not required for service recovery.

Repository worktrees, caches, temporary directories and previous appliance backup archives are excluded. Symbolic-link sources are also excluded so a backup cannot cross the configured data-root boundary through a link.

## Create

Run from an installed or source checkout:

```bash
python3.14 scripts/webnas_backup.py create
```

An optional label can be supplied:

```bash
python3.14 scripts/webnas_backup.py create --label before-upgrade
```

Archives are stored in `<data_dir>/appliance-backups` with mode `0600`. They can contain encrypted credential records and the corresponding encryption key, so treat the archive itself as a secret recovery asset.

## Validate / dry-run

A portable archive can be copied to another WebNAS host and validated without changing the installation:

```bash
python3.14 scripts/webnas_backup.py validate /secure-transfer/webnas-....webnas-backup.zip
python3.14 scripts/webnas_backup.py restore /secure-transfer/webnas-....webnas-backup.zip
```

Validation rejects:

- absolute, parent-traversal or undeclared archive members;
- duplicate ZIP member names or duplicate manifest resource entries;
- symbolic-link archive paths/restore targets and source files outside the data-root model;
- individual members or archives beyond bounded uncompressed-size limits;
- SHA-256 mismatches;
- malformed manifests or unsupported format versions;
- SQLite databases that fail `PRAGMA quick_check`;
- archives requiring a newer WebNAS restore version.

## Restore

A real restore is intentionally explicit:

```bash
systemctl stop webnas.service webnas-backend-blue.service webnas-backend-green.service
python3.14 scripts/webnas_backup.py restore /secure-transfer/webnas-....webnas-backup.zip \
  --apply \
  --confirm 'RESTORE webnas-....webnas-backup.zip'
systemctl start webnas.service
```

Before changing any target the coordinator creates a new `pre-restore` appliance backup. Payloads are fully validated and staged first. Target files are replaced atomically through sibling temporary files; if an apply step fails, already changed files are restored from local preimages.

SQLite targets are revalidated after replacement. The recommended production procedure is an offline/maintenance restore so active SQLite connections cannot keep using a pre-restore inode.

## API

The internal administrative API is available under `/api/system/appliance-backups` and uses existing separate backup-create and backup-restore permissions. Mutations therefore require both an authenticated session and CSRF. Apply restore additionally requires exact text `RESTORE <archive-name>`.

The API returns metadata only. It does not provide an archive-download endpoint because appliance archives may contain credential key material. Export and transfer the root-owned archive through an administrator-controlled channel.

## Recovery-unit rule for credentials

Hosts Manager encrypted credential rows and `secrets/hosts-manager.key` must be kept together. Restoring only one side is unsupported. Appliance backup includes both by default and the archive should remain encrypted at rest by the administrator's storage/backup platform when it leaves the WebNAS host.
