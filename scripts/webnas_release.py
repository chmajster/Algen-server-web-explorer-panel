#!/usr/bin/env python3.14
"""Blue/green release activation for WebNAS.

The updater runs outside both application processes.  It starts and validates a
candidate on a loopback port, atomically reloads nginx, drains the old slot and
keeps the previous release available for rollback.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import grp
import pwd
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def candidate_python_from_argv(argv: list[str]) -> Path | None:
    """Return the candidate release interpreter without importing backend code."""

    try:
        release_index = argv.index("--release")
        release = Path(argv[release_index + 1]).resolve()
    except (ValueError, IndexError, OSError):
        return None
    candidate_python = release / "backend" / ".venv" / "bin" / "python"
    if not candidate_python.is_file() or not os.access(candidate_python, os.X_OK):
        return None
    return candidate_python


def ensure_candidate_runtime() -> None:
    """Re-exec this helper inside the candidate venv before backend imports."""

    candidate_python = candidate_python_from_argv(sys.argv[1:])
    if candidate_python is None:
        return
    try:
        current_python = Path(sys.executable).resolve()
        expected_python = candidate_python.resolve()
    except OSError:
        current_python = Path(sys.executable)
        expected_python = candidate_python
    if current_python == expected_python:
        return
    os.execv(
        str(candidate_python),
        [str(candidate_python), str(Path(__file__).resolve()), *sys.argv[1:]],
    )


# install-standard.sh may itself run under the host Python.  The release helper
# imports application modules, so it must switch to the candidate virtualenv
# before importing anything from backend/app.
ensure_candidate_runtime()


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.redaction import redact_text  # noqa: E402
from app.transport import TransportSettings, render_nginx_transport  # noqa: E402


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


def tls_identity() -> tuple[str, str]:
    """Return a conservative CN and SAN list for a locally generated certificate."""

    names = {"localhost"}
    for candidate in (socket.gethostname(), socket.getfqdn()):
        candidate = candidate.strip().rstrip(".")
        if candidate and re.fullmatch(r"[A-Za-z0-9.-]{1,253}", candidate):
            names.add(candidate)

    addresses = {"127.0.0.1", "::1"}
    for name in tuple(names):
        try:
            resolved = socket.getaddrinfo(name, None)
        except OSError:
            continue
        for item in resolved:
            raw = str(item[4][0]).split("%", 1)[0]
            try:
                address = ipaddress.ip_address(raw)
            except ValueError:
                continue
            if not address.is_unspecified and not address.is_multicast:
                addresses.add(str(address))

    ordered_names = sorted(names, key=lambda value: (value == "localhost", len(value), value))
    common_name = ordered_names[0] if ordered_names else "localhost"
    sans = [*(f"DNS:{name}" for name in sorted(names)), *(f"IP:{address}" for address in sorted(addresses))]
    return common_name, ",".join(sans)


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
        value.update({"state": "running", "message": message})
        if not isinstance(value.get("steps"), list):
            value["phase"] = phase
        atomic_json(self.update_request, value)

    def update_step(self, step_id: str, status: str, message: str, error: str | None = None) -> None:
        try:
            value = json.loads(self.update_request.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(value, dict) or value.get("state") not in ACTIVE_STATES:
            return
        now = time.time()
        steps = value.get("steps") if isinstance(value.get("steps"), list) else []
        step = next((item for item in steps if isinstance(item, dict) and item.get("id") == step_id), None)
        if step is None:
            return
        step["status"] = status
        step["message"] = message
        step["started_at"] = step.get("started_at") or now
        step["finished_at"] = now if status in {"success", "failed", "skipped"} else None
        step["error"] = redact_text(error or "", limit=4000) if status == "failed" else None
        value.update({"phase": step_id, "message": message, "updated_at": now})
        if status == "failed":
            value.update({"state": "failed", "failed_phase": step_id, "finished_at": now})
        value["progress"] = round(sum(item.get("status") in {"success", "skipped"} for item in steps if isinstance(item, dict)) * 100 / len(steps)) if steps else 0
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
            safe_stderr = redact_text(result.stderr.strip(), limit=1000)
            raise RuntimeError(f"Candidate import/config validation failed: {safe_stderr}")
        self.validate_runtime_paths()

    def validate_runtime_paths(self) -> None:
        paths = {
            "data": Path(config_value(self.config, "paths", "data_dir", "/var/lib/webnas")),
            "logs": Path(config_value(self.config, "paths", "log_dir", "/var/log/webnas")),
        }
        for label, path in paths.items():
            if not path.is_absolute() or path == Path("/"):
                raise RuntimeError(f"Configured {label} path must be a dedicated absolute path: {path}")
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe = path / f".webnas-write-check-{os.getpid()}"
                with probe.open("x", encoding="utf-8") as stream:
                    stream.write("ok\n")
                probe.unlink()
            except OSError as error:
                raise RuntimeError(f"Configured {label} path is not writable: {path}: {error}") from error

    def transport_settings(self) -> TransportSettings:
        defaults = TransportSettings(
            use_https=config_value(self.config, "server", "use_https", "false").lower() == "true",
            tls_cert=config_value(self.config, "server", "tls_cert"),
            tls_key=config_value(self.config, "server", "tls_key"),
        )
        data_dir = Path(config_value(self.config, "paths", "data_dir", "/var/lib/webnas"))
        state_path = data_dir / "settings" / "transport.json"
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return defaults
        if not isinstance(payload, dict):
            return defaults
        try:
            return TransportSettings.model_validate({**defaults.model_dump(), **payload})
        except ValueError:
            return defaults

    def transport_include_path(self) -> Path:
        data_dir = Path(config_value(self.config, "paths", "data_dir", "/var/lib/webnas"))
        return data_dir / "settings" / "nginx-transport.conf"

    def write_transport_include(self) -> None:
        path = self.transport_include_path()
        settings = self.transport_settings()
        atomic_write(path, render_nginx_transport(settings, self.public_port), 0o640)
        try:
            shutil.chown(path.parent, user=self.service_user, group=self.service_user)
            shutil.chown(path, user=self.service_user, group=self.service_user)
        except (LookupError, OSError):
            pass

    def ensure_tls_certificate(self) -> None:
        transport = self.transport_settings()
        if not transport.use_https:
            return
        raw_cert = transport.tls_cert
        raw_key = transport.tls_key
        if not raw_cert or not raw_key:
            if transport.use_https:
                raise RuntimeError("TLS is enabled but server.tls_cert or server.tls_key is not configured")
            return
        cert = Path(raw_cert)
        key = Path(raw_key)
        if cert.is_file() and key.is_file() and cert.stat().st_size > 0 and key.stat().st_size > 0:
            return
        executable = shutil.which("openssl")
        if not executable:
            raise RuntimeError("TLS certificate is missing and the openssl command is unavailable")
        cert.parent.mkdir(parents=True, exist_ok=True)
        key.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(cert.parent, 0o750)
        if key.parent != cert.parent:
            os.chmod(key.parent, 0o750)
        temporary_cert = cert.with_name(f".{cert.name}.{os.getpid()}.tmp")
        temporary_key = key.with_name(f".{key.name}.{os.getpid()}.tmp")
        common_name, sans = tls_identity()
        result = command(
            executable,
            "req",
            "-x509",
            "-newkey",
            "rsa:3072",
            "-sha256",
            "-nodes",
            "-days",
            "825",
            "-subj",
            f"/CN={common_name}",
            "-addext",
            f"subjectAltName={sans}",
            "-addext",
            "keyUsage=digitalSignature,keyEncipherment",
            "-addext",
            "extendedKeyUsage=serverAuth",
            "-keyout",
            str(temporary_key),
            "-out",
            str(temporary_cert),
            check=False,
        )
        if result.returncode:
            temporary_cert.unlink(missing_ok=True)
            temporary_key.unlink(missing_ok=True)
            raise RuntimeError(f"Could not generate the WebNAS TLS certificate: {redact_text(result.stderr, limit=2000)}")
        os.chmod(temporary_key, 0o600)
        os.chmod(temporary_cert, 0o644)
        os.replace(temporary_key, key)
        os.replace(temporary_cert, cert)

    def unit_name(self, slot: str) -> str:
        return f"webnas-backend-{slot}.service"

    def write_units(self) -> None:
        runtime = self.runtime_dir
        runtime.mkdir(parents=True, exist_ok=True)
        data_dir = config_value(self.config, "paths", "data_dir", "/var/lib/webnas")
        log_dir = config_value(self.config, "paths", "log_dir", "/var/log/webnas")
        temp_dir = config_value(self.config, "paths", "temp_dir", "/var/lib/webnas/tmp")
        try:
            grp.getgrnam(self.service_user)
        except KeyError:
            command("groupadd", "--system", self.service_user)
        try:
            pwd.getpwnam(self.service_user)
        except KeyError:
            command("useradd", "--system", "--gid", self.service_user, "--home-dir", data_dir, "--shell", "/usr/sbin/nologin", self.service_user)
        for writable in (Path(data_dir), Path(log_dir), Path(temp_dir)):
            writable.mkdir(parents=True, exist_ok=True)
            command("chown", "-R", f"{self.service_user}:{self.service_user}", str(writable))
        socket_unit = self.systemd_dir / "webnas-privileged.socket"
        broker_unit = self.systemd_dir / "webnas-privileged.service"
        atomic_write(socket_unit, "\n".join([
            "[Unit]", "Description=WebNAS privileged operation broker socket", "",
            "[Socket]", "ListenStream=/run/webnas/privileged.sock", "SocketUser=root", f"SocketGroup={self.service_user}",
            "SocketMode=0660", "DirectoryMode=0750", "RemoveOnStop=true", "",
            "[Install]", "WantedBy=sockets.target", "",
        ]))
        atomic_write(broker_unit, "\n".join([
            "[Unit]", "Description=WebNAS privileged operation broker", "Requires=webnas-privileged.socket",
            "After=webnas-privileged.socket", "", "[Service]", "Type=simple", "User=root", "Group=root",
            f"Environment=PYTHONPATH={self.release / 'backend'}", f"Environment=WEBNAS_CONFIG={self.config}",
            f"ExecStart={self.release / 'backend/.venv/bin/python'} -m app.privileged_broker.server",
            "NoNewPrivileges=false", "PrivateTmp=true", "ProtectSystem=false", "ProtectHome=false",
            "ProtectKernelTunables=true", "ProtectKernelModules=true", "ProtectControlGroups=true", "",
        ]))
        command("systemctl", "daemon-reload")
        command("systemctl", "enable", "--now", "webnas-privileged.socket")
        for slot, port in SLOTS.items():
            env_path = runtime / f"backend-{slot}.env"
            unit = self.systemd_dir / self.unit_name(slot)
            atomic_write(unit, "\n".join([
                "[Unit]",
                f"Description=WebNAS backend ({slot})",
                "After=network-online.target",
                "Wants=network-online.target",
                "Requires=webnas-privileged.socket",
                "After=webnas-privileged.socket",
                "StartLimitIntervalSec=120",
                "StartLimitBurst=4",
                "",
                "[Service]",
                "Type=simple",
                f"EnvironmentFile={env_path}",
                f"Environment=WEBNAS_BIND_PORT={port}",
                "Environment=WEBNAS_BIND_HOST=127.0.0.1",
                "ExecStart=/bin/sh -c 'cd \"$WEBNAS_RELEASE/backend\" && exec \"$WEBNAS_RELEASE/backend/.venv/bin/python\" -m app.run'",
                "Restart=on-failure",
                "RestartSec=30",
                "TimeoutStopSec=30",
                "KillSignal=SIGTERM",
                f"User={self.service_user}",
                f"Group={self.service_user}",
                "Environment=WEBNAS_PRIVILEGED_BROKER=required",
                "NoNewPrivileges=true",
                "PrivateTmp=true",
                # Module installation and updates legitimately write below /etc,
                # /usr and /var through the host package manager.
                "ProtectSystem=false",
                "ProtectHome=false",
                "ProtectKernelTunables=true",
                "ProtectKernelModules=true",
                "ProtectControlGroups=true",
                "RestrictSUIDSGID=true",
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
                last_error = redact_text(error, limit=1000)
            time.sleep(0.25)
        raise RuntimeError(f"Candidate health check failed on port {port}: {last_error}")

    def nginx(self, port: int) -> str:
        include_path = self.transport_include_path()
        return f"""server {{
    include {include_path};
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
        self.write_transport_include()
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
            raise RuntimeError(f"nginx candidate configuration is invalid: {redact_text(validation.stderr.strip(), limit=4000)}")
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
        use_https = self.transport_settings().use_https
        scheme = "https" if use_https else "http"
        context = ssl._create_unverified_context() if use_https else None  # noqa: S323 - validates local handover only.
        last_error = ""
        for _ in range(attempts):
            try:
                with urllib.request.urlopen(f"{scheme}://127.0.0.1:{self.public_port}/api/health", timeout=1, context=context) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError) as error:
                last_error = redact_text(error, limit=1000)
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
                # Cleanup happens only after the candidate is healthy and the
                # public handover has completed. A package installer, virus
                # scanner or another short-lived filesystem user can still
                # race with rmtree and recreate a directory between scans.
                # Retry once, then leave the stale release for a later update;
                # cleanup must never turn a successful activation into a
                # reported deployment failure.
                for attempt in range(2):
                    try:
                        shutil.rmtree(path)
                        break
                    except FileNotFoundError:
                        break
                    except OSError as error:
                        if attempt == 0:
                            time.sleep(0.1)
                            continue
                        print(f"WebNAS release cleanup warning: could not remove {path.name}: {redact_text(error, limit=1000)}", file=sys.stderr)

    def deploy(self) -> None:
        self.update_step("switch_version", "running", "Walidacja i przełączanie na nową wersję.")
        self.update_phase("verifying", "Sprawdzanie wersji kandydującej.")
        self.validate_files()
        self.ensure_tls_certificate()
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
            self.update_step("switch_version", "failed", "Przywrócono poprzednią wersję po błędzie przełączenia.", "Public health check failed; rollback completed")
            raise

        self.update_step("switch_version", "success", "Nowa wersja została atomowo aktywowana.")
        self.update_phase("draining", "Nowa wersja działa; kończenie aktywnych żądań starej wersji.")
        self.update_step("restart_services", "running", "Restartowanie i porządkowanie usług.")
        command("systemctl", "enable", "nginx")
        command("systemctl", "enable", self.unit_name(self.new_slot))
        inactive_slot = "green" if self.new_slot == "blue" else "blue"
        if self.old_slot:
            time.sleep(self.drain_seconds)
        command("systemctl", "stop", self.unit_name(inactive_slot), check=False)
        command("systemctl", "disable", self.unit_name(inactive_slot), check=False)
        command("systemctl", "disable", "webnas.service", check=False)
        self.cleanup_releases()
        self.update_step("restart_services", "success", "Usługi nowej wersji działają.")
        self.update_step("health_check", "running", "Sprawdzanie backendu i frontendu.")
        self.public_health()
        self.update_step("health_check", "success", "Backend i frontend odpowiadają poprawnie.")


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
        safe_error = redact_text(error, limit=4000)
        try:
            value = json.loads(deployment.update_request.read_text(encoding="utf-8"))
            phase = str(value.get("phase") or "switch_version") if isinstance(value, dict) else "switch_version"
            deployment.update_step(phase, "failed", "Aktualizacja wdrożenia nie powiodła się.", safe_error)
        except (OSError, json.JSONDecodeError):
            pass
        print(f"WebNAS release activation failed: {safe_error}", file=sys.stderr)
        return 1
    print(f"Activated WebNAS {deployment.new_slot} release {deployment.release}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
