from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
import urllib.parse
from typing import Any

import httpx

from ...package_center.models import api_error


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, hostname: str, port: int, address: str, *, timeout: float) -> None:
        super().__init__(hostname, port, timeout=timeout)
        self._pinned_address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_address, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        hostname: str,
        port: int,
        address: str,
        *,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(hostname, port, timeout=timeout, context=context)
        self._pinned_address = address
        self._tls_context = context

    def connect(self) -> None:
        raw = socket.create_connection((self._pinned_address, self.port), self.timeout)
        try:
            self.sock = self._tls_context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def _tls_context(verify: bool | ssl.SSLContext) -> ssl.SSLContext:
    if isinstance(verify, ssl.SSLContext):
        return verify
    if verify:
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        return context
    return ssl._create_unverified_context()  # nosec B323 - mirrors explicit registry TLS opt-out


def _effective_port(parsed: urllib.parse.SplitResult) -> int:
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def _validated_target(url: str, expected_host: str, require_tls: bool) -> tuple[urllib.parse.SplitResult, list[str]]:
    try:
        parsed = urllib.parse.urlsplit(url)
        expected = urllib.parse.urlsplit(f"https://{expected_host}")
        port = _effective_port(parsed)
        expected_port = expected.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        api_error(400, "UNSAFE_REGISTRY_URL", "Registry URL is not allowed")
    if (
        parsed.scheme not in {"http", "https"}
        or (require_tls and parsed.scheme != "https")
        or (parsed.hostname or "").lower().rstrip(".") != (expected.hostname or "").lower().rstrip(".")
        or port != expected_port
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
    ):
        api_error(400, "UNSAFE_REGISTRY_URL", "Registry URL is not allowed")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname == "metadata.google.internal":
        api_error(400, "UNSAFE_REGISTRY_URL", "Registry URL is not allowed")
    try:
        addresses = sorted({
            str(ipaddress.ip_address(item[4][0]))
            for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        })
    except (socket.gaierror, ValueError):
        api_error(502, "REGISTRY_DNS_FAILED", "The registry host could not be resolved")
    if not addresses or any(
        ipaddress.ip_address(address).is_loopback
        or ipaddress.ip_address(address).is_link_local
        or ipaddress.ip_address(address).is_multicast
        or ipaddress.ip_address(address).is_unspecified
        or ipaddress.ip_address(address).is_reserved
        for address in addresses
    ):
        api_error(400, "UNSAFE_REGISTRY_URL", "Registry URL is not allowed")
    return parsed, addresses


def _connect_timeout(request: httpx.Request, fallback: float = 20.0) -> float:
    timeout = request.extensions.get("timeout")
    if isinstance(timeout, dict):
        value = timeout.get("connect")
        if value is not None:
            try:
                parsed = float(value)
            except (TypeError, ValueError, OverflowError):
                return fallback
            if parsed > 0:
                return parsed
    return fallback


class _PinnedRegistryTransport(httpx.BaseTransport):
    def __init__(
        self,
        *,
        expected_host: str,
        require_tls: bool,
        verify: bool | ssl.SSLContext,
        response_limit: int,
    ) -> None:
        self.expected_host = expected_host
        self.require_tls = require_tls
        self.verify = verify
        self.response_limit = response_limit

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        parsed, addresses = _validated_target(str(request.url), self.expected_host, self.require_tls)
        hostname = parsed.hostname
        if not hostname:
            api_error(400, "UNSAFE_REGISTRY_URL", "Registry URL is not allowed")
        port = _effective_port(parsed)
        target = parsed.path or "/"
        if parsed.query:
            target += f"?{parsed.query}"
        body = request.read()
        request_headers = {name: value for name, value in request.headers.multi_items()}
        # Do not let HTTPX advertise gzip/br/deflate here: constructing a Response
        # from a compressed body may decode it before the post-decode size guard.
        request_headers["Accept-Encoding"] = "identity"
        connect_timeout = _connect_timeout(request)
        last_error: BaseException | None = None
        for address in addresses:
            connection: http.client.HTTPConnection
            if parsed.scheme == "https":
                connection = _PinnedHTTPSConnection(
                    hostname,
                    port,
                    address,
                    timeout=connect_timeout,
                    context=_tls_context(self.verify),
                )
            else:
                connection = _PinnedHTTPConnection(hostname, port, address, timeout=connect_timeout)
            try:
                connection.request(request.method, target, body=body, headers=request_headers)
                response = connection.getresponse()
                response_headers = response.getheaders()
                content_encoding = next(
                    (value for name, value in response_headers if name.lower() == "content-encoding"),
                    "",
                ).strip().lower()
                if content_encoding and content_encoding != "identity":
                    api_error(
                        502,
                        "UNSUPPORTED_REGISTRY_ENCODING",
                        "Registry returned an unsupported compressed response",
                    )
                response_body = response.read(self.response_limit + 1)
                if len(response_body) > self.response_limit:
                    api_error(502, "REGISTRY_RESPONSE_TOO_LARGE", "Registry response exceeded the safety limit")
                return httpx.Response(
                    status_code=int(response.status),
                    headers=response_headers,
                    content=response_body,
                    request=request,
                )
            except (TimeoutError, socket.timeout) as error:
                last_error = error
            except (OSError, ssl.SSLError, http.client.HTTPException) as error:
                last_error = error
            finally:
                connection.close()
        if isinstance(last_error, (TimeoutError, socket.timeout)):
            raise httpx.TimeoutException("Registry request timed out", request=request) from last_error
        raise httpx.ConnectError("Registry connection failed", request=request) from last_error


def install_docker_registry_transport(provider_cls: type[Any]) -> None:
    def _registry_fetch_json(
        self: Any,
        url: str,
        *,
        expected_host: str,
        require_tls: bool,
        verify: bool | ssl.SSLContext,
        auth: httpx.BasicAuth | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        response_limit = int(
            getattr(
                __import__(provider_cls.__module__, fromlist=["REGISTRY_RESPONSE_LIMIT"]),
                "REGISTRY_RESPONSE_LIMIT",
                2 * 1024 * 1024,
            )
        )
        transport = _PinnedRegistryTransport(
            expected_host=expected_host,
            require_tls=require_tls,
            verify=verify,
            response_limit=response_limit,
        )
        try:
            with httpx.Client(
                timeout=httpx.Timeout(20.0, connect=8.0),
                verify=verify,
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client:
                with client.stream(
                    "GET",
                    url,
                    auth=auth,
                    headers={"Accept": "application/json", "Accept-Encoding": "identity", **(headers or {})},
                ) as response:
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > response_limit:
                            api_error(502, "REGISTRY_RESPONSE_TOO_LARGE", "Registry response exceeded the safety limit")
                    response_headers = {key.lower(): value for key, value in response.headers.items()}
                    if not body:
                        payload: dict[str, Any] = {}
                    else:
                        try:
                            decoded = json.loads(body.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            if 200 <= response.status_code < 300:
                                api_error(502, "INVALID_REGISTRY_RESPONSE", "Registry returned an invalid response")
                            decoded = {}
                        if not isinstance(decoded, dict):
                            api_error(502, "INVALID_REGISTRY_RESPONSE", "Registry returned an invalid response")
                        payload = decoded
                    return response.status_code, payload, response_headers
        except httpx.TimeoutException:
            api_error(504, "REGISTRY_TIMEOUT", "The registry did not respond in time")
        except (httpx.HTTPError, UnicodeDecodeError, json.JSONDecodeError):
            api_error(502, "REGISTRY_CONNECTION_FAILED", "Could not read a valid response from the registry")

    provider_cls._registry_fetch_json = _registry_fetch_json
