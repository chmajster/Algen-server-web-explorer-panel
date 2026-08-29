from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .client import BrokerClient
from .protocol import Operation


BROKER_MODE_ENV = "WEBNAS_PRIVILEGED_BROKER"


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
