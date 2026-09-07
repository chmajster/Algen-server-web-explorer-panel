from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ...privileged_broker.client import BrokerClient
from ...privileged_broker.protocol import Operation
from ...privileged_broker.runtime import broker_required


DOCKER_TOOLS = {"docker", "docker-compose"}


def install_docker_broker_transport(provider_class: type[Any]) -> None:
    """Route Docker socket operations through the root broker in installed WebNAS.

    The web application remains unprivileged and never receives membership in the
    root-equivalent ``docker`` group. Development mode keeps the original local
    subprocess behavior when the privileged broker is not required.
    """

    if getattr(provider_class, "_webnas_docker_broker_transport_installed", False):
        return

    original_run = provider_class._run

    def _run(
        self: Any,
        args: list[str],
        *,
        timeout: int = 30,
        input_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        tool = Path(args[0]).name if args else ""
        if tool in DOCKER_TOOLS and broker_required():
            if env:
                # Docker provider call sites do not need caller-controlled environment
                # when using the broker. Refuse it rather than silently widening the
                # privileged execution surface.
                return subprocess.CompletedProcess(args, 126, "", "Docker broker does not accept custom environment variables")
            actor = str(getattr(self, "actor", "") or f"module-{getattr(self, 'module_id', 'docker')}")
            response = BrokerClient().request(
                Operation.DOCKER,
                {"tool": tool, "args": args[1:], "stdin": input_text, "timeout": timeout},
                actor=actor,
            )
            return subprocess.CompletedProcess(
                args=args,
                returncode=int(response.exit_code),
                stdout=str(response.stdout or ""),
                stderr=str(response.stderr or ""),
            )
        return original_run(self, args, timeout=timeout, input_text=input_text, env=env)

    setattr(provider_class, "_run", _run)
    setattr(provider_class, "_webnas_docker_broker_transport_installed", True)
