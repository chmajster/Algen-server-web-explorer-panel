# Long-running jobs

`app.core.jobs` is the common typed contract for long-running operations. A snapshot carries module id, operation, status, progress, typed steps, retry count, cancellation/resume capabilities, result, sanitized logs and a structured error code. Module manifests declare the job kinds and supported actions they expose.

```text
API command -> durable job store -> handler supplied by module
                    |                    |
                    +-> audit/events     +-> progress/steps/result
                    |
                    +-> polling or SSE -> frontend task UI
```

Handlers implement the `JobHandler` port. Infrastructure owns persistence and worker scheduling. A handler must make retry/resume semantics explicit; otherwise retry starts the operation from the beginning. Existing file-transfer and package-operation stores retain their proven persistence implementations and are normalized to this contract at module boundaries; startup recovery remains owned by those adapters.
