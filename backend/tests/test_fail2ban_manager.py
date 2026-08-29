from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.modules.fail2ban_manager.models import JailConfigInput
from app.modules.fail2ban_manager.service import Fail2BanCommandError, Fail2BanService


def _result(*args: str, code: int = 0, output: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(args), code, output, "")


def test_ip_and_jail_validation_happens_before_command_execution(tmp_path: Path):
    service = Fail2BanService(jail_dir=tmp_path)
    calls: list[tuple[str, ...]] = []

    def fake_client(*args: str, check: bool = True):
        calls.append(args)
        return _result(*args)

    service._client = fake_client  # type: ignore[method-assign]

    with pytest.raises(ValueError):
        service.ban("sshd;touch/tmp/x", "192.0.2.10")
    with pytest.raises(ValueError):
        service.ban("sshd", "not-an-ip")
    assert calls == []

    result = service.ban("sshd", "2001:db8::10")
    assert result == {"ok": True, "jail": "sshd", "ip": "2001:db8::10"}
    assert calls == [("set", "sshd", "banip", "2001:db8::10")]


def test_managed_config_is_atomic_validated_and_reloaded(tmp_path: Path):
    service = Fail2BanService(jail_dir=tmp_path)
    calls: list[tuple[str, ...]] = []

    def fake_client(*args: str, check: bool = True):
        calls.append(args)
        return _result(*args)

    service._client = fake_client  # type: ignore[method-assign]
    payload = JailConfigInput(
        enabled=True,
        filter="sshd",
        backend="systemd",
        port="ssh",
        maxretry=4,
        findtime="10m",
        bantime="1h",
        action="action_",
        confirm=True,
    )

    result = service.save_config("sshd", payload)

    path = tmp_path / "webnas-sshd.local"
    assert result["ok"] is True
    content = path.read_text(encoding="utf-8")
    assert "[sshd]" in content
    assert "enabled = true" in content
    assert "maxretry = 4" in content
    assert calls == [("-t",), ("reload",)]


def test_invalid_config_value_is_rejected_without_writing(tmp_path: Path):
    with pytest.raises(ValidationError):
        JailConfigInput(
            enabled=True,
            filter="sshd\n[evil]",
            confirm=True,
        )
    assert not (tmp_path / "webnas-sshd.local").exists()


def test_failed_validation_restores_previous_managed_config(tmp_path: Path):
    service = Fail2BanService(jail_dir=tmp_path)
    path = tmp_path / "webnas-sshd.local"
    path.write_text("[sshd]\nenabled = false\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def fake_client(*args: str, check: bool = True):
        calls.append(args)
        if args == ("-t",):
            return _result(*args, code=1, output="invalid configuration")
        return _result(*args)

    service._client = fake_client  # type: ignore[method-assign]
    payload = JailConfigInput(enabled=True, filter="sshd", confirm=True)

    with pytest.raises(Fail2BanCommandError, match="validation failed"):
        service.save_config("sshd", payload)

    assert path.read_text(encoding="utf-8") == "[sshd]\nenabled = false\n"
    assert calls == [("-t",)]


def test_log_filters_validate_ip_and_action(tmp_path: Path):
    service = Fail2BanService(jail_dir=tmp_path)
    service.journalctl = "/usr/bin/journalctl"
    service._run = lambda *args, **kwargs: _result(  # type: ignore[method-assign]
        "journalctl",
        output=(
            "2026-08-29T10:00:00+00:00 fail2ban.actions [sshd] Ban 192.0.2.10\n"
            "2026-08-29T10:01:00+00:00 fail2ban.actions [nginx] Unban 198.51.100.20\n"
        ),
    )

    items = service.logs(jail="sshd", address="192.0.2.10", action="ban")
    assert len(items) == 1
    assert "192.0.2.10" in items[0]["message"]
    with pytest.raises(ValueError):
        service.logs(action="drop-table")
    with pytest.raises(ValueError):
        service.logs(address="not-an-ip")
