#!/usr/bin/env python3
"""Generate the deterministic FastAPI OpenAPI snapshot used by frontend type generation."""
from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OUTPUT = ROOT / "openapi" / "openapi.json"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Composition imports instantiate a small number of legacy stores. The config
# file itself may be temporary, but all values capable of reaching OpenAPI are
# fixed so the schema is byte-identical across runs and CI workers.
_RUNTIME = tempfile.TemporaryDirectory(prefix="webnas-openapi-config-")
_RUNTIME_CONFIG = Path(_RUNTIME.name) / "config.yaml"
_RUNTIME_CONFIG.write_text(
    "paths:\n"
    "  data_dir: /tmp/webnas-openapi/data\n"
    "  log_dir: /tmp/webnas-openapi/log\n"
    "  temp_dir: /tmp/webnas-openapi/tmp\n"
    "security:\n"
    "  session_secret: openapi-generation-only\n",
    encoding="utf-8",
)
os.environ["WEBNAS_CONFIG"] = str(_RUNTIME_CONFIG)
os.environ["WEBNAS_CANDIDATE"] = "1"

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
        actual = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if actual != expected:
            print(f"OpenAPI snapshot is stale: run {Path(__file__).name}", file=sys.stderr)
            diff = difflib.unified_diff(actual.splitlines(), expected.splitlines(), fromfile="committed", tofile="generated", n=2)
            for line in list(diff)[:80]:
                print(line, file=sys.stderr)
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(expected, encoding="utf-8")
    print(OUTPUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
