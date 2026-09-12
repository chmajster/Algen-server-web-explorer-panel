# Runtime audit 5

## Fixed

- Activity Feed now tolerates unknown persisted `category` and `status` values instead of failing the whole activity listing when SQLite contains a stale or corrupted enum value.
- Package Center now safely decodes `plan_json`, `warnings_json`, `result_json`, and source `metadata_json`; malformed JSON and valid JSON with the wrong root type fall back to the expected object/list shape.
- Package Center no longer calls `.get()` on a non-object persisted plan.
- Ansible Controller now enforces the expected list/object shape for every persisted JSON column and safely decodes enrollment-token tags.
- OS Repositories now isolates malformed or wrong-shaped persisted JSON in repository, source, filter, sync-job, package, build, audit, and settings rows instead of propagating `JSONDecodeError` or an incompatible container type.

## Regression coverage

- Added Activity Feed coverage for corrupted persisted enum values.
- Added Package Center coverage for malformed and wrong-shaped job/source JSON.
- Added typed-shape regression coverage for Ansible Controller and OS Repositories persisted JSON decoders.
