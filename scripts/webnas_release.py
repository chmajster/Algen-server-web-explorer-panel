#!/usr/bin/env python3
"""Blue/green release activation for WebNAS.

The updater runs outside both application processes.  It starts and validates a
candidate on a loopback port, atomically reloads nginx, drains the old slot and
keeps the previous release available for rollback.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


SLOTS = {"blue": 15101, "green": 15102}
ACTIVE_STATES = {"preparing", "running"}


def atomic_write(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2), 0o600)


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=60, check=check)


def config_value(config: Path, section: str, key: str, default: str = "") -> str:
    current = ""
    for raw in config.read_text(encoding="utf-8").splitlines():
        if raw and not raw[0].isspace() and raw.rstrip().endswith(":"):
            current = raw.rstrip()[:-1]
            continue
        match = re.match(r"^\s+([A-Za-z0-9_]+):\s*(.*?)\s*$", raw)
        if current == section and match and match.group(1) == key:
            value = match.group(2).split(" #", 1)[0].strip().strip("\"'")
            return "" if value in {"null", "None", "~"} else value
    return default


class Deployment:
    def __init__(self, args: argparse.Namespace) -> None:
        self.root = args.root.resolve()
        self.release = args.release.resolve()
        self.config = args.config.resolve()
        self.public_port = args.public_port
        self.service_user = args.service_user
        self.drain_seconds = args.drain_seconds
        self.systemd_dir = args.systemd_dir.resolve()
        self.nginx_config = args.nginx_config.resolve()
        data_dir = Path(config_value(self.config, "paths", "data_dir", "/var/lib/webnas"))
        self.state_path = (args.state or data_dir / "settings" / "deployment.json").resolve()
        self.update_request = (args.update_request or data_dir / "settings" / "update_request.json").resolve()
        self.runtime_dir = self.config.parent / "runtime"
        self.current_link = self.root / "current"
        self.releases = self.root / "releases"
        self.previous_state = self.read_state()
        self.old_slot = str(self.previous_state.get("active_slot") or "")
        self.new_slot = "green" if self.old_slot == "blue" else "blue"
        self.old_release = str(self.previous_state.get("active_release") or "")
        self.old_port = int(self.previous_state.get("active_port") or 0)
        self.new_port = SLOTS[self.new_slot]
        self.legacy_was_active = False

    def read_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def update_phase(self, phase: str, message: str) -> None:
        try:
            value = json.loads(self.update_request.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(value, dict) or value.get("state") not in ACTIVE_STATES:
            return
        value.update({"state": "running", "phase": phase, "message": message})
        atomic_json(self.update_request, value)

    def validate_files(self) -> None:
        required = [
            self.release / "backend" / ".venv" / "bin" / "python",
            self.release / "backend" / "app" / "main.py",
            self.release / "frontend" / "dist" / "index.html",
            self.release / "scripts" / "verify_frontend_build.py",
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(f"Candidate release is incomplete: {missing[0]}")
        if not os.access(required[0], os.X_OK):
            raise RuntimeError("Candidate Python runtime is not executable")
        command(str(required[0]), str(required[3]), str(self.release / "frontend" / "dist"))
        environment = {
            **os.environ,
            "PYTHONPATH": str(self.release / "backend"),
            "WEBNAS_CONFIG": str(self.config),
            "WEBNAS_CANDIDATE": "1",
        }
        result = subprocess.run(
            [str(required[0]), "-c", "from app.config import get_config; import app.main; get_config()"],
            cwd=self.release / "backend",
            env=environment,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(f"Candidate import/config validation failed: {result.stderr.strip()[-1000:]}")

    def unit_name(self, slot: str) -> str:
        return f"webnas-backend-{slot}.service"

    def write_units(self) -> None:
        runtime = self.runtime_dir
        runtime.mkdir(parents=True, exist_ok=True)
        data_dir = config_value(self.config, "paths", "data_dir", "/var/lib/webnas")
        log_dir = config_value(self.config, "paths", "log_dir", "/var/log/webnas")
        for slot, port in SLOTS.items():
            env_path = runtime / f"backend-{slot}.env"
            unit = self.systemd_dir / self.unit_name(slot)
            atomic_write(unit, "\n".join([
                "[Unit]",
                f"Description=WebNAS backend ({slot})",
                "After=network-online.target",
                "Wants=network-online.target",
                "",
                "[Service]",
                "Type=simple",
                f"EnvironmentFile={env_path}",
                f"Environment=WEBNAS_BIND_PORT={port}",
                "Environment=WEBNAS_BIND_HOST=127.0.0.1",
                "ExecStart=/bin/sh -c 'cd \"$WEBNAS_RELEASE/backend\" && exec \"$WEBNAS_RELEASE/backend/.venv/bin/python\" -m app.run'",
                "Restart=on-failure",
                "RestartSec=2",
                "TimeoutStopSec=30",
                "KillSignal=SIGTERM",
                "User=root",
                "Group=root",
                "NoNewPrivileges=false",
                "PrivateTmp=true",
                "ProtectSystem=full",
                "ProtectHome=false",
                "ProtectKernelTunables=true",
                "ProtectKernelModules=true",
                "ProtectControlGroups=true",
                "RestrictSUIDSGID=false",
                "LockPersonality=true",
                f"ReadWritePaths={data_dir} {log_dir} /home /mnt/webnas {self.root}",
                "",
                "[Install]",
                "WantedBy=multi-user.target",
                "",
            ]))
        command("systemctl", "daemon-reload")

    def write_slot_environment(self) -> None:
        environment = "\n".join([
            f"WEBNAS_RELEASE={self.release}",
            f"PYTHONPATH={self.release / 'backend'}",
            f"WEBNAS_CONFIG={self.config}",
            "WEBNAS_CANDIDATE=1",
            f"WEBNAS_SLOT={self.new_slot}",
            f"WEBNAS_ACTIVE_SLOT_FILE={self.runtime_dir / 'active-slot'}",
            "",
        ])
        atomic_write(self.runtime_dir / f"backend-{self.new_slot}.env", environment, 0o600)

    def health(self, port: int, attempts: int = 40) -> None:
        last_error = ""
        for _ in range(attempts):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.0) as response:
                    if response.status == 200 and json.loads(response.read()).get("status") == "ok":
                        return
            except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
                last_error = str(error)
            time.sleep(0.25)
        raise RuntimeError(f"Candidate health check failed on port {port}: {last_error}")

    def nginx(self, port: int) -> str:
        use_https = config_value(self.config, "server", "use_https", "false").lower() == "true"
        tls_cert = config_value(self.config, "server", "tls_cert")
        tls_key = config_value(self.config, "server", "tls_key")
        listen = f"listen {self.public_port}{' ssl' if use_https else ''};"
        tls = ""
        if use_https:
            if not tls_cert or not tls_key or not Path(tls_cert).is_file() or not Path(tls_key).is_file():
                raise RuntimeError("TLS is enabled but its certificate or key is unavailable")
            tls = f"\n    ssl_certificate {tls_cert};\n    ssl_certificate_key {tls_key};"
        return f"""server {{
    {listen}{tls}
    client_max_body_size 0;
    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }}
}}
"""

    def activate_nginx(self, port: int) -> None:
        candidate = self.nginx_config.with_suffix(".candidate")
        previous = self.nginx_config.with_suffix(".previous")
        atomic_write(candidate, self.nginx(port))
        previous.unlink(missing_ok=True)
        if self.nginx_config.exists():
            shutil.copy2(self.nginx_config, previous)
        os.replace(candidate, self.nginx_config)
        validation = command("nginx", "-t", "-c", "/etc/nginx/nginx.conf", check=False)
        if validation.returncode:
            if previous.exists():
                os.replace(previous, self.nginx_config)
            else:
                self.nginx_config.unlink(missing_ok=True)
            raise RuntimeError(f"nginx candidate configuration is invalid: {validation.stderr.strip()}")
        previous.unlink(missing_ok=True)
        result = command("systemctl", "reload", "nginx", check=False)
        if result.returncode:
            command("systemctl", "restart", "nginx")

    def switch_current(self, target: Path) -> None:
        temporary = self.root / ".current.next"
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(target)
        os.replace(temporary, self.current_link)

    def public_health(self, attempts: int = 20) -> None:
        use_https = config_value(self.config, "server", "use_https", "false").lower() == "true"
        scheme = "https" if use_https else "http"
        context = ssl._create_unverified_context() if use_https else None  # noqa: S323 - validates local handover only.
        last_error = ""
        for _ in range(attempts):
            try:
                with urllib.request.urlopen(f"{scheme}://127.0.0.1:{self.public_port}/api/health", timeout=1, context=context) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError) as error:
                last_error = str(error)
            time.sleep(0.25)
        raise RuntimeError(f"Public health check failed after handover: {last_error}")

    def rollback(self) -> None:
        if not self.old_slot or not self.old_port or not self.old_release:
            if self.legacy_was_active:
                command("systemctl", "stop", "nginx", check=False)
                command("systemctl", "start", "webnas.service", check=False)
            return
        self.activate_nginx(self.old_port)
        self.switch_current(Path(self.old_release))
        atomic_write(self.runtime_dir / "active-slot", f"{self.old_slot}\n", 0o644)
        command("systemctl", "stop", self.unit_name(self.new_slot), check=False)
        atomic_json(self.state_path, self.previous_state)

    def cleanup_releases(self) -> None:
        keep = {self.release.resolve()}
        if self.old_release:
            keep.add(Path(self.old_release).resolve())
        candidates = sorted((path for path in self.releases.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in candidates:
            if path.resolve() not in keep and len(keep) >= 2:
                shutil.rmtree(path)

    def deploy(self) -> None:
        self.update_phase("verifying", "Sprawdzanie wersji kandydującej.")
        self.validate_files()
        self.write_units()
        self.write_slot_environment()
        command("systemctl", "restart", self.unit_name(self.new_slot))
        try:
            self.health(self.new_port)
        except Exception:
            command("systemctl", "stop", self.unit_name(self.new_slot), check=False)
            if self.release.is_relative_to(self.releases):
                shutil.rmtree(self.release, ignore_errors=True)
            raise

        self.update_phase("switching", "Przełączanie na nową wersję.")
        self.legacy_was_active = command("systemctl", "is-active", "--quiet", "webnas.service", check=False).returncode == 0
        if self.legacy_was_active and not self.old_slot:
            # One-time migration: the legacy process owns the public port.  It
            # is stopped only after the candidate has passed every check.
            command("systemctl", "stop", "webnas.service")
        try:
            self.activate_nginx(self.new_port)
            self.switch_current(self.release)
            atomic_write(self.runtime_dir / "active-slot", f"{self.new_slot}\n", 0o644)
            state = {
                "active_slot": self.new_slot,
                "active_port": self.new_port,
                "active_release": str(self.release),
                "previous_slot": self.old_slot or None,
                "previous_port": self.old_port or None,
                "previous_release": self.old_release or None,
                "switched_at": time.time(),
            }
            atomic_json(self.state_path, state)
            self.public_health()
        except Exception:
            self.rollback()
            raise

        self.update_phase("draining", "Nowa wersja działa; kończenie aktywnych żądań starej wersji.")
        command("systemctl", "enable", "nginx")
        command("systemctl", "enable", self.unit_name(self.new_slot))
        if self.old_slot:
            time.sleep(self.drain_seconds)
            command("systemctl", "stop", self.unit_name(self.old_slot), check=False)
            command("systemctl", "disable", self.unit_name(self.old_slot), check=False)
        command("systemctl", "disable", "webnas.service", check=False)
        self.cleanup_releases()
        self.update_phase("verifying", "Weryfikacja wdrożonej wersji zakończona.")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--root", type=Path, required=True)
    value.add_argument("--release", type=Path, required=True)
    value.add_argument("--config", type=Path, required=True)
    value.add_argument("--public-port", type=int, required=True)
    value.add_argument("--service-user", default="webnas")
    value.add_argument("--drain-seconds", type=int, default=10)
    value.add_argument("--systemd-dir", type=Path, default=Path("/etc/systemd/system"))
    value.add_argument("--nginx-config", type=Path, default=Path("/etc/nginx/conf.d/webnas.conf"))
    value.add_argument("--state", type=Path)
    value.add_argument("--update-request", type=Path)
    return value


def main() -> int:
    deployment = Deployment(parser().parse_args())
    try:
        deployment.deploy()
    except Exception as error:  # noqa: BLE001 - updater must emit one durable failure reason.
        print(f"WebNAS release activation failed: {error}", file=sys.stderr)
        return 1
    print(f"Activated WebNAS {deployment.new_slot} release {deployment.release}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
