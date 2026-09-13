# Runtime audit 7

## Fixed

- Webhook Manager now validates HTTP field names against the HTTP token grammar, rejects control characters in field values, rejects case-insensitive duplicate custom headers, and blocks transport/generated WebNAS headers from being overridden.
- Webhook authentication header names now reject hop-by-hop and WebNAS-managed header names instead of allowing ambiguous outbound requests.
- Persisted Webhook Manager configuration is revalidated when read from SQLite. Malformed legacy/corrupted rows are exposed as disabled safe metadata instead of being delivered with unsafe methods, headers, timeouts, or authentication settings.
- Corrupted persisted Webhook Manager timestamps no longer crash webhook listing or lookup; invalid timestamp values degrade to a safe numeric fallback.
- Webhook delivery revalidates outbound custom/authentication headers and the method/timeout immediately before network I/O.
- Webhook Manager shutdown no longer leaves a stop sentinel that can make the next worker exit immediately after `startup()`.
- Webhook Manager no longer drops the worker reference after a timed-out shutdown join, preventing a subsequent `startup()` from creating a second worker while the original delivery thread is still alive.
- OS Repositories authenticated mirror proxy now pins each outbound connection to an IP address returned by the SSRF validation step. HTTP Host routing and HTTPS SNI/certificate verification still use the original hostname, closing the DNS-rebinding/TOCTOU gap.
- OS Repositories proxy hop-by-hop response filtering now recognizes both the standard `Trailer` field and legacy `Trailers` spelling.
- Shared module API providers now connect directly to the private/loopback IP addresses returned by URL validation instead of resolving the hostname again during transport, closing a DNS-rebinding/TOCTOU gap.
- Shared module API providers no longer follow redirects outside the validated module API origin; non-2xx responses are returned as stable module API failures.

## Regression coverage

- Added validation tests for malformed header names, managed/hop-by-hop headers, case-insensitive duplicates, control characters, and unsafe authentication header names.
- Added a persisted-corruption regression proving an invalid Webhook Manager row is disabled before delivery, including malformed timestamp values.
- Added worker lifecycle coverage proving shutdown does not enqueue a stale stop sentinel, a subsequent startup creates a live worker, and a timed-out join does not permit a second worker.
- Added mirror transport coverage proving the original hostname is retained for HTTP semantics while the TCP connection uses the already-validated numeric address.
- Added shared module API transport coverage proving a request uses the exact private address returned by the validation lookup.
