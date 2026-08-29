from __future__ import annotations

from app.core.cache import TTLCache


def test_ttl_cache_reuses_value_until_invalidated() -> None:
    cache: TTLCache[int] = TTLCache(60)
    calls = 0

    def load() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert cache.get_or_load(load) == 1
    assert cache.get_or_load(load) == 1
    assert calls == 1

    cache.invalidate()
    assert cache.get_or_load(load) == 2
    assert calls == 2


def test_zero_ttl_cache_never_reuses_value() -> None:
    cache: TTLCache[int] = TTLCache(0)
    calls = 0

    def load() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert cache.get_or_load(load) == 1
    assert cache.get_or_load(load) == 2
    assert calls == 2
