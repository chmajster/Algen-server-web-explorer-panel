from __future__ import annotations

import json
import math
from typing import Any


MAX_JSON_DEPTH = 128


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON response contains a non-finite number")
    return number


def loads_with_depth_limit(text: str, *, max_depth: int = MAX_JSON_DEPTH) -> Any:
    """Reject excessive nesting before decoding an already size-bounded response.

    Count only structural braces/brackets outside quoted strings. The standard
    decoder remains responsible for JSON syntax, escapes and number validation.
    This scan is iterative and uses constant extra memory; it does not depend on
    the Python version's C decoder recursion limit. Callers must bound input size.
    """
    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 1:
        raise ValueError("JSON depth limit must be a positive integer")
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > max_depth:
                raise ValueError("JSON response exceeded the nesting limit")
        elif character in "]}":
            depth -= 1
    return json.loads(text, parse_float=_finite_float, parse_constant=_finite_float)
