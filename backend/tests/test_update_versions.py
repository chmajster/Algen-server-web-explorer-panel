import io
import json
import urllib.error

import pytest
from fastapi import HTTPException

from app import update_versions as versions


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch):
    monkeypatch.setattr(versions, "_cached_at", 0.0)
    monkeypatch.setattr(versions, "_cached_versions", [])


def test_candidates_are_validated_deduplicated_and_cached(monkeypatch):
    calls = []

    def fetch(resource):
        calls.append(resource)
        if resource.startswith("tags"):
            return [{"name": "v1.0", "commit": {"sha": "a" * 40}}, {"commit": {"sha": "--upload-pack=bad"}}, None]
        return [
            {"sha": "a" * 40, "commit": {"message": "duplicate"}},
            {"sha": "b" * 40, "commit": {"message": "Fix\nupdate", "committer": {"date": "2026-09-13T12:00:00Z"}}},
            {"sha": "invalid"},
        ]

    monkeypatch.setattr(versions, "_read_candidates", fetch)
    result = versions.repository_versions()
    assert [item["revision"] for item in result] == ["a" * 40, "b" * 40]
    assert result[0]["kind"] == "tag"
    assert result[1]["name"] == "Fix update"
    result[0]["revision"] = "corrupted"
    assert versions.repository_versions()[0]["revision"] == "a" * 40
    assert len(calls) == 2


def test_expired_cache_does_not_authorize_stale_versions(monkeypatch):
    monkeypatch.setattr(versions, "_cached_at", 1.0)
    monkeypatch.setattr(versions, "_cached_versions", [{"revision": "a" * 40}])
    monkeypatch.setattr(versions.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(versions, "_read_candidates", lambda _: (_ for _ in ()).throw(HTTPException(503, "unavailable")))
    with pytest.raises(HTTPException) as caught:
        versions.repository_versions()
    assert caught.value.status_code == 503


@pytest.mark.parametrize("body", [b'{}', b'not json', b'x' * (versions._MAX_RESPONSE + 1)])
def test_malformed_remote_payload_is_a_safe_error(monkeypatch, body):
    monkeypatch.setattr(versions.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(body))
    with pytest.raises(HTTPException) as caught:
        versions._read_candidates("tags?per_page=100")
    assert caught.value.status_code == 503


def test_fixed_source_timeout_and_successful_response(monkeypatch):
    def open_request(request, timeout):
        assert request.full_url == versions._REPOSITORY_API + "/tags?per_page=100"
        assert timeout == 15
        return io.BytesIO(json.dumps([]).encode())

    monkeypatch.setattr(versions.urllib.request, "urlopen", open_request)
    assert versions._read_candidates("tags?per_page=100") == []
    with pytest.raises(ValueError):
        versions._read_candidates("https://attacker.invalid")


def test_network_failure_does_not_expose_remote_exception(monkeypatch):
    def fail(*args, **kwargs):
        raise urllib.error.URLError("SECRET")

    monkeypatch.setattr(versions.urllib.request, "urlopen", fail)
    with pytest.raises(HTTPException) as caught:
        versions._read_candidates("tags?per_page=100")
    assert caught.value.status_code == 503
    assert "SECRET" not in caught.value.detail
