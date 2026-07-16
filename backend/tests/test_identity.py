from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request, Response

from app.identity import linux_accounts
from app.identity.models import GroupPolicy, GroupPolicyRequest, Role, UserCreateRequest, UserPolicy, UserPolicyRequest
from app.identity.permissions import Permission, normalize_permission, require_permission
from app.identity.repository import IdentityRepository
from app.identity.router import _reauth
from app.identity.service import IdentityService
from app.security import SessionUser, create_session


def account(name: str, uid: int, gid: int, shell: str = "/bin/bash"):
    return SimpleNamespace(pw_name=name, pw_uid=uid, pw_gid=gid, pw_dir=f"/home/{name}", pw_shell=shell, pw_gecos=name.title())


def group(name: str, gid: int, members: list[str] | None = None):
    return SimpleNamespace(gr_name=name, gr_gid=gid, gr_mem=members or [], gr_passwd="x")


def fake_accounts(monkeypatch, users: list, groups: list) -> None:
    def get_user(name):
        found = next((item for item in users if item.pw_name == name), None)
        if found is None:
            raise KeyError(name)
        return found

    def get_group(name):
        found = next((item for item in groups if item.gr_name == name), None)
        if found is None:
            raise KeyError(name)
        return found

    def get_gid(gid):
        found = next((item for item in groups if item.gr_gid == gid), None)
        if found is None:
            raise KeyError(gid)
        return found

    monkeypatch.setattr(linux_accounts.pwd, "getpwall", lambda: users)
    monkeypatch.setattr(linux_accounts.pwd, "getpwnam", get_user)
    monkeypatch.setattr(linux_accounts.grp, "getgrall", lambda: groups)
    monkeypatch.setattr(linux_accounts.grp, "getgrnam", get_group)
    monkeypatch.setattr(linux_accounts.grp, "getgrgid", get_gid)
    monkeypatch.setattr(linux_accounts, "_account_status", lambda username: (False, False))


@pytest.mark.parametrize(
    ("users", "groups", "username"),
    [
        ([account("root", 0, 0)], [group("root", 0)], "root"),
        ([account("alice", 1001, 100)], [group("users", 100), group("sudo", 27, ["alice"])], "alice"),
        ([account("alice", 1001, 100)], [group("users", 100), group("wheel", 10, ["alice"])], "alice"),
        ([account("alice", 1001, 27)], [group("sudo", 27)], "alice"),
    ],
)
def test_detects_linux_administrators_including_primary_group(monkeypatch, users, groups, username):
    fake_accounts(monkeypatch, users, groups)
    assert linux_accounts.is_linux_admin(username) is True


def test_effective_permissions_include_group_sources_and_deny_wins(monkeypatch, tmp_path: Path):
    users = [account("root", 0, 0), account("alice", 1001, 100)]
    groups = [group("root", 0), group("users", 100), group("ops", 1100, ["alice"])]
    fake_accounts(monkeypatch, users, groups)
    repository = IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json")
    repository.save_group_policy(GroupPolicy(groupname="ops", allow=[Permission.SERVICES_RESTART.value, Permission.SERVICES_VIEW.value]), "admin")
    repository.save_user_policy(UserPolicy(username="alice", role=Role.user, allow=[Permission.DNS_VIEW.value], deny=[Permission.SERVICES_RESTART.value]), "admin")
    profile = IdentityService(repository).access_profile("alice")

    assert Permission.SERVICES_VIEW.value in profile["permissions"]
    assert Permission.DNS_VIEW.value in profile["permissions"]
    assert Permission.SERVICES_RESTART.value not in profile["permissions"]
    assert profile["permission_sources"][Permission.SERVICES_VIEW.value] == ["group:ops"]
    assert "deny:user" in profile["permission_sources"][Permission.SERVICES_RESTART.value]


def test_unknown_permissions_and_allow_deny_overlap_are_rejected():
    with pytest.raises(ValueError, match="unknown permission"):
        UserPolicy(username="alice", allow=["system.root_shell"])
    with pytest.raises(ValueError, match="both allowed and denied"):
        UserPolicy(username="alice", allow=[Permission.SERVICES_VIEW.value], deny=[Permission.SERVICES_VIEW.value])
    assert normalize_permission("rbac.manage") == Permission.ACCESS_MANAGE_ROLES.value


def test_linux_admin_cannot_be_degraded_or_denied(monkeypatch, tmp_path: Path):
    users = [account("root", 0, 0)]
    fake_accounts(monkeypatch, users, [group("root", 0)])
    service = IdentityService(IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json"))

    with pytest.raises(HTTPException) as error:
        service.save_user_policy("root", UserPolicyRequest(admin_password="pam", role=Role.user), "root")
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        service.save_user_policy("root", UserPolicyRequest(admin_password="pam", role=Role.admin, deny=[Permission.FILES_DELETE.value]), "root")
    assert error.value.detail["code"] == "LINUX_ADMIN_COMPATIBILITY"


def test_last_effective_administrator_is_protected(monkeypatch, tmp_path: Path):
    users = [account("alice", 1001, 100), account("bob", 1002, 100)]
    groups = [group("users", 100)]
    fake_accounts(monkeypatch, users, groups)
    repository = IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json")
    repository.save_user_policy(UserPolicy(username="alice", role=Role.admin), "bootstrap")
    service = IdentityService(repository)

    with pytest.raises(HTTPException) as error:
        service.save_user_policy("alice", UserPolicyRequest(admin_password="pam", role=Role.operator), "alice")

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "LAST_ADMIN_PROTECTION"


def test_group_deny_cannot_remove_last_administrator(monkeypatch, tmp_path: Path):
    users = [account("alice", 1001, 100)]
    groups = [group("users", 100), group("team", 1100, ["alice"])]
    fake_accounts(monkeypatch, users, groups)
    repository = IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json")
    repository.save_user_policy(UserPolicy(username="alice", role=Role.admin), "bootstrap")
    service = IdentityService(repository)

    with pytest.raises(HTTPException) as error:
        service.save_group_policy("team", GroupPolicyRequest(admin_password="pam", deny=[Permission.ACCESS_MANAGE_ROLES.value]), "alice")

    assert error.value.detail["code"] == "LAST_ADMIN_PROTECTION"


def test_legacy_rbac_migration_is_idempotent_and_creates_backup(tmp_path: Path):
    legacy = tmp_path / "rbac.json"
    legacy.write_text(json.dumps({"alice": {"role": "operator", "allow": ["audit.view", "unknown.old"], "deny": ["docker.operate"]}}), encoding="utf-8")
    path = tmp_path / "identity.sqlite3"

    first = IdentityRepository(path, legacy_path=legacy)
    second = IdentityRepository(path, legacy_path=legacy)
    policy = second.user_policy("alice")

    assert policy and policy.role == Role.operator
    assert policy.allow == [Permission.AUDIT_VIEW_ALL.value]
    assert policy.deny == [Permission.DOCKER_CONTAINERS.value]
    assert legacy.with_name("rbac.json.identity-v1.bak").is_file()
    assert len([item for item in first.changes() if item.subject_type == "migration"]) == 1


def test_permission_dependency_requires_csrf_for_mutation(monkeypatch):
    response = Response()
    csrf = create_session(response, "alice")
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    monkeypatch.setattr("app.identity.permissions.has_permission", lambda username, permission: True)
    dependency = require_permission(Permission.USERS_CREATE)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [(b"cookie", cookie.encode("latin-1"))]})

    with pytest.raises(HTTPException) as error:
        dependency(request)
    assert error.value.status_code == 403
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [(b"cookie", cookie.encode("latin-1")), (b"x-csrf-token", csrf.encode("latin-1"))]})
    assert dependency(request).username == "alice"


def test_high_risk_reauthentication_uses_pam_without_persisting_password(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr("app.identity.router.authenticate", lambda username, password: calls.append((username, password)))
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("127.0.0.1", 1)})
    _reauth(request, SessionUser(username="admin", csrf_token="csrf"), "temporary-secret", "user_delete", "alice")
    assert calls == [("admin", "temporary-secret")]


def test_linux_commands_use_closed_argument_arrays_and_password_stdin(monkeypatch):
    users = [account("alice", 1001, 100)]
    groups = [group("users", 100)]
    fake_accounts(monkeypatch, users, groups)
    calls: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(linux_accounts, "_tool", lambda name: f"/usr/sbin/{name}")
    monkeypatch.setattr(linux_accounts, "_run", lambda args, input_text=None, timeout=60: calls.append((args, input_text)) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    linux_accounts.change_password("alice", "new-password", True)

    assert calls[0][0] == ["/usr/sbin/chpasswd"]
    assert calls[0][1] == "alice:new-password\n"
    assert all("sh" not in command[0] for command, _ in calls)


def test_group_rename_moves_application_policy(monkeypatch, tmp_path: Path):
    users = [account("root", 0, 0), account("alice", 1001, 100)]
    groups = [group("root", 0), group("users", 100), group("ops", 1100, ["alice"]), group("support", 1101)]
    fake_accounts(monkeypatch, users, groups)
    repository = IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json")
    repository.save_group_policy(GroupPolicy(groupname="ops", allow=[Permission.SERVICES_VIEW.value]), "root")
    monkeypatch.setattr(linux_accounts, "rename_group", lambda old, new: None)
    service = IdentityService(repository)

    result = service.rename_group("ops", "support", "root")

    assert result["allow"] == [Permission.SERVICES_VIEW.value]
    assert repository.group_policy("ops") is None
    assert repository.group_policy("support") is not None


def test_proxmox_guard_is_checked_before_creating_linux_user(monkeypatch):
    payload = UserCreateRequest(username="alice", password="secret", admin_password="pam")
    monkeypatch.setattr(linux_accounts.pwd, "getpwnam", lambda username: (_ for _ in ()).throw(KeyError(username)))
    monkeypatch.setattr(linux_accounts, "assert_admin_user_allowed", lambda *args: (_ for _ in ()).throw(HTTPException(403, "Proxmox Safe Mode")))
    monkeypatch.setattr(linux_accounts, "_run", lambda *args, **kwargs: pytest.fail("no system command may run after a Proxmox denial"))

    with pytest.raises(HTTPException) as error:
        linux_accounts.create_user(payload)
    assert error.value.status_code == 403


def test_operator_cannot_modify_an_application_administrator(monkeypatch, tmp_path: Path):
    users = [account("admin", 1001, 100), account("operator", 1002, 100)]
    groups = [group("users", 100)]
    fake_accounts(monkeypatch, users, groups)
    repository = IdentityRepository(tmp_path / "identity.sqlite3", legacy_path=tmp_path / "missing.json")
    repository.save_user_policy(UserPolicy(username="admin", role=Role.admin), "bootstrap")
    repository.save_user_policy(UserPolicy(username="operator", role=Role.operator), "bootstrap")
    service = IdentityService(repository)

    with pytest.raises(HTTPException) as error:
        service.set_user_lock("admin", "operator", current_username="operator", locked=True)
    assert error.value.detail["code"] == "ADMIN_TARGET_PROTECTED"


def test_new_and_legacy_identity_routes_are_registered():
    from app.main import app

    routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    assert ("/api/identity/users", "GET") in routes
    assert ("/api/identity/groups/{groupname}/policy", "PUT") in routes
    assert ("/api/admin/users", "GET") in routes
    assert ("/api/admin/groups/{groupname}/members/{username}", "DELETE") in routes
    assert ("/api/rbac/assignments/{username}", "PUT") in routes
