from __future__ import annotations

import re
import subprocess
from typing import Any

from app.core.redaction import redact_text

from . import policy as base
from .protocol import BrokerRequest, BrokerResponse


CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def dispatch(request: BrokerRequest, *, runner: base.Runner | None = None) -> BrokerResponse:
    selected_runner = runner or base._default_runner
    try:
        if set(request.payload) != {"container"}:
            raise base.PolicyError("graceful Docker stop accepts only a container name")
        container = request.payload.get("container")
        if not isinstance(container, str) or not CONTAINER_RE.fullmatch(container):
            raise base.PolicyError("invalid Docker container name")
        result = selected_runner([base._resolve_tool("docker"), "stop", "--time", "-1", container], None, 24 * 60 * 60)
        return BrokerResponse(
            request_id=request.request_id,
            ok=result.exit_code == 0,
            exit_code=result.exit_code,
            stdout=redact_text(result.stdout, limit=base.MAX_OUTPUT),
            stderr=redact_text(result.stderr, limit=base.MAX_OUTPUT),
            error_code=None if result.exit_code == 0 else "COMMAND_FAILED",
        )
    except base.PolicyError as error:
        return BrokerResponse(
            request_id=request.request_id,
            ok=False,
            exit_code=126,
            error_code="POLICY_DENIED",
            stderr=redact_text(error, limit=2000),
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return BrokerResponse(
            request_id=request.request_id,
            ok=False,
            exit_code=127,
            error_code="EXECUTION_FAILED",
            stderr=redact_text(error, limit=2000),
        )
