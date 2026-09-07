from __future__ import annotations

import subprocess

from app.modules.providers import docker_broker_transport
from app.privileged_broker import docker_policy, docker_stop_policy, storage_policy
from app.privileged_broker.protocol import BrokerRequest, BrokerResponse, Operation


def _request(operation: Operation, payload: dict) -> BrokerRequest:
    return BrokerRequest(
        request_id="a" * 32,
        actor="docker-test",
        operation=operation,
        payload=payload,
    )


def _runner_capture(calls: list[tuple[list[str], str | None, float]]):
    def runner(argv, stdin, timeout):
        calls.append((list(argv), stdin, timeout))
        return docker_policy.base.CommandResult(0, "ok\n", "")

    return runner


def test_docker_broker_allows_status_and_safe_container_create(monkeypatch) -> None:
    calls: list[tuple[list[str], str | None, float]] = []
    monkeypatch.setattr(docker_policy.base, "_resolve_tool", lambda name: f"/usr/bin/{name}")
    runner = _runner_capture(calls)

    status = docker_policy.dispatch(
        _request(Operation.DOCKER, {"tool": "docker", "args": ["version", "--format", "{{json .}}"], "stdin": None, "timeout": 15}),
        runner=runner,
    )
    create = docker_policy.dispatch(
        _request(
            Operation.DOCKER,
            {
                "tool": "docker",
                "args": ["run", "-d", "--name", "safe-app", "--network", "bridge", "nginx:stable"],
                "stdin": None,
                "timeout": 120,
            },
        ),
        runner=runner,
    )

    assert status.ok is True
    assert create.ok is True
    assert calls[0][0] == ["/usr/bin/docker", "version", "--format", "{{json .}}"]
    assert calls[1][0][-1] == "nginx:stable"


def test_docker_broker_denies_root_equivalent_escape_hatches(monkeypatch) -> None:
    monkeypatch.setattr(docker_policy.base, "_resolve_tool", lambda name: f"/usr/bin/{name}")

    attempts = [
        ["run", "--privileged", "nginx:stable"],
        ["run", "--mount", "type=bind,src=/,dst=/host", "nginx:stable"],
        ["run", "--mount", "type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock", "nginx:stable"],
        ["exec", "container", "sh"],
    ]

    for args in attempts:
        response = docker_policy.dispatch(
            _request(Operation.DOCKER, {"tool": "docker", "args": args, "stdin": None, "timeout": 30}),
            runner=lambda *_args: (_ for _ in ()).throw(AssertionError("denied command reached runner")),
        )
        assert response.ok is False
        assert response.exit_code == 126
        assert response.error_code == "POLICY_DENIED"


def test_docker_broker_accepts_password_only_via_password_stdin(monkeypatch) -> None:
    calls: list[tuple[list[str], str | None, float]] = []
    monkeypatch.setattr(docker_policy.base, "_resolve_tool", lambda name: f"/usr/bin/{name}")

    allowed = docker_policy.dispatch(
        _request(
            Operation.DOCKER,
            {
                "tool": "docker",
                "args": ["login", "registry.example.com", "--username", "alice", "--password-stdin"],
                "stdin": "top-secret\n",
                "timeout": 30,
            },
        ),
        runner=_runner_capture(calls),
    )
    denied = docker_policy.dispatch(
        _request(Operation.DOCKER, {"tool": "docker", "args": ["info"], "stdin": "secret", "timeout": 30}),
        runner=lambda *_args: (_ for _ in ()).throw(AssertionError("denied stdin reached runner")),
    )

    assert allowed.ok is True
    assert calls[0][1] == "top-secret\n"
    assert denied.ok is False
    assert denied.error_code == "POLICY_DENIED"


def test_storage_policy_routes_docker_operation(monkeypatch) -> None:
    expected = BrokerResponse(request_id="a" * 32, ok=True, stdout="docker")
    monkeypatch.setattr(storage_policy, "docker_dispatch", lambda request, runner=None: expected)

    response = storage_policy.dispatch(
        _request(Operation.DOCKER, {"tool": "docker", "args": ["info"], "stdin": None, "timeout": 30}),
    )

    assert response == expected


def test_graceful_stop_policy_has_one_fixed_command(monkeypatch) -> None:
    calls: list[tuple[list[str], str | None, float]] = []
    monkeypatch.setattr(docker_stop_policy.base, "_resolve_tool", lambda name: f"/usr/bin/{name}")

    response = docker_stop_policy.dispatch(
        _request(Operation.DOCKER_GRACEFUL_STOP, {"container": "safe-app"}),
        runner=_runner_capture(calls),
    )

    assert response.ok is True
    assert calls == [(["/usr/bin/docker", "stop", "--time", "-1", "safe-app"], None, 24 * 60 * 60)]


def test_docker_transport_uses_broker_without_docker_group(monkeypatch) -> None:
    calls: list[tuple[Operation, dict, str, float]] = []

    class FakeResponse:
        exit_code = 0
        stdout = "server-ok"
        stderr = ""

    class FakeClient:
        def __init__(self, *, timeout: float):
            self.timeout = timeout

        def request(self, operation, payload, *, actor):
            calls.append((operation, payload, actor, self.timeout))
            return FakeResponse()

    class Provider:
        module_id = "docker"
        actor = "alice"

        def _run(self, args, *, timeout=30, input_text=None, env=None):
            return subprocess.CompletedProcess(args, 0, "local", "")

    monkeypatch.setattr(docker_broker_transport, "broker_required", lambda: True)
    monkeypatch.setattr(docker_broker_transport, "BrokerClient", FakeClient)
    docker_broker_transport.install_docker_broker_transport(Provider)

    result = Provider()._run(["docker", "info", "--format", "{{json .}}"], timeout=120)

    assert result.returncode == 0
    assert result.stdout == "server-ok"
    assert calls[0][0] == Operation.DOCKER
    assert calls[0][1]["args"] == ["info", "--format", "{{json .}}"]
    assert calls[0][2] == "alice"
    assert calls[0][3] == 125.0
