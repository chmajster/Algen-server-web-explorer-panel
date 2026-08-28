from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit


DEFAULT_PROXMOX_PORT = 8006
SUPPORTED_SCHEMES = {"http", "https"}


def _host_for_url(hostname: str) -> str:
    return f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname


def normalize_endpoint_input(value: str) -> str:
    """Validate an endpoint origin while allowing the scheme to be omitted.

    Scheme-less addresses default to Proxmox's standard port. They remain
    scheme-less here so the backend can determine the transport by probing the
    target host instead of guessing in the browser.
    """

    raw = value.strip().rstrip("/")
    if not raw:
        raise ValueError("Proxmox endpoint is required")

    explicit_scheme = "://" in raw
    parsed = urlsplit(raw if explicit_scheme else f"//{raw}")
    scheme = parsed.scheme.lower() if explicit_scheme else ""
    if explicit_scheme and scheme not in SUPPORTED_SCHEMES:
        raise ValueError("Proxmox endpoint must use HTTP or HTTPS when a protocol is provided")
    if not parsed.hostname:
        raise ValueError("Proxmox endpoint must contain a host name or IP address")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Proxmox endpoint cannot contain credentials, query or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("Proxmox endpoint must be an origin without a path")

    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Proxmox endpoint contains an invalid port") from error
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Proxmox endpoint contains an invalid port")
    if not explicit_scheme and port is None:
        port = DEFAULT_PROXMOX_PORT

    authority = _host_for_url(parsed.hostname)
    if port is not None:
        authority = f"{authority}:{port}"
    return f"{scheme}://{authority}" if scheme else authority


def _transport_responds(endpoint: str, *, timeout: float) -> bool:
    request = urllib.request.Request(
        f"{endpoint}/api2/json/version",
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "WebNAS-Proxmox-Protocol-Probe/1"},
    )
    context = ssl._create_unverified_context() if endpoint.startswith("https://") else None  # noqa: S323 - transport detection only.
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context):  # nosec B310 - administrator-configured Proxmox endpoint.
            return True
    except urllib.error.HTTPError:
        # Authentication failures and other HTTP status codes still prove that
        # the selected transport protocol is correct.
        return True
    except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError):
        return False


def detect_endpoint(value: str, *, timeout: float = 2.0) -> str:
    """Return a canonical endpoint, probing HTTPS first when scheme is absent."""

    normalized = normalize_endpoint_input(value)
    parsed = urlsplit(normalized)
    if parsed.scheme in SUPPORTED_SCHEMES:
        return normalized

    candidates = (f"https://{normalized}", f"http://{normalized}")
    for candidate in candidates:
        if _transport_responds(candidate, timeout=timeout):
            return candidate
    raise ValueError(
        f"Could not detect the Proxmox API protocol for {normalized}; HTTPS and HTTP probes both failed"
    )
