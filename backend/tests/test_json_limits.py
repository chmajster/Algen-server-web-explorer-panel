from __future__ import annotations

import json

import pytest

from app import json_limits


@pytest.mark.parametrize("depth", [1, 127, 128])
@pytest.mark.parametrize("container", ["array", "object", "mixed"])
def test_json_depth_limit_accepts_exact_boundary(depth: int, container: str) -> None:
    text = "0"
    for index in range(depth):
        text = '{"data":' + text + "}" if container == "object" or (container == "mixed" and index % 2) else "[" + text + "]"
    decoded = json_limits.loads_with_depth_limit(text)
    for _ in range(depth):
        decoded = decoded["data"] if isinstance(decoded, dict) else decoded[0]
    assert decoded == 0


@pytest.mark.parametrize("depth", [129, 10000])
@pytest.mark.parametrize("container", ["array", "object"])
def test_json_depth_limit_rejects_before_calling_decoder(monkeypatch: pytest.MonkeyPatch, depth: int, container: str) -> None:
    text = "[" * depth + "0" + "]" * depth if container == "array" else '{"data":' * depth + "0" + "}" * depth

    def must_not_decode(_text: str) -> None:
        raise AssertionError("excessive nesting must be rejected before allocation by the JSON decoder")

    monkeypatch.setattr(json_limits.json, "loads", must_not_decode)
    with pytest.raises(ValueError, match="nesting limit"):
        json_limits.loads_with_depth_limit(text)


@pytest.mark.parametrize("value", ["[" * 10000, "]}" * 1000, '"[{\\"}]', "\\", '\\"', "plain", "雪"])
def test_json_depth_limit_ignores_braces_and_escapes_in_strings(value: str) -> None:
    payload = {value: value}
    assert json_limits.loads_with_depth_limit(json.dumps(payload), max_depth=1) == payload


@pytest.mark.parametrize("value", [None, True, False, 12, 1.5, "test"])
def test_json_depth_limit_preserves_scalar_values(value: object) -> None:
    assert json_limits.loads_with_depth_limit(json.dumps(value)) == value


def test_json_depth_limit_does_not_confuse_width_with_depth() -> None:
    payload = [{} for _ in range(10000)]
    assert json_limits.loads_with_depth_limit(json.dumps(payload), max_depth=2) == payload


@pytest.mark.parametrize("text", ["}", "{]", '["unterminated]', "[1,]", '{}{}', '["bad\\xescape"]'])
def test_json_depth_limit_leaves_syntax_validation_to_json_decoder(text: str) -> None:
    with pytest.raises(json.JSONDecodeError):
        json_limits.loads_with_depth_limit(text)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "2", None])
def test_json_depth_limit_rejects_invalid_limit(limit: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        json_limits.loads_with_depth_limit("{}", max_depth=limit)  # type: ignore[arg-type]


def test_json_depth_limit_counts_containers_after_an_escaped_backslash() -> None:
    text = json.dumps(["\\", [[0]]])
    with pytest.raises(ValueError, match="nesting limit"):
        json_limits.loads_with_depth_limit(text, max_depth=2)
