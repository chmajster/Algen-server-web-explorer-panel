Fixed runtime regressions found during the post-visual audit:

- route log exports through the authenticated API transport so CSRF and session recovery apply to downloads;
- treat every non-success health response as a failed backend probe instead of reporting false connectivity;
- clean orphaned chunk-upload temporary files left by a previous backend process;
- finalize completed chunk uploads outside the global upload-session lock so one slow import does not block unrelated uploads;
- create classic upload temporary files with private permissions from the moment they are created;
- resolve realtime streams and file download links through the active API base URL after network-address changes;
- validate dynamically registered desktop application IDs directly in the settings request schema while retaining strict safe-ID syntax;
- provide Polish and English Network Management controls and transaction messages;
- add regression coverage for API origin handling, CSRF/raw responses, uploads, dynamic application pins, and Network Management localization.
