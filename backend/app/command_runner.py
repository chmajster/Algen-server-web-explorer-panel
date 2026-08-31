from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .privileged_broker.runtime import (
    filesystem_mkdir,
    managed_file_write,
    ownership_change,
    storage_probe,
    systemd_action,
)


logger = logging.getLogger(__name__)
_SECRET_ARGUMENT = re.compile(r"(?i)(password|passwd|token|secret|api[_-]?key|authorization|cookie)")
_DEFAULT_OUTPUT_LIMIT = 1024 * 1024


@dataclass(frozen=True, slots=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandTimeoutError(TimeoutError):
    pass


def _limit_output(value: str, limit: int) -> tuple[str, bool]:
    if limit <= 0 or len(value) <= limit:
        return value, False
    marker = "\n...[output truncated by WebNAS]"
    keep = max(0, limit - len(marker))
    return value[:keep] + marker, True


def _read_output(stream: TextIO, limit: int) -> tuple[str, bool]:
    stream.flush()
    stream.seek(0)
    if limit <= 0:
        return stream.read(), False
    value = stream.read(limit + 1)
    return _limit_output(value, limit)


def _redacted_argv(argv: Sequence[str], secret_indexes: frozenset[int]) -> tuple[str, ...]:
    redacted: list[str] = []
    hide_next = False
    for index, value in enumerate(argv):
        if index in secret_indexes or hide_next:
            redacted.append("***")
            hide_next = False
            continue
        if "=" in value:
            key, separator, _raw = value.partition("=")
            if _SECRET_ARGUMENT.search(key):
                redacted.append(f"{key}{separator}***")
                continue
        redacted.append(value)
        if value.startswith("--") and _SECRET_ARGUMENT.search(value):
            hide_next = True
    return tuple(redacted)


class ReadOnlyCommandRunner:
    """Execute non-privileged read-only commands with a bounded, auditable contract.

    Mutating or privileged operations must use ``PrivilegedCommandRunner`` and
    therefore the existing privileged broker. This runner never invokes a shell.
    """

    def __init__(self, *, output_limit: int = _DEFAULT_OUTPUT_LIMIT) -> None:
        self.output_limit = output_limit

    @staticmethod
    def _environment(extra: Mapping[str, str] | None = None) -> dict[str, str]:
        environment = {
            "PATH": os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
            "HOME": os.environ.get("HOME", "/"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        if extra:
            environment.update({str(key): str(value) for key, value in extra.items()})
        return environment

    def run(
        self,
        argv: Sequence[str],
        *,
        actor: str,
        timeout: float = 30,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
        secret_indexes: frozenset[int] | None = None,
    ) -> CommandResult:
        if not argv or any(not isinstance(value, str) or "\x00" in value for value in argv):
            raise ValueError("argv must contain non-empty safe strings")
        command = [str(value) for value in argv]
        redacted = _redacted_argv(command, secret_indexes or frozenset())
        logger.info("command_started actor=%s argv=%s", actor, redacted)
        with (
            tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_stream,
            tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr_stream,
        ):
            process = subprocess.Popen(  # noqa: S603 - centralized no-shell execution boundary.
                command,
                cwd=str(cwd) if cwd else None,
                env=self._environment(env),
                stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                stdout=stdout_stream,
                stderr=stderr_stream,
                text=True,
                shell=False,
            )
            try:
                process.communicate(input=input_text, timeout=timeout)
            except subprocess.TimeoutExpired as error:
                process.kill()
                process.communicate()
                logger.warning("command_timeout actor=%s argv=%s timeout=%s", actor, redacted, timeout)
                raise CommandTimeoutError(f"command exceeded timeout of {timeout} seconds") from error
            stdout, stdout_truncated = _read_output(stdout_stream, self.output_limit)
            stderr, stderr_truncated = _read_output(stderr_stream, self.output_limit)
        result = CommandResult(tuple(command), process.returncode, stdout, stderr, stdout_truncated or stderr_truncated)
        logger.info("command_finished actor=%s argv=%s returncode=%s truncated=%s", actor, redacted, result.returncode, result.truncated)
        return result


class PrivilegedCommandRunner:
    """Typed facade over the existing privileged broker boundary."""

    def systemd(self, action: str, unit: str = "", *, actor: str) -> subprocess.CompletedProcess[str]:
        return systemd_action(action, unit, actor=actor)

    def write_file(self, target: str, content: str, *, actor: str, mode: int = 0o644) -> None:
        managed_file_write(target, content, actor=actor, mode=mode)

    def chown(self, path: Path, *, actor: str, owner: str = "", group: str = "") -> None:
        ownership_change(path, owner=owner, group=group, actor=actor)

    def mkdir(self, path: Path, *, actor: str, mode: int = 0o750, owner: str = "", group: str = "") -> None:
        filesystem_mkdir(path, mode=mode, owner=owner, group=group, actor=actor)

    def storage(self, tool: str, args: list[str], *, actor: str, timeout: float = 30) -> subprocess.CompletedProcess[str]:
        return storage_probe(tool, args, timeout=timeout, actor=actor)
