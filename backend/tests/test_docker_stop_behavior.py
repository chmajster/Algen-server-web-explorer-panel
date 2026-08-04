from __future__ import annotations

from app.modules.docker_manager.container_action_models import ContainerActionRequest
from app.modules.providers.docker_stop_behavior import graceful_stop_command, install_docker_stop_behavior


def test_graceful_stop_has_no_timeout_limit() -> None:
    assert graceful_stop_command("/usr/bin/docker", "example") == [
        "/usr/bin/docker",
        "stop",
        "--time",
        "-1",
        "example",
    ]


def test_stop_request_accepts_legacy_timeout_without_a_limit() -> None:
    request = ContainerActionRequest.model_validate({"action": "stop", "timeout": 86400})
    assert request.timeout == 86400


def test_force_stop_always_uses_sigkill() -> None:
    captured: dict = {}

    class FakeProvider:
        _webnas_stop_behavior_installed = False

        def manage(self, operation, payload, actor, log, progress, cancelled):
            captured.update({"operation": operation, "payload": payload})
            return {"ok": True}

    install_docker_stop_behavior(FakeProvider)
    FakeProvider().manage(
        "container_kill",
        {"target": "example", "signal": "TERM", "timeout": 20},
        "tester",
        lambda *_: None,
        lambda *_: None,
        lambda: False,
    )

    assert captured["operation"] == "container_kill"
    assert captured["payload"]["signal"] == "KILL"
    assert captured["payload"]["timeout"] is None
