from __future__ import annotations

from pathlib import Path
from typing import Sequence

from app.privileged_broker.extended_policy import dispatch
from app.privileged_broker.policy import CommandResult
from app.privileged_broker.protocol import BrokerRequest, Operation


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _request(operation: Operation, payload: dict) -> BrokerRequest:
    return BrokerRequest(
        request_id="a" * 32,
        actor="security-test",
        operation=operation,
        payload=payload,
    )


def test_normal_web_service_is_unprivileged_and_requires_broker() -> None:
    unit = (REPOSITORY_ROOT / "packaging/webnas.service").read_text(encoding="utf-8")
    unit_section, service_section = unit.split("[Service]", 1)
    assert "Requires=webnas-privileged.socket" in unit_section
    assert "After=webnas-privileged.socket" in unit_section
    assert "User=webnas" in service_section
    assert "Group=webnas" in service_section
    assert "Environment=WEBNAS_PRIVILEGED_BROKER=required" in service_section
    assert "NoNewPrivileges=true" in service_section
    assert "User=root" not in service_section


def test_blue_green_backend_is_unprivileged_but_broker_remains_root() -> None:
    release = (REPOSITORY_ROOT / "scripts/webnas_release.py").read_text(encoding="utf-8")
    assert 'f"User={self.service_user}"' in release
    assert 'f"Group={self.service_user}"' in release
    assert '"Environment=WEBNAS_PRIVILEGED_BROKER=required"' in release
    assert '"NoNewPrivileges=true"' in release
    assert '"Requires=webnas-privileged.socket"' in release
    assert '"User=root", "Group=root"' in release  # dedicated broker only
    assert "runtime, self.root" not in release


def test_broker_server_uses_extended_fail_closed_policy() -> None:
    server = (REPOSITORY_ROOT / "backend/app/privileged_broker/server.py").read_text(encoding="utf-8")
    assert "from .extended_policy import dispatch" in server
    assert "from .policy import dispatch" not in server


def test_account_policy_rejects_uid_override() -> None:
    executed: list[list[str]] = []

    def runner(argv: Sequence[str], _stdin: str | None, _timeout: float) -> CommandResult:
        executed.append(list(argv))
        return CommandResult(0, "", "")

    response = dispatch(
        _request(Operation.ACCOUNT, {"tool": "useradd", "args": ["--uid", "0", "evil"], "stdin": None}),
        runner=runner,
    )
    assert response.ok is False
    assert response.error_code == "POLICY_DENIED"
    assert executed == []


def test_package_policy_rejects_apt_hook_execution() -> None:
    executed: list[list[str]] = []

    def runner(argv: Sequence[str], _stdin: str | None, _timeout: float) -> CommandResult:
        executed.append(list(argv))
        return CommandResult(0, "", "")

    response = dispatch(
        _request(
            Operation.PACKAGE,
            {"tool": "apt-get", "args": ["-o", "APT::Update::Pre-Invoke=/bin/sh", "update"], "timeout": 60},
        ),
        runner=runner,
    )
    assert response.ok is False
    assert response.error_code == "POLICY_DENIED"
    assert executed == []


def test_mount_policy_rejects_target_outside_webnas_roots() -> None:
    executed: list[list[str]] = []

    def runner(argv: Sequence[str], _stdin: str | None, _timeout: float) -> CommandResult:
        executed.append(list(argv))
        return CommandResult(0, "", "")

    response = dispatch(
        _request(
            Operation.MOUNT,
            {
                "tool": "mount",
                "args": ["-t", "nfs", "-o", "nosuid,nodev,rw", "server:/share", "/etc"],
                "timeout": 60,
            },
        ),
        runner=runner,
    )
    assert response.ok is False
    assert response.error_code == "POLICY_DENIED"
    assert executed == []


def test_module_hook_policy_rejects_path_like_module_id() -> None:
    executed: list[list[str]] = []

    def runner(argv: Sequence[str], _stdin: str | None, _timeout: float) -> CommandResult:
        executed.append(list(argv))
        return CommandResult(0, "", "")

    response = dispatch(
        _request(Operation.MODULE_HOOK, {"module_id": "../evil", "action": "install"}),
        runner=runner,
    )
    assert response.ok is False
    assert response.error_code == "POLICY_DENIED"
    assert executed == []
