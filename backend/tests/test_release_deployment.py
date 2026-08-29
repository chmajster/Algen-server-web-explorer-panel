from __future__ import annotations

import importlib.util
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("webnas_release", REPOSITORY / "scripts" / "webnas_release.py")
assert SPEC and SPEC.loader
release_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_module)
Deployment = release_module.Deployment


def deployment(tmp_path: Path, *, active: bool = True):
    root = tmp_path / "webnas"
    release = root / "releases" / "new"
    release.mkdir(parents=True)
    config = tmp_path / "config.yaml"
    data_dir = tmp_path / "data"
    log_dir = tmp_path / "log"
    temp_dir = tmp_path / "tmp"
    config.write_text(
        "server:\n"
        "  port: 5000\n"
        "  use_https: false\n"
        "paths:\n"
        f"  data_dir: {data_dir}\n"
        f"  log_dir: {log_dir}\n"
        f"  temp_dir: {temp_dir}\n",
        encoding="utf-8",
    )
    state = tmp_path / "deployment.json"
    old_release = root / "releases" / "old"
    old_release.mkdir()
    if active:
        state.write_text(json.dumps({
            "active_slot": "blue",
            "active_port": 15101,
            "active_release": str(old_release),
        }), encoding="utf-8")
    args = SimpleNamespace(
        root=root,
        release=release,
        config=config,
        public_port=5000,
        service_user="webnas",
        drain_seconds=0,
        systemd_dir=tmp_path / "systemd",
        nginx_config=tmp_path / "nginx" / "webnas.conf",
        state=state,
        update_request=tmp_path / "update_request.json",
    )
    return Deployment(args)


def completed(returncode: int = 0):
    return SimpleNamespace(returncode=returncode, stdout="", stderr="")


def test_generated_and_legacy_services_retry_three_times_every_thirty_seconds(monkeypatch, tmp_path: Path):
    target = deployment(tmp_path)
    monkeypatch.setattr(release_module, "command", lambda *args, **kwargs: completed())

    target.write_units()

    units = [
        (target.systemd_dir / target.unit_name(slot)).read_text(encoding="utf-8")
        for slot in release_module.SLOTS
    ]
    units.append((REPOSITORY / "packaging" / "webnas.service").read_text(encoding="utf-8"))
    for unit in units:
        assert "Restart=on-failure" in unit
        assert "RestartSec=30" in unit
        assert "StartLimitIntervalSec=120" in unit
        # systemd includes the initial start in the burst count: 1 + 3 retries.
        assert "StartLimitBurst=4" in unit


def test_generated_services_allow_package_manager_writes(monkeypatch, tmp_path: Path):
    target = deployment(tmp_path)
    monkeypatch.setattr(release_module, "command", lambda *args, **kwargs: completed())

    target.write_units()

    for slot in release_module.SLOTS:
        unit = (target.systemd_dir / target.unit_name(slot)).read_text(encoding="utf-8")
        assert "ProtectSystem=false" in unit
        assert "ProtectSystem=full" not in unit


def test_blue_green_handover_validates_before_switch_and_drains_after_public_health(monkeypatch, tmp_path: Path):
    target = deployment(tmp_path)
    events: list[str] = []
    monkeypatch.setattr(target, "validate_files", lambda: events.append("validate-files"))
    monkeypatch.setattr(target, "write_units", lambda: events.append("write-units"))
    monkeypatch.setattr(target, "write_slot_environment", lambda: events.append("write-env"))
    monkeypatch.setattr(target, "health", lambda port: events.append(f"candidate-health:{port}"))
    monkeypatch.setattr(target, "activate_nginx", lambda port: events.append(f"gateway:{port}"))
    monkeypatch.setattr(target, "switch_current", lambda release: events.append(f"current:{release.name}"))
    monkeypatch.setattr(target, "public_health", lambda: events.append("public-health"))
    monkeypatch.setattr(target, "cleanup_releases", lambda: events.append("cleanup"))
    monkeypatch.setattr(target, "update_phase", lambda phase, message: events.append(f"phase:{phase}"))
    monkeypatch.setattr(release_module, "atomic_write", lambda *args, **kwargs: None)
    monkeypatch.setattr(release_module, "atomic_json", lambda *args, **kwargs: None)

    def run(*args, **kwargs):
        if args[:3] == ("systemctl", "stop", "webnas-backend-blue.service"):
            events.append("stop-old")
        return completed()

    monkeypatch.setattr(release_module, "command", run)
    target.deploy()

    assert events.index("candidate-health:15102") < events.index("gateway:15102")
    assert events.index("gateway:15102") < events.index("public-health")
    assert events.index("public-health") < events.index("stop-old")
    assert "phase:switching" in events
    assert "phase:draining" in events


def test_failed_candidate_health_never_switches_gateway_and_removes_candidate(monkeypatch, tmp_path: Path):
    target = deployment(tmp_path)
    switched: list[int] = []
    monkeypatch.setattr(target, "validate_files", lambda: None)
    monkeypatch.setattr(target, "write_units", lambda: None)
    monkeypatch.setattr(target, "write_slot_environment", lambda: None)
    monkeypatch.setattr(target, "health", lambda port: (_ for _ in ()).throw(RuntimeError("candidate failed")))
    monkeypatch.setattr(target, "activate_nginx", lambda port: switched.append(port))
    monkeypatch.setattr(target, "update_phase", lambda *args: None)
    monkeypatch.setattr(release_module, "command", lambda *args, **kwargs: completed())

    with pytest.raises(RuntimeError, match="candidate failed"):
        target.deploy()

    assert switched == []
    assert not target.release.exists()


def test_runtime_paths_are_writable_before_candidate_activation(tmp_path: Path):
    target = deployment(tmp_path)
    data = tmp_path / "state"
    logs = tmp_path / "logs"
    target.config.write_text(f"paths:\n  data_dir: {data}\n  log_dir: {logs}\n", encoding="utf-8")

    target.validate_runtime_paths()

    assert data.is_dir()
    assert logs.is_dir()
    assert not list(data.glob(".webnas-write-check-*"))


def test_plaintext_gateway_is_supported_by_default(tmp_path: Path):
    target = deployment(tmp_path)
    target.config.write_text(
        "server:\n  use_https: false\nsecurity:\n  allow_insecure_http: false\n",
        encoding="utf-8",
    )

    settings = target.transport_settings()
    directives = release_module.render_nginx_transport(settings, target.public_port)

    assert settings.use_https is False
    assert "listen 5000;" in directives
    assert " ssl" not in directives


def test_transport_override_can_enable_https(tmp_path: Path):
    target = deployment(tmp_path)
    cert = tmp_path / "webnas.crt"
    key = tmp_path / "webnas.key"
    cert.write_text("certificate", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    state = tmp_path / "data" / "settings" / "transport.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"use_https": True, "tls_cert": str(cert), "tls_key": str(key)}), encoding="utf-8")

    settings = target.transport_settings()
    directives = release_module.render_nginx_transport(settings, target.public_port)

    assert settings.use_https is True
    assert "listen 5000 ssl;" in directives
    assert f"ssl_certificate {cert};" in directives


def test_tls_gateway_requires_and_uses_configured_certificate(tmp_path: Path):
    target = deployment(tmp_path)
    cert = tmp_path / "webnas.crt"
    key = tmp_path / "webnas.key"
    cert.write_text("certificate", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    target.config.write_text(
        f"server:\n  use_https: true\n  tls_cert: {cert}\n  tls_key: {key}\nsecurity:\n  allow_insecure_http: false\n",
        encoding="utf-8",
    )

    settings = target.transport_settings()
    nginx = release_module.render_nginx_transport(settings, target.public_port)

    assert "listen 5000 ssl;" in nginx
    assert f"ssl_certificate {cert};" in nginx
    assert f"ssl_certificate_key {key};" in nginx


def test_tls_certificate_is_bootstrapped_atomically(monkeypatch, tmp_path: Path):
    target = deployment(tmp_path)
    cert = tmp_path / "tls" / "webnas.crt"
    key = tmp_path / "tls" / "webnas.key"
    target.config.write_text(
        f"server:\n  use_https: true\n  tls_cert: {cert}\n  tls_key: {key}\nsecurity:\n  allow_insecure_http: false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_module.shutil, "which", lambda name: "/usr/bin/openssl" if name == "openssl" else None)

    def fake_command(*args, **kwargs):
        keyout = Path(args[args.index("-keyout") + 1])
        certout = Path(args[args.index("-out") + 1])
        keyout.write_text("private-key", encoding="utf-8")
        certout.write_text("certificate", encoding="utf-8")
        return completed()

    monkeypatch.setattr(release_module, "command", fake_command)

    target.ensure_tls_certificate()

    assert cert.read_text(encoding="utf-8") == "certificate"
    assert key.read_text(encoding="utf-8") == "private-key"
    assert os.stat(cert).st_mode & 0o777 == 0o644
    assert os.stat(key).st_mode & 0o777 == 0o600


def test_http_transport_does_not_require_openssl(monkeypatch, tmp_path: Path):
    target = deployment(tmp_path)
    cert = tmp_path / "tls" / "webnas.crt"
    key = tmp_path / "tls" / "webnas.key"
    target.config.write_text(
        f"server:\n  use_https: false\n  tls_cert: {cert}\n  tls_key: {key}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_module.shutil, "which", lambda _name: None)

    target.ensure_tls_certificate()

    assert not cert.exists()
    assert not key.exists()


def test_tls_bootstrap_reports_missing_openssl(monkeypatch, tmp_path: Path):
    target = deployment(tmp_path)
    cert = tmp_path / "tls" / "webnas.crt"
    key = tmp_path / "tls" / "webnas.key"
    target.config.write_text(
        f"server:\n  use_https: true\n  tls_cert: {cert}\n  tls_key: {key}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(release_module.shutil, "which", lambda _name: None)

    with pytest.raises(RuntimeError, match="openssl"):
        target.ensure_tls_certificate()


def test_release_update_errors_use_shared_redaction(tmp_path: Path):
    target = deployment(tmp_path)
    target.update_request.write_text(
        json.dumps(
            {
                "state": "running",
                "steps": [
                    {
                        "id": "switch_version",
                        "status": "pending",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    target.update_step(
        "switch_version",
        "failed",
        "failed",
        "password=deploy-secret Authorization: Bearer bearer-secret",
    )

    payload = json.loads(target.update_request.read_text(encoding="utf-8"))
    error = payload["steps"][0]["error"]
    assert "deploy-secret" not in error
    assert "bearer-secret" not in error
    assert "password=[REDACTED]" in error
    assert "Authorization: [REDACTED]" in error


def test_handover_stops_stale_inactive_slot_without_deployment_state(monkeypatch, tmp_path: Path):
    target = deployment(tmp_path, active=False)
    stopped: list[str] = []
    monkeypatch.setattr(target, "validate_files", lambda: None)
    monkeypatch.setattr(target, "write_units", lambda: None)
    monkeypatch.setattr(target, "write_slot_environment", lambda: None)
    monkeypatch.setattr(target, "health", lambda port: None)
    monkeypatch.setattr(target, "activate_nginx", lambda port: None)
    monkeypatch.setattr(target, "switch_current", lambda release: None)
    monkeypatch.setattr(target, "public_health", lambda: None)
    monkeypatch.setattr(target, "cleanup_releases", lambda: None)
    monkeypatch.setattr(target, "update_phase", lambda *args: None)
    monkeypatch.setattr(release_module, "atomic_write", lambda *args, **kwargs: None)
    monkeypatch.setattr(release_module, "atomic_json", lambda *args, **kwargs: None)

    def run(*args, **kwargs):
        if args[:2] == ("systemctl", "stop"):
            stopped.append(args[2])
        return completed()

    monkeypatch.setattr(release_module, "command", run)
    target.deploy()

    assert "webnas-backend-green.service" in stopped


def test_failed_public_health_rolls_back_gateway_symlink_and_slot(monkeypatch, tmp_path: Path):
    target = deployment(tmp_path)
    gateways: list[int] = []
    links: list[str] = []
    monkeypatch.setattr(target, "validate_files", lambda: None)
    monkeypatch.setattr(target, "write_units", lambda: None)
    monkeypatch.setattr(target, "write_slot_environment", lambda: None)
    monkeypatch.setattr(target, "health", lambda port: None)
    monkeypatch.setattr(target, "activate_nginx", lambda port: gateways.append(port))
    monkeypatch.setattr(target, "switch_current", lambda release: links.append(release.name))
    monkeypatch.setattr(target, "public_health", lambda: (_ for _ in ()).throw(RuntimeError("public failed")))
    monkeypatch.setattr(target, "update_phase", lambda *args: None)
    monkeypatch.setattr(release_module, "atomic_write", lambda *args, **kwargs: None)
    monkeypatch.setattr(release_module, "atomic_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(release_module, "command", lambda *args, **kwargs: completed())

    with pytest.raises(RuntimeError, match="public failed"):
        target.deploy()

    assert gateways == [15102, 15101]
    assert links == ["new", "old"]


def test_stale_release_cleanup_failure_does_not_fail_activation(monkeypatch, tmp_path: Path, capsys):
    target = deployment(tmp_path)
    stale = target.releases / "stale"
    package = stale / "backend" / ".venv" / "lib" / "python3.14" / "site-packages" / "starlette"
    package.mkdir(parents=True)
    package.joinpath("__init__.py").write_text("", encoding="utf-8")
    real_rmtree = release_module.shutil.rmtree
    attempts = 0

    def busy_rmtree(path, *args, **kwargs):
        nonlocal attempts
        if Path(path) == stale:
            attempts += 1
            raise OSError(39, "Directory not empty", str(package))
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(release_module.shutil, "rmtree", busy_rmtree)
    monkeypatch.setattr(release_module.time, "sleep", lambda _: None)

    target.cleanup_releases()

    assert attempts == 2
    assert stale.exists()
    assert "release cleanup warning" in capsys.readouterr().err


def test_public_health_remains_available_during_simulated_build_and_handover():
    class Health(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    failures: list[str] = []
    stop = threading.Event()

    def probe() -> None:
        while not stop.is_set():
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/api/health", timeout=0.2) as response:
                    if response.status != 200:
                        failures.append(str(response.status))
            except OSError as error:
                failures.append(str(error))
            stop.wait(0.25)

    monitor = threading.Thread(target=probe, daemon=True)
    monitor.start()
    # Represents source download, dependency installation, build, candidate
    # healthcheck and atomic gateway reload.  The stable listener is untouched.
    time.sleep(0.8)
    stop.set()
    monitor.join(timeout=1)
    server.shutdown()
    server.server_close()

    assert failures == []
