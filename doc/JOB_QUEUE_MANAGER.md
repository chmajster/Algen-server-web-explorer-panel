# Job Queue Manager

## Overview

Job Queue Manager is the central asynchronous execution subsystem for WebNAS. It extends the existing `app.jobs` queue instead of introducing a second scheduler. Module code can enqueue work, report progress and structured logs, request cancellation, declare dependencies and correlate parent/child operations.

## Architecture

The backend consists of `backend/app/jobs/models.py`, `repository.py`, `runner.py`, `service.py` and `api.py`. Jobs are persisted in `jobs.sqlite3` under `paths.data_dir`. The repository upgrades older databases in place, adds job/log/dependency indexes and keeps the existing fields/API compatible.

The runner uses a bounded in-process priority queue. Global worker count is controlled by `WEBNAS_JOB_WORKERS` (default 4, maximum 16). Per-module concurrency is controlled by `WEBNAS_JOB_MODULE_WORKERS` (default 2, maximum 16). Priorities are `low`, `normal`, `high` and `critical`.

Supported states are `queued`, `waiting`, `running`, `success`, `failed`, `cancel_requested`, `cancelled`, `timed_out`, `retrying` and `blocked`.

## Reliability

Queued/running/retrying operations are reconciled on WebNAS startup. An operation interrupted by a backend restart is marked failed instead of remaining permanently `running`. Retry-safe handlers can use exponential backoff. Dependencies keep children in `waiting`; a failed/cancelled/timed-out dependency blocks its dependents.

Job logs are bounded to 2,000 entries per job and each entry has a bounded message/data payload. Job metadata, results, errors and logs pass through the shared secret-redaction layer. Terminal history can be retained and cleaned through the manager API.

## API

```text
GET    /api/jobs
GET    /api/jobs/summary
GET    /api/jobs/{job_id}
GET    /api/jobs/{job_id}/logs
POST   /api/jobs/{job_id}/cancel
POST   /api/jobs/{job_id}/retry
DELETE /api/jobs/history
```

The frontend polls the existing API every three seconds and does not reload the full page.

## RBAC

- `jobs.view`
- `jobs.manage`
- `jobs.cancel`
- `jobs.retry`

Mutations enforce CSRF and backend authorization. Cancel/retry/history cleanup are written to Activity Center.

## Usage

Modules can submit registered handlers or one-off callables through `JobService`. Handlers receive `JobContext`, which exposes progress, structured logging and cancellation checks.

## Troubleshooting

If a job is `blocked`, inspect its dependencies. If a job is `failed` with an interruption message immediately after startup, the previous WebNAS process stopped while that job was active. Use Retry only for jobs whose handler is explicitly registered as retry-safe.
