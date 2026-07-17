#!/usr/bin/env python3
"""Mount removable USB filesystems managed by WebNAS.

The script is invoked only by the webnas-usb-mount@.service systemd template.
It deliberately accepts direct /dev kernel names and a small filesystem allowlist.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import unicodedata
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - production is Linux; permits pure-function tests elsewhere
    fcntl = None  # type: ignore[assignment]


MOUNT_ROOT = Path("/media/webnas-usb")
STATE_DIR = Path("/run/webnas/usb-mounts")
LOCK_FILE = Path("/run/webnas/usb-automount.lock")
DEVICE_PATTERN = re.compile(r"/dev/(?P<name>[A-Za-z0-9._+-]{1,128})\Z")
FILESYSTEM_ALLOWLIST = {
    "btrfs",
    "exfat",
    "ext2",
    "ext3",
    "ext4",
    "f2fs",
    "ntfs",
    "ntfs3",
    "vfat",
    "xfs",
}
PERMISSION_OPTION_FILESYSTEMS = {"exfat", "ntfs", "ntfs3", "vfat"}


class AutomountError(RuntimeError):
    """A safe, user-facing automount failure."""


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(  # noqa: S603 - command and every argument are closed above
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AutomountError(f"Could not run {command[0]}: {type(exc).__name__}") from exc
    if check and result.returncode:
        details = (result.stderr or result.stdout).strip()
        raise AutomountError(f"{command[0]} failed: {details[:500] or f'exit {result.returncode}'}")
    return result


def parse_udev_properties(content: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in content.splitlines():
        key, separator, value = line.partition("=")
        if separator and key:
            properties[key] = value
    return properties


def _device_name(device: str) -> str:
    match = DEVICE_PATTERN.fullmatch(device)
    if not match:
        raise AutomountError("Only a direct /dev block-device name is allowed")
    return match.group("name")


def _device_properties(device: str) -> dict[str, str]:
    _device_name(device)
    try:
        mode = os.stat(device, follow_symlinks=False).st_mode
    except OSError as exc:
        raise AutomountError("The USB block device is no longer available") from exc
    if not stat.S_ISBLK(mode):
        raise AutomountError("The selected path is not a block device")
    result = _run(["/usr/bin/udevadm", "info", "--query=property", f"--name={device}"])
    properties = parse_udev_properties(result.stdout)
    fs_type = properties.get("ID_FS_TYPE", "").lower()
    if properties.get("ID_BUS") != "usb":
        raise AutomountError("The selected block device is not connected over USB")
    if properties.get("DEVTYPE") not in {"disk", "partition"}:
        raise AutomountError("Only USB disks and partitions can be mounted")
    if properties.get("ID_FS_USAGE") != "filesystem" or fs_type not in FILESYSTEM_ALLOWLIST:
        raise AutomountError(f"Unsupported or missing USB filesystem: {fs_type or 'unknown'}")
    properties["ID_FS_TYPE"] = fs_type
    return properties


def _display_label(value: str) -> str:
    cleaned = " ".join("".join(character for character in value if character.isprintable()).split())
    return cleaned[:80]


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip(" .-_")
    return normalized[:44] or "usb"


def mountpoint_name(label: str, uuid: str, device_name: str) -> str:
    identity = re.sub(r"[^A-Za-z0-9]+", "", uuid)[:12] or device_name
    return f"{_slug(label or 'usb')}-{identity}"[:64].rstrip(".-_")


def mount_options(fs_type: str) -> list[str]:
    options = ["nosuid", "nodev", "noexec"]
    if fs_type in PERMISSION_OPTION_FILESYSTEMS:
        options.extend(["uid=0", "gid=0", "fmask=0111", "dmask=0000"])
    return options


def _state_file(device: str) -> Path:
    return STATE_DIR / f"{_device_name(device)}.json"


def _prepare_directories() -> None:
    if MOUNT_ROOT.is_symlink() or STATE_DIR.is_symlink():
        raise AutomountError("A managed USB directory cannot be a symlink")
    MOUNT_ROOT.mkdir(parents=True, exist_ok=True, mode=0o755)
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Authenticated local users must be able to traverse to their mounted media.
    os.chmod(MOUNT_ROOT, 0o755)  # nosec B103
    os.chmod(STATE_DIR, 0o700)


@contextmanager
def _locked() -> Iterator[None]:
    if fcntl is None:
        raise AutomountError("USB automount requires Linux")
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    descriptor = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _write_state(device: str, payload: dict[str, str]) -> None:
    state_file = _state_file(device)
    temporary = state_file.with_name(f".{state_file.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, state_file)
        os.chmod(state_file, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_state(device: str) -> dict[str, str] | None:
    state_file = _state_file(device)
    try:
        if state_file.is_symlink() or state_file.stat().st_size > 8192:
            raise AutomountError("Invalid USB mount state file")
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        raise AutomountError("Could not read the USB mount state") from exc
    if not isinstance(payload, dict) or payload.get("device") != device:
        raise AutomountError("USB mount state does not match the device")
    return {str(key): str(value) for key, value in payload.items()}


def _mount_for_source(device: str) -> str:
    result = _run(["/usr/bin/findmnt", "--noheadings", "--raw", "--source", device, "--output", "TARGET"], check=False)
    return result.stdout.splitlines()[0].strip() if result.returncode == 0 and result.stdout.strip() else ""


def _source_for_mount(target: Path) -> str:
    # --mountpoint requires an exact mountpoint. --target would instead return
    # the parent filesystem for a newly created, not-yet-mounted directory.
    result = _run(["/usr/bin/findmnt", "--noheadings", "--raw", "--mountpoint", str(target), "--output", "SOURCE"], check=False)
    return result.stdout.splitlines()[0].strip() if result.returncode == 0 and result.stdout.strip() else ""


def _same_device(left: str, right: str) -> bool:
    try:
        return os.path.realpath(left) == os.path.realpath(right)
    except OSError:
        return left == right


def _safe_target(value: str) -> Path:
    pure = PurePosixPath(value)
    if not pure.is_absolute() or pure.parent != PurePosixPath(str(MOUNT_ROOT)):
        raise AutomountError("USB mount state contains an unsafe mount point")
    target = Path(value)
    if target.is_symlink():
        raise AutomountError("USB mount point cannot be a symlink")
    return target


def mount_device(device: str) -> None:
    properties = _device_properties(device)
    existing = _mount_for_source(device)
    if existing:
        print(f"USB filesystem {device} is already mounted at {existing}")
        return

    _prepare_directories()
    label = _display_label(properties.get("ID_FS_LABEL", ""))
    uuid = properties.get("ID_FS_UUID", "")[:128]
    device_name = _device_name(device)
    target = MOUNT_ROOT / mountpoint_name(label, uuid, device_name)
    _safe_target(str(target))
    target_created = False
    if target.exists():
        if not target.is_dir() or any(target.iterdir()):
            raise AutomountError(f"Refusing to hide existing data at {target}")
    else:
        target.mkdir(mode=0o755)
        target_created = True

    source = _source_for_mount(target)
    if source:
        if not _same_device(source, device):
            raise AutomountError(f"Mount point {target} is already used by another device")
    else:
        command = [
            "/usr/bin/mount",
            "--types",
            properties["ID_FS_TYPE"],
            "--options",
            ",".join(mount_options(properties["ID_FS_TYPE"])),
            "--",
            device,
            str(target),
        ]
        try:
            _run(command)
        except Exception:
            if target_created:
                target.rmdir()
            raise

    display_name = label or (f"USB {uuid[:8]}" if uuid else f"USB {device_name}")
    try:
        _write_state(
            device,
            {
                "device": device,
                "mount_point": str(target),
                "filesystem": properties["ID_FS_TYPE"],
                "label": display_name,
                "uuid": uuid,
            },
        )
    except Exception:
        _run(["/usr/bin/umount", "--", str(target)], check=False)
        if target.exists():
            try:
                target.rmdir()
            except OSError:
                pass
        raise
    print(f"Mounted USB filesystem {device} at {target}")


def unmount_device(device: str) -> None:
    state = _read_state(device)
    if state is None:
        print(f"No WebNAS-managed mount state exists for {device}")
        return
    target = _safe_target(state.get("mount_point", ""))
    source = _source_for_mount(target)
    if source and not _same_device(source, device):
        raise AutomountError(f"Refusing to unmount {target}: it now belongs to another device")
    if source:
        result = _run(["/usr/bin/umount", "--", str(target)], check=False)
        if result.returncode and not Path(device).exists():
            result = _run(["/usr/bin/umount", "--lazy", "--", str(target)], check=False)
        if result.returncode:
            details = (result.stderr or result.stdout).strip()
            raise AutomountError(f"Could not unmount {target}: {details[:500] or f'exit {result.returncode}'}")

    _state_file(device).unlink(missing_ok=True)
    try:
        target.rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        print(f"Kept non-empty USB mount directory {target}", file=sys.stderr)
    print(f"Unmounted USB filesystem {device}")


def cleanup_mounts() -> None:
    if not STATE_DIR.exists() or STATE_DIR.is_symlink():
        return
    failures: list[str] = []
    for state_file in sorted(STATE_DIR.glob("*.json")):
        device = f"/dev/{state_file.stem}"
        try:
            unmount_device(device)
        except AutomountError as exc:
            failures.append(f"{device}: {exc}")
    if failures:
        raise AutomountError("; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description="WebNAS USB filesystem automounter")
    parser.add_argument("action", choices=("mount", "unmount", "cleanup"))
    parser.add_argument("device", nargs="?")
    arguments = parser.parse_args()
    if arguments.action != "cleanup" and not arguments.device:
        parser.error("mount and unmount require a device")
    if arguments.action == "cleanup" and arguments.device:
        parser.error("cleanup does not accept a device")
    try:
        with _locked():
            if arguments.action == "mount":
                mount_device(arguments.device)
            elif arguments.action == "unmount":
                unmount_device(arguments.device)
            else:
                cleanup_mounts()
    except AutomountError as exc:
        print(f"webnas-usb-automount: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
