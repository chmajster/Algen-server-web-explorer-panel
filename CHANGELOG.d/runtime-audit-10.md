# Runtime audit 10

## Fixed

- Restored full `arg-type` and `call-overload` checking in `app.settings` by removing the module-wide mypy override. Persisted numeric values are narrowed at the existing conversion boundary instead of suppressing unrelated diagnostics.
- Completed Docker Registry connect/read timeout regression coverage for HTTP and HTTPS, including the original TLS hostname, the connect-time handshake and the post-connect read timeout. Updated the earlier socket test double to implement and verify `settimeout()` rather than bypass the production behavior.
- Docker Registry and Proxmox reject an HTTP body that ends before its declared `Content-Length`, even when the received prefix is valid JSON. Sized `HTTPResponse.read()` calls can otherwise silently accept that truncated prefix. Error paths close response streams and retain the existing controlled API error contracts.
- Docker Registry preserves non-2xx status codes and `WWW-Authenticate` challenges when the optional JSON error body is a scalar, list or null. Successful responses still require a JSON object.
- The shared Registry/Proxmox JSON decoder rejects `NaN`, `Infinity`, `-Infinity` and exponent overflow before these values reach application state or strict JSON serialization. Finite numbers, strings and the existing nesting limit remain supported.
- LDAP Manager rejects an impossible bind-password clear operation before modifying the independent secrets store. A rejected settings update no longer deletes the working bind credential and leaves a dangling secret reference.
- LDAP Manager normalizes an unknown persisted security mode to StartTLS instead of allowing the connection code to silently fall through to a plaintext bind. Valid configured LDAP, StartTLS and LDAPS modes remain unchanged.

## Regression coverage

- Added `backend/tests/test_runtime_audit_10.py` with 59 cases covering actual standard-library HTTP parsing over controlled socket doubles, HTTP/HTTPS timeout separation, truncated responses, authentication challenge preservation, non-finite JSON, LDAP credential preservation, corrupted transport mode and the mypy configuration guard.
- Retained and repaired the existing validated-address pinning regression in `backend/tests/test_runtime_audit_7.py`.
- A targeted local run of audits 7-10, JSON limits, LDAP Manager and the Proxmox manager/operations/advanced suites passed 242 tests on Python 3.13.5. The local environment is not the pinned production environment; complete Python 3.14 repository CI on the final PR head remains authoritative.

## Integration

- Synchronized the audit branch with `main` at `74f7486247a21d899bdb32cee6a68e512467276a`, preserving the selected-version update recovery and NTP workspace changes alongside the prior runtime audits.
- This entry records confirmed fixes and test scope, not a guarantee that every possible defect has been eliminated.
