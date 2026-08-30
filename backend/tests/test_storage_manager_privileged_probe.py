from __future__ import annotations

from collections.abc import Sequence

import pytest

import app.modules.storage_manager.collectors.probe as probe_module
import app.privileged_broker.storage_policy as storage_policy
from app.modules.storage_manager.collectors.probe import StorageReadOnlyProbe
from app.modules.storage_manager.service import CommandResult as StorageCommandResult
from app.privileged_broker.policy import CommandResult
from app.privileged_broker.protocol import BrokerRequest, Operation
from app.privileged_broker.storage_probe_rules import (
    LVS_ARGS,
    PVS_ARGS,
    SWAPON_ARGS,
    VGS_ARGS,
    ZFS_LIST_ARGS,
    ZPOOL_LIST_ARGS,
)


def _request(tool: str, args: list[str], *, timeout: float = 8.0) -> BrokerRequest:
    return BrokerRequest(
        request_id="a" * 32,
        actor="storage-manager",
        operation=Operation.STORAGE_PROBE,
        payload={"tool": tool, "args": args, "timeout": timeout},
    )


def test_privileged_storage_policy_allows_only_fixed_read_only_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: list[list[str]] = []

    monkeypatch.setattr(storage_policy.base, "_resolve_tool", lambda name: f"/usr/sbin/{name}")

    def runner(argv: Sequence[str], _stdin: str | None, _timeout: float) -> CommandResult:
        executed.append(list(argv))
        return CommandResult(0, "ok", "")

    allowed = [
        ("smartctl", ["-a", "-j", "/dev/sda"]),
        ("nvme", ["smart-log", "-o", "json", "/dev/nvme0n1"]),
        ("pvs", list(PVS_ARGS)),
        ("vgs", list(VGS_ARGS)),
        ("lvs", list(LVS_ARGS)),
        ("swapon", list(SWAPON_ARGS)),
        ("zpool", list(ZPOOL_LIST_ARGS)),
        ("zpool", ["status", "-P", "tank"]),
        ("zfs", list(ZFS_LIST_ARGS)),
        ("btrfs", ["device", "stats", "-c", "/srv/data"]),
        ("btrfs", ["filesystem", "show", "--raw", "/srv/data"]),
        ("btrfs", ["filesystem", "usage", "-b", "/srv/data"]),
        ("btrfs", ["scrub", "status", "-R", "/srv/data"]),
    ]

    for tool, args in allowed:
        response = storage_policy.dispatch(_request(tool, args), runner=runner)
        assert response.ok is True

    assert len(executed) == len(allowed)
    assert executed[0] == ["/usr/sbin/smartctl", "-a", "-j", "/dev/sda"]
    assert executed[-1] == ["/usr/sbin/btrfs", "scrub", "status", "-R", "/srv/data"]


def test_privileged_storage_policy_rejects_malicious_cli_before_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved: list[str] = []
    executed: list[list[str]] = []

    def resolver(name: str) -> str:
        resolved.append(name)
        return f"/usr/sbin/{name}"

    def runner(argv: Sequence[str], _stdin: str | None, _timeout: float) -> CommandResult:
        executed.append(list(argv))
        return CommandResult(0, "", "")

    monkeypatch.setattr(storage_policy.base, "_resolve_tool", resolver)

    malicious = [
        _request("pvs", ["--reportformat", "json", "--config", "devices { filter=[\"a|.*|\"] }"]),
        _request("zpool", ["status", "-P", "tank;id"]),
        _request("zfs", ["list", "-H", "-p", "-o", "name", "$(id)"]),
        _request("btrfs", ["filesystem", "show", "--raw", "/mnt/../etc"]),
        _request("smartctl", ["-a", "-j", "/dev/sda;id"]),
        _request("nvme", ["smart-log", "-o", "json", "--output-format=json"]),
        _request("sh", ["-c", "id"]),
    ]

    for request in malicious:
        response = storage_policy.dispatch(request, runner=runner)
        assert response.ok is False
        assert response.error_code == "POLICY_DENIED"

    assert resolved == []
    assert executed == []


def test_privileged_storage_policy_rejects_invalid_timeout_and_extra_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage_policy.base, "_resolve_tool", lambda name: f"/usr/sbin/{name}")

    timeout_response = storage_policy.dispatch(_request("pvs", list(PVS_ARGS), timeout=31))
    assert timeout_response.ok is False
    assert timeout_response.error_code == "POLICY_DENIED"

    request = _request("pvs", list(PVS_ARGS))
    request.payload["command"] = "id"
    extra_response = storage_policy.dispatch(request)
    assert extra_response.ok is False
    assert extra_response.error_code == "POLICY_DENIED"


def test_storage_read_only_probe_uses_broker_when_required(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[str], float]] = []

    monkeypatch.setattr(probe_module, "broker_required", lambda: True)

    def broker(tool: str, args: list[str], *, timeout: float):
        calls.append((tool, args, timeout))
        return type("Completed", (), {"returncode": 0, "stdout": "brokered", "stderr": ""})()

    monkeypatch.setattr(probe_module, "storage_probe", broker)

    def local_runner(argv: Sequence[str], timeout: float) -> StorageCommandResult:
        raise AssertionError(f"local runner must not execute in broker-required mode: {list(argv)} timeout={timeout}")

    probe = StorageReadOnlyProbe(runner=local_runner, tool_resolver=lambda name: f"/usr/sbin/{name}")
    result = probe.run("pvs", PVS_ARGS, timeout=9.0)

    assert result == StorageCommandResult(0, "brokered", "")
    assert calls == [("pvs", list(PVS_ARGS), 9.0)]


def test_storage_read_only_probe_fails_closed_when_broker_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe_module, "broker_required", lambda: True)

    def unavailable(tool: str, args: list[str], *, timeout: float):
        del tool, args, timeout
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(probe_module, "storage_probe", unavailable)

    probe = StorageReadOnlyProbe(tool_resolver=lambda name: f"/usr/sbin/{name}")
    result = probe.run("zfs", ZFS_LIST_ARGS)

    assert result is not None
    assert result.returncode == 127
    assert result.stdout == ""


def test_storage_read_only_probe_rejects_unknown_tool_before_local_resolution() -> None:
    resolved: list[str] = []

    def resolver(name: str) -> str | None:
        resolved.append(name)
        return f"/usr/sbin/{name}"

    probe = StorageReadOnlyProbe(tool_resolver=resolver)

    assert probe.run("bash", ["-c", "id"]) is None
    assert resolved == []
