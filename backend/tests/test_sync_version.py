from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sync-version.py"
SPEC = importlib.util.spec_from_file_location("sync_version", SCRIPT)
assert SPEC and SPEC.loader
sync_version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_version)


def make_repo(root: Path, version: str = "0.1.21") -> Path:
    (root / "frontend").mkdir(parents=True)
    (root / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["setuptools"]\n\n[project]\nname = "webnas"\nversion = "0.1.21"\n',
        encoding="utf-8",
    )
    package = {"name": "webnas-frontend", "version": "0.1.21", "private": True}
    (root / "frontend" / "package.json").write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    lock = {
        "name": "webnas-frontend",
        "version": "0.1.21",
        "lockfileVersion": 3,
        "packages": {"": {"name": "webnas-frontend", "version": "0.1.21"}},
    }
    (root / "frontend" / "package-lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("value", ["0.0.0", "0.1.21", "1.0.0", "10.20.30"])
def test_accepts_semver(value: str) -> None:
    assert sync_version.parse_version(value) == tuple(map(int, value.split(".")))


@pytest.mark.parametrize("value", ["", "v1.2.3", "1.2", "1.2.3.4", "01.2.3", "1.2.3-beta"])
def test_rejects_invalid_semver(value: str) -> None:
    with pytest.raises(sync_version.VersionError):
        sync_version.parse_version(value)


def test_check_succeeds_without_modifying_files(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert sync_version.main(["--root", str(root), "--check"]) == 0
    after = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert after == before


def test_check_detects_mismatched_versions(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    package_path = root / "frontend" / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["version"] = "9.9.9"
    package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    assert sync_version.main(["--root", str(root), "--check"]) == 1


@pytest.mark.parametrize(
    ("part", "expected"),
    [("patch", "0.1.22"), ("minor", "0.2.0"), ("major", "1.0.0")],
)
def test_bump_updates_all_version_files(tmp_path: Path, part: str, expected: str) -> None:
    root = make_repo(tmp_path)
    assert sync_version.main(["--root", str(root), "--bump", part]) == 0
    assert (root / "VERSION").read_text(encoding="utf-8") == f"{expected}\n"
    assert sync_version.project_version((root / "pyproject.toml").read_text(encoding="utf-8")) == expected
    package = json.loads((root / "frontend" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    assert package["version"] == expected
    assert lock["version"] == expected
    assert lock["packages"][""]["version"] == expected


def test_sync_repairs_package_json_and_pyproject(tmp_path: Path) -> None:
    root = make_repo(tmp_path, version="2.3.4")
    assert sync_version.main(["--root", str(root)]) == 0
    assert sync_version.project_version((root / "pyproject.toml").read_text(encoding="utf-8")) == "2.3.4"
    package = json.loads((root / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert package["version"] == "2.3.4"


def test_invalid_version_fails_before_writes(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / "VERSION").write_text("v0.1.21\n", encoding="utf-8")
    pyproject_before = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert sync_version.main(["--root", str(root)]) == 2
    assert (root / "pyproject.toml").read_text(encoding="utf-8") == pyproject_before
