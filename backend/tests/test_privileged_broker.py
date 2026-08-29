from __future__ import annotations

from typing import Sequence

import pytest
from pydantic import ValidationError

from app.privileged_broker.policy import CommandResult, dispatch
from app.privileged_broker.protocol import BrokerRequest, Operation
from app.privileged_broker.server import authorize_peer


def request(operation: Operation, payload: dict) -> BrokerRequest:
    return BrokerRequest(
        request_id="a" * 32,
        actor="administrator",
        operation=operation,
        payload=payload,
    )


def no_execute(argv: Sequence[str], input_text: str | None, timeout: float) -> CommandResult:
    raise AssertionError(f"policy unexpectedly executed {list(argv)} stdin={input_text!r} timeout={timeout}")


def test_protocol_rejects_unknown_operation_and_extra_envelope_fields() -> None:
    with pytest.raises(ValidationError):
        BrokerRequest.model_validate(
            {
                "version": 1,
                "request_id": "a" * 32,
                "actor": "admin",
                "operation": "shell",
                "payload": {"command": "id"},
            }
        )
    with pytest.raises(ValidationError):
        BrokerRequest.model_validate(
            {
                "version": 1,
                "request_id": "a" * 32,
                "actor": "admin",
                "operation": "power",
                "payload": {"action": "poweroff"},
                "command": "id",
            }
        )


def test_protocol_rejects_invalid_actor_and_request_id() -> None:
    with pytest.raises(ValidationError):
        BrokerRequest(request_id="../bad", actor="admin", operation=Operation.POWER, payload={"action": "poweroff"})
    with pytest.raises(ValidationError):
        BrokerRequest(request_id="b" * 32, actor="admin\nroot", operation=Operation.POWER, payload={"action": "poweroff"})


def test_peer_authorization_is_exact_uid_match() -> None:
    assert authorize_peer(1234, expected_uid=1234) is True
    assert authorize_peer(0, expected_uid=1234) is False
    assert authorize_peer(1235, expected_uid=1234) is False


def test_systemd_policy_rejects_protected_and_arbitrary_units_before_execution() -> None:
    protected = dispatch(request(Operation.SYSTEMD, {"action": "restart", "unit": "ssh.service"}), runner=no_execute)
    arbitrary = dispatch(request(Operation.SYSTEMD, {"action": "restart", "unit": "postgresql.service"}), runner=no_execute)

    assert protected.ok is False
    assert protected.error_code == "POLICY_DENIED"
    assert arbitrary.ok is False
    assert arbitrary.error_code == "POLICY_DENIED"


def test_account_policy_rejects_root_and_prefix_escape_before_execution() -> None:
    protected = dispatch(request(Operation.ACCOUNT, {"tool": "usermod", "args": ["--lock", "root"]}), runner=no_execute)
    prefix_escape = dispatch(
        request(Operation.ACCOUNT, {"tool": "useradd", "args": ["--prefix", "/tmp/fake-root", "operator"]}),
        runner=no_execute,
    )

    assert protected.ok is False
    assert protected.error_code == "POLICY_DENIED"
    assert prefix_escape.ok is False
    assert prefix_escape.error_code == "POLICY_DENIED"


def test_chpasswd_never_accepts_multiple_records_or_protected_account() -> None:
    multi = dispatch(
        request(Operation.ACCOUNT, {"tool": "chpasswd", "args": [], "stdin": "alice:first\nbob:second\n"}),
        runner=no_execute,
    )
    protected = dispatch(
        request(Operation.ACCOUNT, {"tool": "chpasswd", "args": [], "stdin": "root:secret\n"}),
        runner=no_execute,
    )

    assert multi.error_code == "POLICY_DENIED"
    assert protected.error_code == "POLICY_DENIED"
    assert "secret" not in protected.stderr


def test_ownership_rejects_system_paths() -> None:
    response = dispatch(
        request(Operation.OWNERSHIP, {"action": "chown", "path": "/etc/shadow", "owner": "operator"}),
        runner=no_execute,
    )
    assert response.ok is False
    assert response.error_code == "POLICY_DENIED"


def test_managed_file_rejects_arbitrary_etc_target() -> None:
    response = dispatch(
        request(Operation.MANAGED_FILE, {"target": "/etc/sudoers", "content": "operator ALL=(ALL) NOPASSWD:ALL\n"}),
        runner=no_execute,
    )
    assert response.ok is False
    assert response.error_code == "POLICY_DENIED"


def test_package_policy_rejects_shell_syntax_and_unlisted_tool() -> None:
    shell = dispatch(
        request(Operation.PACKAGE, {"tool": "apt-get", "args": ["install", "-y", "curl;id"]}),
        runner=no_execute,
    )
    executable = dispatch(
        request(Operation.PACKAGE, {"tool": "bash", "args": ["-c", "id"]}),
        runner=no_execute,
    )
    assert shell.error_code == "POLICY_DENIED"
    assert executable.error_code == "POLICY_DENIED"


def test_disabled_operation_fails_closed() -> None:
    response = dispatch(
        request(Operation.UPDATE_SERVICE, {"unit": "webnas-self-update-1.service"}),
        runner=no_execute,
    )
    assert response.ok is False
    assert response.error_code == "POLICY_DENIED"
