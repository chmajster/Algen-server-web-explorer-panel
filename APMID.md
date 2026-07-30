# APMID

APMID is an installable WebNAS module (`id: apmid`) that owns the application
identifier registry previously embedded in Hosts Manager. Its Package Center
manifest has no system packages or systemd services and is Proxmox-safe.

## Architecture and data

`backend/app/modules/apmid/service.py` is the authoritative persistence and
authorization boundary. `router.py` exposes the typed API. Hosts Manager calls
the same service for enrollment and generated `<APMID>.<ENVIRONMENT>` groups.
The dedicated React application is `ApmidApp.tsx`; `/access` controls its
dynamic launcher visibility.

The private `${data_dir}/apmid/apmid.sqlite3` database uses a `0700` directory
and `0600` files. It contains:

- `schema_version` and `migration_markers`;
- `apmids` with stable ID, case-insensitive code, name, description, state,
  business owner, timestamps and attribution;
- `apmid_members` with existing Linux/WebNAS usernames and roles;
- `apmid_member_permissions` with enum-constrained allow/deny overrides;
- `apmid_history`, mirrored to Activity Center.

No password or Identity secret is copied.

## Authorization

Global permissions are `apmid.view`, `apmid.create`, `apmid.update`,
`apmid.delete`, `apmid.members.view`, `apmid.members.manage`,
`apmid.permissions.view`, `apmid.permissions.manage`, `apmid.audit.view`,
`apmid.backup` and `apmid.restore`.

Administrators have full access. Operators can view, create, update, manage
members, inspect permissions/audit and back up, but cannot delete, change
permission overrides or restore. Auditors have read/audit access. Users have no
global access and enter only through membership.

Resource roles are `viewer`, `operator`, `manager` and `owner`. Individual
allow extends the role; deny always wins. The backend calculates effective
permissions and rejects removal, demotion or denial that would remove the last
effective owner.

## API

Base path: `/api/modules/apmid`.

- `GET /access`, `/dashboard`, `/items`, `/items/{id}`
- `POST /items`, `PUT|DELETE /items/{id}`
- `GET|POST /items/{id}/members`
- `PUT|DELETE /items/{id}/members/{username}`
- `GET /items/{id}/permissions`
- `PUT|DELETE /items/{id}/members/{username}/permissions`
- `GET /items/{id}/history`, `GET /history`
- `GET /users`
- `GET|POST /backups`, `POST /backups/{backup_id}/restore`

Lists support bounded pagination (maximum 200), search, status, sort and
direction. Every mutation requires a valid session, CSRF, payload validation
and backend authorization. Old `/api/modules/hosts-manager/apmids...` routes
remain adapters to this service.

## Migration

On first initialization APMID checks `hosts-manager/hosts.sqlite3`. If legacy
records exist it:

1. creates a private SQLite backup under `apmid/migrations`;
2. copies records transactionally without changing IDs;
3. records marker `hosts-manager-v1`;
4. leaves the old database, relations and group IDs untouched as rollback.

The marker makes repeated starts idempotent. Runtime reads and writes use the
new domain.

## Backup, restore and uninstall

A backup is a consistent SQLite snapshot plus JSON manifest with schema
version, SHA-256, time and actor. Restore requires `apmid.restore` and exact
confirmation `APMID`, verifies SHA-256 and SQLite integrity, creates a safety
backup and atomically replaces the database.

Normal uninstall preserves data. Full data removal requires exact text `APMID`
and is blocked while Hosts Manager enrollment tokens or managed groups with
hosts reference an APMID.

## Manual verification

1. Install APMID and confirm its launcher icon appears without browser reload.
2. Create a lowercase code and verify it is stored uppercase.
3. Assign an existing non-technical user; test role, allow and deny precedence.
4. Confirm the same record is selectable in the Hosts Manager installer.
5. Create an enrollment token and verify deletion returns `409 APMID_IN_USE`.
6. Back up, edit, restore with `APMID`, and verify the old value returns.
7. Uninstall without data removal, reinstall and verify records remain.

