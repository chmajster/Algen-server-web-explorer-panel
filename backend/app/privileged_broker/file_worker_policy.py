from __future__ import annotations

import base64
import json
import os
import pwd
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.config import get_config
from app.path_policy import resolve_user_path

from . import policy as base
from .protocol import BrokerRequest, BrokerResponse


ALLOWED_FILE_OPERATIONS = frozenset(
    {
        "list",
        "stat",
        "mkdir",
        "create",
        "copy",
        "move",
        "rename",
        "delete",
        "trash",
        "chmod",
        "import_upload",
        "export_download",
        "preview",
        "read_text",
        "write_text",
        "search",
    }
)
ALLOWED_PAYLOAD_KEYS: dict[str, frozenset[str]] = {
    "list": frozenset({"path", "paginate", "sort", "direction", "page", "page_size", "folders_first", "filter", "show_hidden"}),
    "stat": frozenset({"path"}),
    "mkdir": frozenset({"path"}),
    "create": frozenset({"path"}),
    "copy": frozenset({"src", "dst"}),
    "move": frozenset({"src", "dst"}),
    "rename": frozenset({"src", "dst"}),
    "delete": frozenset({"path"}),
    "trash": frozenset({"path"}),
    "chmod": frozenset({"path", "mode"}),
    "import_upload": frozenset({"tmp", "dst"}),
    "export_download": frozenset({"src", "tmp"}),
    "preview": frozenset({"path", "limit"}),
    "read_text": frozenset({"path"}),
    "write_text": frozenset({"path", "content", "expected_mtime_ns"}),
    "search": frozenset({"path", "query", "limit", "max_entries", "timeout_seconds"}),
}
PATH_KEYS = frozenset({"path", "src", "dst"})
TEMP_SUFFIXES = {"import_upload": ".upload", "export_download": ".download"}


def _failure(request: BrokerRequest, message: str, *, code: str = "POLICY_DENIED", exit_code: int = 126) -> BrokerResponse:
    return BrokerResponse(
        request_id=request.request_id,
        ok=False,
        exit_code=exit_code,
        error_code=code,
        stderr=message[:2000],
    )


def _worker_timeout(operation: str) -> float:
    return 30.0 if operation == "search" else 3600.0


def _validated_temp_path(raw: object, operation: str) -> Path:
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise base.PolicyError("invalid temporary file path")
    temp_root = Path(get_config().paths.temp_dir).resolve(strict=False)
    candidate = Path(raw)
    if not candidate.is_absolute() or candidate.parent.resolve(strict=False) != temp_root:
        raise base.PolicyError("temporary file is outside the WebNAS temporary directory")
    expected_suffix = TEMP_SUFFIXES[operation]
    if candidate.suffix != expected_suffix or len(candidate.stem) != 32 or any(ch not in "0123456789abcdef" for ch in candidate.stem):
        raise base.PolicyError("invalid WebNAS temporary file name")
    return candidate


def _validate_request(request: BrokerRequest) -> tuple[str, str, dict[str, Any], pwd.struct_passwd, Path | None]:
    extra = set(request.payload) - {"username", "op", "payload"}
    if extra:
        raise base.PolicyError(f"unsupported file worker parameters: {', '.join(sorted(extra))}")

    username = request.payload.get("username")
    operation = request.payload.get("op")
    payload = request.payload.get("payload")
    if not isinstance(username, str) or not username or username != request.actor:
        raise base.PolicyError("file worker actor does not match target user")
    if not isinstance(operation, str) or operation not in ALLOWED_FILE_OPERATIONS:
        raise base.PolicyError("file worker operation is not allowlisted")
    if not isinstance(payload, dict):
        raise base.PolicyError("file worker payload must be an object")

    allowed_keys = ALLOWED_PAYLOAD_KEYS[operation]
    payload_extra = set(payload) - allowed_keys
    if payload_extra:
        raise base.PolicyError(f"unsupported {operation} parameters: {', '.join(sorted(payload_extra))}")

    try:
        user = pwd.getpwnam(username)
    except KeyError as error:
        raise base.PolicyError("file worker target user does not exist") from error

    for key in PATH_KEYS:
        if key not in payload:
            continue
        raw = payload[key]
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise base.PolicyError(f"invalid {key}")
        resolved = resolve_user_path(username, raw)
        if resolved != Path(raw).resolve(strict=False):
            raise base.PolicyError(f"invalid {key}")

    temp_path: Path | None = None
    if operation in TEMP_SUFFIXES:
        temp_path = _validated_temp_path(payload.get("tmp"), operation)
    elif "tmp" in payload:
        raise base.PolicyError("temporary file is not valid for this operation")

    return username, operation, payload, user, temp_path


def _prepare_upload(path: Path, user: pwd.struct_passwd) -> None:
    try:
        details = path.lstat()
    except FileNotFoundError as error:
        raise base.PolicyError("upload temporary file does not exist") from error
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise base.PolicyError("upload temporary path is not a standalone regular file")
    os.chown(path, user.pw_uid, user.pw_gid)
    os.chmod(path, 0o600)


def _make_download_readable(path: Path) -> None:
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise base.PolicyError("download temporary path is not a standalone regular file")
    service_user = os.environ.get("WEBNAS_BROKER_ALLOWED_USER", "webnas")
    owner = pwd.getpwnam(service_user)
    os.chown(path, owner.pw_uid, owner.pw_gid)
    os.chmod(path, 0o600)


def dispatch(request: BrokerRequest) -> BrokerResponse:
    upload_temp: Path | None = None
    try:
        username, operation, payload, user, temp_path = _validate_request(request)
        if operation == "import_upload":
            assert temp_path is not None
            upload_temp = temp_path
            _prepare_upload(temp_path, user)

        envelope = base64.b64encode(
            json.dumps({"user": username, "op": operation, "payload": payload}, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        command = [sys.executable, "-m", "app.worker", "--user", "-", "--op", "-", "--payload", "-"]
        completed = subprocess.run(  # nosec B603 - executable and argv are fixed; worker validates the allowlisted envelope.
            command,
            input=envelope,
            capture_output=True,
            text=True,
            timeout=_worker_timeout(operation),
            check=False,
            shell=False,
            env=base.SAFE_ENV,
        )
        if completed.returncode != 0:
            return BrokerResponse(
                request_id=request.request_id,
                ok=False,
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                error_code="FILE_WORKER_FAILED",
            )
        if operation == "export_download":
            assert temp_path is not None
            _make_download_readable(temp_path)
        return BrokerResponse(
            request_id=request.request_id,
            ok=True,
            exit_code=0,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except base.PolicyError as error:
        return _failure(request, str(error))
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return _failure(request, type(error).__name__, code="EXECUTION_FAILED", exit_code=127)
    finally:
        if upload_temp is not None:
            try:
                upload_temp.unlink(missing_ok=True)
            except OSError:
                pass
