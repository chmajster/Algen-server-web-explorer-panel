# NTP Manager

## Overview

NTP Manager provides WebNAS-native visibility and controlled administration of Linux time synchronization. It detects `chrony`/`chronyd`, `systemd-timesyncd` and optional `ntpd` without assuming one distribution-specific backend.

The dashboard now includes a normalized diagnostics layer while preserving its existing status fields. Diagnostics are read-only and do not expand the privileged broker command surface.

## Health model

The dashboard classifies the current state as:

- `healthy` — a supported backend is available, synchronization is active, the service is not failed/inactive, a selected source is visible when source telemetry is available, and absolute offset is not above 100 ms.
- `degraded` — synchronization exists, but the service/source state or offset quality indicates a problem.
- `unsynchronized` — an NTP backend exists but the host is not currently synchronized.
- `unavailable` — no supported NTP backend is available.

The health value is intended for dashboard/status use. It does not replace backend-specific telemetry.

## Backend diagnostics

### chrony

NTP Manager reads:

- `chronyc tracking` for reference ID/time, stratum, system time correction, last/RMS offset, frequency, residual frequency, skew, root delay, root dispersion, update interval and leap status;
- `chronyc -n sources` for selected/candidate/unreachable/falseticker/jittery source state, mode, stratum, poll, reach, last receive age, sample offset and uncertainty;
- `chronyc -n sourcestats` for sample count, runs, sample span, frequency estimate/skew, estimated offset and standard deviation.

### systemd-timesyncd

NTP Manager combines the existing `timedatectl` synchronization state with `timedatectl show-timesync --all` to expose the active server/address, server port, poll intervals, maximum root distance and frequency data when supported by the installed systemd version.

### ntpd

NTP Manager reads `ntpq -pn` for live peer state, selected peer, stratum, poll, reach, delay, offset and jitter. `ntpq -c rv` supplies system-level stratum, refid, root delay/dispersion, frequency, system jitter, clock wander and leap state.

Backend command failures are returned as diagnostics warnings where possible instead of discarding all remaining telemetry.

## Status and sources

The dashboard reports synchronization state, timezone, system time, selected backend/service, service state, selected source, offset, stratum, jitter/dispersion, root delay, frequency and leap status when supported.

The source table normalizes live data across backends and can show source state, mode, selection, stratum, reach, last receive age, delay, offset and jitter/uncertainty. Existing source management remains unchanged.

NTP source changes are confined to a WebNAS-managed block. Existing distribution-managed lines outside that block are preserved. Before a write, WebNAS stores a private backup under `paths.data_dir/ntp-backups`, writes atomically, restarts the detected service and restores the previous content on failure.

## Privilege boundary

In standard installations where `WEBNAS_PRIVILEGED_BROKER=required`, writes to `/etc/chrony/chrony.conf`, `/etc/chrony.conf`, `/etc/systemd/timesyncd.conf` and `/etc/ntp.conf`, NTP service changes and resync are executed by the existing root privileged broker. The broker has fixed file/service allowlists and accepts no arbitrary executable or path.

Diagnostics commands are read-only and execute through the existing unprivileged NTP service process. No new root broker operation is required.

## API

```text
GET    /api/modules/ntp-manager/dashboard
GET    /api/modules/ntp-manager/sources
POST   /api/modules/ntp-manager/sources
DELETE /api/modules/ntp-manager/sources/{server}
POST   /api/modules/ntp-manager/sources/test
POST   /api/modules/ntp-manager/resync
POST   /api/modules/ntp-manager/service
```

`GET /dashboard` preserves the previous status properties and adds normalized diagnostics fields:

```json
{
  "backend": "chrony",
  "available": true,
  "synchronized": true,
  "health": "healthy",
  "metrics": {},
  "sources": [],
  "summary": {
    "source_count": 0,
    "selected_count": 0,
    "reachable_count": 0
  },
  "warnings": [],
  "collected_at": 0
}
```

`resync` is executed through Job Queue Manager. Chrony uses `chronyc makestep`; timesyncd/ntpd use a controlled service restart.

## RBAC

- `ntp.view`
- `ntp.manage`
- `ntp.resync`

Dashboard diagnostics require only `ntp.view`. Configuration/service changes require explicit confirmation, CSRF and Activity Center audit.

## Distribution notes

Debian/Ubuntu commonly use `/etc/chrony/chrony.conf`; Fedora/RHEL commonly use `/etc/chrony.conf`. `systemd-timesyncd` is optional and may be masked on systems using chrony. `show-timesync` fields depend on the installed systemd version. If no supported backend is installed, the health model reports `unavailable`; mutating operations still return the controlled `NTP_UNAVAILABLE` response.

## Troubleshooting

Check the health value first, then inspect service state, selected source, reach, offset, jitter/dispersion and backend warnings. For chrony use `chronyc tracking`, `chronyc sources -n` and `chronyc sourcestats -n`; for ntpd use `ntpq -pn` and `ntpq -c rv`; for timesyncd use `timedatectl show-timesync --all`.

The server test performs DNS resolution only. Actual UDP/123 synchronization quality is reported by the active NTP backend.
