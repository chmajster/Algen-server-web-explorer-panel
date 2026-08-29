"""Typed privileged boundary for Firewall Manager.

Only the three supported firewall executables are exposed and every argv shape is
validated again inside the root broker. No shell is involved.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from . import policy as base
from .extended_policy import dispatch as extended_dispatch
from .protocol import BrokerRequest, BrokerResponse, Operation

_BACKENDS = {"ufw": "ufw", "firewalld": "firewall-cmd", "nftables": "nft"}
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_./:@,+\-=\[\]{};]+$")
_ZONE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_INTERFACE = re.compile(r"^[A-Za-z0-9_.:@-]{1,32}$")


def _failure(request: BrokerRequest, message: str, *, policy: bool = True) -> BrokerResponse:
    return BrokerResponse(request_id=request.request_id, ok=False, exit_code=126 if policy else 127, error_code="POLICY_DENIED" if policy else "EXECUTION_FAILED", stderr=message[:1000])


def _result(request: BrokerRequest, result: base.CommandResult) -> BrokerResponse:
    return BrokerResponse(request_id=request.request_id, ok=result.exit_code == 0, exit_code=result.exit_code, stdout=result.stdout[:base.MAX_OUTPUT], stderr=result.stderr[:base.MAX_OUTPUT], error_code=None if result.exit_code == 0 else "COMMAND_FAILED")


def _clean_args(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 48:
        raise base.PolicyError("invalid firewall arguments")
    args: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 2048 or "\x00" in item or "\n" in item or "\r" in item:
            raise base.PolicyError("invalid firewall argument")
        args.append(item)
    return args


def _validate_ufw(args: list[str]) -> None:
    if args in (["status"], ["status", "numbered"], ["status", "verbose"], ["--force", "enable"], ["disable"], ["reload"]):
        return
    if len(args) == 3 and args[:2] == ["--force", "delete"] and args[2].isdigit() and 1 <= int(args[2]) <= 100000:
        return
    if not args or args[0] not in {"allow", "deny", "reject"}:
        raise base.PolicyError("unsupported ufw operation")
    if len(args) > 24:
        raise base.PolicyError("ufw rule is too complex")
    allowed_keywords = {"allow", "deny", "reject", "in", "out", "on", "proto", "tcp", "udp", "from", "to", "any", "port", "comment"}
    for index, item in enumerate(args):
        if item in allowed_keywords:
            continue
        if index > 0 and args[index - 1] == "comment":
            if len(item) > 120:
                raise base.PolicyError("ufw comment is too long")
            continue
        if not _SAFE_TOKEN.fullmatch(item):
            raise base.PolicyError("invalid ufw token")


def _validate_firewalld(args: list[str]) -> None:
    if args == ["--state"] or args == ["--reload"]:
        return
    if len(args) == 2 and args[1] == "--list-rich-rules" and args[0].startswith("--zone=") and _ZONE.fullmatch(args[0][7:]):
        return
    if len(args) == 3 and args[0] == "--permanent" and args[1].startswith("--zone=") and _ZONE.fullmatch(args[1][7:]):
        option = args[2]
        if option.startswith("--add-rich-rule="):
            rule = option[len("--add-rich-rule="):]
        elif option.startswith("--remove-rich-rule="):
            rule = option[len("--remove-rich-rule="):]
        else:
            raise base.PolicyError("unsupported firewalld operation")
        if not rule.startswith("rule ") or len(rule) > 1800 or any(character in rule for character in "\r\n\x00"):
            raise base.PolicyError("invalid firewalld rich rule")
        if not re.fullmatch(r'[A-Za-z0-9_./:@\-=" ]+', rule):
            raise base.PolicyError("unsupported firewalld rich rule token")
        return
    raise base.PolicyError("unsupported firewalld operation")


def _validate_nft(args: list[str]) -> None:
    if args in (["-j", "list", "ruleset"], ["list", "ruleset"]):
        return
    if args == ["add", "table", "inet", "webnas"]:
        return
    if args[:4] in (["add", "chain", "inet", "webnas"], ["add", "rule", "inet", "webnas"]):
        if len(args) < 5 or args[4] not in {"input", "output"}:
            raise base.PolicyError("nftables changes are limited to WebNAS input/output chains")
        for index, item in enumerate(args[5:], start=5):
            if index > 0 and args[index - 1] == "comment":
                if len(item) > 120 or any(ord(character) < 32 for character in item):
                    raise base.PolicyError("invalid nftables comment")
                continue
            if not _SAFE_TOKEN.fullmatch(item) and not _INTERFACE.fullmatch(item):
                raise base.PolicyError("invalid nftables token")
        return
    if len(args) == 7 and args[:4] == ["delete", "rule", "inet", "webnas"] and args[4] in {"input", "output"} and args[5] == "handle" and args[6].isdigit():
        return
    raise base.PolicyError("unsupported nftables operation")


def dispatch(request: BrokerRequest, *, runner: base.Runner | None = None) -> BrokerResponse:
    if request.operation != Operation.FIREWALL:
        return extended_dispatch(request, runner=runner)
    selected = runner or base._default_runner
    try:
        extra = set(request.payload) - {"backend", "args", "timeout"}
        if extra:
            raise base.PolicyError("unsupported firewall parameters")
        backend = request.payload.get("backend")
        if backend not in _BACKENDS:
            raise base.PolicyError("unsupported firewall backend")
        args = _clean_args(request.payload.get("args"))
        timeout = request.payload.get("timeout", 15)
        if not isinstance(timeout, (int, float)) or not 1 <= float(timeout) <= 30:
            raise base.PolicyError("invalid firewall timeout")
        if backend == "ufw":
            _validate_ufw(args)
        elif backend == "firewalld":
            _validate_firewalld(args)
        else:
            _validate_nft(args)
        result = selected([base._resolve_tool(_BACKENDS[backend]), *args], None, float(timeout))
    except base.PolicyError as error:
        return _failure(request, str(error))
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return _failure(request, type(error).__name__, policy=False)
    return _result(request, result)
