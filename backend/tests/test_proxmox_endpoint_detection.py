from __future__ import annotations

import io
import urllib.error
from typing import Any

import pytest

from app.modules.proxmox_manager import endpoint as endpoint_module
from app.modules.proxmox_manager.endpoint import detect_endpoint, normalize_endpoint_input


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


def test_scheme_less_endpoint_defaults_to_proxmox_port():
    assert normalize_endpoint_input("10.0.0.10") == "10.0.0.10:8006"
    assert normalize_endpoint_input("pve.example:9000") == "pve.example:9000"


def test_explicit_protocol_is_preserved():
    assert normalize_endpoint_input("https://pve.example:8006/") == "https://pve.example:8006"
    assert detect_endpoint("http://pve.example:8006") == "http://pve.example:8006"


def test_invalid_endpoint_path_and_credentials_are_rejected():
    with pytest.raises(ValueError):
        normalize_endpoint_input("10.0.0.10/api2/json")
    with pytest.raises(ValueError):
        normalize_endpoint_input("https://root:secret@10.0.0.10:8006")


def test_detection_prefers_https(monkeypatch):
    calls: list[str] = []

    def open_url(request, **_kwargs):
        calls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(endpoint_module.urllib.request, "urlopen", open_url)

    assert detect_endpoint("10.0.0.10:8006") == "https://10.0.0.10:8006"
    assert calls == ["https://10.0.0.10:8006/api2/json/version"]


def test_detection_falls_back_to_http(monkeypatch):
    calls: list[str] = []

    def open_url(request, **_kwargs):
        calls.append(request.full_url)
        if request.full_url.startswith("https://"):
            raise urllib.error.URLError("wrong version number")
        return FakeResponse()

    monkeypatch.setattr(endpoint_module.urllib.request, "urlopen", open_url)

    assert detect_endpoint("10.0.0.10:8006") == "http://10.0.0.10:8006"
    assert calls == [
        "https://10.0.0.10:8006/api2/json/version",
        "http://10.0.0.10:8006/api2/json/version",
    ]


def test_http_error_still_confirms_transport(monkeypatch):
    def open_url(request, **_kwargs):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", hdrs=None, fp=io.BytesIO(b"{}"))

    monkeypatch.setattr(endpoint_module.urllib.request, "urlopen", open_url)

    assert detect_endpoint("pve.example:8006") == "https://pve.example:8006"


def test_detection_fails_if_neither_transport_responds(monkeypatch):
    monkeypatch.setattr(
        endpoint_module.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )

    with pytest.raises(ValueError, match="HTTPS and HTTP probes both failed"):
        detect_endpoint("10.0.0.10:8006")
