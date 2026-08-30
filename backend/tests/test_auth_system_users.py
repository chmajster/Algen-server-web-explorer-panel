from types import SimpleNamespace

from fastapi import HTTPException

from app import auth


def _pw(uid: int = 1000, shell: str = "/bin/bash", home: str = "/home/alice"):
    return SimpleNamespace(pw_uid=uid, pw_shell=shell, pw_dir=home)


def _mark_local(monkeypatch):
    monkeypatch.setattr(auth, "is_local_passwd_user", lambda username: True)


def test_login_allowed_for_interactive_system_user(monkeypatch):
    seen = []
    _mark_local(monkeypatch)
    monkeypatch.setattr(auth.pwd, "getpwnam", lambda username: seen.append(username) or _pw())

    user = auth.assert_login_allowed(" alice ")

    assert user.pw_dir == "/home/alice"
    assert seen == ["alice"]


def test_login_rejects_service_uid(monkeypatch):
    _mark_local(monkeypatch)
    monkeypatch.setattr(auth.pwd, "getpwnam", lambda username: _pw(uid=999))

    try:
        auth.assert_login_allowed("webnas")
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("service users should not be allowed to log in")


def test_uid_zero_break_glass_login_still_requires_an_interactive_account(monkeypatch):
    _mark_local(monkeypatch)
    monkeypatch.setattr(auth.pwd, "getpwnam", lambda username: _pw(uid=0, home="/root"))

    user = auth.assert_login_allowed("root")

    assert user.pw_uid == 0
    assert user.pw_dir == "/root"


def test_login_rejects_nologin_shell(monkeypatch):
    _mark_local(monkeypatch)
    monkeypatch.setattr(auth.pwd, "getpwnam", lambda username: _pw(shell="/usr/sbin/nologin"))

    try:
        auth.assert_login_allowed("alice")
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("nologin users should not be allowed to log in")


def test_login_rejects_unknown_local_user(monkeypatch):
    monkeypatch.setattr(auth, "is_local_passwd_user", lambda username: False)

    def missing(username):
        raise KeyError(username)

    monkeypatch.setattr(auth.pwd, "getpwnam", missing)

    try:
        auth.assert_login_allowed("missing")
    except HTTPException as exc:
        assert exc.status_code == 401
    else:
        raise AssertionError("unknown users should not be allowed to log in")
