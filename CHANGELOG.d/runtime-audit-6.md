# Runtime audit 6

## Fixed

- Login History no longer returns raw `journalctl`, privileged-broker, or `loginctl` failure text through API error messages.
- Fail2Ban Manager no longer includes captured command output in `FAIL2BAN_COMMAND_FAILED` API responses; the safe command name and stable failure message remain available.
- GitOps Config Manager no longer exposes Git `stdout`/`stderr`, repository paths, or remote diagnostics through conflict and operation failure responses.
- Network Tools now converts non-allowlisted command failures to a stable public error and replaces raw `dig` diagnostic text returned by DNS lookups with a generic failure message while preserving explicit rate-limit/concurrency responses.
- OS Repositories RPM publication no longer embeds `createrepo_c` stderr in raised operation errors.
- Detached Linux update sessions no longer persist arbitrary exception text from package-manager/broker failures in `status.json`; failed sessions now store a stable public error string.

## Regression coverage

- Added API-boundary tests that inject sentinel diagnostic strings into Login History, Fail2Ban, GitOps, and Network Tools and verify they cannot escape in HTTP error payloads.
- Added DNS response coverage proving raw tool diagnostics are replaced before returning to the client.
- Added RPM repository publication coverage proving `createrepo_c` stderr is not included in the raised error.
- Added detached Linux update coverage proving exception details are absent from the persisted session state.
