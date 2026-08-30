from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from app.privileged_broker.client import BrokerError
from app.privileged_broker.runtime import broker_required, storage_probe
from app.privileged_broker.storage_probe_rules import ALLOWED_STORAGE_PROBE_TOOLS, storage_probe_args_allowed

from ..service import CommandResult


logger = logging.getLogger(__name__)
SAFE_TOOL_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
ALLOWED_DETAIL_TOOLS = set(ALLOWED_STORAGE_PROBE_TOOLS) - {"smartctl", "nvme"}


Runner = Callable[[Sequence[str], float], CommandResult]


def _default_runner(argv: Sequence[str], timeout: float) -> CommandResult:
    completed = subprocess.run(  # nosec B603 - executable and argv shapes are strictly allowlisted below.
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _safe_probe_args(name: str, args: Sequence[str]) -> bool:
    return name in ALLOWED_DETAIL_TOOLS and storage_probe_args_allowed(name, args)


class StorageReadOnlyProbe:
    def __init__(
        self,
        *,
        runner: Runner | None = None,
        tool_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self._runner = runner or _default_runner
        self._tool_resolver = tool_resolver or self._resolve_tool

    @staticmethod
    def _resolve_tool(name: str) -> str | None:
        if name not in ALLOWED_DETAIL_TOOLS:
            return None
        resolved = shutil.which(name, path=SAFE_TOOL_PATH)
        if not resolved:
            return None
        path = Path(resolved).resolve(strict=False)
        if path.name != name or str(path.parent) not in {"/usr/sbin", "/usr/bin", "/sbin", "/bin"}:
            return None
        return str(path)

    def tool_available(self, name: str) -> bool:
        return name in ALLOWED_DETAIL_TOOLS and self._tool_resolver(name) is not None

    def run(self, name: str, args: Sequence[str], *, timeout: float = 8.0) -> CommandResult | None:
        if not _safe_probe_args(name, args):
            return None

        try:
            if broker_required():
                result = storage_probe(name, list(args), timeout=timeout)
                return CommandResult(result.returncode, result.stdout, result.stderr)

            executable = self._tool_resolver(name)
            if executable is None:
                return None
            return self._runner([executable, *args], timeout)
        except (BrokerError, OSError, RuntimeError, subprocess.SubprocessError) as error:
            logger.warning("storage_detail_probe_failed tool=%s error=%s", name, type(error).__name__)
            return CommandResult(127, "", type(error).__name__)
