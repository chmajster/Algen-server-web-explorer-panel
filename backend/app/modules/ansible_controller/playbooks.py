from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .security import sensitive_key


BLOCKED_LOCAL_KEYS = {"local_action"}
LOCAL_ADDRESSES = {"localhost", "127.0.0.1", "::1"}
RISK_MODULES = {"shell", "command", "raw", "script"}
DESTRUCTIVE_RE = re.compile(r"(?i)\b(remove|absent|delete|purge|reboot|shutdown|poweroff|firewall|iptables|nftables|sudoers|userdel|network)\b")


def _module_name(key: str) -> str:
    return key.rsplit(".", 1)[-1]


def _walk(value: Any, path: str = "$", warnings: list[dict[str, str]] | None = None, blocked: list[dict[str, str]] | None = None) -> None:
    warnings = warnings if warnings is not None else []
    blocked = blocked if blocked is not None else []
    if isinstance(value, dict):
        for raw_key, nested in value.items():
            key = str(raw_key)
            location = f"{path}.{key}"
            normalized = key.casefold()
            if normalized in BLOCKED_LOCAL_KEYS:
                blocked.append({"code": "LOCAL_EXECUTION", "message": f"{key} is blocked", "path": location})
            if normalized == "connection" and str(nested).casefold() == "local":
                blocked.append({"code": "LOCAL_CONNECTION", "message": "connection: local is blocked", "path": location})
            if normalized == "delegate_to" and str(nested).casefold() in LOCAL_ADDRESSES:
                blocked.append({"code": "LOCAL_DELEGATION", "message": "delegation to the controller is blocked", "path": location})
            if normalized in {"action_plugins", "callback_plugins", "connection_plugins", "lookup_plugins"}:
                blocked.append({"code": "CUSTOM_PLUGIN", "message": "user supplied local plugins are blocked", "path": location})
            if _module_name(normalized) in RISK_MODULES:
                warnings.append({"code": "COMMAND_MODULE", "message": f"module {key} executes commands", "path": location})
            if normalized == "become" and nested is True:
                warnings.append({"code": "BECOME", "message": "privilege escalation is enabled", "path": location})
            if normalized == "hosts" and str(nested).strip() == "all":
                warnings.append({"code": "ALL_HOSTS", "message": "play targets all hosts", "path": location})
            if sensitive_key(key):
                warnings.append({"code": "POSSIBLE_SECRET", "message": f"variable {key} may contain a secret", "path": location})
            if isinstance(nested, str):
                if re.search(r"(?i)lookup\s*\(\s*['\"](?:ansible\.builtin\.)?pipe['\"]", nested) or re.search(r"(?i)\bwith_pipe\b", normalized):
                    blocked.append({"code": "PIPE_LOOKUP", "message": "pipe lookup is blocked", "path": location})
                if DESTRUCTIVE_RE.search(nested):
                    warnings.append({"code": "DESTRUCTIVE_OPERATION", "message": "possibly destructive operation", "path": location})
            _walk(nested, location, warnings, blocked)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _walk(nested, f"{path}[{index}]", warnings, blocked)


def analyze_playbook(content: str, *, max_documents: int = 20, max_tasks: int = 10_000) -> dict[str, Any]:
    if len(content.encode("utf-8")) > 2_000_000:
        raise ValueError("playbook exceeds 2 MiB")
    try:
        documents = list(yaml.safe_load_all(content))
    except yaml.MarkedYAMLError as error:
        mark = getattr(error, "problem_mark", None)
        return {"ok": False, "errors": [{"code": "INVALID_YAML", "message": str(error), "line": (mark.line + 1) if mark else None}], "warnings": [], "blocked": [], "task_count": 0}
    if len(documents) > max_documents:
        raise ValueError("playbook contains too many YAML documents")
    if not documents or any(document is not None and not isinstance(document, list) for document in documents):
        return {"ok": False, "errors": [{"code": "INVALID_PLAYBOOK", "message": "each playbook document must be a list of plays"}], "warnings": [], "blocked": [], "task_count": 0}
    task_count = 0
    for document in documents:
        for play in document or []:
            if not isinstance(play, dict):
                continue
            for key in ("tasks", "pre_tasks", "post_tasks", "handlers"):
                if isinstance(play.get(key), list):
                    task_count += len(play[key])
    if task_count > max_tasks:
        raise ValueError("playbook contains too many tasks")
    warnings: list[dict[str, str]] = []
    blocked: list[dict[str, str]] = []
    _walk(documents, warnings=warnings, blocked=blocked)
    unique_warnings = list({json.dumps(item, sort_keys=True): item for item in warnings}.values())
    unique_blocked = list({json.dumps(item, sort_keys=True): item for item in blocked}.values())
    return {"ok": not unique_blocked, "errors": [], "warnings": unique_warnings, "blocked": unique_blocked, "task_count": task_count, "documents": len(documents)}


def safe_project_path(project_root: Path, relative: str) -> Path:
    if not relative or "\x00" in relative or Path(relative).is_absolute():
        raise ValueError("project path must be relative")
    root = project_root.resolve(strict=False)
    target = (root / relative).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as error:
        raise ValueError("project path escapes its project") from error
    return target


def build_ansible_playbook_args(
    playbook: Path,
    inventory: Path,
    *,
    limit: str = "",
    tags: list[str] | None = None,
    skip_tags: list[str] | None = None,
    check: bool = False,
    diff: bool = False,
    verbosity: int = 0,
    forks: int = 10,
    extra_vars_file: Path | None = None,
) -> list[str]:
    if playbook.suffix not in {".yml", ".yaml"} or not inventory.is_file():
        raise ValueError("invalid managed playbook or inventory path")
    args = ["ansible-playbook", "--inventory", str(inventory), "--forks", str(max(1, min(forks, 100)))]
    if limit:
        if not re.fullmatch(r"[A-Za-z0-9_.,:&!*-]{1,512}", limit):
            raise ValueError("invalid Ansible limit")
        args.extend(["--limit", limit])
    if tags:
        args.extend(["--tags", ",".join(tags)])
    if skip_tags:
        args.extend(["--skip-tags", ",".join(skip_tags)])
    if check:
        args.append("--check")
    if diff:
        args.append("--diff")
    if verbosity:
        args.append("-" + "v" * max(1, min(verbosity, 4)))
    if extra_vars_file:
        args.extend(["--extra-vars", f"@{extra_vars_file}"])
    args.append(str(playbook))
    return args


def syntax_check_args(playbook: Path, inventory: Path) -> list[str]:
    return ["ansible-playbook", "--inventory", str(inventory), "--syntax-check", str(playbook)]


def validation_commands(playbook: Path, inventory: Path) -> list[list[str]]:
    """Return the complete, fixed pre-flight command set for a managed playbook."""
    if playbook.suffix not in {".yml", ".yaml"} or not inventory.is_file():
        raise ValueError("invalid managed playbook or inventory path")
    base = ["ansible-playbook", "--inventory", str(inventory)]
    return [
        [*base, "--syntax-check", str(playbook)],
        [*base, "--list-hosts", str(playbook)],
        [*base, "--list-tasks", str(playbook)],
        [*base, "--list-tags", str(playbook)],
    ]
