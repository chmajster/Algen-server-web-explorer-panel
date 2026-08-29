from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .client import BrokerClient
from .protocol import Operation


BROKER_MODE_ENV = "WEBNAS_PRIVILEGED_BROKER"
ACCOUNT_TOOLS = {"useradd", "usermod", "userdel", "groupadd", "groupmod", "groupdel", "gpasswd", "chpasswd", "chage"}
PACKAGE_TOOLS = {"apt-get", "dnf", "yum", "zypper", "pacman", "apk", "dpkg", "rpm"}
SYSTEMD_MUTATIONS = {"start", "stop", "restart", "reload", "enable", "disable"}


def broker_required() -> bool:
    return os.environ.get(BROKER_MODE_ENV, "").strip().lower() == "required"


def _completed(args: list[str], response: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=args,
        returncode=int(response.exit_code),
        stdout=str(response.stdout or ""),
        stderr=str(response.stderr or ""),
    )


def systemd_action(
    action: str,
    unit: str = "",
    *,
    actor: str,
    client: BrokerClient | None = None,
) -> subprocess.CompletedProcess[str]:
    payload: dict[str, Any] = {"action": action}
    if action != "daemon-reload":
        payload["unit"] = unit
    selected = client or BrokerClient()
    response = selected.request(Operation.SYSTEMD, payload, actor=actor)
    args = ["systemctl", action] + ([unit] if unit else [])
    return _completed(args, response)


def managed_file_write(
    target: str,
    content: str,
    *,
    actor: str,
    mode: int = 0o644,
    client: BrokerClient | None = None,
) -> None:
    selected = client or BrokerClient()
    response = selected.require(
        Operation.MANAGED_FILE,
        {"target": target, "content": content, "mode": mode},
        actor=actor,
    )
    if not response.ok:  # pragma: no cover - require() raises, retained as a fail-closed invariant.
        raise RuntimeError("privileged managed-file write failed")


def ownership_change(
    path: Path,
    *,
    owner: str = "",
    group: str = "",
    actor: str,
    client: BrokerClient | None = None,
) -> None:
    selected = client or BrokerClient()
    selected.require(
        Operation.OWNERSHIP,
        {"action": "chown", "path": str(path), "owner": owner, "group": group},
        actor=actor,
    )


def filesystem_mkdir(
    path: Path,
    *,
    mode: int = 0o750,
    owner: str = "",
    group: str = "",
    actor: str,
    client: BrokerClient | None = None,
) -> None:
    selected = client or BrokerClient()
    selected.require(
        Operation.OWNERSHIP,
        {"action": "mkdir", "path": str(path), "mode": mode, "owner": owner, "group": group},
        actor=actor,
    )


def filesystem_chmod(
    path: Path,
    mode: int,
    *,
    actor: str,
    client: BrokerClient | None = None,
) -> None:
    selected = client or BrokerClient()
    selected.require(Operation.OWNERSHIP, {"action": "chmod", "path": str(path), "mode": mode}, actor=actor)


def module_hook(
    module_id: str,
    action: str,
    *,
    actor: str,
    client: BrokerClient | None = None,
) -> subprocess.CompletedProcess[str]:
    selected = client or BrokerClient()
    response = selected.request(Operation.MODULE_HOOK, {"module_id": module_id, "action": action}, actor=actor)
    return _completed(["module-hook", module_id, action], response)


def update_service(
    *,
    update_config: bool,
    npm_audit_fix: bool,
    actor: str,
    client: BrokerClient | None = None,
) -> dict[str, Any]:
    selected = client or BrokerClient()
    response = selected.require(
        Operation.UPDATE_SERVICE,
        {"update_config": update_config, "npm_audit_fix": npm_audit_fix},
        actor=actor,
    )
    try:
        payload = json.loads(response.stdout or "{}")
    except json.JSONDecodeError as error:
        raise RuntimeError("privileged update service returned invalid metadata") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("unit"), str):
        raise RuntimeError("privileged update service returned incomplete metadata")
    return payload


def mount_unit_action(
    action: str,
    *,
    mount_id: str,
    mount_point: str,
    remote: str = "",
    fs_type: str = "",
    options: str = "",
    automount: bool = False,
    actor: str,
    client: BrokerClient | None = None,
) -> subprocess.CompletedProcess[str]:
    payload: dict[str, Any] = {
        "action": action,
        "mount_id": mount_id,
        "mount_point": mount_point,
        "remote": remote,
        "fs_type": fs_type,
        "options": options,
        "automount": automount,
    }
    selected = client or BrokerClient()
    response = selected.request(Operation.MOUNT_UNIT, payload, actor=actor)
    return _completed(["mount-unit", action, mount_point], response)


def storage_probe(
    tool: str,
    args: list[str],
    *,
    timeout: float,
    actor: str = "storage-manager",
    client: BrokerClient | None = None,
) -> subprocess.CompletedProcess[str]:
    selected = client or BrokerClient()
    response = selected.request(Operation.STORAGE_PROBE, {"tool": tool, "args": args, "timeout": timeout}, actor=actor)
    return _completed([tool, *args], response)


def broker_command(
    args: list[str],
    *,
    input_text: str | None = None,
    timeout: int | float = 120,
    actor: str = "webnas",
    client: BrokerClient | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """Translate a finite set of legacy argv call sites into typed broker operations.

    Unknown commands deliberately return ``None`` so read-only probes can continue
    locally. Callers must never use this helper as a generic root-exec fallback.
    """

    if not args:
        return None
    tool = Path(args[0]).name
    selected = client or BrokerClient()

    if tool == "systemctl" and len(args) >= 2:
        action = args[1]
        if action in {"poweroff", "reboot"} and len(args) == 2:
            response = selected.request(Operation.POWER, {"action": action}, actor=actor)
            return _completed(args, response)
        if action == "daemon-reload" and len(args) == 2:
            return systemd_action(action, actor=actor, client=selected)
        if action in SYSTEMD_MUTATIONS and len(args) == 3:
            return systemd_action(action, args[2], actor=actor, client=selected)
        return None

    if tool in ACCOUNT_TOOLS:
        response = selected.request(
            Operation.ACCOUNT,
            {"tool": tool, "args": args[1:], "stdin": input_text},
            actor=actor,
        )
        return _completed(args, response)

    if tool == "setquota" and len(args) == 8 and args[1] == "-u" and args[5:7] == ["0", "0"]:
        try:
            soft_blocks = int(args[3])
            hard_blocks = int(args[4])
        except ValueError:
            return None
        response = selected.request(
            Operation.QUOTA,
            {"username": args[2], "soft_blocks": soft_blocks, "hard_blocks": hard_blocks, "mountpoint": args[7]},
            actor=actor,
        )
        return _completed(args, response)

    if tool == "chown" and len(args) == 3:
        owner_group = args[1]
        owner, separator, group = owner_group.partition(":")
        if not separator:
            group = ""
        response = selected.request(
            Operation.OWNERSHIP,
            {"action": "chown", "path": args[2], "owner": owner, "group": group},
            actor=actor,
        )
        return _completed(args, response)

    if tool in PACKAGE_TOOLS:
        # rpm -q is a read-only verification command and does not require the broker.
        if tool == "rpm" and args[1:2] == ["-q"]:
            return None
        response = selected.request(
            Operation.PACKAGE,
            {"tool": tool, "args": args[1:], "timeout": timeout},
            actor=actor,
        )
        return _completed(args, response)

    if tool == "smbpasswd":
        if len(args) == 4 and args[1:3] == ["-s", "-a"] and input_text is not None:
            lines = input_text.splitlines()
            if len(lines) != 2 or lines[0] != lines[1]:
                raise RuntimeError("Samba password confirmation mismatch")
            response = selected.request(
                Operation.SAMBA_ACCOUNT,
                {"action": "set", "username": args[3], "password": lines[0]},
                actor=actor,
            )
            return _completed(args, response)
        if len(args) == 3 and args[1] in {"-e", "-d"}:
            response = selected.request(
                Operation.SAMBA_ACCOUNT,
                {"action": "enable" if args[1] == "-e" else "disable", "username": args[2]},
                actor=actor,
            )
            return _completed(args, response)
        return None

    if tool in {"mount", "umount", "sshfs"}:
        response = selected.request(
            Operation.MOUNT,
            {"tool": tool, "args": args[1:], "timeout": timeout},
            actor=actor,
        )
        return _completed(args, response)

    return None
