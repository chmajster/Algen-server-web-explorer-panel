#!/usr/bin/env python3
"""Generate the deterministic FastAPI OpenAPI snapshot used by frontend type generation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OUTPUT = ROOT / "openapi" / "openapi.json"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.bootstrap import create_app  # noqa: E402


def render() -> str:
    app = create_app(mount_frontend=False)
    schema = app.openapi()
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the committed OpenAPI snapshot is stale")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            print(f"OpenAPI snapshot is stale: run {Path(__file__).name}", file=sys.stderr)
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8")
    print(OUTPUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
