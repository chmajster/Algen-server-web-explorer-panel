from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import auth
from app.privileged_broker import authentication_policy
from app.privileged_broker.client import BrokerError
from app.privileged_broker.protocol import BrokerRequest, BrokerResponse, Operation


def _request(payload: dict[str, str]) -> BrokerRequest:
    return BrokerRequest(
        request_id="a" * 32,
        actor="authentication-test",
        operation=Operation.PAM_AUTH,
        payload=payload,
    )


def _prepare_runtime_auth(monkeypatch, tmp_path) -> None:
    pam_file = tmp_path / "webnas"
    pam_file.write_text("#%PAM-1.0\n", encoding="utf-8")
    monkeypatch.setattr(auth, "assert_login_allowed", lambda username: None)
    monkeypatch.setattr(auth, "get_config", lambda: SimpleNamespace(auth=SimpleNamespace(pam_service="webnas")))
    monkeypatch.setattr(auth, "WEBNAS_PAM_PATH", pam_file)
    monkeypatch.setattr(auth, "broker_required", lambda: True)


def test_standard_install_pam_authentication_uses_privileged_broker(monkeypatch, tmp_path):
    _prepare_runtime_auth(monkeypatch, tmp_path)
    calls: list[tuple[Operation, dict[str, str], str]] = []

    class FakeBrokerClient:
        def __init__(self, *, timeout: float):
            assert timeout == 30.0

        def request(self, operation, payload, *, actor):
            calls.append((operation, payload, actor))
            return BrokerResponse(request_id="a" * 32, ok=True)

    monkeypatch.setattr(auth, "BrokerClient", FakeBrokerClient)

    auth.authenticate("alice", "local-secret")

    assert calls == [
        (
            Operation.PAM_AUTH,
            {"username": "alice", "password": "local-secret", "service": "webnas"},
            "authentication",
        )
    ]


def test_standard_install_invalid_pam_password_remains_unauthorized(monkeypatch, tmp_path):
    _prepare_runtime_auth(monkeypatch, tmp_path)

    class FakeBrokerClient:
        def __init__(self, *, timeout: float):
            pass

        def request(self, operation, payload, *, actor):
            return BrokerResponse(
                request_id="a" * 32,
                ok=False,
                exit_code=1,
                error_code="PAM_INVALID_CREDENTIALS",
                stderr="Invalid username or password",
            )

    monkeypatch.setattr(auth, "BrokerClient", FakeBrokerClient)

    with pytest.raises(HTTPException) as error:
        auth.authenticate("alice", "wrong-secret")

    assert error.value.status_code == 401


def test_standard_install_broker_outage_returns_sanitized_diagnostics(monkeypatch, tmp_path):
    _prepare_runtime_auth(monkeypatch, tmp_path)

    class FakeBrokerClient:
        def __init__(self, *, timeout: float):
            pass

        def request(self, operation, payload, *, actor):
            raise BrokerError(
                "do not expose this low-level exception text",
                error_code="BROKER_UNAVAILABLE",
                exit_code=1,
            )

    monkeypatch.setattr(auth, "BrokerClient", FakeBrokerClient)

    with pytest.raises(HTTPException) as error:
        auth.authenticate("alice", "local-secret")

    assert error.value.status_code == 503
    assert error.value.detail == {
        "code": "PAM_BROKER_UNAVAILABLE",
        "message": "PAM authentication service is unavailable",
        "stage": "broker_connect",
        "reason": "BROKER_UNAVAILABLE",
        "hint": "Check webnas-privileged.socket and webnas-privileged.service status and journal.",
        "exit_code": 1,
    }
    assert "low-level" not in str(error.value.detail)


def test_standard_install_pam_broker_failure_returns_request_id(monkeypatch, tmp_path):
    _prepare_runtime_auth(monkeypatch, tmp_path)

    class FakeBrokerClient:
        def __init__(self, *, timeout: float):
            pass

        def request(self, operation, payload, *, actor):
            return BrokerResponse(
                request_id="b" * 32,
                ok=False,
                exit_code=127,
                error_code="PAM_UNAVAILABLE",
                stderr="sensitive implementation detail must stay server-side",
            )

    monkeypatch.setattr(auth, "BrokerClient", FakeBrokerClient)

    with pytest.raises(HTTPException) as error:
        auth.authenticate("alice", "local-secret")

    assert error.value.status_code == 503
    assert error.value.detail == {
        "code": "PAM_SERVICE_UNAVAILABLE",
        "message": "PAM authentication service is unavailable",
        "stage": "broker_response",
        "reason": "PAM_UNAVAILABLE",
        "hint": "Check the WebNAS PAM service and privileged broker journal.",
        "request_id": "b" * 32,
        "exit_code": 127,
    }
    assert "sensitive" not in str(error.value.detail)


def test_privileged_pam_policy_authenticates_with_webnas_service(monkeypatch, tmp_path):
    pam_file = tmp_path / "webnas"
    pam_file.write_text("#%PAM-1.0\n", encoding="utf-8")
    monkeypatch.setattr(authentication_policy, "WEBNAS_PAM_PATH", pam_file)
    calls: list[tuple[str, str, str]] = []

    class FakePam:
        reason = ""

        def authenticate(self, username: str, password: str, *, service: str):
            calls.append((username, password, service))
            return True

    monkeypatch.setattr(authentication_policy.pam, "pam", lambda: FakePam())

    response = authentication_policy.dispatch(
        _request({"username": "alice", "password": "local-secret", "service": "webnas"})
    )

    assert response.ok is True
    assert response.error_code is None
    assert calls == [("alice", "local-secret", "webnas")]


def test_privileged_pam_policy_returns_specific_invalid_credentials_code(monkeypatch, tmp_path):
    pam_file = tmp_path / "webnas"
    pam_file.write_text("#%PAM-1.0\n", encoding="utf-8")
    monkeypatch.setattr(authentication_policy, "WEBNAS_PAM_PATH", pam_file)

    class FakePam:
        reason = "Authentication failure"

        def authenticate(self, username: str, password: str, *, service: str):
            return False

    monkeypatch.setattr(authentication_policy.pam, "pam", lambda: FakePam())

    response = authentication_policy.dispatch(
        _request({"username": "alice", "password": "wrong-secret", "service": "webnas"})
    )

    assert response.ok is False
    assert response.exit_code == 1
    assert response.error_code == "PAM_INVALID_CREDENTIALS"
    assert response.stderr == "Invalid username or password"


def test_privileged_pam_policy_rejects_service_override():
    response = authentication_policy.dispatch(
        _request({"username": "alice", "password": "secret", "service": "login"})
    )

    assert response.ok is False
    assert response.exit_code == 126
    assert response.error_code == "POLICY_DENIED"
