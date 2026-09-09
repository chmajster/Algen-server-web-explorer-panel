# File transfers use the persistent Job Service

- Route File Manager copy/move background execution through the shared persistent `JobService` instead of creating ad-hoc daemon threads.
- Preserve the existing transfer API and `transfers.sqlite3` compatibility history while exposing each execution attempt in the global operations store.
- Claim queued transfers under the existing cross-process coordination lock so multiple backend workers do not submit the same transfer concurrently.
- Report transfer progress and cancellation through the central job context.
- Mark transfers interrupted by an application restart as failed and require an explicit retry or resume instead of automatically repeating a potentially destructive move operation.
- Add regression and architecture tests for persistent recovery, global job submission, and multi-manager single-claim behavior.
