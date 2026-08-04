#!/usr/bin/env python3
"""Reject incomplete, corrupted or contract-incompatible frontend builds."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


ASSET_RE = re.compile(r"(?:src|href)=[\"'](?P<path>/assets/[^\"']+)[\"']")
MANIFEST_NAME = ".webnas-assets.json"


def _asset_inventory(dist: Path, index: Path) -> dict[str, dict[str, int | str]]:
    assets_dir = dist / "assets"
    if not assets_dir.is_dir():
        raise ValueError(f"Frontend assets directory is missing: {assets_dir}")

    files = [index, *sorted(path for path in assets_dir.rglob("*") if path.is_file())]
    inventory: dict[str, dict[str, int | str]] = {}

    for path in files:
        if path.is_symlink():
            raise ValueError(f"Frontend build contains a symbolic-link asset: {path}")
        size = path.stat().st_size
        if size <= 0:
            raise ValueError(f"Frontend build contains an empty asset: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        inventory[path.relative_to(dist).as_posix()] = {"size": size, "sha256": digest}

    return inventory


def _validate_javascript(scripts: list[Path]) -> None:
    node = shutil.which("node")
    if not node:
        raise ValueError("Node.js is required to validate the generated frontend JavaScript")

    for script in scripts:
        result = subprocess.run(
            [node, "--check", str(script)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()[-2000:]
            raise ValueError(f"Frontend JavaScript is truncated or invalid: {script}: {detail}")


def _write_manifest(manifest_path: Path, payload: dict[str, object]) -> None:
    temporary = manifest_path.with_name(f".{manifest_path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, manifest_path)


def _write_or_verify_manifest(dist: Path, inventory: dict[str, dict[str, int | str]]) -> None:
    manifest_path = dist / MANIFEST_NAME
    payload: dict[str, object] = {"version": 1, "algorithm": "sha256", "files": inventory}

    if not manifest_path.is_file():
        _write_manifest(manifest_path, payload)
        return

    try:
        stored = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Frontend integrity manifest is invalid: {manifest_path}") from error

    if stored == payload:
        return

    if (
        not isinstance(stored, dict)
        or stored.get("version") != 1
        or stored.get("algorithm") != "sha256"
        or not isinstance(stored.get("files"), dict)
    ):
        raise ValueError(f"Frontend integrity manifest is invalid: {manifest_path}")

    stored_files = stored["files"]
    changed_or_missing = sorted(
        relative_path
        for relative_path, expected in stored_files.items()
        if inventory.get(relative_path) != expected
    )
    if changed_or_missing:
        raise ValueError(
            "Frontend files changed after the integrity manifest was created: "
            f"{changed_or_missing[0]}"
        )

    # During blue/green updates the installer intentionally copies immutable,
    # hashed assets from the previous release after the new build was verified.
    # Accept only this additive change. The active index and every previously
    # tracked file must remain byte-for-byte identical. Extend the manifest so
    # the copied compatibility assets are protected by subsequent validations.
    added = sorted(set(inventory) - set(stored_files))
    unsafe_added = [relative_path for relative_path in added if not relative_path.startswith("assets/")]
    if unsafe_added:
        raise ValueError(
            "Frontend files changed after the integrity manifest was created: "
            f"{unsafe_added[0]}"
        )

    _write_manifest(manifest_path, payload)


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

    scripts = sorted((dist / "assets").rglob("*.js"))
    if not scripts:
        raise ValueError("Frontend build does not contain any JavaScript assets")

    _validate_javascript(scripts)

    bundle = "\n".join(path.read_text(encoding="utf-8", errors="strict") for path in scripts)
    if "/api/modules/hosts-manager/enrollment-tokens" not in bundle:
        raise ValueError("Frontend bundle does not contain the enrollment-token API")
    if "apmid_id" not in bundle:
        raise ValueError("Frontend bundle does not contain the canonical apmid_id contract")

    inventory = _asset_inventory(dist, index)
    _write_or_verify_manifest(dist, inventory)
    return referenced


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", type=Path)
    args = parser.parse_args()
    referenced = verify(args.dist.resolve())
    print(
        "Verified frontend build: "
        f"{len(referenced)} active assets, JavaScript syntax valid, SHA-256 manifest consistent"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
