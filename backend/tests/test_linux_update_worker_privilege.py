from __future__ import annotations

import subprocess
from pathlib import Path

from app.modules import linux_update_worker
from app.package_center.detached_updates import read_update_state


SESSION_ID = "0123456789abcdef01234567"


def test_unprivileged_security_update_uses_broker_instead_of_direct_apt(monkeypatch, tmp_path: Path) -> None:
    captured: list[list[str]] = []

    class Client:
        def __init__(self, *, timeout: float) -> None:
            assert timeout > 3600

    def broker_runner(args, **kwargs):
        captured.append(args)
        assert kwargs["timeout"] == 3600
        assert kwargs["actor"] == "linux-updates-detached"
        return subprocess.CompletedProcess(args, 0, "openssl upgraded\n", "")

    monkeypatch.setattr(linux_update_worker.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(linux_update_worker.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(linux_update_worker, "_broker_runtime", lambda: (Client, broker_runner))
    monkeypatch.setattr(
        linux_update_worker.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unprivileged update must not execute apt directly")),
    )

    result = linux_update_worker.run_update(
        tmp_path,
        SESSION_ID,
        ["apt-get", "install", "--only-upgrade", "-y", "openssl"],
    )

    assert result == 0
    assert captured == [["apt-get", "install", "-y", "openssl"]]
    state = read_update_state(tmp_path)
    assert state and state["status"] == "completed"
    assert "privileged broker" in (tmp_path / "output.log").read_text(encoding="utf-8")


def test_unprivileged_full_apt_upgrade_is_translated_to_closed_package_list(monkeypatch, tmp_path: Path) -> None:
    captured: list[list[str]] = []

    class Client:
        def __init__(self, *, timeout: float) -> None:
            assert timeout > 3600

    def broker_runner(args, **kwargs):
        captured.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(linux_update_worker.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(linux_update_worker.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(linux_update_worker, "_apt_upgrade_packages", lambda: ["openssl", "curl"])
    monkeypatch.setattr(linux_update_worker, "_broker_runtime", lambda: (Client, broker_runner))

    result = linux_update_worker.run_update(tmp_path, SESSION_ID, ["apt-get", "upgrade", "-y"])

    assert result == 0
    assert captured == [["apt-get", "install", "-y", "openssl", "curl"]]
