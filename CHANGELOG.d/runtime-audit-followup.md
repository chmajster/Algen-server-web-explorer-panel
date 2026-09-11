Fixed runtime regressions found during the post-visual audit:

- route log exports through the authenticated API transport so CSRF and session recovery apply to downloads;
- treat every non-success health response as a failed backend probe instead of reporting false connectivity;
- clean orphaned chunk-upload temporary files left by a previous backend process;
- finalize completed chunk uploads outside the global upload-session lock so one slow import does not block unrelated uploads.
