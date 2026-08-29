from __future__ import annotations

import re
from typing import Any


SENSITIVE_MARKERS = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "authorization",
    "credential",
    "cookie",
    "connection_string",
    "connection string",
    "database_url",
    "database url",
    "private_key",
    "private key",
    "api_key",
    "api key",
    "access_key",
    "access key",
    "vault",
)
TEXT_SECRET_RE = re.compile(
    r"(?i)(password|passwd|passphrase|token|secret|cookie|"
    r"connection[_ -]?string|database[_ -]?url|private[_ -]?key|api[_ -]?key|"
    r"access[_ -]?key|vault)(\s*[:=]\s*)([^\s,;]+)"
)
AUTHORIZATION_RE = re.compile(
    r"(?i)(\bauthorization\s*[:=]\s*)(?:bearer\s+|basic\s+)?([^\s,;]+)"
)
BEARER_RE = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
    re.DOTALL,
)
URL_CREDENTIAL_RE = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^:/\s]+:)[^@\s]+@")


def sensitive_key(value: object) -> bool:
    normalized = str(value).casefold()
    return any(marker in normalized for marker in SENSITIVE_MARKERS)


def redact_text(
    value: object,
    known_secrets: list[str] | tuple[str, ...] | set[str] | None = None,
    limit: int = 512 * 1024,
) -> str:
    """Return bounded text with common secret representations removed.

    ``known_secrets`` is intentionally optional so callers can redact values that
    do not carry a recognizable key name, such as subprocess output containing a
    credential copied verbatim from another source.
    """

    text = str(value)
    for secret in known_secrets or ():
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", text)
    text = URL_CREDENTIAL_RE.sub(r"\1[REDACTED]@", text)
    text = AUTHORIZATION_RE.sub(r"\1[REDACTED]", text)
    text = BEARER_RE.sub(r"\1[REDACTED]", text)
    text = TEXT_SECRET_RE.sub(r"\1\2[REDACTED]", text)
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) > limit:
        text = encoded[:limit].decode("utf-8", errors="ignore") + "\n[TRUNCATED]"
    return text


def redact(
    value: Any,
    known_secrets: list[str] | tuple[str, ...] | set[str] | None = None,
    *,
    depth: int = 0,
) -> Any:
    """Recursively redact structured values while bounding hostile payloads."""

    if depth > 6:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            str(key)[:128]: "[REDACTED]"
            if sensitive_key(key)
            else redact(nested, known_secrets, depth=depth + 1)
            for key, nested in list(value.items())[:500]
        }
    if isinstance(value, (list, tuple, set)):
        return [redact(item, known_secrets, depth=depth + 1) for item in list(value)[:5000]]
    if isinstance(value, str):
        return redact_text(value, known_secrets)
    return value
