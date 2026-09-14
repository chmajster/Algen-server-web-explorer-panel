"""Bounded, cached recovery candidates from the fixed WebNAS repository."""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from fastapi import HTTPException

_REPOSITORY_API = "https://api.github.com/repos/chmajster/Algen-server-web-explorer-panel"
_MAX_RESPONSE = 2 * 1024 * 1024
_CACHE_SECONDS = 300
_lock = threading.Lock()
_cached_at = 0.0
_cached_versions: list[dict[str, Any]] = []


def _read_candidates(resource: str) -> list:
    # Only these fixed resources may be fetched; no client-controlled URL/ref.
    if resource not in {"tags?per_page=100", "commits?sha=main&per_page=30"}:
        raise ValueError("Unsupported version resource")
    request = urllib.request.Request(
        f"{_REPOSITORY_API}/{resource}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "WebNAS-update-recovery/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310 - fixed HTTPS repository
            raw = response.read(_MAX_RESPONSE + 1)
        if len(raw) > _MAX_RESPONSE:
            raise ValueError("Version response is too large")
        value = json.loads(raw)
        if not isinstance(value, list):
            raise ValueError("Invalid version response")
        return value
    except (OSError, urllib.error.URLError, ValueError) as error:
        raise HTTPException(503, "Nie można pobrać wersji z GitHub. Sprawdź połączenie lub spróbuj ponownie później.") from error


def _label(value: Any, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    return re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()[:160] or fallback


def repository_versions() -> list[dict[str, Any]]:
    global _cached_at, _cached_versions
    with _lock:
        if _cached_at and time.monotonic() - _cached_at < _CACHE_SECONDS:
            return [dict(item) for item in _cached_versions]
        versions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for kind, resource in (("tag", "tags?per_page=100"), ("commit", "commits?sha=main&per_page=30")):
            for item in _read_candidates(resource):
                if not isinstance(item, dict):
                    continue
                commit = item.get("commit")
                commit = commit if isinstance(commit, dict) else {}
                revision = commit.get("sha") if kind == "tag" else item.get("sha")
                if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision) or revision in seen:
                    continue
                committer = commit.get("committer")
                date = committer.get("date") if isinstance(committer, dict) else None
                versions.append({
                    "revision": revision,
                    "name": _label(item.get("name") if kind == "tag" else commit.get("message"), revision[:12]),
                    "kind": kind,
                    "published_at": date if isinstance(date, str) else None,
                })
                seen.add(revision)
        _cached_versions = versions
        _cached_at = time.monotonic()
        return [dict(item) for item in versions]
