from __future__ import annotations

import grp
import json
import os
import pwd
import re
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

from app.config import get_config
from app.core.redaction import redact_text
from app.package_center.manifests import module_script

from . import policy as base
from .protocol import BrokerRequest, BrokerResponse, Operation


MODULE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MOUNT_ID_RE = re.compile(r"^[a-f0-9]{32}$")
MOUNT_UNIT_RE = re.compile(r"^[A-Za-z0-9_.\\x-]{1,240}\.(?:mount|automount)$")
DEVICE_RE = re.compile(r"^/dev/[A-Za-z0-9._/+:-]+$")
SAFE_SHELLS = {
    "/bin/bash",
    "/bin/sh",
    "/bin/dash",
    "/bin/false",
    "/usr/bin/bash",
    "/usr/bin/sh",
    "/usr/bin/dash",
    "/usr/bin/zsh",
    "/usr/bin/fish",
    "/usr/bin/false",
    "/usr/sbin/nologin",
    "/sbin/nologin",
}
MODULE_HOOK_ACTIONS = {"prepare", "install", "update", "uninstall", "rollback", "health"}
MOUNT_TYPES = {"cifs", "nfs", "davfs", "fuse.sshfs"}
MOUNT_OPTION_KEYS = {
    "nosuid", "nodev", "_netdev", "nofail", "ro", "rw", "noexec",
    "ac", "actimeo", "async", "atime", "cache", "dirsync", "hard", "intr", "iocharset",
    "lookupcache", "noac", "noatime", "nodiratime", "noserverino", "retrans", "rsize",
    "serverino", "soft", "sync", "timeo", "wsize", "credentials", "username", "password",
    "domain", "guest", "file_mode", "dir_mode", "vers", "uid", "gid", "forceuid", "forcegid",
    "ServerAliveInterval", "StrictHostKeyChecking", "port", "allow_other", "default_permissions", "conf",
}
MOUNT_SIMPLE_OPTIONS = {
    "nosuid", "nodev", "_netdev", "nofail", "ro", "rw", "noexec", "async", "atime", "dirsync",
    "hard", "intr", "noac", "noatime", "nodiratime", "noserverino", "serverino", "soft", "sync",
    "guest", "forceuid", "forcegid", "allow_other", "default_permissions",
}
MAX_OPTION_TEXT = 16 * 1024
MAX_UPDATE_INSTALLER = 2 * 1024 * 1024


def _failure(request: BrokerRequest, error: Exception, *, policy: bool) -> BrokerResponse:
    return BrokerResponse(
        request_id=request.request_id,
        ok=False,
        exit_code=126 if policy else 127,
        error_code="POLICY_DENIED" if policy else "EXECUTION_FAILED",
        stderr=redact_text(error, limit=2000),
    )


def _result(request: BrokerRequest, result: base.CommandResult) -> BrokerResponse:
    return BrokerResponse(
        request_id=request.request_id,
        ok=result.exit_code == 0,
        exit_code=result.exit_code,
        stdout=redact_text(result.stdout, limit=base.MAX_OUTPUT),
        stderr=redact_text(result.stderr, limit=base.MAX_OUTPUT),
        error_code=None if result.exit_code == 0 else "COMMAND_FAILED",
    )


def _payload_keys(payload: dict[str, Any], allowed: set[str]) -> None:
    extra = set(payload) - allowed
    if extra:
        raise base.PolicyError(f"unsupported parameters: {', '.join(sorted(extra))}")


def _clean_token(value: Any, name: str, *, limit: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        raise base.PolicyError(f"invalid {name}")
    if any(ord(character) < 32 for character in value):
        raise base.PolicyError(f"invalid {name}")
    return value


def _csv_names(value: str, kind: str) -> None:
    items = value.split(",")
    if not items or any(not item for item in items):
        raise base.PolicyError(f"invalid {kind} list")
    for item in items:
        base._name(item, kind)


def _account(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    _payload_keys(payload, {"tool", "args", "stdin"})
    tool = _clean_token(payload.get("tool"), "account tool", limit=16)
    args = payload.get("args") or []
    stdin = payload.get("stdin")
    if tool not in base.ACCOUNT_TOOLS or not isinstance(args, list) or len(args) > 24:
        raise base.PolicyError("unsupported account operation")
    if any(not isinstance(item, str) or len(item) > 512 or "\x00" in item for item in args):
        raise base.PolicyError("invalid account arguments")

    if tool == "chpasswd":
        if args or not isinstance(stdin, str) or len(stdin) > 4096 or len(stdin.splitlines()) != 1 or ":" not in stdin:
            raise base.PolicyError("chpasswd requires one credential record")
        username, password = stdin.rstrip("\n").split(":", 1)
        base._name(username, "user")
        if not password or any(character in password for character in "\r\n"):
            raise base.PolicyError("invalid password")
        return runner([base._resolve_tool(tool)], stdin, 60)
    if stdin is not None:
        raise base.PolicyError("stdin is not accepted for this account operation")

    if tool == "useradd":
        if not args:
            raise base.PolicyError("useradd target is required")
        username = base._name(args[-1], "user")
        options = args[:-1]
        index = 0
        while index < len(options):
            flag = options[index]
            if flag in {"--user-group", "--create-home"}:
                index += 1
                continue
            if flag in {"--shell", "--comment", "--groups"} and index + 1 < len(options):
                value = _clean_token(options[index + 1], flag, limit=256)
                if flag == "--shell" and value not in SAFE_SHELLS:
                    raise base.PolicyError("unsupported login shell")
                if flag == "--groups":
                    _csv_names(value, "group")
                index += 2
                continue
            raise base.PolicyError("unsupported useradd option")
        return runner([base._resolve_tool(tool), *options, username], None, 60)

    if tool == "usermod":
        if not args:
            raise base.PolicyError("usermod target is required")
        username = base._name(args[-1], "user")
        options = args[:-1]
        index = 0
        seen_lock = False
        while index < len(options):
            flag = options[index]
            if flag in {"--append", "--lock", "--unlock"}:
                if flag in {"--lock", "--unlock"}:
                    if seen_lock:
                        raise base.PolicyError("conflicting user lock option")
                    seen_lock = True
                index += 1
                continue
            if flag in {"--shell", "--comment", "--groups"} and index + 1 < len(options):
                value = _clean_token(options[index + 1], flag, limit=256)
                if flag == "--shell" and value not in SAFE_SHELLS:
                    raise base.PolicyError("unsupported login shell")
                if flag == "--groups":
                    _csv_names(value, "group")
                index += 2
                continue
            raise base.PolicyError("unsupported usermod option")
        if not options:
            raise base.PolicyError("usermod requires a change")
        return runner([base._resolve_tool(tool), *options, username], None, 60)

    if tool == "userdel":
        if len(args) == 1:
            username = base._name(args[0], "user")
            validated = [username]
        elif len(args) == 2 and args[0] == "--remove":
            username = base._name(args[1], "user")
            validated = ["--remove", username]
        else:
            raise base.PolicyError("unsupported userdel arguments")
        return runner([base._resolve_tool(tool), *validated], None, 60)

    if tool == "chage":
        if len(args) != 3 or args[0] != "-d" or args[1] not in {"0", "-1"}:
            raise base.PolicyError("unsupported chage arguments")
        username = base._name(args[2], "user")
        return runner([base._resolve_tool(tool), "-d", args[1], username], None, 60)

    if tool == "gpasswd":
        if len(args) != 3 or args[0] != "--delete":
            raise base.PolicyError("unsupported gpasswd arguments")
        username = base._name(args[1], "user")
        groupname = base._name(args[2], "group")
        return runner([base._resolve_tool(tool), "--delete", username, groupname], None, 60)

    if tool == "groupadd":
        if len(args) not in {1, 2} or (len(args) == 2 and args[0] != "--system"):
            raise base.PolicyError("unsupported groupadd arguments")
        groupname = base._name(args[-1], "group")
        validated = (["--system"] if len(args) == 2 else []) + [groupname]
        return runner([base._resolve_tool(tool), *validated], None, 60)

    if tool == "groupmod":
        if len(args) != 3 or args[0] != "--new-name":
            raise base.PolicyError("unsupported groupmod arguments")
        new_name = base._name(args[1], "group")
        old_name = base._name(args[2], "group")
        return runner([base._resolve_tool(tool), "--new-name", new_name, old_name], None, 60)

    if tool == "groupdel":
        if len(args) != 1:
            raise base.PolicyError("unsupported groupdel arguments")
        groupname = base._name(args[0], "group")
        return runner([base._resolve_tool(tool), groupname], None, 60)

    raise base.PolicyError("account operation is not enabled")


def _filesystem_roots() -> list[Path]:
    roots = [Path("/home"), Path("/mnt/webnas")]
    try:
        config = get_config()
    except Exception:  # noqa: BLE001 - fail closed to fixed roots
        return roots
    roots.extend([Path(config.paths.data_dir), Path(config.paths.log_dir), Path(config.paths.temp_dir)])
    return roots


def _ownership(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    _payload_keys(payload, {"action", "path", "owner", "group", "mode"})
    action = _clean_token(payload.get("action"), "filesystem action", limit=16)
    path = base._safe_absolute_path(_clean_token(payload.get("path"), "path", limit=4096), roots=_filesystem_roots())
    if action == "mkdir":
        mode = payload.get("mode", 0o750)
        if not isinstance(mode, int) or mode < 0o700 or mode > 0o775:
            raise base.PolicyError("invalid directory mode")
        path.mkdir(parents=True, exist_ok=True, mode=mode)
        os.chmod(path, mode)
        owner = str(payload.get("owner") or "")
        group = str(payload.get("group") or "")
        if owner or group:
            if owner:
                base._name(owner, "user")
            if group:
                base._name(group, "group")
            spec = f"{owner}:{group}" if group else owner
            result = runner([base._resolve_tool("chown"), spec, str(path)], None, 60)
            if result.exit_code:
                return result
        return base.CommandResult(0, "", "")
    if action == "chmod":
        mode = payload.get("mode")
        if not isinstance(mode, int) or mode < 0o600 or mode > 0o775:
            raise base.PolicyError("invalid permission mode")
        os.chmod(path, mode)
        return base.CommandResult(0, "", "")
    if action == "chown":
        owner = str(payload.get("owner") or "")
        group = str(payload.get("group") or "")
        if not owner and not group:
            raise base.PolicyError("owner or group is required")
        if owner:
            base._name(owner, "user")
        if group:
            base._name(group, "group")
        spec = f"{owner}:{group}" if group else owner
        return runner([base._resolve_tool("chown"), spec, str(path)], None, 60)
    raise base.PolicyError("unsupported filesystem action")


def _quota(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    _payload_keys(payload, {"username", "soft_blocks", "hard_blocks", "mountpoint"})
    username = base._name(_clean_token(payload.get("username"), "username"), "user")
    soft = payload.get("soft_blocks")
    hard = payload.get("hard_blocks")
    if not isinstance(soft, int) or not isinstance(hard, int) or soft < 0 or hard < soft or hard > 2**63 - 1:
        raise base.PolicyError("invalid quota")
    mountpoint = _clean_token(payload.get("mountpoint"), "mountpoint", limit=4096)
    pure = PurePosixPath(mountpoint)
    if not pure.is_absolute() or ".." in pure.parts or any(part in {"proc", "sys", "dev"} for part in pure.parts[1:2]):
        raise base.PolicyError("invalid quota mountpoint")
    return runner(
        [base._resolve_tool("setquota"), "-u", username, str(soft), str(hard), "0", "0", pure.as_posix()],
        None,
        60,
    )


def _package_path(value: str) -> str:
    roots = [Path("/run/webnas-package-center"), Path("/var/lib/webnas")]
    try:
        roots.append(Path(get_config().paths.data_dir))
    except Exception:  # noqa: BLE001
        pass
    return str(base._safe_absolute_path(value, roots=roots))


def _package_token(value: str) -> str:
    if not base.PACKAGE_RE.fullmatch(value):
        raise base.PolicyError("invalid package token")
    return value


def _package(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    _payload_keys(payload, {"tool", "args", "timeout"})
    tool = _clean_token(payload.get("tool"), "package manager", limit=16)
    args = payload.get("args") or []
    if tool not in base.PACKAGE_TOOLS or not isinstance(args, list) or len(args) > 256:
        raise base.PolicyError("unsupported package manager")
    if any(not isinstance(item, str) or len(item) > 4096 or "\x00" in item for item in args):
        raise base.PolicyError("invalid package arguments")
    timeout_raw = payload.get("timeout", 1800)
    if not isinstance(timeout_raw, (int, float)) or not 1 <= float(timeout_raw) <= 3600:
        raise base.PolicyError("invalid package timeout")
    timeout = float(timeout_raw)

    validated: list[str] = []
    if tool == "apt-get":
        index = 0
        while index < len(args) and args[index] == "-o":
            if index + 1 >= len(args):
                raise base.PolicyError("incomplete apt option")
            option = args[index + 1]
            if option == "Dpkg::Options::=--force-overwrite":
                validated.extend(["-o", option])
            elif option.startswith("Dir::Etc::sourcelist="):
                validated.extend(["-o", f"Dir::Etc::sourcelist={_package_path(option.split('=', 1)[1])}"])
            elif option.startswith("Dir::Etc::sourceparts="):
                validated.extend(["-o", f"Dir::Etc::sourceparts={_package_path(option.split('=', 1)[1])}"])
            else:
                raise base.PolicyError("unsupported apt option")
            index += 2
        if index >= len(args) or args[index] not in {"update", "install", "remove", "purge"}:
            raise base.PolicyError("unsupported apt operation")
        command = args[index]
        validated.append(command)
        rest = args[index + 1 :]
        if command == "update":
            if rest:
                raise base.PolicyError("apt update does not accept extra arguments")
        else:
            for item in rest:
                if item in {"-y", "--reinstall", "--no-install-recommends"}:
                    validated.append(item)
                elif item.startswith("-"):
                    raise base.PolicyError("unsupported apt flag")
                else:
                    validated.append(_package_token(item))
            if not any(not item.startswith("-") for item in rest):
                raise base.PolicyError("package list is required")
    elif tool in {"dnf", "yum"}:
        if not args or args[0] not in {"install", "reinstall", "remove"}:
            raise base.PolicyError("unsupported rpm package operation")
        validated.append(args[0])
        for item in args[1:]:
            if item == "-y":
                validated.append(item)
            elif item.startswith("-"):
                raise base.PolicyError("unsupported package flag")
            else:
                validated.append(_package_token(item))
    elif tool == "zypper":
        index = 0
        if args[:1] == ["--non-interactive"]:
            validated.append("--non-interactive")
            index = 1
        if index >= len(args) or args[index] not in {"install", "remove"}:
            raise base.PolicyError("unsupported zypper operation")
        validated.append(args[index])
        for item in args[index + 1 :]:
            if item == "--force":
                validated.append(item)
            elif item.startswith("-"):
                raise base.PolicyError("unsupported zypper flag")
            else:
                validated.append(_package_token(item))
    elif tool == "pacman":
        if not args or args[0] not in {"-S", "-R"}:
            raise base.PolicyError("unsupported pacman operation")
        validated.append(args[0])
        for item in args[1:]:
            if item in {"--noconfirm", "--needed"}:
                validated.append(item)
            elif item.startswith("-"):
                raise base.PolicyError("unsupported pacman flag")
            else:
                validated.append(_package_token(item))
    elif tool == "apk":
        if not args or args[0] not in {"add", "del", "fix"}:
            raise base.PolicyError("unsupported apk operation")
        validated.append(args[0])
        validated.extend(_package_token(item) for item in args[1:])
    elif tool == "dpkg":
        if len(args) != 2 or args[0] != "--install":
            raise base.PolicyError("unsupported dpkg operation")
        validated = ["--install", _package_path(args[1])]
    elif tool == "rpm":
        if len(args) != 2 or args[0] != "-Uvh":
            raise base.PolicyError("unsupported rpm operation")
        validated = ["-Uvh", _package_path(args[1])]
    else:
        raise base.PolicyError("package operation is not enabled")
    return runner([base._resolve_tool(tool), *validated], None, timeout)


def _module_hook(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    _payload_keys(payload, {"module_id", "action"})
    module_id = _clean_token(payload.get("module_id"), "module id", limit=64)
    action = _clean_token(payload.get("action"), "hook action", limit=16)
    if not MODULE_ID_RE.fullmatch(module_id) or action not in MODULE_HOOK_ACTIONS:
        raise base.PolicyError("unsupported module hook")
    script = module_script(module_id, action)
    if script is None:
        return base.CommandResult(0, "", "")
    resolved = script.resolve(strict=True)
    modules_root = (Path(__file__).resolve().parents[1] / "modules").resolve(strict=True)
    if not resolved.is_relative_to(modules_root) or resolved.suffix not in {".py", ".sh"}:
        raise base.PolicyError("module hook resolved outside the trusted module tree")
    executable = sys.executable if resolved.suffix == ".py" else base._resolve_tool("bash")
    return runner([executable, str(resolved)], None, 1800 if action in {"prepare", "rollback", "health"} else 300)


def _samba_account(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    _payload_keys(payload, {"action", "username", "password"})
    action = _clean_token(payload.get("action"), "Samba account action", limit=16)
    username = base._name(_clean_token(payload.get("username"), "username", limit=64), "user")
    executable = base._resolve_tool("smbpasswd")
    if action == "set":
        password = payload.get("password")
        if not isinstance(password, str) or not password or len(password) > 1024 or any(character in password for character in "\r\n"):
            raise base.PolicyError("invalid Samba password")
        return runner([executable, "-s", "-a", username], f"{password}\n{password}\n", 60)
    if action == "enable":
        return runner([executable, "-e", username], None, 60)
    if action == "disable":
        return runner([executable, "-d", username], None, 60)
    raise base.PolicyError("unsupported Samba account action")


def _mount_root(path: str, *, allow_home: bool = False) -> str:
    roots = [Path("/mnt/webnas")]
    if allow_home:
        roots.append(Path("/home"))
    return str(base._safe_absolute_path(path, roots=roots))


def _mount_option(option: str) -> str:
    if not option or len(option) > 4096 or "\x00" in option or any(ord(character) < 32 for character in option):
        raise base.PolicyError("invalid mount option")
    key, separator, value = option.partition("=")
    if key not in MOUNT_OPTION_KEYS:
        raise base.PolicyError("unsupported mount option")
    if not separator:
        if key not in MOUNT_SIMPLE_OPTIONS:
            raise base.PolicyError("mount option requires a value")
        return key
    if key in {"credentials", "conf"}:
        roots = [Path("/var/lib/webnas")]
        try:
            roots.append(Path(get_config().paths.data_dir))
        except Exception:  # noqa: BLE001
            pass
        safe_path = base._safe_absolute_path(value, roots=roots)
        return f"{key}={safe_path}"
    if key in {"uid", "gid", "port", "file_mode", "dir_mode", "ServerAliveInterval", "timeo", "retrans", "rsize", "wsize", "actimeo"}:
        if not re.fullmatch(r"[0-9]{1,12}", value):
            raise base.PolicyError("invalid numeric mount option")
    elif key == "StrictHostKeyChecking":
        if value != "accept-new":
            raise base.PolicyError("unsupported SSH host-key policy")
    elif key == "password":
        if value:
            raise base.PolicyError("inline mount passwords are forbidden")
    elif not re.fullmatch(r"[A-Za-z0-9_.:/@+ -]{0,512}", value):
        raise base.PolicyError("invalid mount option value")
    return option


def _validated_mount_options(raw: Any) -> str:
    if not isinstance(raw, str) or len(raw) > MAX_OPTION_TEXT:
        raise base.PolicyError("invalid mount option list")
    options = [_mount_option(item) for item in raw.split(",") if item]
    if "nosuid" not in options or "nodev" not in options:
        raise base.PolicyError("mandatory mount safety options are missing")
    return ",".join(options)


def _mount(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    _payload_keys(payload, {"tool", "args", "timeout"})
    tool = _clean_token(payload.get("tool"), "mount tool", limit=16)
    args = payload.get("args") or []
    if not isinstance(args, list) or any(not isinstance(item, str) or len(item) > 16_384 or "\x00" in item for item in args):
        raise base.PolicyError("invalid mount arguments")
    timeout_raw = payload.get("timeout", 180)
    if not isinstance(timeout_raw, (int, float)) or not 1 <= float(timeout_raw) <= 300:
        raise base.PolicyError("invalid mount timeout")
    timeout = float(timeout_raw)
    if tool == "umount":
        if len(args) != 1:
            raise base.PolicyError("unsupported umount arguments")
        target = _mount_root(args[0], allow_home=True)
        return runner([base._resolve_tool("umount"), target], None, timeout)
    if tool == "mount":
        if len(args) != 6 or args[0] != "-t" or args[2] != "-o" or args[1] not in {"cifs", "nfs", "davfs"}:
            raise base.PolicyError("unsupported mount command")
        filesystem = args[1]
        options = _validated_mount_options(args[3])
        remote = _clean_token(args[4], "mount remote", limit=4096)
        target = _mount_root(args[5])
        return runner([base._resolve_tool("mount"), "-t", filesystem, "-o", options, remote, target], None, timeout)
    if tool == "sshfs":
        if len(args) != 4 or args[2] != "-o":
            raise base.PolicyError("unsupported sshfs command")
        remote = _clean_token(args[0], "SSHFS remote", limit=4096)
        target = _mount_root(args[1])
        options = _validated_mount_options(args[3])
        return runner([base._resolve_tool("sshfs"), remote, target, "-o", options], None, timeout)
    raise base.PolicyError("unsupported mount tool")


def _systemd_escape(path: str, suffix: str, runner: base.Runner) -> str:
    result = runner([base._resolve_tool("systemd-escape"), "--path", f"--suffix={suffix}", path], None, 15)
    if result.exit_code != 0:
        raise base.PolicyError("systemd-escape failed")
    name = result.stdout.strip()
    if not MOUNT_UNIT_RE.fullmatch(name):
        raise base.PolicyError("invalid generated mount unit name")
    return name


def _atomic_unit(path: Path, content: str) -> None:
    descriptor, temporary_raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _mount_unit(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    _payload_keys(payload, {"action", "mount_id", "mount_point", "remote", "fs_type", "options", "automount"})
    action = _clean_token(payload.get("action"), "mount unit action", limit=16)
    mount_id = _clean_token(payload.get("mount_id"), "mount id", limit=32)
    if not MOUNT_ID_RE.fullmatch(mount_id):
        raise base.PolicyError("invalid mount id")
    mount_point = _mount_root(_clean_token(payload.get("mount_point"), "mount point", limit=4096), allow_home=True)
    mount_name = _systemd_escape(mount_point, "mount", runner)
    automount_name = _systemd_escape(mount_point, "automount", runner)
    legacy = [f"webnas-mount-{mount_id}.mount", f"webnas-mount-{mount_id}.automount"]
    systemd_dir = Path("/etc/systemd/system")
    systemd_dir.mkdir(parents=True, exist_ok=True)
    systemctl = base._resolve_tool("systemctl")
    if action == "remove":
        for name in [mount_name, automount_name, *legacy]:
            if MOUNT_UNIT_RE.fullmatch(name):
                runner([systemctl, "disable", "--now", name], None, 60)
                (systemd_dir / name).unlink(missing_ok=True)
        return runner([systemctl, "daemon-reload"], None, 60)
    if action != "apply":
        raise base.PolicyError("unsupported mount unit action")
    remote = _clean_token(payload.get("remote"), "mount remote", limit=4096)
    fs_type = _clean_token(payload.get("fs_type"), "filesystem type", limit=32)
    if fs_type not in MOUNT_TYPES:
        raise base.PolicyError("unsupported mount filesystem")
    options = _validated_mount_options(_clean_token(payload.get("options"), "mount options", limit=MAX_OPTION_TEXT))
    automount = payload.get("automount")
    if not isinstance(automount, bool):
        raise base.PolicyError("invalid automount flag")
    mount_content = "\n".join([
        "[Unit]",
        "Description=WebNAS network mount",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Mount]",
        f"What={remote}",
        f"Where={mount_point}",
        f"Type={fs_type}",
        f"Options={options}",
        "TimeoutSec=120",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ])
    _atomic_unit(systemd_dir / mount_name, mount_content)
    if automount:
        automount_content = "\n".join([
            "[Unit]",
            "Description=WebNAS network automount",
            "After=network-online.target",
            "",
            "[Automount]",
            f"Where={mount_point}",
            "TimeoutIdleSec=300",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
            "",
        ])
        _atomic_unit(systemd_dir / automount_name, automount_content)
    else:
        (systemd_dir / automount_name).unlink(missing_ok=True)
    result = runner([systemctl, "daemon-reload"], None, 60)
    if result.exit_code:
        return result
    selected = automount_name if automount else mount_name
    return runner([systemctl, "enable", selected], None, 60)


def _storage_probe(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    _payload_keys(payload, {"tool", "args", "timeout"})
    tool = _clean_token(payload.get("tool"), "storage tool", limit=16)
    args = payload.get("args") or []
    if not isinstance(args, list) or any(not isinstance(item, str) or len(item) > 512 or "\x00" in item for item in args):
        raise base.PolicyError("invalid storage probe arguments")
    timeout_raw = payload.get("timeout", 12)
    if not isinstance(timeout_raw, (int, float)) or not 1 <= float(timeout_raw) <= 30:
        raise base.PolicyError("invalid storage probe timeout")
    if tool == "smartctl":
        if len(args) != 3 or args[:2] != ["-a", "-j"] or not DEVICE_RE.fullmatch(args[2]):
            raise base.PolicyError("unsupported smartctl probe")
    elif tool == "nvme":
        if len(args) != 4 or args[:3] != ["smart-log", "-o", "json"] or not DEVICE_RE.fullmatch(args[3]):
            raise base.PolicyError("unsupported nvme probe")
    else:
        raise base.PolicyError("storage probe is not enabled")
    return runner([base._resolve_tool(tool), *args], None, float(timeout_raw))


def _update_service(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    _payload_keys(payload, {"update_config", "npm_audit_fix"})
    update_config = payload.get("update_config", False)
    npm_audit_fix = payload.get("npm_audit_fix", False)
    if not isinstance(update_config, bool) or not isinstance(npm_audit_fix, bool):
        raise base.PolicyError("invalid update options")
    config = get_config()
    settings_dir = Path(config.paths.data_dir) / "settings"
    log_dir = Path(config.paths.log_dir)
    settings_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    unit_name = f"webnas-self-update-{int(time.time() * 1000)}.service"
    if not base.UPDATE_UNIT_RE.fullmatch(unit_name):
        raise base.PolicyError("invalid update unit")
    runtime_root = Path("/run/webnas-update") / unit_name.removesuffix(".service")
    runtime_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    installer = runtime_root / "install.sh"
    runner_path = runtime_root / "runner.sh"
    request = urllib.request.Request(
        "https://raw.githubusercontent.com/chmajster/Algen-server-web-explorer-panel/main/install.sh",
        headers={"User-Agent": "WebNAS-privileged-update/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310 - fixed HTTPS origin
            content = response.read(MAX_UPDATE_INSTALLER + 1)
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError("could not download the trusted WebNAS installer") from error
    if len(content) > MAX_UPDATE_INSTALLER or not content.startswith(b"#!/usr/bin/env bash"):
        raise base.PolicyError("downloaded WebNAS installer is invalid")
    installer.write_bytes(content)
    os.chmod(installer, 0o700)
    progress = settings_dir / "update_progress.json"
    log_path = log_dir / "update.log"
    webnas_user = pwd.getpwnam("webnas")
    try:
        webnas_group = grp.getgrnam("webnas")
    except KeyError as error:
        raise RuntimeError("webnas group is unavailable") from error
    command = [base._resolve_tool("bash"), str(installer), "--existing-action", "update", "--yes"]
    if update_config:
        command.append("--update-config")
    if npm_audit_fix:
        command.append("--npm-audit-fix")
    command_text = " ".join(shlex.quote(item) for item in command)
    runner_text = "\n".join([
        "#!/usr/bin/env bash",
        "set +e",
        f"touch {shlex.quote(str(log_path))}",
        f"chown {webnas_user.pw_uid}:{webnas_group.gr_gid} {shlex.quote(str(log_path))}",
        f"chmod 0640 {shlex.quote(str(log_path))}",
        f"exec >> {shlex.quote(str(log_path))} 2>&1",
        f"printf '\\n=== WebNAS update started (%s) ===\\n' {shlex.quote(unit_name)}",
        f"printf '{{\"running\":true,\"exit_code\":null,\"started_at\":%s,\"finished_at\":null,\"pid\":%s,\"unit\":\"{unit_name}\"}}\\n' \"$(date +%s)\" \"$$\" > {shlex.quote(str(progress))}.tmp",
        f"chown {webnas_user.pw_uid}:{webnas_group.gr_gid} {shlex.quote(str(progress))}.tmp",
        f"chmod 0640 {shlex.quote(str(progress))}.tmp",
        f"mv -f -- {shlex.quote(str(progress))}.tmp {shlex.quote(str(progress))}",
        command_text,
        "rc=$?",
        f"printf '{{\"running\":false,\"exit_code\":%s,\"started_at\":null,\"finished_at\":%s,\"pid\":%s,\"unit\":\"{unit_name}\"}}\\n' \"$rc\" \"$(date +%s)\" \"$$\" > {shlex.quote(str(progress))}.tmp",
        f"chown {webnas_user.pw_uid}:{webnas_group.gr_gid} {shlex.quote(str(progress))}.tmp",
        f"chmod 0640 {shlex.quote(str(progress))}.tmp",
        f"mv -f -- {shlex.quote(str(progress))}.tmp {shlex.quote(str(progress))}",
        "exit \"$rc\"",
        "",
    ])
    runner_path.write_text(runner_text, encoding="utf-8")
    os.chmod(runner_path, 0o700)
    result = runner(
        [
            base._resolve_tool("systemd-run"),
            "--unit", unit_name,
            "--collect",
            "--no-block",
            "--property=Type=exec",
            "--property=TimeoutStopSec=infinity",
            "--",
            base._resolve_tool("bash"),
            str(runner_path),
        ],
        None,
        30,
    )
    if result.exit_code:
        return result
    return base.CommandResult(0, json.dumps({"unit": unit_name, "pid": None, "log": str(log_path)}), "")


def dispatch(request: BrokerRequest, *, runner: base.Runner | None = None) -> BrokerResponse:
    selected_runner = runner or base._default_runner
    custom = {
        Operation.ACCOUNT,
        Operation.OWNERSHIP,
        Operation.PACKAGE,
        Operation.MODULE_HOOK,
        Operation.SAMBA_ACCOUNT,
        Operation.MOUNT,
        Operation.MOUNT_UNIT,
        Operation.QUOTA,
        Operation.STORAGE_PROBE,
        Operation.UPDATE_SERVICE,
    }
    if request.operation not in custom:
        return base.dispatch(request, runner=selected_runner)
    try:
        if request.operation == Operation.ACCOUNT:
            result = _account(request.payload, selected_runner)
        elif request.operation == Operation.OWNERSHIP:
            result = _ownership(request.payload, selected_runner)
        elif request.operation == Operation.PACKAGE:
            result = _package(request.payload, selected_runner)
        elif request.operation == Operation.MODULE_HOOK:
            result = _module_hook(request.payload, selected_runner)
        elif request.operation == Operation.SAMBA_ACCOUNT:
            result = _samba_account(request.payload, selected_runner)
        elif request.operation == Operation.MOUNT:
            result = _mount(request.payload, selected_runner)
        elif request.operation == Operation.MOUNT_UNIT:
            result = _mount_unit(request.payload, selected_runner)
        elif request.operation == Operation.QUOTA:
            result = _quota(request.payload, selected_runner)
        elif request.operation == Operation.STORAGE_PROBE:
            result = _storage_probe(request.payload, selected_runner)
        elif request.operation == Operation.UPDATE_SERVICE:
            result = _update_service(request.payload, selected_runner)
        else:  # pragma: no cover - guarded by custom set
            raise base.PolicyError("operation is not enabled")
    except base.PolicyError as error:
        return _failure(request, error, policy=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return _failure(request, error, policy=False)
    return _result(request, result)
