# NTP Manager

## Overview

NTP Manager provides WebNAS-native visibility and controlled administration of Linux time synchronization. It detects `chrony`/`chronyd`, `systemd-timesyncd` and optional `ntpd` without assuming one distribution-specific backend.

## Status and sources

The dashboard reports synchronization state, timezone, system time, selected backend/service, service state, source, offset, stratum and chrony dispersion data when available. Chrony sources are read with `chronyc -n sources`; `chronyc tracking` supplies tracking data. `systemd-timesyncd` uses `timedatectl`, `systemctl` and its configuration file.

NTP source changes are confined to a WebNAS-managed block. Existing distribution-managed lines outside that block are preserved. Before a write, WebNAS stores a private backup under `paths.data_dir/ntp-backups`, writes atomically, restarts the detected service and restores the previous content on failure.

## Privilege boundary

In standard installations where `WEBNAS_PRIVILEGED_BROKER=required`, writes to `/etc/chrony/chrony.conf`, `/etc/chrony.conf`, `/etc/systemd/timesyncd.conf` and `/etc/ntp.conf`, NTP service changes and resync are executed by the existing root privileged broker. The broker has fixed file/service allowlists and accepts no arbitrary executable or path.

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

`resync` is executed through Job Queue Manager. Chrony uses `chronyc makestep`; timesyncd/ntpd use a controlled service restart.

## RBAC

- `ntp.view`
- `ntp.manage`
- `ntp.resync`

Configuration/service changes require explicit confirmation, CSRF and Activity Center audit.

## Distribution notes

Debian/Ubuntu commonly use `/etc/chrony/chrony.conf`; Fedora/RHEL commonly use `/etc/chrony.conf`. `systemd-timesyncd` is optional and may be masked on systems using chrony. If no supported backend is installed, the API returns a controlled `NTP_UNAVAILABLE` response instead of HTTP 500.

## Troubleshooting

Check that the detected service exists and is active, the privileged broker is running when required, and outbound UDP/123 is permitted. The server test performs DNS resolution; actual synchronization verification is performed by the selected NTP backend.
