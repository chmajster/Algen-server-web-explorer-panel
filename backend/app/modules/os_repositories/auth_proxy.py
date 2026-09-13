from __future__ import annotations

import contextlib
import http.client
import socket
import ssl
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import SplitResult, urljoin, urlsplit

from .security import validate_mirror_url

_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "trailers", "transfer-encoding", "upgrade"}


class _ProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, source_url: str, authorization: str, allow_private_network: bool, allow_private_http: bool) -> None:
        super().__init__(("127.0.0.1", 0), _ProxyHandler)
        self.source_url = source_url.rstrip("/") + "/"
        self.authorization = authorization
        self.allow_private_network = allow_private_network
        self.allow_private_http = allow_private_http


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, hostname: str, port: int, address: str, *, timeout: float) -> None:
        super().__init__(hostname, port, timeout=timeout)
        self._pinned_address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self.source_address,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, port: int, address: str, *, timeout: float) -> None:
        super().__init__(hostname, port, timeout=timeout, context=ssl.create_default_context())
        self._pinned_address = address

    def connect(self) -> None:
        raw = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def _connection_for(parsed: SplitResult, address: str, *, timeout: float = 60) -> http.client.HTTPConnection:
    if not parsed.hostname:
        raise ValueError("mirror target has no hostname")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if parsed.scheme == "https":
        return _PinnedHTTPSConnection(parsed.hostname, port, address, timeout=timeout)
    return _PinnedHTTPConnection(parsed.hostname, port, address, timeout=timeout)


class _ProxyHandler(BaseHTTPRequestHandler):
    server: _ProxyServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self._forward(False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._forward(True)

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _forward(self, head_only: bool) -> None:
        target = urljoin(self.server.source_url, self.path.lstrip("/"))
        original_origin = _origin(self.server.source_url)
        try:
            for _ in range(6):
                addresses = validate_mirror_url(
                    target,
                    allow_private_network=self.server.allow_private_network,
                    allow_private_http=self.server.allow_private_http,
                )
                parsed = urlsplit(target)
                if not parsed.hostname:
                    raise ValueError("mirror target has no hostname")
                headers = {"User-Agent": "WebNAS repository mirror proxy/1"}
                if self.headers.get("Range"):
                    headers["Range"] = self.headers["Range"]
                if _origin(target) == original_origin:
                    headers["Authorization"] = self.server.authorization
                path = parsed.path or "/"
                if parsed.query:
                    path += f"?{parsed.query}"

                connection: http.client.HTTPConnection | None = None
                response: http.client.HTTPResponse | None = None
                last_error: OSError | http.client.HTTPException | None = None
                for address in addresses:
                    candidate = _connection_for(parsed, address)
                    try:
                        candidate.request("HEAD" if head_only else "GET", path, headers=headers)
                        response = candidate.getresponse()
                        connection = candidate
                        break
                    except (OSError, http.client.HTTPException) as error:
                        last_error = error
                        candidate.close()
                if response is None or connection is None:
                    if last_error is not None:
                        raise last_error
                    raise OSError("mirror target has no validated address")

                if response.status in {301, 302, 303, 307, 308} and response.getheader("Location"):
                    target = urljoin(target, response.getheader("Location") or "")
                    response.read()
                    connection.close()
                    continue
                self.send_response(response.status)
                for name, value in response.getheaders():
                    if name.lower() not in _HOP_HEADERS and name.lower() not in {"content-length", "location"}:
                        self.send_header(name, value)
                length = response.getheader("Content-Length")
                if length:
                    self.send_header("Content-Length", length)
                else:
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                if not head_only:
                    while chunk := response.read(1024 * 128):
                        self.wfile.write(chunk)
                connection.close()
                return
            self.send_error(502, "Too many upstream redirects")
        except (OSError, ValueError, http.client.HTTPException):
            self.send_error(502, "Mirror upstream request failed")


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80 if parsed.scheme == "http" else None)
    return parsed.scheme, parsed.hostname or "", port


@contextlib.contextmanager
def authenticated_mirror_proxy(
    source_url: str,
    authorization: str,
    *,
    allow_private_network: bool,
    allow_private_http: bool,
) -> Iterator[str]:
    server = _ProxyServer(source_url, authorization, allow_private_network, allow_private_http)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="os-repositories-auth-proxy")
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
