from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_frontend_build import MANIFEST_NAME, verify


def _valid_build(root: Path) -> Path:
    dist = root / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<script type="module" src="/assets/index-test.js"></script>',
        encoding="utf-8",
    )
    (assets / "index-test.js").write_text(
        'const endpoint="/api/modules/hosts-manager/enrollment-tokens";'
        'const field="apmid_id"; console.log(endpoint, field);',
        encoding="utf-8",
    )
    return dist


def test_verify_creates_and_rechecks_integrity_manifest(tmp_path: Path) -> None:
    dist = _valid_build(tmp_path)

    verify(dist)
    manifest = json.loads((dist / MANIFEST_NAME).read_text(encoding="utf-8"))

    assert manifest["algorithm"] == "sha256"
    assert "assets/index-test.js" in manifest["files"]
    verify(dist)


def test_verify_rejects_asset_changed_after_manifest(tmp_path: Path) -> None:
    dist = _valid_build(tmp_path)
    verify(dist)
    (dist / "assets/index-test.js").write_text("const truncated='", encoding="utf-8")

    with pytest.raises(ValueError):
        verify(dist)
