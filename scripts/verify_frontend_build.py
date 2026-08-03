#!/usr/bin/env python3
"""Fail when a frontend build is incomplete or carries the old enrollment contract."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ASSET_RE = re.compile(r"(?:src|href)=[\"'](?P<path>/assets/[^\"']+)[\"']")


def verify(dist: Path) -> list[Path]:
    index = dist / "index.html"
    if not index.is_file():
        raise ValueError(f"Frontend index is missing: {index}")
    html = index.read_text(encoding="utf-8")
    referenced = [dist / match.group("path").lstrip("/") for match in ASSET_RE.finditer(html)]
    if not referenced:
        raise ValueError("Frontend index does not reference any hashed assets")
    missing = [path for path in referenced if not path.is_file()]
    if missing:
        raise ValueError(f"Frontend index references missing asset: {missing[0]}")
    scripts = list((dist / "assets").glob("*.js"))
    bundle = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in scripts)
    if "/api/modules/hosts-manager/enrollment-tokens" not in bundle:
        raise ValueError("Frontend bundle does not contain the enrollment-token API")
    if "apmid_id" not in bundle:
        raise ValueError("Frontend bundle does not contain the canonical apmid_id contract")
    return referenced


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", type=Path)
    args = parser.parse_args()
    referenced = verify(args.dist.resolve())
    print(f"Verified frontend build: {len(referenced)} active assets, canonical apmid_id contract present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
