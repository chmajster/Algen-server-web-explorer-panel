from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace

from app.identity import linux_accounts
from app.privileged_broker import file_worker_policy
from app.privileged_broker.protocol import BrokerRequest, Operation


def _forbid_local_run(*_args: object, **_kwargs: object) -> CompletedProcess[str]:
    raise AssertionError("privileged-broker-required mode must not execute account tools locally")


def test_linux_account_mutation_uses_broker_when_required(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_broker(args: list[str], **kwargs: object) -> CompletedProcess[str]:
        calls.append((args, kwargs))
        return CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(linux_accounts, "broker_required", lambda: True)
    monkeypatch.setattr(linux_accounts, "broker_command", fake_broker)
    monkeypatch.setattr(linux_accounts, "_local_run", _forbid_local_run)

    result = linux_accounts._run(["/usr/sbin/usermod", "--lock", "alice"])

    assert result.returncode == 0
    assert calls == [
        (
            ["/usr/sbin/usermod", "--lock", "alice"],
            {"input_text": None, "timeout": 60, "actor": "identity"},
        )
    ]


def test_shadow_backed_account_status_uses_broker_when_required(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_which(tool: str) -> str:
        return f"/usr/bin/{tool}"

    def fake_broker(args: list[str], **_kwargs: object) -> CompletedProcess[str]:
        calls.append(args)
        if Path(args[0]).name == "passwd":
            return CompletedProcess(args=args, returncode=0, stdout="alice L 2026-08-31 0 99999 7 -1\n", stderr="")
        return CompletedProcess(args=args, returncode=0, stdout="Password must be changed\n", stderr="")

    monkeypatch.setattr(linux_accounts, "broker_required", lambda: True)
    monkeypatch.setattr(linux_accounts.shutil, "which", fake_which)
    monkeypatch.setattr(linux_accounts, "broker_command", fake_broker)
    monkeypatch.setattr(linux_accounts, "_local_run", _forbid_local_run)

    locked, password_change_required = linux_accounts._account_status("alice")

    assert locked is True
    assert password_change_required is True
    assert calls == [
        ["/usr/bin/passwd", "-S", "alice"],
        ["/usr/bin/chage", "-l", "alice"],
    ]


def test_file_worker_runs_from_backend_package_root(monkeypatch) -> None:
    request = BrokerRequest(
        request_id="a" * 32,
        actor="alice",
        operation=Operation.FILE_WORKER,
        payload={},
    )
    fake_user = SimpleNamespace(pw_uid=1000, pw_gid=1000)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        file_worker_policy,
        "_validate_request",
        lambda _request: ("alice", "list", {}, fake_user, None),
    )

    def fake_run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        captured.update(kwargs)
        return CompletedProcess(args=command, returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(file_worker_policy.subprocess, "run", fake_run)

    response = file_worker_policy.dispatch(request)

    assert response.ok is True
    assert captured["cwd"] == Path(file_worker_policy.__file__).resolve().parents[2]
