from __future__ import annotations

import json
import os
import pwd
import shutil
import stat
from pathlib import Path, PurePosixPath
from typing import TypedDict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .audit import logger
from .config import get_config
from .proxmox_guard import assert_path_allowed, validate_allowed_roots
from .security import SessionUser, get_session_user


router = APIRouter(prefix="/api/files")

PSEUDO_FILESYSTEMS = {
    "autofs", "binfmt_misc", "bpf", "cgroup", "cgroup2", "configfs", "debugfs", "devpts",
    "devtmpfs", "efivarfs", "fuse.portal", "fusectl", "hugetlbfs", "mqueue", "nsfs",
    "overlay", "proc", "pstore", "ramfs", "rootfs", "rpc_pipefs", "securityfs",
    "selinuxfs", "squashfs", "sysfs", "tmpfs", "tracefs",
}
NETWORK_FILESYSTEMS = {
    "9p", "afs", "ceph", "cifs", "davfs", "davfs2", "fuse.davfs", "fuse.glusterfs",
    "fuse.rclone", "fuse.s3fs", "fuse.sshfs", "glusterfs", "nfs", "nfs4", "smb3",
    "sshfs", "virtiofs",
}
PREFERRED_ROOTS = (PurePosixPath("/mnt"), PurePosixPath("/media"), PurePosixPath("/srv"))
USB_MOUNT_ROOT = PurePosixPath("/media/webnas-usb")
USB_STATE_DIR = Path("/run/webnas/usb-mounts")
BLOCKED_ROOTS = tuple(
    PurePosixPath(path)
    for path in (
        "/boot", "/etc", "/usr", "/var", "/proc", "/sys", "/dev", "/run",
        "/tmp",  # nosec B108
        "/mnt/pve", "/mnt/webnas", "/srv/webnas-shares", "/etc/pve", "/var/lib/vz",
    )
)


class MountRecord(TypedDict):
    device: str
    mount_point: str
    fs_type: str
    options: list[str]


class LocalDisk(BaseModel):
    device: str
    mount_point: str
    name: str
    fs_type: str
    read_only: bool
    removable: bool = False
    total: int
    used: int
    free: int


def _decode_mount_field(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 3 < len(value):
            digits = value[index + 1 : index + 4]
            if all(character in "01234567" for character in digits):
                result.append(chr(int(digits, 8)))
                index += 4
                continue
        result.append(value[index])
        index += 1
    return "".join(result)


def parse_proc_mounts(content: str) -> list[MountRecord]:
    mounts: list[MountRecord] = []
    for line in content.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        mounts.append(
            {
                "device": _decode_mount_field(fields[0]),
                "mount_point": _decode_mount_field(fields[1]),
                "fs_type": _decode_mount_field(fields[2]).lower(),
                "options": [_decode_mount_field(option) for option in fields[3].split(",")],
            }
        )
    return mounts


def _read_mounts() -> list[MountRecord]:
    try:
        content = Path("/proc/self/mounts").read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("local_disks_mount_table_unavailable error=%s", type(exc).__name__)
        return []
    return parse_proc_mounts(content)


def _same_or_child(path: PurePosixPath, root: PurePosixPath) -> bool:
    return path == root or root in path.parents


def _looks_like_block_device(device: str) -> bool:
    return device.startswith("/dev/") and device != "/dev"


def _is_local_candidate(mount: MountRecord) -> bool:
    fs_type = mount["fs_type"]
    if fs_type in PSEUDO_FILESYSTEMS or fs_type in NETWORK_FILESYSTEMS or fs_type.startswith("fuse.sshfs"):
        return False
    if "bind" in mount["options"] or "rbind" in mount["options"]:
        return False
    if any(ord(character) < 32 for character in mount["mount_point"]):
        return False
    try:
        point = PurePosixPath(mount["mount_point"])
    except (TypeError, ValueError):
        return False
    if not point.is_absolute() or ".." in point.parts or point == PurePosixPath("/"):
        return False
    if any(_same_or_child(point, blocked) for blocked in BLOCKED_ROOTS):
        return False
    preferred = any(_same_or_child(point, root) for root in PREFERRED_ROOTS)
    return preferred or _looks_like_block_device(mount["device"])


def _secure_mount_path(username: str, mount_point: str) -> Path | None:
    candidate = Path(mount_point).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_dir():
            return None
        # A mountpoint supplied through a symlink can alias an otherwise protected tree.
        if os.name != "nt" and resolved != candidate:
            return None
        cfg = get_config()
        validate_allowed_roots(username, [resolved], cfg)
        assert_path_allowed(resolved, "local-disk", cfg, include_parent=False)
        return resolved
    except (HTTPException, OSError, RuntimeError):
        return None


def _mode_allows(mode: int, uid: int, gids: set[int], owner: int, group: int, *, read: bool) -> bool:
    if uid == 0:
        return True
    if uid == owner:
        required = stat.S_IXUSR | (stat.S_IRUSR if read else 0)
    elif group in gids:
        required = stat.S_IXGRP | (stat.S_IRGRP if read else 0)
    else:
        required = stat.S_IXOTH | (stat.S_IROTH if read else 0)
    return mode & required == required


def user_can_access_mount(username: str, path: Path) -> bool:
    try:
        account = pwd.getpwnam(username)
        gids = set(os.getgrouplist(username, account.pw_gid))
        current = path
        first = True
        while True:
            details = current.stat()
            if not _mode_allows(details.st_mode, account.pw_uid, gids, details.st_uid, details.st_gid, read=first):
                return False
            if current.parent == current:
                return True
            current = current.parent
            first = False
    except (KeyError, OSError):
        return False


def _visible_mount_records(username: str) -> list[tuple[MountRecord, Path]]:
    visible: list[tuple[MountRecord, Path]] = []
    seen: set[str] = set()
    for mount in _read_mounts():
        if not _is_local_candidate(mount):
            continue
        root = _secure_mount_path(username, mount["mount_point"])
        if root is None or not user_can_access_mount(username, root):
            continue
        key = os.path.normcase(str(root))
        if key in seen:
            continue
        seen.add(key)
        visible.append((mount, root))
    return visible


def visible_local_disk_roots(username: str) -> list[Path]:
    return [root for _mount, root in _visible_mount_records(username)]


def _usb_metadata(device: str, mount_point: str | Path) -> tuple[bool, str]:
    try:
        point = PurePosixPath(str(mount_point))
    except (TypeError, ValueError):
        return False, ""
    if point.parent != USB_MOUNT_ROOT:
        return False, ""

    # The private runtime record adds the filesystem label. The mount location
    # remains authoritative, so a USB disk is still identified if /run state is
    # briefly unavailable during startup or removal.
    device_name = PurePosixPath(device).name
    if not device_name or "/" in device_name or device_name in {".", ".."}:
        return True, ""
    state_file = USB_STATE_DIR / f"{device_name}.json"
    try:
        if state_file.is_symlink() or state_file.stat().st_size > 8192:
            return True, ""
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return True, ""
    if not isinstance(payload, dict) or payload.get("device") != device or payload.get("mount_point") != str(mount_point):
        return True, ""
    label = payload.get("label", "")
    if not isinstance(label, str):
        return True, ""
    label = " ".join("".join(character for character in label if character.isprintable()).split())[:80]
    return True, label


def local_disk_mounts(username: str) -> list[dict]:
    disks: list[dict] = []
    for mount, root in _visible_mount_records(username):
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        removable, usb_label = _usb_metadata(mount["device"], mount["mount_point"])
        name = usb_label or root.name or PurePosixPath(mount["device"]).name or mount["device"]
        disks.append(
            LocalDisk(
                device=mount["device"],
                mount_point=str(root),
                name=name,
                fs_type=mount["fs_type"],
                read_only="ro" in mount["options"],
                removable=removable,
                total=usage.total,
                used=usage.used,
                free=usage.free,
            ).model_dump()
        )
    return sorted(disks, key=lambda disk: (str(disk["name"]).casefold(), str(disk["mount_point"])))


def local_disk_for_path(path: str | Path) -> MountRecord | None:
    candidate = PurePosixPath(str(path))
    matches = []
    for mount in _read_mounts():
        if not _is_local_candidate(mount):
            continue
        root = PurePosixPath(mount["mount_point"])
        if _same_or_child(candidate, root):
            matches.append((len(root.parts), mount))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def assert_write_allowed(path: str | Path) -> None:
    mount = local_disk_for_path(path)
    if mount and "ro" in mount["options"]:
        raise HTTPException(403, "Local disk is read-only")


@router.get("/local-disks", response_model=list[LocalDisk])
def list_local_disks(user: SessionUser = Depends(get_session_user)) -> list[dict]:
    return local_disk_mounts(user.username)
