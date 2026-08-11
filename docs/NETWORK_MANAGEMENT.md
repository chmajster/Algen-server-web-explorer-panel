# Linux network management

WebNAS extends the existing read-only network diagnostics in **Settings → Network** with typed configuration workflows. The UI is divided into General, Interfaces, Traffic Control, Static Routes, and Connectivity. Existing interface counters, DNS diagnostics, and kernel routing views remain available under Connectivity.

## Provider architecture

`backend/app/network_management.py` detects one active provider and exposes its capabilities:

- **NetworkManager** — writable through fixed `nmcli` argument arrays. WebNAS profiles use the `webnas-` prefix.
- **systemd-networkd** — writable through files named `79-webnas-*` and `80-webnas-*` in `/etc/systemd/network`, followed by `networkctl reload/reconfigure`.
- **Netplan** — writable through `90-webnas-*.yaml` in `/etc/netplan`, followed by `netplan generate` and `netplan apply`.
- **ifupdown** — detected but deliberately read-only. WebNAS never rewrites `/etc/network/interfaces`.

If more than one writable manager appears active, mutation is blocked. WebNAS does not install, enable, disable, or migrate between network managers. Files without a WebNAS prefix and traffic-control handles outside the WebNAS `7000:`–`7fff:` range are not deleted. An existing foreign root `qdisc` blocks traffic-control changes.

Managed domain state, plans, snapshots, and transactions are stored with private permissions below `<data_dir>/network-management`. Static routes and WebNAS traffic rules are restored after boot by `webnas-network-managed.service`. The unit invokes the same typed server-side renderer; it does not contain client-supplied commands.

## API

All routes are under `/api/admin/network`:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/management` | Provider capabilities, live interfaces/DNS/routes, managed objects and pending transaction |
| POST | `/plans` | Validate one typed change and produce before/after, warnings, risk and redacted commands |
| POST | `/apply` | Apply a current user-bound plan |
| POST | `/confirm` | Keep a pending configuration |
| POST | `/rollback` | Restore a pending snapshot immediately |
| GET | `/transactions/active` | Recover the active transaction after a service or page restart |
| GET | `/transactions/{id}/status` | Read the authoritative deadline and rollback status during reconnect |
| POST | `/transactions/{id}/confirm` | Confirm through a server address approved by the plan |
| POST | `/transactions/{id}/rollback` | Request rollback through a server address approved by the plan |
| GET | `/policy` | Read the network confirmation policy and its limits |
| PUT | `/policy` | Confirm and persist a new timeout for future transactions |
| POST | `/policy/reset` | Confirm and restore the 15-second default |
| GET | `/overview` | Existing interface diagnostics |
| GET | `/dns` | Effective resolver state |
| POST | `/dns/test` | Bounded direct DNS resolution test |
| GET | `/routing` | Kernel routes and policy rules |
| POST | `/connectivity/test` | Validated ping, tracepath/traceroute or TCP test |

Mutation payloads contain only strict Pydantic domain models. Extra fields, raw commands, executable names, file paths and raw provider configuration are rejected. Commands use `shell=False`, fixed server-side argument arrays and timeouts.

## Safety transaction

Every mutation follows **plan → apply → confirm**:

1. The plan is bound to the authenticated user for ten minutes.
2. WebNAS detects the interface used to reach the browser and default-route interfaces. A matching target is marked high-risk and requires the exact phrase shown by the server.
3. Before apply, WebNAS stores live interface/routing/DNS diagnostics, managed state, affected WebNAS files and active NetworkManager connection UUIDs.
4. WebNAS persists the transaction and arms an independent transient systemd service and timer before changing any managed file or live network state.
5. Apply reads the central `network.change_confirmation_timeout_seconds` policy and stores that value with `created_at` and `deadline_at` in the transaction. The timer uses the stored value; failure to arm it blocks the change.
6. The browser stores only the transaction identifier, deadline and server addresses in `sessionStorage`, keeps counting while offline, and probes the current, predicted, previous and other server-approved addresses with one bounded reconnect loop.
7. Confirm is accepted only before the persisted server deadline. A durable confirmed state is written before the timer is stopped, so a late timer process cannot undo a confirmed change. Manual rollback restores immediately, and a partial command failure also rolls back immediately.
8. After the local countdown expires, the browser continues reconnecting until the backend reports `confirmed`, `rolled_back`, or `failed`; reconnect never starts a fresh confirmation window.
9. Only one pending network transaction is allowed.

The timer does not depend on FastAPI or the browser remaining alive. Snapshots may contain addresses and topology but never cookies, session headers, CSRF tokens or credentials.

The timeout policy accepts strict integers from 5 through 300 seconds and defaults to 15. It is stored privately below `<data_dir>/network-management/policy.json`. Changing it affects only transactions created afterwards; an active transaction retains its original deadline and systemd timer.

## Permissions and audit

The permission family is:

`network.view`, `network.manage_interfaces`, `network.manage_bonds`, `network.manage_vlans`, `network.manage_bridges`, `network.manage_dns`, `network.manage_routes`, `network.manage_traffic`, `network.manage_connections`, `network.confirm`, `network.rollback`, `network.policy.view`, and `network.policy.edit`.

Administrators receive all registered permissions. Operators and auditors receive read access only by default; ordinary users receive no new access. Normal mutations require a session, CSRF validation and the operation-specific permission. During the active confirmation window, the random 128-bit transaction identifier acts as a short-lived capability only for status, confirmation and rollback through addresses approved in the server-generated plan; it is invalid for confirmation after the deadline. Policy changes audit the old and new values, actor, source and result. Plans and transactions audit the timeout selected for them.

## Recovery from the local console

If remote access is lost, sign in locally as root:

1. Inspect `systemctl status 'webnas-network-rollback-*'` and wait for the rollback timer, or run the WebNAS Python 3.14 environment: `/opt/webnas/backend/.venv/bin/python -m app.network_management --rollback <transaction-id>`.
2. Inspect `<data_dir>/network-management/transactions/<id>/snapshot.json`.
3. Reload the active provider: `nmcli connection reload`, `networkctl reload`, or `netplan apply`.
4. Inspect only WebNAS-owned files before removing anything. Do not replace administrator-owned configuration with the JSON diagnostic snapshot.

For an intentionally confirmed bad configuration, restore the host using its native manager and then reconcile or remove the corresponding object through WebNAS. Keep manual administrator configuration in non-WebNAS files/profiles. If a provider is ambiguous, resolve that ambiguity in the provider itself; WebNAS will remain read-only until detection is safe.

## Current boundaries

- ifupdown remains read-only.
- Ingress shaping is offered only when the IFB kernel module is already available.
- WebNAS refuses to replace a foreign root traffic-control configuration.
- NetworkManager profile restoration is limited to WebNAS profile files plus reactivation of previously active connection UUIDs; arbitrary third-party profile contents are not rewritten.
