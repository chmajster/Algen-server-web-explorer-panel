from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.app_store import api as app_store_api
from app.app_store import state as app_state
from app.ldap_authentication.repository import LdapAuthenticationRepository
from app.modules.providers import home_assistant as home_assistant_module
from app.modules.providers.home_assistant import HomeAssistantProvider
from app.modules.webhook_manager.service import WebhookManagerService


def test_app_state_path_rejects_traversal_and_separators(monkeypatch, tmp_path):
    monkeypatch.setattr(app_state, "APP_STATE_DIR", tmp_path / "apps")
    for app_id in ("../settings/deployment", "../../secret", "nested/app", r"nested\\app", ".hidden", ""):
        with pytest.raises(ValueError):
            app_state.app_state_path(app_id)
    assert app_state.app_state_path("samba") == (tmp_path / "apps" / "samba.json").resolve(strict=False)


def test_generic_app_config_endpoint_rejects_unknown_app(monkeypatch):
    monkeypatch.setattr(app_store_api, "authorize", lambda *args, **kwargs: None)
    user = SimpleNamespace(username="alice")
    with pytest.raises(HTTPException) as caught:
        app_store_api.get_config_app("../../settings/deployment", user=user)
    assert caught.value.status_code == 404


def test_home_assistant_inspect_rejects_non_object_payload(monkeypatch):
    provider = object.__new__(HomeAssistantProvider)
    monkeypatch.setattr(home_assistant_module.shutil, "which", lambda name: "/usr/bin/docker")
    provider._run = lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, '["unexpected"]', "")  # type: ignore[method-assign]
    assert provider._inspect() is None


def test_ldap_json_decoder_preserves_expected_container_shape():
    decode = LdapAuthenticationRepository._json
    assert decode('"admins"', []) == []
    assert decode('{"group":"admins"}', []) == []
    assert decode('["admins"]', []) == ["admins"]
    assert decode('["admins"]', {}) == {}
    assert decode('{"group":"admins"}', {}) == {"group": "admins"}


def test_webhook_json_decoder_preserves_expected_container_shape():
    decode = WebhookManagerService._decode_json
    assert decode('"event"', []) == []
    assert decode('{"event":"x"}', []) == []
    assert decode('["event"]', []) == ["event"]
    assert decode('["header"]', {}) == {}
    assert decode('{"X-Test":"1"}', {}) == {"X-Test": "1"}
