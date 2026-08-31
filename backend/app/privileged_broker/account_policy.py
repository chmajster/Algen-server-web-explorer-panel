from __future__ import annotations

from typing import Any

from . import policy as base
from .protocol import BrokerRequest, BrokerResponse, Operation


ACCOUNT_TOOLS = {
    "useradd",
    "usermod",
    "userdel",
    "groupadd",
    "groupmod",
    "groupdel",
    "gpasswd",
    "chpasswd",
    "chage",
    "passwd",
}
SAFE_SHELLS = {
    "/bin/bash", "/bin/sh", "/bin/dash", "/bin/false",
    "/usr/bin/bash", "/usr/bin/sh", "/usr/bin/dash", "/usr/bin/zsh",
    "/usr/bin/fish", "/usr/bin/false", "/usr/sbin/nologin", "/sbin/nologin",
}


def _failure(request: BrokerRequest, error: Exception, *, policy: bool) -> BrokerResponse:
    return BrokerResponse(
        request_id=request.request_id,
        ok=False,
        exit_code=126 if policy else 127,
        error_code="POLICY_DENIED" if policy else "EXECUTION_FAILED",
        stderr=str(error)[:2000],
    )


def _result(request: BrokerRequest, result: base.CommandResult) -> BrokerResponse:
    return BrokerResponse(
        request_id=request.request_id,
        ok=result.exit_code == 0,
        exit_code=result.exit_code,
        stdout=result.stdout[-base.MAX_OUTPUT:],
        stderr=result.stderr[-base.MAX_OUTPUT:],
        error_code=None if result.exit_code == 0 else "COMMAND_FAILED",
    )


def _payload_keys(payload: dict[str, Any], allowed: set[str]) -> None:
    extra = set(payload) - allowed
    if extra:
        raise base.PolicyError(f"unsupported parameters: {', '.join(sorted(extra))}")


def _token(value: Any, name: str, *, limit: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        raise base.PolicyError(f"invalid {name}")
    if any(ord(character) < 32 for character in value):
        raise base.PolicyError(f"invalid {name}")
    return value


def _readable_user(value: Any) -> str:
    username = _token(value, "user", limit=64)
    if not base.NAME_RE.fullmatch(username):
        raise base.PolicyError("invalid user name")
    return username


def _csv_names(value: str, kind: str) -> None:
    items = value.split(",")
    if not items or any(not item for item in items):
        raise base.PolicyError(f"invalid {kind} list")
    for item in items:
        base._name(item, kind)


def _account(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    _payload_keys(payload, {"tool", "args", "stdin"})
    tool = _token(payload.get("tool"), "account tool", limit=16)
    args = payload.get("args") or []
    stdin = payload.get("stdin")
    if tool not in ACCOUNT_TOOLS or not isinstance(args, list) or len(args) > 24:
        raise base.PolicyError("unsupported account operation")
    if any(not isinstance(item, str) or len(item) > 512 or "\x00" in item for item in args):
        raise base.PolicyError("invalid account arguments")

    # Read-only shadow-backed status calls. They are intentionally allowed for
    # protected/system accounts because they do not mutate credentials.
    if tool == "passwd" and len(args) == 2 and args[0] in {"-S", "--status"} and stdin is None:
        username = _readable_user(args[1])
        return runner([base._resolve_tool("passwd"), "-S", username], None, 60)
    if tool == "chage" and len(args) == 2 and args[0] in {"-l", "--list"} and stdin is None:
        username = _readable_user(args[1])
        return runner([base._resolve_tool("chage"), "-l", username], None, 60)

    if tool == "chpasswd":
        if args or not isinstance(stdin, str) or len(stdin) > 4096 or len(stdin.splitlines()) != 1 or ":" not in stdin:
            raise base.PolicyError("chpasswd requires one credential record")
        username, password = stdin.rstrip("\n").split(":", 1)
        base._name(username, "user")
        if not password or any(character in password for character in "\r\n"):
            raise base.PolicyError("invalid password")
        return runner([base._resolve_tool(tool)], stdin, 60)
    if stdin is not None:
        raise base.PolicyError("stdin is not accepted for this account operation")

    if tool == "useradd":
        if not args:
            raise base.PolicyError("useradd target is required")
        username = base._name(args[-1], "user")
        options = args[:-1]
        index = 0
        while index < len(options):
            flag = options[index]
            if flag in {"--user-group", "--create-home"}:
                index += 1
                continue
            if flag in {"--shell", "--comment", "--groups"} and index + 1 < len(options):
                value = _token(options[index + 1], flag, limit=256)
                if flag == "--shell" and value not in SAFE_SHELLS:
                    raise base.PolicyError("unsupported login shell")
                if flag == "--groups":
                    _csv_names(value, "group")
                index += 2
                continue
            raise base.PolicyError("unsupported useradd option")
        return runner([base._resolve_tool(tool), *options, username], None, 60)

    if tool == "usermod":
        if not args:
            raise base.PolicyError("usermod target is required")
        username = base._name(args[-1], "user")
        options = args[:-1]
        index = 0
        seen_lock = False
        while index < len(options):
            flag = options[index]
            if flag in {"--append", "--lock", "--unlock"}:
                if flag in {"--lock", "--unlock"}:
                    if seen_lock:
                        raise base.PolicyError("conflicting user lock option")
                    seen_lock = True
                index += 1
                continue
            if flag in {"--shell", "--comment", "--groups"} and index + 1 < len(options):
                value = _token(options[index + 1], flag, limit=256)
                if flag == "--shell" and value not in SAFE_SHELLS:
                    raise base.PolicyError("unsupported login shell")
                if flag == "--groups":
                    _csv_names(value, "group")
                index += 2
                continue
            raise base.PolicyError("unsupported usermod option")
        if not options:
            raise base.PolicyError("usermod requires a change")
        return runner([base._resolve_tool(tool), *options, username], None, 60)

    if tool == "userdel":
        if len(args) == 1:
            username = base._name(args[0], "user")
            validated = [username]
        elif len(args) == 2 and args[0] == "--remove":
            username = base._name(args[1], "user")
            validated = ["--remove", username]
        else:
            raise base.PolicyError("unsupported userdel arguments")
        return runner([base._resolve_tool(tool), *validated], None, 60)

    if tool == "chage":
        if len(args) != 3 or args[0] != "-d" or args[1] not in {"0", "-1"}:
            raise base.PolicyError("unsupported chage arguments")
        username = base._name(args[2], "user")
        return runner([base._resolve_tool(tool), "-d", args[1], username], None, 60)

    if tool == "gpasswd":
        if len(args) != 3 or args[0] != "--delete":
            raise base.PolicyError("unsupported gpasswd arguments")
        username = base._name(args[1], "user")
        groupname = base._name(args[2], "group")
        return runner([base._resolve_tool(tool), "--delete", username, groupname], None, 60)

    if tool == "groupadd":
        if len(args) not in {1, 2} or (len(args) == 2 and args[0] != "--system"):
            raise base.PolicyError("unsupported groupadd arguments")
        groupname = base._name(args[-1], "group")
        validated = (["--system"] if len(args) == 2 else []) + [groupname]
        return runner([base._resolve_tool(tool), *validated], None, 60)

    if tool == "groupmod":
        if len(args) != 3 or args[0] != "--new-name":
            raise base.PolicyError("unsupported groupmod arguments")
        new_name = base._name(args[1], "group")
        old_name = base._name(args[2], "group")
        return runner([base._resolve_tool(tool), "--new-name", new_name, old_name], None, 60)

    if tool == "groupdel":
        if len(args) != 1:
            raise base.PolicyError("unsupported groupdel arguments")
        groupname = base._name(args[0], "group")
        return runner([base._resolve_tool(tool), groupname], None, 60)

    raise base.PolicyError("account operation is not enabled")


def dispatch(request: BrokerRequest, *, runner: base.Runner | None = None) -> BrokerResponse:
    if request.operation != Operation.ACCOUNT:
        return _failure(request, base.PolicyError("unsupported account policy operation"), policy=True)
    try:
        result = _account(request.payload, runner or base._default_runner)
    except base.PolicyError as error:
        return _failure(request, error, policy=True)
    except (OSError, RuntimeError) as error:
        return _failure(request, error, policy=False)
    return _result(request, result)
