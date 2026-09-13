from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules import linux_update_worker
from app.modules.fail2ban_manager import router as fail2ban_router
from app.modules.fail2ban_manager.service import Fail2BanCommandError
from app.modules.gitops_manager import router as gitops_router
from app.modules.gitops_manager.service import GitOpsConflict
from app.modules.login_history import router as login_history_router
from app.modules.login_history.service import LoginHistoryUnavailable
from app.modules.network_tools import router as network_tools_router
from app.modules.network_tools.models import DnsLookupRequest
from app.modules.network_tools.service import NetworkToolError
from app.modules.os_repositories.adapters import rpm as rpm_adapter
from app.package_center.detached_updates import read_update_state


def _raise(error: Exception):
    raise error


def _detail(callable_):
    with pytest.raises(HTTPException) as caught:
        callable_()
    assert isinstance(caught.value.detail, dict)
    return caught.value.status_code, caught.value.detail


def test_login_history_boundary_does_not_expose_backend_diagnostics():
    status, detail = _detail(
        lambda: login_history_router._controlled(lambda: _raise(LoginHistoryUnavailable("journalctl secret stderr")))
    )
    assert status == 503
    assert detail == {"code": "LOGIN_HISTORY_UNAVAILABLE", "message": "Login history backend is unavailable"}

    status, detail = _detail(
        lambda: login_history_router._controlled(lambda: _raise(RuntimeError("loginctl secret stderr")))
    )
    assert status == 502
    assert detail == {"code": "LOGIN_HISTORY_OPERATION_FAILED", "message": "Login history operation failed"}


def test_fail2ban_boundary_drops_raw_command_output():
    error = Fail2BanCommandError(
        "fail2ban-client exited with status 1",
        command="fail2ban-client",
        output="SECRET_FAIL2BAN_STDERR",
    )
    status, detail = _detail(lambda: fail2ban_router._controlled(lambda: _raise(error)))

    assert status == 502
    assert detail == {
        "code": "FAIL2BAN_COMMAND_FAILED",
        "message": "fail2ban-client exited with status 1",
        "command": "fail2ban-client",
    }
    assert "SECRET_FAIL2BAN_STDERR" not in str(detail)
    assert "output" not in detail


def test_gitops_boundary_does_not_expose_git_output():
    status, detail = _detail(
        lambda: gitops_router._controlled(lambda: _raise(GitOpsConflict("CONFLICT SECRET_GIT_PATH")))
    )
    assert status == 409
    assert detail == {
        "code": "GITOPS_CONFLICT",
        "message": "GitOps operation encountered a repository conflict",
    }
    assert "SECRET_GIT_PATH" not in str(detail)

    status, detail = _detail(
        lambda: gitops_router._controlled(lambda: _raise(RuntimeError("fatal: SECRET_GIT_REMOTE")))
    )
    assert status == 502
    assert detail == {"code": "GITOPS_OPERATION_FAILED", "message": "GitOps operation failed"}
    assert "SECRET_GIT_REMOTE" not in str(detail)


def test_network_tool_boundary_keeps_rate_limits_but_hides_command_diagnostics(monkeypatch: pytest.MonkeyPatch):
    fake_service = SimpleNamespace(execute=lambda actor, action, callback: callback())
    monkeypatch.setattr(network_tools_router, "service", lambda: fake_service)
    user = SimpleNamespace(username="tester")

    status, detail = _detail(
        lambda: network_tools_router._run(
            user,
            "route-lookup",
            lambda: _raise(NetworkToolError("RTNETLINK answers: SECRET_ROUTE_DETAIL")),
        )
    )
    assert status == 422
    assert detail == {"code": "NETWORK_TOOL_FAILED", "message": "Network diagnostic failed"}
    assert "SECRET_ROUTE_DETAIL" not in str(detail)

    status, detail = _detail(
        lambda: network_tools_router._run(
            user,
            "ping",
            lambda: _raise(NetworkToolError("network diagnostic rate limit exceeded")),
        )
    )
    assert status == 429
    assert detail["message"] == "network diagnostic rate limit exceeded"


def test_dns_endpoint_replaces_raw_tool_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(network_tools_router, "_allow", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        network_tools_router,
        "_run",
        lambda *args, **kwargs: {"hostname": "example.com", "answers": [], "success": False, "error": "SECRET_DIG_STDERR"},
    )

    result = network_tools_router.dns(
        DnsLookupRequest(hostname="example.com", record_type="A"),
        user=SimpleNamespace(username="tester"),
    )

    assert result["error"] == "DNS lookup failed"
    assert "SECRET_DIG_STDERR" not in str(result)


def test_rpm_repository_publish_error_does_not_include_tool_stderr(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        rpm_adapter,
        "run_tool",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "SECRET_CREATEREPO_STDERR"),
    )
    adapter = rpm_adapter.RpmRepositoryAdapter(tmp_path)

    with pytest.raises(RuntimeError) as caught:
        adapter.publish(tmp_path / "generation", {"architectures": ["x86_64"]}, "testing", [])

    assert str(caught.value) == "createrepo_c failed for x86_64"
    assert "SECRET_CREATEREPO_STDERR" not in str(caught.value)


def test_detached_linux_update_state_does_not_persist_exception_text(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(linux_update_worker.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(linux_update_worker.os, "geteuid", lambda: 1000, raising=False)

    def fail_update(command, output):
        raise RuntimeError("SECRET_PACKAGE_MANAGER_DIAGNOSTIC")

    monkeypatch.setattr(linux_update_worker, "_run_privileged_update", fail_update)

    with pytest.raises(RuntimeError, match="SECRET_PACKAGE_MANAGER_DIAGNOSTIC"):
        linux_update_worker.run_update(
            tmp_path,
            "0123456789abcdef01234567",
            ["apt-get", "upgrade", "-y"],
        )

    state = read_update_state(tmp_path)
    assert state is not None
    assert state["status"] == "failed"
    assert state["error"] == "Linux update worker failed"
    assert "SECRET_PACKAGE_MANAGER_DIAGNOSTIC" not in (tmp_path / "status.json").read_text(encoding="utf-8")
