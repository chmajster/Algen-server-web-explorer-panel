# Runtime audit 4

## Fixed

- Hardened Docker package rollback state parsing. Invalid or wrong-shaped persisted rollback state now fails closed instead of constructing unsafe package-manager arguments.
- Fixed Docker package rollback after partial upgrades so packages introduced by a failed installation are removed even when other Docker packages existed before the operation.
- Hardened persisted job restoration: unknown/corrupt job statuses degrade to `failed`, unknown priorities to `normal`, and dependency status reads no longer crash the scheduler.
- Hardened App Store manifest loading. Invalid YAML, unreadable files, and non-object manifests no longer crash the complete application catalog; malformed entries are skipped while direct lookup returns a controlled HTTP error.
- Added a shared safe Web Storage boundary for local/session storage reads, writes, removals, and key enumeration. Browser `SecurityError`/`QuotaExceededError` conditions no longer crash application bootstrap or UI modules.
- Migrated bootstrap language/theme/update-reload persistence, Desktop window/session state, recent apps and legacy pins, File Manager preferences, Directory Tree state, Transfer Center filters, log search history, Package Center view mode, Docker draft/section state, network transaction state, and API error-language lookup to the safe storage boundary.
- Fixed Settings search memoization so translated category labels cannot become stale when the translation callback changes.

## Regression coverage

- Added Docker rollback tests for malformed state and partial-install rollback behavior.
- Added job repository tests for corrupt persisted status/priority values.
- Added App Store tests for invalid and wrong-shaped manifests.
- Added persistence tests for blocked browser storage reads and failed writes/removals.
- Added a frontend source regression gate that forbids direct Web Storage access outside `core/persistence.ts`.
