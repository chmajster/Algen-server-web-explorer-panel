from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from secrets import token_hex
from typing import Any

from pydantic import ValidationError

from .protocol import BrokerRequest, BrokerResponse, MAX_FRAME_BYTES, Operation, encode_frame


DEFAULT_SOCKET = Path("/run/webnas/privileged.sock")


class BrokerError(RuntimeError):
    def __init__(self, message: str, *, error_code: str = "BROKER_ERROR", exit_code: int = 1) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.exit_code = exit_code


class BrokerClient:
    def __init__(self, socket_path: Path = DEFAULT_SOCKET, *, timeout: float = 65.0) -> None:
        self.socket_path = socket_path
        self.timeout = timeout

    def request(self, operation: Operation, payload: dict[str, Any], *, actor: str) -> BrokerResponse:
        request = BrokerRequest(
            request_id=token_hex(16),
            actor=actor,
            operation=operation,
            payload=payload,
        )
        frame = encode_frame(request)
        deadline = time.monotonic() + self.timeout
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            try:
                connection.connect(str(self.socket_path))
                connection.sendall(frame)
                chunks: list[bytes] = []
                size = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("privileged broker timed out")
                    chunk = connection.recv(min(65536, MAX_FRAME_BYTES + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_FRAME_BYTES:
                        raise BrokerError("privileged broker response is too large", error_code="FRAME_TOO_LARGE")
                    if b"\n" in chunk:
                        break
            except (OSError, TimeoutError) as error:
                raise BrokerError(f"privileged broker is unavailable: {type(error).__name__}", error_code="BROKER_UNAVAILABLE") from error
        raw = b"".join(chunks).split(b"\n", 1)[0]
        try:
            response = BrokerResponse.model_validate(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            raise BrokerError("privileged broker returned an invalid response", error_code="INVALID_RESPONSE") from error
        if response.request_id != request.request_id:
            raise BrokerError("privileged broker response id mismatch", error_code="RESPONSE_MISMATCH")
        return response

    def require(self, operation: Operation, payload: dict[str, Any], *, actor: str) -> BrokerResponse:
        response = self.request(operation, payload, actor=actor)
        if not response.ok:
            raise BrokerError(
                response.stderr or "privileged operation failed",
                error_code=response.error_code or "COMMAND_FAILED",
                exit_code=response.exit_code,
            )
        return response
