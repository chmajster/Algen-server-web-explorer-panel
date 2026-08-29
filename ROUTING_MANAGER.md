# Routing Manager

## Overview

Routing Manager provides IPv4/IPv6 route, policy-rule and routing-table visibility plus controlled route mutations. Runtime state is read using JSON output from `iproute2`, avoiding locale-dependent text parsing where possible.

## Capabilities

The module lists routes from all IPv4/IPv6 tables, policy rules and named tables from `/etc/iproute2/rt_tables`. It supports route replace/delete, policy rule add/delete, metrics, gateways, interfaces, source addresses and custom tables. Diagnostics provide `ip route get`, one-shot ping and bounded traceroute when the tools are installed.

Backend detection reports NetworkManager, systemd-networkd, netplan or runtime iproute2. Runtime route management works through iproute2. Persistent route mutation is currently implemented transactionally for NetworkManager; other detected backends are reported as runtime-only instead of modifying unknown configuration formats.

## Safe transaction lifecycle

Every route mutation follows:

```text
Preview -> Snapshot -> Apply -> Verify -> Pending confirmation -> Confirm
                                              |
                                              +-> timed rollback
```

Preview exposes the current route, proposed route and warnings, including default-route risk, overlapping routes and unreachable gateway/interface combinations. Apply captures an inverse runtime command. NetworkManager persistent changes also capture the complete current route property for the relevant connection/family.

After apply, WebNAS verifies route lookup. A successful change is persisted as a private transaction under `paths.data_dir/routing-transactions` with a confirmation deadline. If the browser does not confirm before the deadline, runtime routing and the NetworkManager route snapshot are restored. Pending transactions are reconciled after a WebNAS restart, so restarting the backend cannot disable the safety timer permanently.

## Privilege boundary

When the privileged broker is required, only validated `ip -4/-6 route replace/delete`, `ip -4/-6 rule add/delete` and structured NetworkManager route mutations are accepted. Arbitrary executables, shell fragments, batch files and option injection are rejected. `shell=True` is never used.

## API

```text
GET  /api/modules/routing-manager/overview
GET  /api/modules/routing-manager/routes
GET  /api/modules/routing-manager/rules
GET  /api/modules/routing-manager/tables
POST /api/modules/routing-manager/routes/preview/{replace|delete}
POST /api/modules/routing-manager/routes/{replace|delete}
POST /api/modules/routing-manager/rules/{add|delete}
POST /api/modules/routing-manager/diagnostics
GET  /api/modules/routing-manager/transactions/{id}
POST /api/modules/routing-manager/transactions/{id}/confirm
POST /api/modules/routing-manager/transactions/{id}/rollback
```

Route apply runs through Job Queue Manager.

## RBAC

- `routing.view`
- `routing.manage`
- `routing.commit`

`routing.commit` is critical-risk and backend-enforced. Mutations require CSRF and explicit confirmation and are written to Activity Center.

## Troubleshooting and limitations

Persistent configuration for systemd-networkd/netplan is intentionally not generated until it can use the same snapshot/verify/rollback guarantees as NetworkManager. Such hosts can still inspect and change runtime routes. Missing `ping` or `traceroute` is reported as an unavailable diagnostic capability rather than an HTTP 500.
