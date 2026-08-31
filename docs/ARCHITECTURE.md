# WebNAS Architecture

WebNAS is a Linux-first administration panel with a FastAPI backend and a React/Vite frontend. The frontend is served from `frontend/dist` by the backend after installation.

## Backend

- `app.main` exposes the REST API, session handling, CSRF checks, and static frontend hosting.
- `app.auth` authenticates local Linux users through PAM. Passwords are never stored.
- `app.path_policy` resolves all requested paths against the authenticated user's home directory or configured allowed roots.
- `app.worker` performs file operations after dropping privileges to the authenticated Linux account with `setgid`, `initgroups`, and `setuid`.
- `app.tasks` provides an in-memory queue for long copy, move, and delete operations.
- `app.security` signs HTTP-only session cookies and rate-limits login attempts.

The systemd service runs as root because impersonating arbitrary local users requires privilege. The worker immediately drops privileges before touching user files.

### Application services and dependency direction

The composition root owns shared runtime services through `ApplicationContainer`. HTTP handlers consume explicit application state/dependencies rather than mutating module globals at startup. The intended dependency direction for administrative features is:

```text
Router
  ↓
Service
  ↓
Repository / Adapter
  ↓
Privileged Broker
```

Read-only system probes should use the bounded `ReadOnlyCommandRunner`. Mutating operations that require privilege use typed `PrivilegedCommandRunner` operations backed by the existing privileged broker. The compatibility `broker_command()` translator remains migration-only and must not become a generic root-command escape hatch.

Settings schemas and the administrative rate limiter live outside the compatibility settings router in `app.settings_support`. Further settings decomposition should preserve existing endpoint paths while moving business logic toward services/adapters.

### Module lifecycle

Builtin modules are discovered from data-only `manifest.yaml` files. A module manifest may declare:

```text
Module Manifest
├── routers
├── startup
├── shutdown
└── health_check
```

`bootstrap.py` does not import schedulers from individual business modules. Module-owned schedulers and other side effects start through manifest lifecycle callbacks and stop in reverse dependency order. Lifecycle start/stop operations are idempotent.

Lifecycle state and health state are deliberately separate:

- lifecycle: `active`, `disabled`, `unavailable`, `broken`
- health: `healthy`, `degraded`, `unhealthy`, `unknown`

A transient health-check failure does not change an active module to `broken`. A later successful health check can therefore recover from `unhealthy` to `healthy` without restarting WebNAS. Optional module initialization failures are isolated and exposed through diagnostics; only a manifest explicitly marked `critical` may fail the application startup.

Application-owned asyncio tasks are registered with `BackgroundTaskManager`, then cancelled and awaited during shutdown. This prevents orphaned pending coroutines and centralizes background-task failure logging.

## Infrastructure module boundaries

Backend modules are discovered from manifests and may consume another module only through an explicitly supported public contract. Secrets Manager is the authoritative encrypted secret boundary. Browser-facing APIs expose metadata only; plaintext is returned only to a backend consumer that provides its module ID and purpose and is present in the secret's `shared_with` allowlist.

The Secrets Manager master key is stored outside SQLite with private filesystem permissions. Existing Hosts Manager credential IDs remain stable during migration: legacy envelopes are decrypted only in memory, re-encrypted with the Secrets Manager WAC2 key, authenticated before commit and backed up before migration. The legacy database remains a rollback artifact, while new compatibility rows needed for local foreign keys contain no encrypted secret material.

Webhook Manager references Secrets Manager IDs rather than storing credentials. A webhook target is resolved and validated immediately before each attempt; blocked address classes fail closed. Delivery connects to the validated numeric address rather than resolving the hostname again, preserves the original hostname for HTTP `Host` and TLS certificate verification, and does not automatically follow redirects. Private RFC1918/ULA targets require the separate critical `webhook-manager.configure` permission.

Fail2Ban Manager owns only WebNAS-managed override files, uses fixed subprocess argument arrays, validates jail/IP/config input, validates the complete Fail2Ban configuration before reload and restores the previous managed file on failure. Fail2Ban and Secrets Manager publish metadata-only events to the existing in-process event bus; Webhook Manager subscribes through a bounded worker queue.

## Performance architecture

### Resource Sampler

Resource Monitor uses one process-local sampler shared by all clients. FAST metrics (CPU, RAM/swap, network and disk I/O) are sampled at most once per second. MEDIUM probes (temperature, CPU frequency and WebNAS service status) use a 7.5 second interval. SLOW mount/filesystem data uses a 45 second interval. Hostname, OS, kernel and logical CPU count are STATIC for the process lifetime.

Allowed-root filesystem usage is cached per authenticated username with the same SLOW TTL and a bounded 64-user LRU. The cache contains no credentials or secrets and preserves the existing user-specific path policy. The sampler runs from the FastAPI lifespan and blocking host probes execute through `asyncio.to_thread`, so they do not block the event loop.

Each new FAST snapshot publishes `resource.sample.updated` through the existing runtime event broker. MonitorApp consumes that shared SSE connection and refreshes from the cached snapshot. Continuous polling is disabled while realtime is healthy; when the stream is unavailable, fallback polling is at least five seconds and stops again after reconnect. Hidden tabs do not perform automatic Resource Monitor refreshes.

### File Manager pagination

For name/type sorting, the privileged user worker scans a directory with `os.scandir()`, applies hidden/filter rules and sorting using lightweight `DirEntry` data, slices the requested page, then expands full owner/group/permission/stat metadata only for that page. Sorts whose correctness depends on full metadata (`size`, `owner`, `group`, `permissions`, `mtime`) still collect metadata for every candidate before sorting, preserving API semantics.

Recursive search uses a bounded iterative `scandir()` traversal rather than unbounded `rglob("*")`. It has result, entry and time budgets and does not recurse through directory symlinks.

File operations intentionally keep the short-lived UID/GID worker boundary. The existing privileged broker is a multi-threaded root process; changing process credentials with `setuid()`/`setgid()` inside one broker thread would change credentials process-wide and weaken isolation. A persistent per-user broker should only replace this model if it uses a separately supervised process-per-identity or an equally strong credential boundary.

### Cache TTL and invalidation

Resource cache tiers are in-memory and process-local. User filesystem cache entries may be explicitly invalidated with `resource_sampler.invalidate_user()`. No API response cache is added and the existing `Cache-Control: no-store` policy for user data remains unchanged.

### Profiling

`app.performance.performance_timing` logs structured timing fields for `/api/files/list`, `/api/system/resources`, and Hosts Manager API routes: endpoint path, `duration_ms`, and HTTP status. Query strings, user file paths, request bodies and credentials are not logged. Use these timings together with the File Manager regression tests and Resource Sampler concurrency tests when comparing changes.

## Frontend

The UI is a desktop-in-browser experience with a top bar, taskbar, windowed File Manager, breadcrumbs, directory sidebar, list/icon views, upload/download, preview, drag-and-drop move, and task progress display.

Desktop runtime concerns that are independent of window/business state are separated into dedicated hooks. Clock updates, system dark-mode observation and viewport/chrome measurement live outside `DesktopController`, reducing effect density while preserving the existing window state and persistence contract.

## Security Boundaries

Every API path is resolved server-side before use. Client-provided paths are not passed to a shell. File operations use `subprocess.run` with argument arrays and a base64 JSON payload, then execute after privilege drop in the worker process.

Architecture tests prevent module-private cross-imports, concrete business-module imports from the composition root, direct command execution from module HTTP routers and any `shell=True` backend invocation.
