## Unreleased — File Manager worker runtime fixes

### Fixed

- Preserve numeric zero in worker and legacy file-list sorting. Empty files are
  sorted by size correctly, and an epoch `mtime` is not replaced by a fallback
  timestamp.
- Fall back to numeric UID/GID strings when NSS cannot resolve a file's owner or
  group. Such files no longer abort metadata retrieval, listing, or search.
- Bound preview I/O itself to at most 1 MiB instead of reading the complete file
  and slicing the result afterwards. Clamp negative preview lengths to zero.
- Reject known non-regular files before opening them for previews or text editing.
  Use non-blocking, no-follow opens and recheck the opened descriptor so FIFOs do
  not leave workers waiting for another process.
- Retry short unbuffered text writes before truncating the file. A write which
  makes no progress now fails instead of reporting success with truncated data.
  This does not make text saves transactional or provide rollback after I/O errors.
- Attempt to remove partial download exports when the worker or response
  construction fails, while preserving the original exception if cleanup fails.
  Successful responses retain their existing background cleanup.
- Translate timeouts of the directly launched file worker into an HTTP 504 with
  the stable `file_worker_timeout` code, without exposing captured worker output.

### Regression coverage

- `backend/tests/test_file_worker_boundaries.py`
- `backend/tests/test_file_ops_boundaries.py`
- Existing `backend/tests/test_worker_file_listing.py` remains unchanged.
