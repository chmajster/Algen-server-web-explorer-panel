from __future__ import annotations

import base64
import io
import json
from types import SimpleNamespace

from app import file_ops, worker
from app.privileged_broker.protocol import Operation


def test_run_user_op_keeps_identity_operation_and_payload_out_of_argv(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["input"] = kwargs.get("input")
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(file_ops, "current_process_can_impersonate", lambda: True)
    monkeypatch.setattr(file_ops.subprocess, "run", fake_run)

    result = file_ops.run_user_op("alice", "stat", {"token": "sensitive-marker"})

    assert result == {"ok": True}
    command = captured["cmd"]
    assert isinstance(command, list)
    assert command[-6:] == ["--user", "-", "--op", "-", "--payload", "-"]
    command_text = " ".join(command)
    assert "alice" not in command_text
    assert "stat" not in command_text
    assert "sensitive-marker" not in command_text

    encoded = captured["input"]
    assert isinstance(encoded, str)
    envelope = json.loads(base64.b64decode(encoded).decode("utf-8"))
    assert envelope == {"user": "alice", "op": "stat", "payload": {"token": "sensitive-marker"}}


def test_run_user_op_delegates_to_privileged_broker_when_http_service_is_unprivileged(monkeypatch):
    captured: dict[str, object] = {}

    class FakeBrokerClient:
        def __init__(self, *, timeout: float):
            captured["timeout"] = timeout

        def require(self, operation, payload, *, actor):
            captured["operation"] = operation
            captured["payload"] = payload
            captured["actor"] = actor
            return SimpleNamespace(stdout='{"ok": true}')

    monkeypatch.setattr(file_ops, "current_process_can_impersonate", lambda: False)
    monkeypatch.setattr(file_ops, "BrokerClient", FakeBrokerClient)

    result = file_ops.run_user_op("alice", "stat", {"token": "sensitive-marker"})

    assert result == {"ok": True}
    assert captured["operation"] == Operation.FILE_WORKER
    assert captured["payload"] == {"username": "alice", "op": "stat", "payload": {"token": "sensitive-marker"}}
    assert captured["actor"] == "alice"
    assert captured["timeout"] == 3605.0


def test_worker_decodes_constant_argv_stdin_envelope(monkeypatch):
    envelope = {"user": "alice", "op": "list", "payload": {"path": "/home/alice"}}
    encoded = base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("ascii")
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO(encoded))

    username, operation, payload = worker._decode_request(SimpleNamespace(user="-", op="-", payload="-"))

    assert username == "alice"
    assert operation == "list"
    assert payload == {"path": "/home/alice"}
