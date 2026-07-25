# Logs API and operations

The Logs application uses the authenticated WebNAS session, the existing CSRF mechanism for saved-view mutations, Activity Center auditing, and the identity permission registry. It never accepts a filesystem path or command string.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/logs/sources` | Available, unavailable, and permission-visible source tree |
| `GET` | `/api/logs/entries` | Filtered bounded records with continuation token |
| `GET` | `/api/logs/stream` | Filter-aware SSE live tail |
| `GET` | `/api/logs/boots` | Detected systemd boots |
| `GET` | `/api/logs/services` | Dynamically detected systemd services |
| `GET` | `/api/logs/services/{unit}` | Service state and recent records |
| `GET` | `/api/logs/containers` | Running and stopped Docker containers |
| `GET` | `/api/logs/fields` | Supported structured journal fields |
| `POST` | `/api/logs/export` | Bounded TXT, JSON, JSONL, or CSV export (CSRF) |
| `GET` | `/api/logs/saved-views` | Built-in and private user views |
| `POST` | `/api/logs/saved-views` | Create a private view (CSRF) |
| `PATCH` | `/api/logs/saved-views/{id}` | Replace a private view (CSRF) |
| `DELETE` | `/api/logs/saved-views/{id}` | Delete a private view (CSRF) |

`/api/logs/entries` accepts `source`, `query`, `regex`, `case_sensitive`, `negate`, `message_only`, repeated `priority`, `unit`, `pid`, `uid`, `identifier`, `transport`, `hostname`, `device`, `username`, `group`, `boot_id`, `container_id`, `since`, `until`, `cursor`, `direction`, and `limit`. The default limit is 200 and the maximum is 1,000. Invalid combinations return a user-safe HTTP error.

## Permissions

- `logs.view_own`
- `logs.view_system`
- `logs.view_kernel`
- `logs.view_services`
- `logs.view_security`
- `logs.view_webnas`
- `logs.view_containers`
- `logs.live`
- `logs.export`
- `logs.saved_views.manage`

Administrators receive all permissions. Operators receive system, kernel, service, WebNAS and container visibility, live tail, export and saved views, but not sensitive authentication/security files by default. Auditors receive read/export access without live or mutation rights. Regular users receive only explicitly personal Activity Center data and private saved views.

Every endpoint verifies the concrete source permission. UI visibility is not treated as authorization.

## Safety and limits

- journal records use structured JSON; important fields are normalized while bounded original fields remain available;
- systemd units, container identifiers, boot IDs, identifiers, time ranges, priorities, cursors and limits are validated;
- subprocesses use argument arrays, fixed environments, timeouts and bounded stdout/stderr; `shell=True` is never used;
- classic files come from a closed source map, are read from the end, and support bounded `.1`–`.5` and `.gz` rotations;
- gzip expansion is capped by compressed size, decompressed bytes, and elapsed time;
- messages, fields, private keys, authorization values, cookies, passwords, tokens, credentials and connection strings pass through shared redaction;
- browsing/export auditing records the source, count and filter presence, never the query or returned message;
- SSE closes on disconnect, sends keepalives, isolates source errors, and is bounded in both server batches and browser memory;
- one failed source does not prevent `/sources` or other providers from working.

## Manual verification

1. Grant the service account only the required journal access and restart WebNAS.
2. Open **Logs** from Start and confirm Journal, Kernel, Services, Files, WebNAS, and optional Containers statuses.
3. Search for a known non-secret phrase, enable errors-only and current-boot filters, then load an older page.
4. Select a record and inspect normalized fields and raw JSON.
5. Start Live mode, pause it, generate a service event, and confirm the pending count before resuming.
6. Export the same filtered view in all four formats and verify UTF-8.
7. Save and delete a view, then sign in as another user to confirm isolation.
8. Remove journal permission temporarily and confirm graceful `permission_denied` behavior while allowed files/Activity Center remain usable.
