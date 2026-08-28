#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "backend" / "requirements.txt"
HEADER = "# Generated from pyproject.toml by scripts/sync-python-deps.py. Do not edit manually."


def render_requirements() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dependencies = data.get("project", {}).get("dependencies")
    if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
        raise SystemExit("pyproject.toml must define project.dependencies as a list of strings")
    return f"{HEADER}\n" + "\n".join(dependencies) + "\n"


def check(expected: str) -> int:
    actual = REQUIREMENTS.read_text(encoding="utf-8") if REQUIREMENTS.exists() else ""
    if actual == expected:
        print("backend/requirements.txt matches pyproject.toml")
        return 0

    diff = difflib.unified_diff(
        actual.splitlines(keepends=True),
        expected.splitlines(keepends=True),
        fromfile=str(REQUIREMENTS.relative_to(ROOT)),
        tofile="generated from pyproject.toml",
    )
    sys.stderr.write("backend/requirements.txt is out of sync with pyproject.toml\n")
    sys.stderr.writelines(diff)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize backend runtime requirements from pyproject.toml")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail when backend/requirements.txt differs")
    mode.add_argument("--write", action="store_true", help="regenerate backend/requirements.txt")
    args = parser.parse_args()

    expected = render_requirements()
    if args.write:
        REQUIREMENTS.write_text(expected, encoding="utf-8")
        print(f"updated {REQUIREMENTS.relative_to(ROOT)}")
        return 0
    return check(expected)


if __name__ == "__main__":
    raise SystemExit(main())
