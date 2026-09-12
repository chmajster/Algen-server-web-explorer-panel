# Runtime audit 4

## Fixed

- Hardened Docker package rollback state parsing and rejected malformed/wrong-shaped rollback state before package-manager commands are built.
- Fixed partial Docker installation rollback so packages introduced by a failed operation are removed even when some Docker packages were already installed.
- Hardened persisted job restoration: corrupt/unknown statuses now degrade to `failed`, unknown priorities to `normal`, and dependency-state reads no longer crash scheduling.
- Hardened App Store manifests: unreadable, invalid YAML, and non-object manifests cannot crash the catalog; direct lookup returns a controlled error and catalog enumeration skips broken entries.
- Added safe browser storage helpers for local/session reads, writes, removals, and key enumeration. `SecurityError` and `QuotaExceededError` no longer crash application startup or persisted UI state.
- Migrated bootstrap language/theme/update reload state, Desktop windows/recent apps/legacy pins, File Manager preferences, Directory Tree state, Transfer Center filters, log history, Package Center view, Docker drafts/sections, network transactions, and API error-language lookup to the safe storage boundary.
- Fixed Settings search memoization so translated category labels refresh with the translation callback instead of using a stale closure.

## Regression coverage

- Added Docker rollback tests for malformed state and partial rollback.
- Added job repository tests for corrupt persisted status/priority values.
- Added App Store tests for invalid and wrong-shaped manifests.
- Added persistence tests for blocked Web Storage reads and failed writes/removals.
- Added a frontend source regression test forbidding direct Web Storage access outside `core/persistence.ts`.
