from __future__ import annotations

from types import SimpleNamespace

from app.platform_api import _asset_response_is_complete, _strip_asset_range_headers


def test_asset_range_headers_are_removed() -> None:
    request = SimpleNamespace(
        scope={
            "headers": [
                (b"host", b"localhost"),
                (b"range", b"bytes=100-200"),
                (b"if-range", b'"etag"'),
                (b"accept", b"*/*"),
            ]
        }
    )

    _strip_asset_range_headers(request)

    assert request.scope["headers"] == [
        (b"host", b"localhost"),
        (b"accept", b"*/*"),
    ]


def test_only_nonempty_200_response_is_cacheable() -> None:
    complete = SimpleNamespace(status_code=200, headers={"Content-Length": "123"})
    partial = SimpleNamespace(status_code=206, headers={"Content-Length": "50"})
    empty = SimpleNamespace(status_code=200, headers={"Content-Length": "0"})
    missing_length = SimpleNamespace(status_code=200, headers={})

    assert _asset_response_is_complete(complete) is True
    assert _asset_response_is_complete(partial) is False
    assert _asset_response_is_complete(empty) is False
    assert _asset_response_is_complete(missing_length) is False
