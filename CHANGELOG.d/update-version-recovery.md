## Recovery after a failed system update

- Added an “Install a selected repository version” action on the failed WebNAS update screen for users with `updates.apply` permission, with Polish and English labels, version loading/retry, an explicit selection and confirmation, and an older-version compatibility warning.
- Recovery lists up to 100 repository tags and 30 recent `main` commits and resolves each selection to an immutable commit SHA. The backend verifies the selection, CSRF/session permissions and failure ID, rejects stale or duplicate recovery requests, and keeps the pinned revision while waiting for active operations.
- Both update launch paths and the privileged broker pass the validated revision to the standard installer. Explicit `--revision` installs download that exact archive instead of silently using `main` or a local checkout.
- Recovery preserves `config.yaml`, uses the existing update progress/logging and service handover, and does not reverse database migrations. Back up application data before installing an older release.
