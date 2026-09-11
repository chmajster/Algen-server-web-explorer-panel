from __future__ import annotations

import subprocess

import pytest

from app.modules.providers import get_provider
from app.modules.providers.linux_updates_repair import LinuxUpdatesRepairProvider


def test_linux_updates_provider_advertises_repair_action() -> None:
    provider = get_provider("linux-updates")

    assert isinstance(provider, LinuxUpdatesRepairProvider)
    assert "repair_dpkg" in provider.manifest.capabilities.actions


def test_repair_dpkg_runs_exact_recovery_command(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LinuxUpdatesRepairProvider("linux-updates")
    monkeypatch.setattr(provider, "_manager", lambda: "apt-get")
    monkeypatch.setattr(
        "app.modules.providers.linux_updates_repair.shutil.which",
        lambda tool: "/usr/bin/dpkg" if tool == "dpkg" else None,
    )
    monkeypatch.setattr(provider, "_reboot_required", lambda: False)

    calls: list[tuple[list[str], int, dict[str, str]]] = []

    def fake_run(
        args: list[str],
        *,
        timeout: int = 30,
        input_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((args, timeout, env or {}))
        return subprocess.CompletedProcess(args, 0, "configured\n", "")

    monkeypatch.setattr(provider, "_run", fake_run)
    logs: list[tuple[str, str]] = []
    progress: list[tuple[int, str]] = []

    result = provider.manage(
        "repair_dpkg",
        {},
        "tester",
        lambda stream, line: logs.append((stream, line)),
        lambda percent, message: progress.append((percent, message)),
        lambda: False,
    )

    assert calls == [
        (["dpkg", "--configure", "-a"], 3600, {"DEBIAN_FRONTEND": "noninteractive"})
    ]
    assert result["repaired"] is True
    assert result["command"] == "dpkg --configure -a"
    assert result["reboot_required"] is False
    assert ("stdout", "Running dpkg --configure -a") in logs
    assert ("stdout", "configured") in logs
    assert progress[-1][0] == 95


def test_repair_dpkg_rejects_non_apt_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = LinuxUpdatesRepairProvider("linux-updates")
    monkeypatch.setattr(provider, "_manager", lambda: "dnf")

    with pytest.raises(RuntimeError, match="APT-based systems"):
        provider.manage(
            "repair_dpkg",
            {},
            "tester",
            lambda *_: None,
            lambda *_: None,
            lambda: False,
        )
