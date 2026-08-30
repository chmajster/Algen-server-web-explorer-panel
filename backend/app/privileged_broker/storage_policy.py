from __future__ import annotations

import subprocess
from typing import Any

from app.core.redaction import redact_text

from . import policy as base
from .extended_policy import dispatch as extended_dispatch
from .file_worker_policy import dispatch as file_worker_dispatch
from .protocol import BrokerRequest, BrokerResponse, Operation
from .storage_probe_rules import ALLOWED_STORAGE_PROBE_TOOLS, storage_probe_args_allowed


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


def _storage_probe(payload: dict[str, Any], runner: base.Runner) -> base.CommandResult:
    extra = set(payload) - {"tool", "args", "timeout"}
    if extra:
        raise base.PolicyError(f"unsupported parameters: {', '.join(sorted(extra))}")

    tool = payload.get("tool")
    args = payload.get("args") or []
    timeout_raw = payload.get("timeout", 12)

    if not isinstance(tool, str) or tool not in ALLOWED_STORAGE_PROBE_TOOLS:
        raise base.PolicyError("storage probe tool is not allowlisted")
    if not isinstance(args, list) or any(not isinstance(item, str) or len(item) > 4096 or "\x00" in item for item in args):
        raise base.PolicyError("invalid storage probe arguments")
    if not storage_probe_args_allowed(tool, args):
        raise base.PolicyError("unsupported storage probe arguments")
    if not isinstance(timeout_raw, (int, float)) or isinstance(timeout_raw, bool) or not 1 <= float(timeout_raw) <= 30:
        raise base.PolicyError("invalid storage probe timeout")

    executable = base._resolve_tool(tool)
    return runner([executable, *args], None, float(timeout_raw))


def dispatch(request: BrokerRequest, *, runner: base.Runner | None = None) -> BrokerResponse:
    if request.operation == Operation.FILE_WORKER:
        return file_worker_dispatch(request)
    if request.operation != Operation.STORAGE_PROBE:
        return extended_dispatch(request, runner=runner)

    selected_runner = runner or base._default_runner
    try:
        result = _storage_probe(request.payload, selected_runner)
    except base.PolicyError as error:
        return _failure(request, error, policy=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return _failure(request, error, policy=False)
    return _result(request, result)
