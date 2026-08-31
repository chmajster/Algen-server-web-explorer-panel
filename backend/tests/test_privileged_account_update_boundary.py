from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_shadow_backed_account_status_is_brokered() -> None:
    runtime = (ROOT / "backend" / "app" / "privileged_broker" / "runtime.py").read_text(encoding="utf-8")
    policy = (ROOT / "backend" / "app" / "privileged_broker" / "account_policy.py").read_text(encoding="utf-8")
    server = (ROOT / "backend" / "app" / "privileged_broker" / "server.py").read_text(encoding="utf-8")

    assert '"passwd"' in runtime
    assert "Operation.ACCOUNT" in runtime
    assert 'args[0] in {"-S", "--status"}' in policy
    assert 'args[0] in {"-l", "--list"}' in policy
    assert "base._name(username, \"user\")" in policy
    assert "request.operation == Operation.ACCOUNT" in server
    assert "dispatch_account(request)" in server


def test_transient_update_uses_root_system_manager_without_interactive_auth() -> None:
    policy = (ROOT / "backend" / "app" / "privileged_broker" / "update_policy.py").read_text(encoding="utf-8")
    server = (ROOT / "backend" / "app" / "privileged_broker" / "server.py").read_text(encoding="utf-8")

    assert 'base._resolve_tool("systemd-run")' in policy
    assert '"--system"' in policy
    assert '"--no-ask-password"' in policy
    assert "request.operation == Operation.UPDATE_SERVICE" in server
    assert "dispatch_update(request)" in server
