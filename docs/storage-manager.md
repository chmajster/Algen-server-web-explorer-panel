# Storage Manager

Storage Manager is the native read-only storage inventory and health application for WebNAS. The first release intentionally separates observation from privileged storage mutation: it discovers local block devices, filesystems and storage health without accepting shell commands or device paths from the browser.

## First-release scope

The module exposes:

- recursive block-device and partition topology from `lsblk`;
- disk model, serial, transport, filesystem and mount metadata;
- SMART health for ATA/SATA/SAS devices when `smartctl` is available;
- NVMe critical warning, temperature, wear, spare and media-error data when `nvme` is available;
- local filesystem capacity from the kernel mount table and `statvfs`;
- Linux software RAID state from `/proc/mdstat`;
- ZFS pool health when `zpool` is available;
- Btrfs device-stat status when `btrfs` is available;
- diagnostics for failed device health, degraded RAID/ZFS/Btrfs and local filesystems below 10% free space.

The desktop application contains Overview, Devices, Filesystems and Health views. It has no format, partition, mount, unmount, delete, pool-create or filesystem-create controls.

## Safety model

The storage API is read-only. The browser cannot provide a command, executable or target device to a probe endpoint.

Backend probes use a fixed executable allowlist: `lsblk`, `smartctl`, `nvme`, `zpool` and `btrfs`. Executables are resolved only from `/usr/sbin`, `/usr/bin`, `/sbin` and `/bin`, subprocesses are launched without a shell, and device paths are accepted only when they came from normalized `lsblk` inventory and match an absolute `/dev/...` path.

Mounts at `/`, `/boot`, `/boot/efi`, `/etc/pve` and `/var/lib/vz` (including their descendants) are marked protected. Protection propagates from a mounted partition to its parent physical disk so the UI can make system storage visually explicit even though no destructive operation exists in this release.

Pseudo filesystems and network filesystems are excluded from local capacity inventory.

## Permissions and API

Viewing summary, devices and filesystems requires `modules.view`. Diagnostics requires `modules.diagnostics`. All routes are `GET` and the module API is intentionally outside the generated public OpenAPI contract; the native frontend uses its own typed module client.

Internal routes:

- `GET /api/storage/summary`
- `GET /api/storage/devices`
- `GET /api/storage/filesystems`
- `GET /api/storage/diagnostics`

## Testing

Unit coverage is fixture-based and does not inspect or mutate the CI host's real disks. Tests cover recursive `lsblk` parsing, protected-system-disk propagation, device-path rejection, fixed NVMe/SMART command construction, degraded mdadm parsing, aggregate diagnostics and pseudo/network filesystem filtering.

Trusted future tests for destructive storage operations must use only loop devices or disposable virtual disks.

## Deferred privileged operations

Formatting, partitioning, filesystem creation, mount lifecycle, mdadm/ZFS/Btrfs mutation, scrub, snapshot and quota operations are intentionally deferred until WebNAS has the privileged operation broker. Those actions must use typed broker operations, protected-device policy, dry-run/preview, exact confirmation and Activity Center audit rather than granting the web process unrestricted root execution.
