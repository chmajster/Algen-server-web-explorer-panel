from __future__ import annotations

import importlib.util
import json
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
    config.write_text("server:\n  port: 5000\n  use_https: false\n", encoding="utf-8")
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
