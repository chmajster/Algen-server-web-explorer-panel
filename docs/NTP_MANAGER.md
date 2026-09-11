# NTP Manager

NTP Manager is the WebNAS-native module for Linux time synchronization. It supports NTP client, NTP server and combined client+server operation while reusing the existing WebNAS module registry, RBAC, Activity Center audit log, Job Queue and privileged broker.

## Supported modes

- **Disabled** — WebNAS does not configure active upstream or server access in its managed configuration.
- **Client** — the host synchronizes from configured external NTP sources.
- **Server** — the host serves time to explicitly allowed local networks. Server mode requires `chrony`.
- **Client + Server** — the recommended LAN-server mode. WebNAS synchronizes from upstream sources and serves that time to explicitly allowed local clients.

Server mode never generates `allow all`. At least one explicitly enabled IPv4 or IPv6 CIDR is required.

## Supported backends and distributions

The module detects the installed backend and the correct systemd unit instead of assuming a single service name:

- `chrony` / `chronyd` — preferred and required for NTP server mode;
- `systemd-timesyncd` — client mode only;
- `ntpd` — supported for legacy client status/source management.

The implementation supports the distribution families used by WebNAS, including Debian, Ubuntu, RHEL, Rocky Linux, AlmaLinux, Fedora and SUSE/openSUSE. Chrony installation selects `apt-get`, `dnf`, `yum` or `zypper` through the existing typed privileged package operation.

Common service/configuration paths include:

- Debian/Ubuntu: `chrony.service`, `/etc/chrony/chrony.conf`;
- RHEL/Rocky/Alma/Fedora: `chronyd.service`, `/etc/chrony.conf`;
- other distributions are detected from available binaries, units and configuration files.

## Configuration ownership and safety

NTP Manager does not blindly overwrite an existing system configuration. For chrony it prefers a WebNAS-owned drop-in when the base configuration declares a supported `confdir`:

```text
/etc/chrony/conf.d/webnas.conf
/etc/chrony.d/webnas.conf
```

If a compatible drop-in is not available, WebNAS manages only a bounded block in the existing file:

```text
# BEGIN WEBNAS NTP
...
# END WEBNAS NTP
```

Unmanaged NTP directives outside the WebNAS block are preserved. The UI reports **Wykryto istniejącą konfigurację NTP** when it sees upstream configuration that WebNAS does not own.

Every configuration activation follows this transaction:

1. validate the typed request;
2. generate the candidate configuration;
3. reject unsafe constructs such as `allow all`;
4. use native `chronyd -p -f` validation when the binary is available;
5. create a private backup with actor/change metadata;
6. atomically write the candidate through the privileged broker in production;
7. restart the detected NTP service;
8. roll back the previous configuration and restart again if activation fails.

Backups are stored below WebNAS `paths.data_dir/ntp-backups` and can be restored from the NTP Manager UI/API.

## Upstream NTP sources

The Sources tab supports:

- hostname, IPv4 and IPv6 sources;
- `server` and `pool` chrony directives;
- enable/disable state;
- preferred sources (`prefer`);
- add, edit and delete operations;
- live source quality and selection state.

Example managed chrony lines:

```text
server time.cloudflare.com iburst prefer
pool pool.ntp.org iburst
```

Source input is parsed and validated as structured data. User input is never concatenated into a shell command.

## NTP server and allowed networks

NTP server mode is available with chrony. Configure clients as explicit IPv4/IPv6 CIDRs:

```text
allow 192.168.10.0/24
allow 192.168.20.0/24
allow 2001:db8::/64
```

Each network can be enabled/disabled and carries a description in WebNAS configuration state. `allow all` is intentionally prohibited.

### Local stratum

The advanced option **Udostępniaj lokalny czas, gdy upstream NTP jest niedostępny** generates, for example:

```text
local stratum 10
```

Use this only when intentionally designing a LAN time hierarchy. A server using local stratum can continue serving time even when it is no longer synchronized to a trustworthy upstream source.

## Firewall

NTP uses **UDP/123**. NTP Manager detects:

- `firewalld`;
- `ufw`;
- `nftables`.

The dashboard/server tab reports the port as `open`, `blocked` or `unknown`. WebNAS does not open UDP/123 automatically. The administrator must explicitly invoke **Otwórz UDP/123** and have `ntp.firewall.manage`.

For `firewalld`, WebNAS creates the explicit UDP/123 rule and reloads the firewall. For `ufw`, the WebNAS-created rule is labelled `WebNAS NTP`. An unknown nftables ruleset is treated as unmanaged and is not modified automatically; the operation returns a manual-action status instead of guessing the correct table/chain. Existing firewall rules that WebNAS did not create are never removed when NTP server mode is disabled.

## Synchronization status

For chrony the diagnostics layer parses `chronyc tracking` and exposes structured fields such as:

- Reference ID;
- Stratum;
- Reference time;
- System time;
- Last offset;
- RMS offset;
- Frequency / residual frequency;
- Root delay / root dispersion;
- Leap status.

The normal UI presents parsed data. Raw/native details remain secondary diagnostics rather than the primary interface.

## Source states

`chronyc sources -v` is normalized to user-facing states:

| Chrony | WebNAS state | Meaning |
| --- | --- | --- |
| `^*` | Synchronizacja | currently selected source |
| `^+` | Dostępny | valid candidate |
| `^-` | Nieużywany | valid but not selected |
| `^?` | Niedostępny | communication unavailable |
| `^x` | Błędny | falseticker / invalid source |
| `^~` | Niestabilny | excessive variability |

The source table also exposes stratum, poll, reach, last receive time, offset and available jitter/uncertainty telemetry.

## NTP clients

When chrony is acting as a server, the Clients tab reads `chronyc clients` and exposes:

- client address;
- reverse-DNS hostname when available;
- NTP request count;
- dropped request count when present;
- last activity data.

Reverse-DNS failure is non-fatal and leaves the hostname blank.

## Test NTP server

The test action performs a real UDP NTP query to port 123 using Python sockets. It does not invoke a shell. The result includes:

- reachability/status;
- resolved response address;
- stratum;
- calculated offset in milliseconds;
- request/response delay in milliseconds.

Hostnames and IPv4/IPv6 addresses are validated before resolution.

## Force synchronization

**Synchronizuj teraz** is protected by `ntp.sync` and requires an explicit UI confirmation because a step change can affect applications, logs, databases, Kerberos and other time-dependent services.

- chrony: `chronyc makestep` through the typed `Operation.NTP` broker policy;
- timesyncd/ntpd: controlled service restart.

The operation runs as a Job Queue task and the resulting state is re-read after execution.

## Service control

Start, stop and restart are exposed through `ntp.service.control`. NTP Manager detects the actual unit, including `chrony` versus `chronyd`, and the privileged broker accepts only a fixed allowlist of NTP units/actions.

## Time zone and timedatectl

The Timezone tab reads the installed list from:

```text
timedatectl list-timezones
```

Search is available in the UI. A timezone change is accepted only if the requested value exists in that list. Production mutation is performed by the typed NTP broker operation using:

```text
timedatectl set-timezone <validated-zone>
```

Status includes timezone, system synchronization state, NTP service state and RTC/local-time metadata available from `timedatectl`.

## Diagnostics

The Diagnostics tab checks at least:

- supported backend detection;
- service state;
- synchronization state and selected source;
- UDP/123 firewall status when server mode is active;
- conflicting active NTP services (`chronyd` + `systemd-timesyncd`, `chronyd` + `ntpd`, etc.);
- generated/current configuration validity.

Backend-specific telemetry comes from `chronyc`, `timedatectl` and `ntpq` as appropriate. Failures are surfaced as diagnostic warnings/checks rather than raw shell output.

## History and dashboard widget

NTP Manager stores a lightweight history sample containing:

- timestamp;
- active source;
- stratum;
- offset;
- synchronized true/false.

Samples are throttled to at most one record per five minutes; there is no per-second polling history.

Users with `ntp.view` also receive an NTP widget on the main WebNAS dashboard showing synchronization, source, stratum, offset, role and current chrony client count. The widget uses the same `/dashboard` endpoint and does not expand privilege.

## API

The module follows the existing WebNAS module API convention rather than introducing a parallel `/api/system/...` routing style:

```text
GET    /api/modules/ntp-manager/dashboard
GET    /api/modules/ntp-manager/status
GET    /api/modules/ntp-manager/config
PUT    /api/modules/ntp-manager/config
POST   /api/modules/ntp-manager/config/validate

GET    /api/modules/ntp-manager/sources
POST   /api/modules/ntp-manager/sources
PUT    /api/modules/ntp-manager/sources/{server}
DELETE /api/modules/ntp-manager/sources/{server}
POST   /api/modules/ntp-manager/test

GET    /api/modules/ntp-manager/clients
POST   /api/modules/ntp-manager/sync
POST   /api/modules/ntp-manager/service

GET    /api/modules/ntp-manager/timezones
PUT    /api/modules/ntp-manager/timezone
GET    /api/modules/ntp-manager/diagnostics

GET    /api/modules/ntp-manager/firewall
POST   /api/modules/ntp-manager/firewall/open

GET    /api/modules/ntp-manager/backups
POST   /api/modules/ntp-manager/backups/{backup_id}/restore
GET    /api/modules/ntp-manager/history
POST   /api/modules/ntp-manager/chrony/install
```

Legacy `/resync` and `/sources/test` endpoints are retained as compatibility aliases while the UI uses `/sync` and `/test`.

## RBAC

Backend authorization is mandatory; hiding controls in the frontend is not considered authorization.

- `ntp.view` — status, sources, clients, diagnostics, history and backups metadata;
- `ntp.manage` — configuration, sources, timezone, restore and chrony installation;
- `ntp.service.control` — start/stop/restart;
- `ntp.sync` — force synchronization;
- `ntp.firewall.manage` — open UDP/123; admin-only by default.

`ntp.resync` remains registered only for backward compatibility with existing assignments.

Mutating endpoints use the existing WebNAS CSRF/session dependencies. Administrative operations are recorded in Activity Center with the actor, operation, basic non-sensitive parameters and result context.

## Privileged boundary and command injection protection

Production mutations use the existing root privileged broker. `Operation.NTP` is a typed, allowlisted policy; it is not a generic root shell. The broker:

- resolves binaries only from the fixed system path;
- runs `subprocess` with `shell=False`;
- accepts only known NTP systemd units/actions;
- writes only fixed NTP configuration targets;
- validates timezone syntax and installed zoneinfo paths;
- exposes explicit firewall operations instead of arbitrary firewall arguments;
- applies timeouts and bounded output;
- rejects unknown actions/parameters.

API models separately validate hostnames, IPv4, IPv6, CIDR and timezone values. Tests cover shell-like source strings, path traversal and unallowlisted broker targets/services.

## Network example

```text
Internet
  |
  v
time.cloudflare.com / pool.ntp.org
  |
  v
WebNAS
NTP Client + Server
  | UDP/123
  +-----------------------------+
  |              |              |
  v              v              v
Server01       Server02         PC01
```

## Troubleshooting

1. Check NTP Manager → **Przegląd** for backend, service state, synchronization, source, stratum and offset.
2. Open **Diagnostyka** for service conflicts, firewall state and configuration validation.
3. For chrony, verify source reachability and state in **Źródła czasu**.
4. If server mode is enabled, confirm at least one explicit allowed network and verify UDP/123.
5. If chrony is missing, use **Zainstaluj Chrony** and then configure Client, Server or Client + Server mode.
6. If WebNAS reports existing unmanaged configuration, review it before deciding which settings should be migrated into the WebNAS-managed block.
7. Use configuration restore if a deliberate change must be reverted.

## Testing policy

Backend tests mock or isolate system effects and never change the CI machine clock. Coverage includes backend/source parsing, IPv4/IPv6/CIDR/hostname validation, client/server/client+server rendering, rollback-related configuration primitives, RBAC/policy boundaries, command injection cases, timezone validation and service/broker allowlists. Frontend tests cover the main source/server forms, view-only RBAC behavior and the main-dashboard NTP widget.
