# Credential encryption and recovery

Secrets Manager is the authoritative secret store for WebNAS. WebNAS keeps secret master keys outside SQLite and never returns stored plaintext values or encrypted envelopes through browser APIs.

## Envelope versions

- `WAC2` is the current write format. It uses ChaCha20-Poly1305 from the maintained `cryptography` package with a random 96-bit nonce and associated data bound to the secret identifier or backup context.
- `WAC1` is the legacy authenticated envelope. It remains read-only compatible so upgrades and migration do not make existing credentials inaccessible.
- New or edited Secrets Manager values and newly exported encrypted backups are written as `WAC2`.

The 256-bit master key remains a root/private file outside SQLite. The WAC2 AEAD key is domain-separated from that master key before use.

## Hosts Manager -> Secrets Manager migration

The historical credential store uses:

- database: `/var/lib/webnas/hosts-manager/hosts.sqlite3`;
- key: `/var/lib/webnas/secrets/hosts-manager.key`.

The authoritative Secrets Manager store uses:

- database: `/var/lib/webnas/secrets-manager/secrets.sqlite3`;
- key: `/var/lib/webnas/secrets/secrets-manager.key`.

At first successful Secrets Manager startup, the migration creates a mode-`0600` SQLite backup of the legacy database, reads the legacy credential rows, decrypts each non-empty WAC1/WAC2 envelope only in memory with the historical key and original credential ID as associated data, immediately writes a WAC2 envelope with the Secrets Manager key and the same ID, authenticates the new envelope, and commits all destination rows with an idempotent migration marker.

Credential IDs, metadata, `shared_with`, environment relationships, timestamps and actors are preserved. The historical credential rows are retained unchanged as rollback/reference artifacts. If any legacy envelope fails authentication, the destination transaction is rolled back and the legacy runtime remains active.

The old `scripts/migrate_credentials_wac2.py` utility remains relevant for an installation that needs to normalize legacy WAC1 Hosts Manager data before a controlled migration, but it is no longer the primary ownership transition mechanism.

## Master-key backup

Treat each encrypted database and the key that protects it as one recovery unit. For the authoritative store, back up `/var/lib/webnas/secrets-manager/secrets.sqlite3` and `/var/lib/webnas/secrets/secrets-manager.key` through a trusted root-only channel. Losing the key makes the encrypted secret data unrecoverable; copying only SQLite is not a usable backup.

During the post-upgrade rollback window, keep the pre-migration Hosts Manager database backup together with `/var/lib/webnas/secrets/hosts-manager.key`.

Do not store a master key inside SQLite, in Git, in the frontend bundle, in logs, event payloads, audit details, or WebNAS API responses.

## Master-key rotation

Do not replace `secrets-manager.key` in place while encrypted records still depend on it. A safe rotation requires offline maintenance because the external key-file replacement and SQLite envelope replacement cannot be made crash-atomic while requests are being served.

Supported procedure:

1. stop WebNAS services;
2. take and verify a backup of the current Secrets Manager database and current master key as one recovery set;
3. ensure all active envelopes are readable and WAC2 is the write format;
4. generate a new random 32-byte key as a root-only temporary file with mode `0600`;
5. decrypt every envelope with the old key in memory and immediately re-encrypt it with the new key using the same associated-data identifier;
6. authenticate every new envelope with the new key before committing the database transaction;
7. atomically replace the master-key file only as part of the controlled rotation procedure;
8. start WebNAS and verify Hosts Manager, Ansible, Proxmox, webhook and other secret-backed operations;
9. keep the old database/key recovery set until rotation is operationally confirmed.

`POST /api/modules/secrets-manager/rotate-key` deliberately returns this maintenance plan instead of performing a dangerous online raw-key replacement.

A raw key-file replacement without re-encryption is destructive and unsupported.
