from __future__ import annotations

import subprocess

from app.modules import linux_update_worker
from app.modules.providers.linux_updates_repair import LinuxUpdatesRepairProvider


def test_linux_updates_apt_listing_uses_upgrade_simulation(monkeypatch) -> None:
    provider = LinuxUpdatesRepairProvider("linux-updates")
    monkeypatch.setattr(provider, "_manager", lambda: "apt-get")
    calls: list[list[str]] = []

    def fake_run(args: list[str], *, timeout: int = 30, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args,
            0,
            "Inst openssl [1.0] (1.1 Debian-Security:stable-security [amd64])\n",
            "",
        )

    monkeypatch.setattr(provider, "_run", fake_run)

    packages = provider._packages()

    assert calls == [["apt-get", "-s", "-o", "Debug::NoLocking=1", "upgrade"]]
    assert [item["name"] for item in packages] == ["openssl"]
    assert packages[0]["security"] is True


def test_privileged_apt_upgrade_translation_uses_upgrade_simulation(monkeypatch) -> None:
    calls: list[tuple[list[str], set[int]]] = []

    def fake_probe(command: list[str], *, accepted_codes: set[int]):
        calls.append((command, accepted_codes))
        return subprocess.CompletedProcess(
            command,
            0,
            "Inst openssl [1.0] (1.1 Debian-Security:stable-security [amd64])\n",
            "",
        )

    monkeypatch.setattr(linux_update_worker, "_probe", fake_probe)

    packages = linux_update_worker._apt_upgrade_packages()

    assert calls == [
        (["apt-get", "-s", "-o", "Debug::NoLocking=1", "upgrade"], {0})
    ]
    assert packages == ["openssl"]
