# Login History

## Overview

Login History exposes authentication activity without duplicating the complete system journal into a WebNAS database. It reads bounded Linux sources on demand and applies backend-side filtering/pagination.

## Sources

The primary source is systemd journal data for `sshd`, `sudo`, `login` and `systemd-logind`. The parser recognizes successful/failed SSH authentication, PAM session open/close and sudo activity. If relevant journal entries are unavailable, `last`/`lastb` are used as a compatibility fallback. Active sessions use `loginctl` and fall back to `who`.

The module therefore works across common Debian/Ubuntu/Raspberry Pi OS and Fedora/RHEL systemd deployments without requiring every legacy utility to be installed.

## Security correlation

The backend detects repeated failures from one address, password spraying across multiple accounts and targeted account attacks. Findings are emitted to the existing Alert Manager instead of creating a parallel alert store. The overview reports successful/failed logins in the current window, unique source IPs, active sessions and the most attacked account.

## API

```text
GET  /api/modules/login-history/overview
GET  /api/modules/login-history/events
GET  /api/modules/login-history/sessions
GET  /api/modules/login-history/findings
POST /api/modules/login-history/sessions/terminate
```

Event filters include username, source IP, result, session type, free-text query and journal time window. Response rows are capped and paginated.

## Session termination

Session termination requires `login_history.sessions.terminate`, CSRF and explicit confirmation. In broker-required deployments the backend sends only an allowlisted `loginctl terminate-session <validated-id>` request to the privileged broker.

## RBAC

- `login_history.view`
- `login_history.sessions.terminate`

Session termination is audited in Activity Center.

## Limitations

Exact legacy `wtmp`/`btmp` duration/timestamp fidelity varies by implementation and locale; journal timestamps are authoritative when available. Systems without systemd-journald or without readable authentication records degrade to available legacy sources rather than failing the entire module.
