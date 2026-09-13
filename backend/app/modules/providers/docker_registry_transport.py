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
        return ssl.create_default_context()
    return ssl._create_unverified_context()  # nosec B323 - mirrors explicit registry TLS opt-out


def _validated_target(url: str, expected_host: str, require_tls: bool) -> tuple[urllib.parse.SplitResult, list[str]]:
    try:
        parsed = urllib.parse.urlsplit(url)
        expected = urllib.parse.urlsplit(f"https://{expected_host}")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        api_error(400, "UNSAFE_REGISTRY_URL", "Registry URL is not allowed")
    if (
        parsed.scheme not in {"http", "https"}
        or (require_tls and parsed.scheme != "https")
        or parsed.hostname != expected.hostname
        or parsed.port != expected.port
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


def _auth_headers(url: str, auth: httpx.BasicAuth | None, headers: dict[str, str] | None) -> dict[str, str]:
    result = {"Accept": "application/json", **(headers or {})}
    if auth is None:
        return result
    request = httpx.Request("GET", url)
    try:
        authenticated = next(auth.auth_flow(request))
    except StopIteration:
        api_error(502, "REGISTRY_AUTH_FAILED", "Registry authentication failed")
    authorization = authenticated.headers.get("Authorization")
    if authorization:
        result["Authorization"] = authorization
    return result


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
        parsed, addresses = _validated_target(url, expected_host, require_tls)
        hostname = parsed.hostname
        if not hostname:
            api_error(400, "UNSAFE_REGISTRY_URL", "Registry URL is not allowed")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        target = parsed.path or "/"
        if parsed.query:
            target += f"?{parsed.query}"
        request_headers = _auth_headers(url, auth, headers)
        response_limit = int(getattr(self, "REGISTRY_RESPONSE_LIMIT", 0) or 2 * 1024 * 1024)
        # DockerProvider keeps this as a module-level constant, so read it from the
        # defining module without importing docker.py here and creating a cycle.
        module_limit = getattr(__import__(provider_cls.__module__, fromlist=["REGISTRY_RESPONSE_LIMIT"]), "REGISTRY_RESPONSE_LIMIT", response_limit)
        response_limit = int(module_limit)
        last_error: BaseException | None = None
        timed_out = False
        for address in addresses:
            connection: http.client.HTTPConnection
            if parsed.scheme == "https":
                connection = _PinnedHTTPSConnection(
                    hostname,
                    port,
                    address,
                    timeout=20.0,
                    context=_tls_context(verify),
                )
            else:
                connection = _PinnedHTTPConnection(hostname, port, address, timeout=20.0)
            try:
                connection.request("GET", target, headers=request_headers)
                response = connection.getresponse()
                body = response.read(response_limit + 1)
                if len(body) > response_limit:
                    api_error(502, "REGISTRY_RESPONSE_TOO_LARGE", "Registry response exceeded the safety limit")
                response_headers = {key.lower(): value for key, value in response.getheaders()}
                if not body:
                    payload: dict[str, Any] = {}
                else:
                    try:
                        decoded = json.loads(body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        if 200 <= response.status < 300:
                            api_error(502, "INVALID_REGISTRY_RESPONSE", "Registry returned an invalid response")
                        decoded = {}
                    if not isinstance(decoded, dict):
                        api_error(502, "INVALID_REGISTRY_RESPONSE", "Registry returned an invalid response")
                    payload = decoded
                return int(response.status), payload, response_headers
            except (TimeoutError, socket.timeout) as error:
                timed_out = True
                last_error = error
            except (OSError, ssl.SSLError, http.client.HTTPException) as error:
                last_error = error
            finally:
                connection.close()
        if timed_out and last_error is not None:
            api_error(504, "REGISTRY_TIMEOUT", "The registry did not respond in time")
        api_error(502, "REGISTRY_CONNECTION_FAILED", "Could not read a valid response from the registry")

    provider_cls._registry_fetch_json = _registry_fetch_json
