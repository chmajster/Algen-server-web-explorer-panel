from __future__ import annotations

import json
import logging
import os
import pwd
import socket
import struct
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.redaction import redact_text

from .protocol import BrokerRequest, BrokerResponse, MAX_FRAME_BYTES, encode_frame
from .storage_policy import dispatch


logger = logging.getLogger("webnas.privileged_broker")
DEFAULT_SOCKET = Path("/run/webnas/privileged.sock")
DEFAULT_ALLOWED_USER = "webnas"
_MAX_WORKERS = 16
_workers = threading.BoundedSemaphore(_MAX_WORKERS)


def peer_credentials(connection: socket.socket) -> tuple[int, int, int]:
    if not hasattr(socket, "SO_PEERCRED"):
        raise RuntimeError("SO_PEERCRED is required by the privileged broker")
    raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    pid, uid, gid = struct.unpack("3i", raw)
    return pid, uid, gid


def allowed_peer_uid(username: str = DEFAULT_ALLOWED_USER) -> int:
    try:
        return pwd.getpwnam(username).pw_uid
    except KeyError as error:
        raise RuntimeError(f"privileged broker caller account does not exist: {username}") from error


def authorize_peer(uid: int, *, expected_uid: int) -> bool:
    return uid == expected_uid


def _error_response(request_id: str, code: str, message: str, exit_code: int = 126) -> BrokerResponse:
    return BrokerResponse(
        request_id=request_id if len(request_id) == 32 else "0" * 32,
        ok=False,
        exit_code=exit_code,
        error_code=code,
        stderr=redact_text(message, limit=2000),
    )


def _receive_frame(connection: socket.socket) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = connection.recv(min(65536, MAX_FRAME_BYTES + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_FRAME_BYTES:
            raise ValueError("request frame is too large")
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    raw = b"".join(chunks)
    if b"\n" not in raw:
        raise ValueError("request frame is incomplete")
    return raw.split(b"\n", 1)[0]


def handle_connection(connection: socket.socket, *, expected_uid: int) -> None:
    request_id = "0" * 32
    try:
        pid, uid, _gid = peer_credentials(connection)
        if not authorize_peer(uid, expected_uid=expected_uid):
            logger.warning("privileged_broker_denied peer_pid=%s peer_uid=%s", pid, uid)
            connection.sendall(encode_frame(_error_response(request_id, "UNAUTHORIZED_PEER", "caller uid is not authorized")))
            return
        raw = _receive_frame(connection)
        try:
            decoded: Any = json.loads(raw.decode("utf-8"))
            if isinstance(decoded, dict) and isinstance(decoded.get("request_id"), str):
                request_id = decoded["request_id"]
            request = BrokerRequest.model_validate(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            connection.sendall(encode_frame(_error_response(request_id, "INVALID_REQUEST", type(error).__name__)))
            return
        logger.info(
            "privileged_broker_request request_id=%s actor=%s operation=%s peer_pid=%s peer_uid=%s",
            request.request_id,
            request.actor,
            request.operation.value,
            pid,
            uid,
        )
        response = dispatch(request)
        logger.info(
            "privileged_broker_result request_id=%s operation=%s ok=%s exit_code=%s error_code=%s",
            request.request_id,
            request.operation.value,
            response.ok,
            response.exit_code,
            response.error_code or "",
        )
        connection.sendall(encode_frame(response))
    except (OSError, ValueError, RuntimeError) as error:
        logger.warning("privileged_broker_protocol_error error=%s", type(error).__name__)
        try:
            connection.sendall(encode_frame(_error_response(request_id, "PROTOCOL_ERROR", type(error).__name__)))
        except OSError:
            pass
    finally:
        connection.close()
        _workers.release()


def _activated_socket() -> socket.socket | None:
    try:
        listen_pid = int(os.environ.get("LISTEN_PID", "0"))
        listen_fds = int(os.environ.get("LISTEN_FDS", "0"))
    except ValueError:
        return None
    if listen_pid != os.getpid() or listen_fds != 1:
        return None
    inherited = socket.fromfd(3, socket.AF_UNIX, socket.SOCK_STREAM)
    inherited.setblocking(True)
    return inherited


def _standalone_socket(path: Path) -> socket.socket:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    os.chmod(path, 0o660)
    listener.listen(32)
    return listener


def serve_forever() -> None:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise RuntimeError("privileged broker must run as root")
    username = os.environ.get("WEBNAS_BROKER_ALLOWED_USER", DEFAULT_ALLOWED_USER)
    expected_uid = allowed_peer_uid(username)
    listener = _activated_socket()
    standalone = listener is None
    if listener is None:
        path = Path(os.environ.get("WEBNAS_BROKER_SOCKET", str(DEFAULT_SOCKET)))
        listener = _standalone_socket(path)
    logger.info("privileged_broker_started allowed_user=%s allowed_uid=%s socket_activated=%s", username, expected_uid, not standalone)
    while True:
        connection, _ = listener.accept()
        if not _workers.acquire(timeout=5):
            connection.close()
            continue
        threading.Thread(
            target=handle_connection,
            args=(connection,),
            kwargs={"expected_uid": expected_uid},
            daemon=True,
            name="webnas-privileged-request",
        ).start()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
