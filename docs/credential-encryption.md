# Credential encryption and recovery

WebNAS keeps credential master keys outside SQLite and never returns stored secret envelopes through browser APIs.

## Envelope versions

- `WAC2` is the current write format. It uses ChaCha20-Poly1305 from the maintained `cryptography` package with a random 96-bit nonce and associated data bound to the credential identifier or backup context.
- `WAC1` is the legacy authenticated envelope. It remains read-only compatible so upgrades do not make existing credentials or encrypted backups inaccessible.
- New or edited credential secrets and newly exported encrypted backups are written as `WAC2`.

The 256-bit master key remains a root/private file outside the Hosts Manager SQLite database. The WAC2 AEAD key is domain-separated from that master key before use.

## Migrating existing WAC1 credentials

First inspect without changing anything:

```bash
sudo python3.14 scripts/migrate_credentials_wac2.py
```

The command reports only counts. It never prints plaintext or stored envelopes.

For the actual migration, place WebNAS in maintenance mode and stop the application services so no credential write can race the migration. Then run:

```bash
sudo systemctl stop 'webnas@*.service'
sudo python3.14 scripts/migrate_credentials_wac2.py --apply
```

Before modifying SQLite, the command creates a mode-`0600` online backup beside the Hosts Manager database. Only active non-empty WAC1 envelopes are rewritten. WAC2 records are left byte-for-byte unchanged. If any WAC1 authentication check fails, the transaction is rolled back.

After migration, start WebNAS and verify health before deleting the pre-migration backup.

## Master-key backup

Treat the Hosts Manager database and `/var/lib/webnas/secrets/hosts-manager.key` as one recovery unit. Back up both through a trusted root-only channel. Losing the key makes WAC1 and WAC2 data unrecoverable; copying only SQLite is not a usable credential backup.

Do not store the master key inside SQLite, in Git, in the frontend bundle, in logs, or in a WebNAS API response.

## Master-key rotation

Do not replace `hosts-manager.key` in place while encrypted records still depend on it. A safe rotation requires an offline re-encryption transaction:

1. stop WebNAS services;
2. take and verify a backup of the current database and current master key as one recovery set;
3. migrate all WAC1 records to WAC2 first;
4. generate a new random 32-byte key as a root-only temporary file with mode `0600`;
5. decrypt every envelope with the old key in memory and immediately re-encrypt it with the new key using the same associated-data identifier;
6. verify every new envelope with the new key before committing the database transaction;
7. atomically replace the master-key file only as part of the controlled rotation procedure;
8. start WebNAS and verify credential-backed operations;
9. keep the old database/key recovery set until the rotation is operationally confirmed.

A raw key-file replacement without re-encryption is destructive and is not a supported rotation method.
