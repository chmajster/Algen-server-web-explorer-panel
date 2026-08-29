from __future__ import annotations

import subprocess
from pathlib import Path

from app.modules.dhcp.broker import BrokerDhcpService, BrokerDhcpSystem
from app.modules.dhcp.models import DhcpBackend


def test_dhcp_service_action_uses_broker_when_required(monkeypatch) -> None:
    monkeypatch.setenv("WEBNAS_PRIVILEGED_BROKER", "required")
    system = BrokerDhcpSystem()
    monkeypatch.setattr(system, "selected_service", lambda _backend: "kea-dhcp4-server")
    calls: list[tuple[str, str, str]] = []

    def broker(action: str, unit: str, *, actor: str):
        calls.append((action, unit, actor))
        return subprocess.CompletedProcess(["systemctl", action, unit], 0, "", "")

    monkeypatch.setattr("app.modules.dhcp.broker.systemd_action", broker)

    result = system.service_action(DhcpBackend.kea, "restart")

    assert result.returncode == 0
    assert calls == [("restart", "kea-dhcp4-server", "dhcp-manager")]


def test_dhcp_managed_config_write_uses_symbolic_broker_target(monkeypatch) -> None:
    monkeypatch.setenv("WEBNAS_PRIVILEGED_BROKER", "required")
    calls: list[tuple[str, str, str, int]] = []

    def broker(target: str, content: str, *, actor: str, mode: int):
        calls.append((target, content, actor, mode))

    monkeypatch.setattr("app.modules.dhcp.broker.managed_file_write", broker)

    BrokerDhcpService._atomic_write(
        Path("/etc/kea/kea-dhcp4.conf"),
        b'{"Dhcp4": {}}\n',
        default_mode=0o644,
    )

    assert len(calls) == 1
    assert calls[0][0] == "dhcp_kea"
    assert calls[0][1] == '{"Dhcp4": {}}\n'
    assert calls[0][2] == "dhcp-manager"
    assert calls[0][3] in {0o600, 0o640, 0o644}


def test_dhcp_state_file_stays_unprivileged(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEBNAS_PRIVILEGED_BROKER", "required")
    monkeypatch.setattr(
        "app.modules.dhcp.broker.managed_file_write",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("broker must not handle local state")),
    )
    target = tmp_path / "state.json"

    BrokerDhcpService._atomic_write(target, b"{}\n", default_mode=0o600)

    assert target.read_text(encoding="utf-8") == "{}\n"
