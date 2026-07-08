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

## Frontend

The UI is a desktop-in-browser experience with a top bar, taskbar, windowed File Manager, breadcrumbs, directory sidebar, list/icon views, upload/download, preview, drag-and-drop move, and task progress display.

## Security Boundaries

Every API path is resolved server-side before use. Client-provided paths are not passed to a shell. File operations use `subprocess.run` with argument arrays and a base64 JSON payload, then execute after privilege drop in the worker process.
