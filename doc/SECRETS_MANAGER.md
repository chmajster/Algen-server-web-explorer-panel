# Secrets Manager

Secrets Manager (`secrets-manager`) is the authoritative secret store for WebNAS. Hosts Manager is no longer the owner of credential secret material.

## Storage and encryption

The module stores metadata and encrypted envelopes in `/var/lib/webnas/secrets-manager/secrets.sqlite3`. The database is private and must not be opened directly by other modules. The master key is stored separately at `/var/lib/webnas/secrets/secrets-manager.key`.

Secret values use the existing WAC2 envelope implementation backed by ChaCha20-Poly1305. A random 96-bit nonce is generated for every write and the secret identifier is supplied as associated data. WAC1 remains readable only for migration compatibility. New and edited values are written as WAC2.

The Secrets Manager data directory is mode `0700`; the SQLite database, backup artifacts and master key are mode `0600`. Secret values and encrypted envelopes are never returned by browser-facing APIs.

## Credential migration

On startup Secrets Manager checks the legacy Hosts Manager credential store at `/var/lib/webnas/hosts-manager/hosts.sqlite3`.

If the legacy `credentials` table has not already been migrated, Secrets Manager:

1. creates an online SQLite backup under the Secrets Manager backup directory and sets mode `0600`;
2. reads legacy credential rows without modifying them;
3. decrypts each non-empty WAC1/WAC2 envelope in memory with `/var/lib/webnas/secrets/hosts-manager.key` and the original credential ID as associated data;
4. immediately re-encrypts the payload with the Secrets Manager key and the same credential ID;
5. authenticates each new envelope before commit;
6. preserves IDs, names, types, usernames, descriptions, environment references, `shared_with`, active state, timestamps and actors;
7. commits the destination transaction and writes an idempotent migration marker.

If any source envelope fails authentication or another migration step fails, the destination transaction is rolled back and the legacy Hosts Manager credential runtime remains active. The source database is not deleted or rewritten by the migration.

Existing Hosts Manager foreign keys still reference the legacy `credentials` table. Migrated legacy rows are therefore retained as rollback/reference artifacts. When a brand-new Secrets Manager secret must be referenced by one of those legacy local foreign keys, a metadata-only compatibility row is created in the legacy table with an empty `encrypted_secret`. Secret material remains authoritative only in Secrets Manager.

## Compatibility

After a successful migration the legacy `HostRegistryService.credentials`, `save_credential`, `verified_credential` and `delete_credential` surface is redirected to Secrets Manager. This preserves existing consumers such as Hosts Manager, Ansible Controller, Proxmox Manager, Redfish/IPMI, repository authentication and power profiles while they transition to the public Secrets Manager contract.

The old Credentials frontend module is hidden from normal navigation and is retained only so previously restored window state does not fail. New administration uses the Secrets Manager application.

## Secret types

Current types are:

- `username_password`
- `ssh_password`
- `ssh_private_key`
- `become_password`
- `api_token`
- `generic_secret`
- `proxmox_api`
- `redfish`
- `ipmi`
- `git_private_key`
- `wol`

The storage model keeps the type as data so additional types can be introduced without a new encryption format.

## Backend contract

Cross-module code must use `app.modules.secrets_manager.public` and must not open the Secrets Manager database or read the key directly.

A secret request requires:

- `secret_id`;
- the consuming module ID;
- a non-empty purpose.

`verified_secret()` checks that the secret exists, is active and contains encrypted material, verifies that the consumer is present in `shared_with`, decrypts only on the backend and writes a use audit record. Plaintext is returned only to backend code in memory.

## Browser API

Base path: `/api/modules/secrets-manager`.

Endpoints include:

- `GET /status`
- `GET /types`
- `GET /share-targets`
- `GET /secrets`
- `GET /secrets/{id}`
- `POST /secrets`
- `PUT /secrets/{id}`
- `DELETE /secrets/{id}`
- `GET /audit`
- `POST /backup`
- `POST /restore`
- `POST /rotate-key`

Secret metadata includes configuration flags such as `secret_configured` and `passphrase_configured`; it never contains plaintext secret values or stored envelopes. During edit, an empty secret field keeps the existing encrypted value.

## RBAC

Permissions:

- `secrets-manager.view`
- `secrets-manager.manage`
- `secrets-manager.use`
- `secrets-manager.audit.view`
- `secrets-manager.backup`
- `secrets-manager.restore`
- `secrets-manager.rotate`

Administrators receive all Secrets Manager permissions. Auditors receive metadata/audit read access only.

## Events

Secrets Manager publishes metadata-only events:

- `secret.created`
- `secret.updated`
- `secret.deleted`

Payloads contain identifiers and safe metadata only. Secret values, passphrases and encrypted envelopes are prohibited.

## Backup and restore

`POST /backup` returns a WAC-encrypted Secrets Manager backup payload. Restore validates the backup format and authenticates every stored envelope before committing. A local safety SQLite backup is created before replacement.

Treat `secrets.sqlite3` and `secrets-manager.key` as one disaster-recovery unit. Losing the key makes encrypted records unrecoverable.

## Key rotation

Online key replacement is intentionally not implemented because replacing the SQLite envelopes and external key cannot be made crash-atomic while the service remains active. `/rotate-key` returns the supported offline rotation plan. Rotation requires stopping WebNAS, backing up database+key, re-encrypting and authenticating every envelope, atomically replacing the key only after database verification, then validating secret-backed operations before removing the recovery set.
