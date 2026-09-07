from __future__ import annotations

import ipaddress
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from app.config import get_config
from app.core.redaction import redact_text

from . import policy as base
from .protocol import BrokerRequest, BrokerResponse


IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+,-]{0,255}$")
SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
PORT_RE = re.compile(r"^(?:[0-9.:[\]]+:)?[1-9][0-9]{0,4}(?:-[1-9][0-9]{0,4})?:[1-9][0-9]{0,4}(?:-[1-9][0-9]{0,4})?(?:/(?:tcp|udp))?$")
DURATION_RE = re.compile(r"^(?:0s|[1-9][0-9]{0,7}[smhd])$")
SIGNALS = {"KILL", "TERM", "HUP", "INT", "QUIT", "USR1", "USR2"}
SYSTEM_NETWORKS = {"host", "none"}
COMPOSE_SERVICE_FIELDS = {
    "image", "container_name", "hostname", "restart", "ports", "volumes", "environment", "networks",
    "depends_on", "labels", "read_only", "tmpfs", "init", "mem_limit", "cpus", "pids_limit", "working_dir", "user",
}
COMPOSE_ROOT_FIELDS = {"name", "version", "services", "networks", "volumes"}
COMPOSE_DEFINITION_FIELDS = {"name", "driver", "internal", "labels", "ipam", "external"}
RUN_VALUE_FLAGS = {
    "--name", "--restart", "--network", "--label", "--env-file", "--network-alias", "--hostname", "--entrypoint",
    "--workdir", "--user", "--publish", "--mount", "--cpus", "--cpu-shares", "--cpuset-cpus", "--cpu-period",
    "--cpu-quota", "--memory", "--memory-swap", "--memory-reservation", "--memory-swappiness", "--shm-size",
    "--pids-limit", "--blkio-weight", "--oom-score-adj", "--ulimit", "--health-cmd", "--health-interval",
    "--health-timeout", "--health-retries", "--health-start-period",
}
RUN_BOOL_FLAGS = {"-d", "--init", "--read-only", "--oom-kill-disable"}


def _failure(request: BrokerRequest, error: Exception, *, policy: bool) -> BrokerResponse:
    return BrokerResponse(
        request_id=request.request_id,
        ok=False,
        exit_code=126 if policy else 127,
        error_code="POLICY_DENIED" if policy else "EXECUTION_FAILED",
        stderr=redact_text(error, limit=2000),
    )


def _result(request: BrokerRequest, result: base.CommandResult) -> BrokerResponse:
    return BrokerResponse(
        request_id=request.request_id,
        ok=result.exit_code == 0,
        exit_code=result.exit_code,
        stdout=redact_text(result.stdout, limit=base.MAX_OUTPUT),
        stderr=redact_text(result.stderr, limit=base.MAX_OUTPUT),
        error_code=None if result.exit_code == 0 else "COMMAND_FAILED",
    )


def _token(value: Any, label: str, *, limit: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or "\x00" in value:
        raise base.PolicyError(f"invalid {label}")
    if any(ord(character) < 32 for character in value):
        raise base.PolicyError(f"invalid {label}")
    return value


def _identifier(value: str, label: str = "identifier") -> str:
    if value.startswith("-") or not IDENTIFIER_RE.fullmatch(value):
        raise base.PolicyError(f"invalid Docker {label}")
    return value


def _image(value: str) -> str:
    if value.startswith("-") or not IMAGE_RE.fullmatch(value):
        raise base.PolicyError("invalid Docker image reference")
    return value


def _data_root() -> Path:
    try:
        return Path(get_config().paths.data_dir).resolve(strict=False)
    except Exception:  # noqa: BLE001 - fail closed to the standard appliance data directory.
        return Path("/var/lib/webnas")


def _allowed_bind_roots() -> list[Path]:
    roots = [Path("/srv"), Path("/mnt"), Path("/media"), _data_root()]
    try:
        configured = get_config().paths.allowed_roots
    except Exception:  # noqa: BLE001 - fixed roots remain available.
        configured = []
    for raw in configured:
        path = Path(str(raw))
        if path.is_absolute():
            roots.append(path.resolve(strict=False))
    return roots


def _within(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve(strict=False)
    return any(resolved == root or root in resolved.parents for root in roots)


def _data_path(value: str, label: str) -> str:
    path = Path(value)
    if not path.is_absolute() or not _within(path, [_data_root()]):
        raise base.PolicyError(f"Docker {label} must stay inside the WebNAS data directory")
    return str(path)


def _bind_source(value: str) -> str:
    path = Path(value)
    if not path.is_absolute() or path.resolve(strict=False) == Path("/var/run/docker.sock") or not _within(path, _allowed_bind_roots()):
        raise base.PolicyError("Docker bind mount is outside approved data roots")
    return str(path)


def _mount(value: str) -> None:
    fields: dict[str, str] = {}
    flags: set[str] = set()
    for part in value.split(","):
        if "=" in part:
            key, item = part.split("=", 1)
            fields[key] = item
        elif part:
            flags.add(part)
    kind = fields.get("type", "")
    target = fields.get("dst") or fields.get("destination") or fields.get("target") or ""
    if kind not in {"bind", "volume", "tmpfs"} or not target.startswith("/") or ".." in Path(target).parts:
        raise base.PolicyError("invalid Docker mount")
    source = fields.get("src") or fields.get("source") or ""
    if kind == "bind":
        _bind_source(source)
    elif kind == "volume":
        _identifier(source, "volume")
    elif source:
        raise base.PolicyError("tmpfs mount cannot specify a host source")
    if set(fields) - {"type", "src", "source", "dst", "destination", "target", "tmpfs-size"}:
        raise base.PolicyError("unsupported Docker mount option")
    if flags - {"readonly", "ro"}:
        raise base.PolicyError("unsupported Docker mount flag")


def _port(value: str) -> None:
    if not PORT_RE.fullmatch(value):
        raise base.PolicyError("invalid Docker port mapping")


def _validate_run(args: list[str]) -> None:
    if not args or args[0] not in {"run", "create"}:
        raise base.PolicyError("invalid Docker container creation command")
    index = 1
    image: str | None = None
    while index < len(args):
        item = args[index]
        if not item.startswith("-"):
            image = _image(item)
            if index != len(args) - 1:
                raise base.PolicyError("Docker container commands after the image are not permitted")
            break
        if item in RUN_BOOL_FLAGS:
            index += 1
            continue
        if item in {"--privileged", "--device", "--cap-add", "--cap-drop", "--pid", "--ipc", "-v", "--volume"}:
            raise base.PolicyError("high-risk Docker runtime option is not permitted")
        if item not in RUN_VALUE_FLAGS or index + 1 >= len(args):
            raise base.PolicyError(f"unsupported Docker runtime option: {item}")
        value = args[index + 1]
        if item == "--network" and value in SYSTEM_NETWORKS:
            raise base.PolicyError("host and none Docker network modes are not permitted")
        if item == "--network":
            _identifier(value, "network")
        elif item == "--env-file":
            _data_path(value, "environment file")
        elif item == "--mount":
            _mount(value)
        elif item == "--publish":
            _port(value)
        elif item == "--user" and not re.fullmatch(r"[0-9]{1,10}(?::[0-9]{1,10})?", value):
            raise base.PolicyError("Docker container user must be a numeric UID or UID:GID")
        elif item in {"--name", "--network-alias"}:
            _identifier(value, item.removeprefix("--"))
        index += 2
    if image is None:
        raise base.PolicyError("Docker image is required")


def _validate_compose_file(path_value: str) -> None:
    path = Path(_data_path(path_value, "Compose file"))
    if not path.is_file() or path.stat().st_size > 512 * 1024:
        raise base.PolicyError("Docker Compose file is missing or too large")
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise base.PolicyError("Docker Compose file is invalid") from error
    if not isinstance(document, dict) or set(document) - COMPOSE_ROOT_FIELDS:
        raise base.PolicyError("Docker Compose file contains unsupported root fields")
    services = document.get("services")
    if not isinstance(services, dict) or not services:
        raise base.PolicyError("Docker Compose services are required")
    for service_name, service in services.items():
        if not SLUG_RE.fullmatch(str(service_name)) or not isinstance(service, dict) or set(service) - COMPOSE_SERVICE_FIELDS:
            raise base.PolicyError("Docker Compose service contains unsupported fields")
        _image(str(service.get("image") or ""))
        for value in service.get("ports") or []:
            _port(str(value))
        for raw in service.get("volumes") or []:
            text = str(raw)
            source = text.split(":", 1)[0]
            if source.startswith("/"):
                _bind_source(source)
            else:
                _identifier(source, "volume")
        user = str(service.get("user") or "")
        if user and not re.fullmatch(r"[0-9]{1,10}(?::[0-9]{1,10})?", user):
            raise base.PolicyError("Docker Compose container user must be numeric")
    for section in ("networks", "volumes"):
        definitions = document.get(section) or {}
        if not isinstance(definitions, dict):
            raise base.PolicyError(f"Docker Compose {section} must be a mapping")
        for name, definition in definitions.items():
            if not SLUG_RE.fullmatch(str(name)) or str(name) in SYSTEM_NETWORKS:
                raise base.PolicyError(f"invalid Docker Compose {section} name")
            if definition is None:
                continue
            if not isinstance(definition, dict) or set(definition) - COMPOSE_DEFINITION_FIELDS:
                raise base.PolicyError(f"unsupported Docker Compose {section} definition")
            external_name = str(definition.get("name") or "")
            if section == "networks" and external_name in SYSTEM_NETWORKS:
                raise base.PolicyError("Docker Compose cannot attach services to host/none networks")
            driver = definition.get("driver")
            if driver not in {None, "bridge", "local"}:
                raise base.PolicyError("unsupported Docker Compose network/volume driver")


def _validate_compose(args: list[str]) -> None:
    if args and args[0] == "compose":
        args = args[1:]
    if not args:
        raise base.PolicyError("Docker Compose command is required")
    if args[0] == "version":
        if args[1:] not in ([], ["--short"]):
            raise base.PolicyError("unsupported Docker Compose version options")
        return
    index = 0
    compose_file = ""
    while index < len(args) and args[index].startswith("-"):
        option = args[index]
        if option == "--ansi" and index + 1 < len(args) and args[index + 1] == "never":
            index += 2
        elif option in {"--env-file", "-f", "-p"} and index + 1 < len(args):
            value = args[index + 1]
            if option in {"--env-file", "-f"}:
                _data_path(value, "Compose input")
            else:
                _identifier(value, "Compose project")
            if option == "-f":
                compose_file = value
            index += 2
        else:
            raise base.PolicyError(f"unsupported Docker Compose option: {option}")
    if index >= len(args):
        raise base.PolicyError("Docker Compose subcommand is required")
    command = args[index]
    tail = args[index + 1:]
    if command not in {"config", "ps", "logs", "up", "down", "start", "stop", "restart", "pull", "scale"}:
        raise base.PolicyError("unsupported Docker Compose subcommand")
    if command != "config" and not compose_file:
        raise base.PolicyError("managed Docker Compose operations require an explicit Compose file")
    if compose_file:
        _validate_compose_file(compose_file)
    if command == "config":
        if tail not in ([], ["--quiet"]):
            raise base.PolicyError("unsupported Docker Compose config options")
        return
    if command == "ps":
        if tail not in ([], ["--format", "json"]):
            raise base.PolicyError("unsupported Docker Compose ps options")
        return
    if command == "logs":
        position = 0
        while position < len(tail) and tail[position].startswith("-"):
            option = tail[position]
            if option in {"--no-color", "--timestamps"}:
                position += 1
            elif option in {"--tail", "--since"} and position + 1 < len(tail):
                if option == "--tail" and not tail[position + 1].isdigit():
                    raise base.PolicyError("invalid Docker Compose log tail")
                position += 2
            else:
                raise base.PolicyError("unsupported Docker Compose logs option")
        if position < len(tail):
            if position != len(tail) - 1:
                raise base.PolicyError("only one Docker Compose log service is permitted")
            _identifier(tail[position], "service")
        return
    if command == "up":
        while tail and tail[0] in {"-d", "--force-recreate"}:
            tail = tail[1:]
    elif command == "down":
        if tail and tail[0] == "--volumes":
            tail = tail[1:]
    if command == "scale":
        if not tail:
            raise base.PolicyError("Docker Compose scale requires at least one service")
        for item in tail:
            name, separator, replicas = item.partition("=")
            if not separator or not replicas.isdigit() or int(replicas) > 1000:
                raise base.PolicyError("invalid Docker Compose scale value")
            _identifier(name, "service")
        return
    for service in tail:
        _identifier(service, "service")


def _validate_simple(args: list[str]) -> None:
    command = args[0]
    tail = args[1:]
    if command == "version":
        if tail not in ([], ["--format", "{{json .}}"]):
            raise base.PolicyError("unsupported Docker version options")
    elif command == "info":
        if tail not in ([], ["--format", "{{json .}}"]):
            raise base.PolicyError("unsupported Docker info options")
    elif command == "ps":
        allowed_flags = {"-a", "--no-trunc", "--size"}
        index = 0
        while index < len(tail):
            if tail[index] in allowed_flags:
                index += 1
            elif tail[index] in {"--format", "--filter"} and index + 1 < len(tail):
                index += 2
            else:
                raise base.PolicyError("unsupported Docker ps option")
    elif command in {"start", "pause", "unpause"}:
        if len(tail) != 1:
            raise base.PolicyError(f"Docker {command} requires one container")
        _identifier(tail[0], "container")
    elif command in {"stop", "restart"}:
        if len(tail) != 3 or tail[0] != "--time" or not tail[1].isdigit() or not 1 <= int(tail[1]) <= 300:
            raise base.PolicyError(f"unsupported Docker {command} options")
        _identifier(tail[2], "container")
    elif command == "kill":
        if len(tail) != 3 or tail[0] != "--signal" or tail[1] not in SIGNALS:
            raise base.PolicyError("unsupported Docker kill options")
        _identifier(tail[2], "container")
    elif command == "rename":
        if len(tail) != 2:
            raise base.PolicyError("Docker rename requires source and destination")
        _identifier(tail[0], "container")
        _identifier(tail[1], "container")
    elif command == "rm":
        values = tail[1:] if tail and tail[0] in {"--force", "-f"} else tail
        if len(values) != 1:
            raise base.PolicyError("Docker rm requires one container")
        _identifier(values[0], "container")
    elif command == "inspect":
        if not tail or len(tail) > 500:
            raise base.PolicyError("invalid Docker inspect request")
        for value in tail:
            _identifier(value, "object")
    elif command == "top":
        if len(tail) != 3 or tail[1] != "-eo":
            raise base.PolicyError("unsupported Docker top options")
        _identifier(tail[0], "container")
    elif command == "logs":
        if not tail:
            raise base.PolicyError("Docker logs target is required")
        index = 0
        while index < len(tail) - 1:
            option = tail[index]
            if option == "--timestamps":
                index += 1
            elif option in {"--tail", "--since", "--until"} and index + 1 < len(tail):
                index += 2
            else:
                raise base.PolicyError("unsupported Docker logs option")
        _identifier(tail[-1], "container")
    elif command == "stats":
        index = 0
        if index < len(tail) and tail[index] == "--no-stream":
            index += 1
        if index + 1 < len(tail) and tail[index] == "--format":
            index += 2
        if len(tail) - index > 1:
            raise base.PolicyError("Docker stats accepts at most one container")
        if index < len(tail):
            _identifier(tail[index], "container")
    elif command == "events":
        if len(tail) != 6 or tail[0] != "--since" or tail[2] != "--until" or tail[4] != "--format":
            raise base.PolicyError("unsupported Docker events options")
        if not DURATION_RE.fullmatch(tail[1]) or not DURATION_RE.fullmatch(tail[3]):
            raise base.PolicyError("invalid Docker events duration")
    elif command == "search":
        if len(tail) != 5 or tail[0] != "--limit" or not tail[1].isdigit() or tail[2] != "--format":
            raise base.PolicyError("unsupported Docker search options")
        if not 1 <= int(tail[1]) <= 100:
            raise base.PolicyError("Docker search limit is out of range")
    elif command == "pull":
        image = tail[-1] if tail else ""
        if len(tail) == 3 and tail[0] == "--platform" and tail[1] in {"linux/amd64", "linux/arm64", "linux/arm/v7"}:
            pass
        elif len(tail) != 1:
            raise base.PolicyError("unsupported Docker pull options")
        _image(image)
    elif command == "update":
        if len(tail) < 1:
            raise base.PolicyError("Docker update target is required")
        index = 0
        allowed = {"--cpu-shares", "--memory", "--memory-swap", "--restart"}
        while index < len(tail) - 1:
            if tail[index] not in allowed or index + 1 >= len(tail) - 0:
                raise base.PolicyError("unsupported Docker update option")
            index += 2
        if index != len(tail) - 1:
            raise base.PolicyError("invalid Docker update arguments")
        _identifier(tail[-1], "container")
    elif command in {"login", "logout"}:
        if command == "logout":
            if len(tail) != 1:
                raise base.PolicyError("Docker logout requires one registry")
            _identifier(tail[0], "registry")
        else:
            if len(tail) != 4 or tail[1] != "--username" or tail[3] != "--password-stdin":
                raise base.PolicyError("Docker login must use password-stdin")
            _identifier(tail[0], "registry")
    else:
        raise base.PolicyError("Docker command is not allowlisted")


def _validate_family(args: list[str]) -> None:
    family = args[0]
    tail = args[1:]
    if family == "system":
        if tail != ["df", "--format", "{{json .}}"]:
            raise base.PolicyError("unsupported Docker system command")
        return
    if family == "builder":
        if tail != ["prune", "--force"]:
            raise base.PolicyError("unsupported Docker builder command")
        return
    if family == "container":
        if not tail:
            raise base.PolicyError("Docker container subcommand is required")
        action = tail[0]
        values = tail[1:]
        if action == "inspect":
            if not values or len(values) > 500:
                raise base.PolicyError("invalid Docker container inspect request")
            for value in values:
                _identifier(value, "container")
        elif action == "export":
            if len(values) != 3 or values[0] != "--output":
                raise base.PolicyError("unsupported Docker container export options")
            _data_path(values[1], "container export")
            _identifier(values[2], "container")
        elif action == "import":
            if len(values) != 2:
                raise base.PolicyError("Docker container import requires archive and image")
            _data_path(values[0], "container import")
            _image(values[1])
        else:
            raise base.PolicyError("unsupported Docker container command")
        return
    if family == "image":
        if not tail:
            raise base.PolicyError("Docker image subcommand is required")
        action = tail[0]
        values = tail[1:]
        if action == "ls":
            index = 0
            while index < len(values):
                if values[index] in {"--digests", "--no-trunc"}:
                    index += 1
                elif values[index] in {"--filter", "--format"} and index + 1 < len(values):
                    index += 2
                else:
                    raise base.PolicyError("unsupported Docker image ls option")
        elif action == "inspect":
            index = 0
            if len(values) >= 2 and values[0] == "--format":
                index = 2
            if index >= len(values):
                raise base.PolicyError("Docker image inspect target is required")
            for value in values[index:]:
                _image(value)
        elif action == "rm":
            if values and values[0] == "--force":
                values = values[1:]
            if len(values) != 1:
                raise base.PolicyError("Docker image rm requires one image")
            _image(values[0])
        elif action == "prune":
            if values != ["--force"]:
                raise base.PolicyError("unsupported Docker image prune options")
        elif action == "save":
            if len(values) != 3 or values[0] != "--output":
                raise base.PolicyError("unsupported Docker image save options")
            _data_path(values[1], "image archive")
            _image(values[2])
        elif action == "load":
            if len(values) != 2 or values[0] != "--input":
                raise base.PolicyError("unsupported Docker image load options")
            _data_path(values[1], "image archive")
        elif action == "import":
            index = 0
            while index + 1 < len(values) and values[index] == "--change":
                index += 2
            if len(values) - index != 2:
                raise base.PolicyError("invalid Docker image import request")
            _data_path(values[index], "image import")
            _image(values[index + 1])
        else:
            raise base.PolicyError("unsupported Docker image command")
        return
    if family == "volume":
        if not tail:
            raise base.PolicyError("Docker volume subcommand is required")
        action, values = tail[0], tail[1:]
        if action == "ls":
            index = 0
            while index < len(values):
                if values[index] in {"--format", "--filter"} and index + 1 < len(values):
                    index += 2
                else:
                    raise base.PolicyError("unsupported Docker volume ls option")
        elif action == "inspect":
            if len(values) != 1:
                raise base.PolicyError("Docker volume inspect requires one volume")
            _identifier(values[0], "volume")
        elif action == "create":
            index = 0
            while index + 1 < len(values) and values[index] == "--label":
                index += 2
            if len(values) - index != 1:
                raise base.PolicyError("invalid Docker volume create request")
            _identifier(values[index], "volume")
        elif action == "rm":
            if values and values[0] == "--force":
                values = values[1:]
            if len(values) != 1:
                raise base.PolicyError("Docker volume rm requires one volume")
            _identifier(values[0], "volume")
        elif action == "prune":
            if values != ["--force"]:
                raise base.PolicyError("unsupported Docker volume prune options")
        else:
            raise base.PolicyError("unsupported Docker volume command")
        return
    if family == "network":
        if not tail:
            raise base.PolicyError("Docker network subcommand is required")
        action, values = tail[0], tail[1:]
        if action == "ls":
            index = 0
            while index < len(values):
                if values[index] == "--no-trunc":
                    index += 1
                elif values[index] in {"--format", "--filter"} and index + 1 < len(values):
                    index += 2
                else:
                    raise base.PolicyError("unsupported Docker network ls option")
        elif action == "inspect":
            if not values or len(values) > 500:
                raise base.PolicyError("invalid Docker network inspect request")
            for value in values:
                _identifier(value, "network")
        elif action == "create":
            index = 0
            while index < len(values) - 1:
                option = values[index]
                if option in {"--internal", "--ipv6"}:
                    index += 1
                elif option in {"--driver", "--opt", "--subnet", "--ip-range", "--gateway", "--label"} and index + 1 < len(values):
                    value = values[index + 1]
                    if option == "--driver" and value != "bridge":
                        raise base.PolicyError("only the Docker bridge network driver is permitted")
                    if option == "--opt" and value != "com.docker.network.bridge.enable_ip_masquerade=false":
                        raise base.PolicyError("unsupported Docker network option")
                    if option in {"--subnet", "--ip-range"}:
                        try:
                            ipaddress.ip_network(value, strict=False)
                        except ValueError as error:
                            raise base.PolicyError("invalid Docker network range") from error
                    if option == "--gateway":
                        try:
                            ipaddress.ip_address(value)
                        except ValueError as error:
                            raise base.PolicyError("invalid Docker network gateway") from error
                    index += 2
                else:
                    raise base.PolicyError("unsupported Docker network create option")
            if index != len(values) - 1:
                raise base.PolicyError("Docker network name is required")
            _identifier(values[-1], "network")
            if values[-1] in SYSTEM_NETWORKS:
                raise base.PolicyError("protected Docker network name")
        elif action == "rm":
            if len(values) != 1 or values[0] in SYSTEM_NETWORKS:
                raise base.PolicyError("invalid Docker network removal")
            _identifier(values[0], "network")
        elif action == "prune":
            if values != ["--force"]:
                raise base.PolicyError("unsupported Docker network prune options")
        elif action in {"connect", "disconnect"}:
            if action == "disconnect" and values and values[0] == "--force":
                values = values[1:]
            if len(values) != 2 or values[0] in SYSTEM_NETWORKS:
                raise base.PolicyError("invalid Docker network connection request")
            _identifier(values[0], "network")
            _identifier(values[1], "container")
        else:
            raise base.PolicyError("unsupported Docker network command")
        return
    raise base.PolicyError("Docker command family is not allowlisted")


def _docker(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    extra = set(payload) - {"tool", "args", "stdin", "timeout"}
    if extra:
        raise base.PolicyError(f"unsupported parameters: {', '.join(sorted(extra))}")
    tool = _token(payload.get("tool"), "Docker tool", limit=32)
    args_raw = payload.get("args") or []
    stdin = payload.get("stdin")
    timeout_raw = payload.get("timeout", 60)
    if tool not in {"docker", "docker-compose"}:
        raise base.PolicyError("Docker broker accepts only docker or docker-compose")
    if not isinstance(args_raw, list) or not 1 <= len(args_raw) <= 512:
        raise base.PolicyError("invalid Docker argument list")
    args = [_token(item, "Docker argument") for item in args_raw]
    if stdin is not None and (not isinstance(stdin, str) or len(stdin.encode("utf-8")) > 64 * 1024 or "\x00" in stdin):
        raise base.PolicyError("invalid Docker standard input")
    if not isinstance(timeout_raw, (int, float)) or isinstance(timeout_raw, bool) or not 1 <= float(timeout_raw) <= 3600:
        raise base.PolicyError("invalid Docker timeout")

    if tool == "docker-compose" or args[0] == "compose":
        _validate_compose(args)
    elif args[0] in {"run", "create"}:
        _validate_run(args)
    elif args[0] in {"container", "image", "volume", "network", "system", "builder"}:
        _validate_family(args)
    else:
        _validate_simple(args)

    if stdin is not None and not (tool == "docker" and args[0] == "login" and args[-1] == "--password-stdin"):
        raise base.PolicyError("Docker standard input is accepted only for registry login")
    executable = base._resolve_tool(tool)
    return runner([executable, *args], stdin, float(timeout_raw))


def dispatch(request: BrokerRequest, *, runner: base.Runner | None = None) -> BrokerResponse:
    selected_runner = runner or base._default_runner
    try:
        result = _docker(request.payload, selected_runner)
    except base.PolicyError as error:
        return _failure(request, error, policy=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return _failure(request, error, policy=False)
    return _result(request, result)
