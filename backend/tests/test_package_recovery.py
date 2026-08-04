from __future__ import annotations

from pathlib import Path

from app.package_center import executor


def test_systemctl_disable_read_only_does_not_abort_uninstall(monkeypatch):
    calls: list[list[str]] = []
    logs: list[tuple[str, str]] = []

    def fake_run(args: list[str], timeout: int, log) -> None:
        calls.append(args)
        raise executor.CommandExecutionError(
            "systemctl",
            1,
            "update-rc.d: error: Read-only file system",
        )

    monkeypatch.setattr(executor, "_run", fake_run)

    executor._run_systemctl_command(
        ["systemctl", "disable", "smbd"],
        120,
        lambda stream, line: logs.append((stream, line)),
    )

    assert calls == [["systemctl", "disable", "smbd"]]
    assert any("package removal will continue" in line for _, line in logs)


def test_bad_cifs_state_is_reinstalled_before_removal(monkeypatch):
    original = ["apt-get", "remove", "-y", "samba", "smbclient", "cifs-utils"]
    calls: list[list[str]] = []
    logs: list[tuple[str, str]] = []

    failure = (
        "dpkg: error processing package cifs-utils (--remove):\n"
        " package is in a very bad inconsistent state; you should\n"
        " reinstall it before attempting a removal"
    )

    def fake_run(args: list[str], timeout: int, log) -> None:
        calls.append(list(args))
        if len(calls) == 1:
            raise executor.CommandExecutionError("apt-get", 100, failure)

    monkeypatch.setattr(executor, "_run", fake_run)

    executor._run_apt_with_cifs_recovery(
        original,
        1800,
        lambda stream, line: logs.append((stream, line)),
    )

    assert calls == [
        original,
        [
            "apt-get",
            "install", "-y", "--reinstall", "--no-install-recommends",
            "cifs-utils",
        ],
        original,
    ]
    assert any("reinstalling the affected package" in line for _, line in logs)
    assert any("retrying the original removal" in line for _, line in logs)


def test_bad_state_recovery_does_not_reinstall_unrequested_package():
    output = (
        "dpkg: error processing package unrelated (--remove):\n"
        " package is in a very bad inconsistent state; you should\n"
        " reinstall it before attempting a removal"
    )

    result = executor._bad_state_removal_packages(
        ["apt-get", "remove", "-y", "cifs-utils"],
        output,
    )

    assert result == []


def test_system_mutation_uses_transient_admin_unit(monkeypatch):
    executables = {
        "systemd-run": "/usr/bin/systemd-run",
        "apt-get": "/usr/bin/apt-get",
    }
    monkeypatch.setattr(executor.shutil, "which", executables.get)
    original_exists = Path.exists
    monkeypatch.setattr(
        Path,
        "exists",
        lambda self: True if str(self) == "/run/systemd/system" else original_exists(self),
    )

    result = executor._transient_admin_command(
        ["apt-get", "remove", "-y", "cifs-utils"],
        1800,
    )

    assert result[0] == "/usr/bin/systemd-run"
    assert "--property=ProtectSystem=false" in result
    assert "--property=PrivateTmp=false" in result
    assert result[-4:] == ["/usr/bin/apt-get", "remove", "-y", "cifs-utils"]
