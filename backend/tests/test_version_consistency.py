import json
import tomllib
from pathlib import Path

from app import __version__


ROOT = Path(__file__).resolve().parents[2]


def test_release_version_is_consistent_across_backend_and_frontend_metadata():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    package_lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == __version__
    assert package["version"] == __version__
    assert package_lock["version"] == __version__
    assert package_lock["packages"][""]["version"] == __version__


def test_displayed_versions_are_derived_from_canonical_sources():
    settings_source = (ROOT / "backend/app/settings.py").read_text(encoding="utf-8")
    frontend_source = (ROOT / "frontend/src/features/settings/SettingsApp.tsx").read_text(encoding="utf-8")

    assert '"version": __version__' in settings_source
    assert '"version": "0.1.18"' not in settings_source
    assert "packageMetadata.version" in frontend_source
    assert ">0.1.18<" not in frontend_source
