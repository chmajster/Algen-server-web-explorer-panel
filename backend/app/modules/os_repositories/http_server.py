#!/usr/bin/env python3
from __future__ import annotations

import mimetypes
import os
import re
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(os.environ.get("WEBNAS_OS_REPOSITORIES_PUBLISHED", "/var/lib/webnas/os-repositories/published"))
CONFIG = Path(os.environ.get("WEBNAS_OS_REPOSITORIES_CONFIG", "/etc/webnas/os-repositories.yaml"))
MAX_RANGE = 256 * 1024 * 1024
CONNECTIONS = threading.BoundedSemaphore(64)


class RepositoryServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64
    allow_reuse_address = True


class RepositoryHandler(BaseHTTPRequestHandler):
    server_version = "WebNASRepository/1.0"

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.client_address[0]} {format % args}"[:1000], flush=True)

    def _path(self) -> Path | None:
        raw = unquote(urlsplit(self.path).path).lstrip("/")
        parts = Path(raw).parts
        if not raw or "\x00" in raw or ".." in parts or "\\" in raw or any(part.startswith(".") for part in parts):
            return None
        candidate = (ROOT / raw).resolve()
        base = ROOT.resolve()
        if base not in candidate.parents or not candidate.is_file():
            return None
        return candidate

    def _serve(self, send_body: bool) -> None:
        self.connection.settimeout(30)
        if not CONNECTIONS.acquire(blocking=False):
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        try:
            self._serve_locked(send_body)
        finally:
            CONNECTIONS.release()

    def _serve_locked(self, send_body: bool) -> None:
        path = self._path()
        if path is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        size, start, end = path.stat().st_size, 0, path.stat().st_size - 1
        status = HTTPStatus.OK
        header = self.headers.get("Range", "")
        if header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
            if not match:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            start = int(match.group(1) or 0)
            end = min(int(match.group(2) or end), end)
            if start > end or start >= size or end - start + 1 > MAX_RANGE:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            status = HTTPStatus.PARTIAL_CONTENT
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if send_body:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining:
                    block = handle.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)

    def do_GET(self) -> None:
        self._serve(True)

    def do_HEAD(self) -> None:
        self._serve(False)


def main() -> None:
    settings: dict[str, str] = {}
    if CONFIG.exists():
        for line in CONFIG.read_text(encoding="utf-8").splitlines():
            if ":" in line and not line.lstrip().startswith("#"):
                key, value = line.split(":", 1)
                settings[key.strip()] = value.strip()
    address, port = str(settings.get("listen_address", "0.0.0.0")), int(settings.get("port", 8088))
    if ":" in address:
        RepositoryServer.address_family = socket.AF_INET6
    server = RepositoryServer((address, port), RepositoryHandler)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
