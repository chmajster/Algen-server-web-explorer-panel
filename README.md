# WebNAS

WebNAS is a Linux web administration panel inspired by NAS-style desktop interfaces without copying third-party branding or UI assets. The MVP includes PAM login, a desktop web UI, and a File Manager for browsing the authenticated user's home directory.

## MVP Features

- FastAPI backend with PAM authentication.
- HTTP-only signed sessions and CSRF protection.
- Login rate limiting.
- React + TypeScript + Vite frontend.
- File Manager with list/icon views, breadcrumbs, directory sidebar, upload, download, copy, move, rename, delete, trash, preview, search, stat, chmod, multi-select, and drag-and-drop move.
- Background tasks for copy, move, and delete.
- Copy and move transfers use `rsync` and expose live progress: status, percent, speed, transferred bytes, ETA, current file, exit code, and log tail.
- Ubuntu/Debian installer, updater, uninstaller, and systemd service.

## Development

Backend:

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=$PWD uvicorn app.main:app --reload --host 0.0.0.0 --port 5000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

For full per-user file access, run the backend on Linux with sufficient privileges to drop into the authenticated user context.

## File Transfers

`/api/files/copy` and `/api/files/move` enqueue `rsync` transfer tasks. Move is implemented as rsync first and source removal only after a successful transfer, so a failed or cancelled move keeps the source intact.

Task endpoints:

```text
GET  /api/files/tasks
GET  /api/files/tasks/{task_id}
GET  /api/files/tasks/{task_id}/events
POST /api/files/tasks/{task_id}/cancel
```

The frontend uses Server-Sent Events for live updates when available and falls back to polling. Completed transfers stay visible in the Transfers panel until the user hides them. To debug transfer failures, inspect the task `log_tail`, `rsync_exit_code`, and the service log.
