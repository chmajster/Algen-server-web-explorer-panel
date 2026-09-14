import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.privileged_broker import extended_policy, policy, runtime, update_policy


@pytest.mark.parametrize("module", [update_policy, extended_policy])
@pytest.mark.parametrize("payload", [
    {"revision": "main"}, {"revision": "a" * 40 + "; id"}, {"revision": 123},
    {"revision": "a" * 40, "update_config": True},
    {"revision": "a" * 40, "npm_audit_fix": True},
])
def test_broker_rejects_invalid_pins_before_side_effects(monkeypatch, module, payload):
    monkeypatch.setattr(module, "get_config", lambda: pytest.fail("must validate before filesystem work"))
    with pytest.raises(policy.PolicyError):
        module._update_service(payload, lambda *args: pytest.fail("must not execute"))


@pytest.mark.parametrize("module", [update_policy, extended_policy])
def test_broker_runner_pins_exact_archive_without_regenerating_config(monkeypatch, tmp_path, module):
    config = SimpleNamespace(paths=SimpleNamespace(data_dir=str(tmp_path / "data"), log_dir=str(tmp_path / "logs")))
    monkeypatch.setattr(module, "get_config", lambda: config)
    monkeypatch.setattr(module, "Path", lambda value: tmp_path / "runtime" if str(value) == "/run/webnas-update" else Path(value))
    monkeypatch.setattr(module.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=1000))
    monkeypatch.setattr(module.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=1000))
    monkeypatch.setattr(policy, "_resolve_tool", lambda value: "/usr/bin/" + value)
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"#!/usr/bin/env bash\nexit 0\n"))
    commands = []
    result = module._update_service({"revision": "a" * 40}, lambda *args: commands.append(args) or policy.CommandResult(0, "", ""))
    assert result.exit_code == 0
    runner = Path(commands[0][0][-1]).read_text()
    assert "--revision " + "a" * 40 in runner
    assert "--update-config" not in runner
    assert "--npm-audit-fix" not in runner
    assert "--existing-action update --yes" in runner


def test_runtime_sends_optional_revision_without_changing_normal_payload():
    calls = []
    client = SimpleNamespace(require=lambda *args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(stdout=json.dumps({"unit": "webnas-test.service"})))
    runtime.update_service(update_config=False, npm_audit_fix=False, actor="admin", client=client)
    assert "revision" not in calls[0][0][1]
    runtime.update_service(update_config=False, npm_audit_fix=False, actor="admin", client=client, revision="a" * 40)
    assert calls[1][0][1]["revision"] == "a" * 40
