#!/usr/bin/env python3.14
"""Restore the previous WebNAS blue/green release after a post-deploy failure."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from webnas_release import Deployment, atomic_json, atomic_write, command


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--root", type=Path, required=True)
    value.add_argument("--config", type=Path, required=True)
    value.add_argument("--public-port", type=int, required=True)
    value.add_argument("--service-user", default="webnas")
    value.add_argument("--drain-seconds", type=int, default=0)
    value.add_argument("--systemd-dir", type=Path, default=Path("/etc/systemd/system"))
    value.add_argument("--nginx-config", type=Path, default=Path("/etc/nginx/conf.d/webnas.conf"))
    value.add_argument("--state", type=Path)
    value.add_argument("--update-request", type=Path)
    return value


def main() -> int:
    args = parser().parse_args()
    state_path = args.state or Path("/var/lib/webnas/settings/deployment.json")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"Rollback state is unavailable: {error}", file=sys.stderr)
        return 1

    previous_slot = state.get("previous_slot")
    previous_port = state.get("previous_port")
    previous_release = state.get("previous_release")
    active_slot = state.get("active_slot")
    active_port = state.get("active_port")
    active_release = state.get("active_release")
    if not previous_slot or not previous_port or not previous_release:
        print("Rollback state does not contain a previous release", file=sys.stderr)
        return 1
    previous_path = Path(str(previous_release)).resolve()
    if not previous_path.is_dir():
        print(f"Previous release is missing: {previous_path}", file=sys.stderr)
        return 1

    # Deployment owns the canonical nginx/systemd/current-link operations. The
    # release argument is required by its constructor but is not activated here.
    args.release = Path(str(active_release or previous_release))
    deployment = Deployment(args)
    previous_unit = deployment.unit_name(str(previous_slot))
    active_unit = deployment.unit_name(str(active_slot)) if active_slot else ""

    deployment.write_units()
    command("systemctl", "enable", previous_unit)
    command("systemctl", "start", previous_unit)
    deployment.health(int(previous_port))
    deployment.activate_nginx(int(previous_port))
    deployment.switch_current(previous_path)
    atomic_write(deployment.runtime_dir / "active-slot", f"{previous_slot}\n", 0o644)
    if active_unit and active_unit != previous_unit:
        command("systemctl", "stop", active_unit, check=False)
        command("systemctl", "disable", active_unit, check=False)

    atomic_json(state_path, {
        "active_slot": previous_slot,
        "active_port": int(previous_port),
        "active_release": str(previous_path),
        "previous_slot": active_slot,
        "previous_port": active_port,
        "previous_release": active_release,
        "switched_at": time.time(),
        "rollback": True,
    })
    deployment.public_health()
    print(f"Rolled back WebNAS to {previous_slot} release {previous_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
