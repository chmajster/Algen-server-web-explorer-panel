# Runtime audit 7

## Fixed

- Webhook Manager now validates HTTP field names against the HTTP token grammar, rejects control characters in field values, rejects case-insensitive duplicate custom headers, and blocks transport/generated WebNAS headers from being overridden.
- Webhook authentication header names now reject hop-by-hop and WebNAS-managed header names instead of allowing ambiguous outbound requests.
- Persisted Webhook Manager configuration is revalidated when read from SQLite. Malformed legacy/corrupted rows are exposed as disabled safe metadata instead of being delivered with unsafe methods, headers, timeouts, or authentication settings.
- Corrupted persisted Webhook Manager timestamps no longer crash webhook listing or lookup; invalid and non-finite timestamp values (`nan`, `inf`, `-inf`) degrade to a safe numeric fallback.
- Webhook Manager dashboard counts only configurations that remain enabled after persisted-row validation, so malformed rows are no longer reported as active webhooks.
- Webhook delivery revalidates outbound custom/authentication headers and the method/timeout immediately before network I/O.
- Webhook Manager shutdown no longer leaves a stop sentinel that can make the next worker exit immediately after `startup()`.
- Webhook Manager no longer drops the worker reference after a timed-out shutdown join, preventing a subsequent `startup()` from creating a second worker while the original delivery thread is still alive.
- OS Repositories authenticated mirror proxy now pins each outbound connection to an IP address returned by the SSRF validation step. HTTP Host routing and HTTPS SNI/certificate verification still use the original hostname, closing the DNS-rebinding/TOCTOU gap.
- OS Repositories authenticated HTTPS mirror connections now require TLS 1.2 or newer.
- OS Repositories proxy hop-by-hop response filtering now recognizes both the standard `Trailer` field and legacy `Trailers` spelling.
- Shared module API providers now connect directly to the private/loopback IP addresses returned by URL validation instead of resolving the hostname again during transport, closing a DNS-rebinding/TOCTOU gap.
- Shared module API providers preserve configured reverse-proxy base-path prefixes when issuing module API requests.
- Shared module API providers bound non-2xx response reads to the same 2 MiB safety limit used for successful responses.
- Shared module API providers no longer follow redirects outside the validated module API origin; non-2xx responses are returned as stable module API failures.
- Docker Registry browsing now uses a pinned transport installed on `DockerProvider`: registry DNS is resolved and policy-checked once, then TCP connects to that exact numeric address while HTTP Host and HTTPS SNI/certificate validation retain the configured registry hostname.
- Docker Registry transport compares effective default ports after URL normalization, so explicit `:443`/`:80` configurations remain valid when HTTPX elides the default port.
- Docker Registry transport honors the configured HTTPX connect timeout for every validated address instead of using a hard-coded per-address timeout.
- Docker Registry requests advertise `Accept-Encoding: identity` and reject unexpected compressed responses before HTTPX can decode them, preventing compressed response expansion from bypassing the response-size limit.
- Docker Registry connection failures are classified from the final attempt, so an earlier timeout no longer masks a later refusal/TLS failure as a 504 timeout.
- Docker Registry authentication and custom CA handling continue to work through the pinned transport without following redirects, closing the loopback/link-local DNS-rebinding gap that existed between `_assert_safe_registry_url()` and HTTPX connection establishment.
- LDAP Authentication now connects only to the exact addresses returned by its safety-checked DNS lookup while retaining the configured hostname for LDAPS/StartTLS certificate verification, closing the DNS-rebinding/TOCTOU gap between validation and `ldap3` connection establishment.
- LDAP Manager uses the same pinned-address policy for administrative directory operations, so its post-validation transport cannot silently resolve the hostname to a different target.
- LDAP Authentication and LDAP Manager now disable automatic LDAP referrals and referral credential forwarding. A directory response can no longer redirect an authenticated connection to an arbitrary referral host with the configured bind/user credentials.
- Persisted update-request state now normalizes timestamps, progress, log offsets, step timestamps, and acknowledgement lists before use. Syntactically valid but type-corrupted `update_request.json` data can no longer crash update progress recovery or scheduler paths through unchecked `float()`/`int()` conversions.
- Update-request writes pass through the same normalization boundary as reads, preventing malformed in-memory state from being persisted back into the durable update coordinator.
- Persisted automatic-update policy now accepts only typed, bounded values for booleans, interval, timestamps, PID and error text. Malformed but syntactically valid `auto_update.json` values no longer escape into scheduler `float()`/`int()` conversions or poison later state writes.
- Persisted update-process state now normalizes `running`, exit code, timestamps and PID before recovery. Invalid values in `update_progress.json` degrade to safe defaults rather than crashing the update status endpoint.
- Persisted update-process unit names are validated before being passed to `systemctl`; malformed option-like values such as `--root=...` are discarded instead of being interpreted as systemctl arguments.
- AWX authenticated API requests now disable HTTP redirects, preventing a 30x response from forwarding the configured bearer token to another origin.
- Proxmox Manager installs a hardened API client that disables redirects for login, API-token and ticket/cookie authenticated requests, preventing Proxmox credentials from being forwarded to a redirect target.
- Alert Manager webhook and ntfy delivery now disables HTTP redirects, preventing configured bearer tokens from being forwarded to a redirect target.
- Hosts Manager Agent now refuses redirects for enrollment, heartbeat, report and self-update HTTP requests. Enrollment/agent bearer tokens can no longer be forwarded to a redirect target, while the standalone one-file standard-library deployment and existing instrumentation hook remain intact.
- Persisted App Store state now normalizes the shared `installed`, `history`, and mutable `changes` fields. Type-corrupted JSON can no longer make Samba/App Store mutation paths fail on list operations while unrelated app-specific state is preserved.
- HTTPS transport configuration now treats type-corrupted `deployment.json.active_port` values as an unavailable standard gateway instead of allowing `TypeError`/`OverflowError` to escape from the settings endpoint.

## Regression coverage

- Added validation tests for malformed header names, managed/hop-by-hop headers, case-insensitive duplicates, control characters, and unsafe authentication header names.
- Added a persisted-corruption regression proving an invalid Webhook Manager row is disabled before delivery, non-finite timestamps degrade safely, and invalid rows are excluded from the dashboard enabled count.
- Added worker lifecycle coverage proving shutdown does not enqueue a stale stop sentinel, a subsequent startup creates a live worker, and a timed-out join does not permit a second worker.
- Added mirror transport coverage proving the original hostname is retained for HTTP semantics while the TCP connection uses the already-validated numeric address and HTTPS uses TLS 1.2 or newer.
- Added shared module API transport coverage proving a request uses the exact private address returned by validation, preserves a configured base-path prefix, and bounds error-response reads.
- Added Docker Registry transport coverage for effective default ports, validated-address pinning, configured connect timeouts, identity content encoding, compressed-response rejection, and final connection-failure classification.
- Added LDAP Authentication and LDAP Manager regressions proving their `ldap3` candidate address lists contain the policy-checked numeric address, the original hostname remains available for TLS semantics, and automatic referrals are disabled.
- Added corrupted update-request coverage proving invalid numeric/timestamp fields and acknowledgement-list types degrade to safe defaults instead of escaping into update recovery logic.
- Added automatic-update policy coverage proving wrong JSON types and unknown fields fall back to defaults, and update-progress coverage proving malformed numeric fields and option-like systemd unit names are rejected.
- Added authenticated redirect regressions for AWX, Proxmox Manager, Alert Manager and Hosts Manager Agent, including verification that the hardened Proxmox client is installed into the service module.
- Added App Store corruption coverage for wrong shared-state types and transport-gateway coverage proving malformed deployment port values return a controlled 409 response instead of crashing.

## Verification

CI is authoritative for the current pull-request head. Automated tests, CodeQL, Dependency Review, LDAP integration, Real stack E2E and Installation smoke test must all be green before merge.
