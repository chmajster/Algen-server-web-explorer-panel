from __future__ import annotations

from typing import Sequence

from app.privileged_broker.policy import CommandResult
from app.privileged_broker.protocol import BrokerRequest, Operation
from app.privileged_broker.storage_policy import dispatch


def request(payload: dict) -> BrokerRequest:
    return BrokerRequest(
        request_id="d" * 32,
        actor="dpkg-repair-test",
        operation=Operation.PACKAGE,
        payload=payload,
    )


def test_broker_allows_only_exact_dpkg_configure_recovery(monkeypatch) -> None:
    executed: list[tuple[list[str], float]] = []

    monkeypatch.setattr(
        "app.privileged_broker.policy._resolve_tool",
        lambda tool: f"/usr/bin/{tool}",
    )

    def runner(argv: Sequence[str], _stdin: str | None, timeout: float) -> CommandResult:
        executed.append((list(argv), timeout))
        return CommandResult(0, "configured", "")

    response = dispatch(
        request({"tool": "dpkg", "args": ["--configure", "-a"], "timeout": 3600}),
        runner=runner,
    )

    assert response.ok is True
    assert executed == [(["/usr/bin/dpkg", "--configure", "-a"], 3600.0)]


def test_broker_does_not_expand_dpkg_recovery_surface(monkeypatch) -> None:
    executed: list[list[str]] = []

    monkeypatch.setattr(
        "app.privileged_broker.policy._resolve_tool",
        lambda tool: f"/usr/bin/{tool}",
    )

    def runner(argv: Sequence[str], _stdin: str | None, _timeout: float) -> CommandResult:
        executed.append(list(argv))
        return CommandResult(0, "", "")

    for args in (
        ["--configure", "openssl"],
        ["--configure", "-a", "--force-all"],
        ["--unpack", "/tmp/package.deb"],
    ):
        response = dispatch(
            request({"tool": "dpkg", "args": args, "timeout": 3600}),
            runner=runner,
        )
        assert response.ok is False
        assert response.error_code == "POLICY_DENIED"

    assert executed == []
