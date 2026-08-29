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

## Security Boundaries

Every API path is resolved server-side before use. Client-provided paths are not passed to a shell. File operations use `subprocess.run` with argument arrays and a base64 JSON payload, then execute after privilege drop in the worker process.
