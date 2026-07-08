# WebNAS

WebNAS is a Linux web administration panel inspired by NAS-style desktop interfaces without copying third-party branding or UI assets. The MVP includes PAM login, a desktop web UI, and a File Manager for browsing the authenticated user's home directory.

## MVP Features

- FastAPI backend with PAM authentication.
- HTTP-only signed sessions and CSRF protection.
- Login rate limiting.
- React + TypeScript + Vite frontend.
- File Manager with list/icon views, breadcrumbs, directory sidebar, upload, download, copy, move, rename, delete, trash, preview, search, stat, chmod, multi-select, and drag-and-drop move.
- Background tasks for copy, move, and delete.
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
