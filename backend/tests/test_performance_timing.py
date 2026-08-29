from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app import performance


def test_only_hot_paths_are_instrumented():
    assert performance.tracked_endpoint("/api/files/list") is True
    assert performance.tracked_endpoint("/api/system/resources") is True
    assert performance.tracked_endpoint("/api/modules/hosts-manager/hosts") is True
    assert performance.tracked_endpoint("/api/settings/me") is False


def test_timing_does_not_log_query_string(monkeypatch):
    messages: list[tuple] = []
    monkeypatch.setattr(performance.logger, "info", lambda *args: messages.append(args))
    request = SimpleNamespace(url=SimpleNamespace(path="/api/files/list"))
    response = SimpleNamespace(status_code=200)

    async def call_next(_request):
        return response

    assert asyncio.run(performance.performance_timing(request, call_next)) is response
    assert messages
    assert messages[0][0] == "performance_timing endpoint=%s duration_ms=%.2f status=%s"
    assert messages[0][1] == "/api/files/list"
    assert len(messages[0]) == 4
