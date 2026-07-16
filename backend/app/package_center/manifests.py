from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import MODULE_ID_RE, ModuleManifest, api_error

MODULES_DIR = Path(__file__).resolve().parents[1] / "modules"


def module_directory(module_id: str, modules_dir: Path = MODULES_DIR) -> Path:
    if not MODULE_ID_RE.fullmatch(module_id):
        api_error(400, "INVALID_MODULE_ID", "Invalid module identifier")
    root = modules_dir.resolve(strict=False)
    candidate = (root / module_id).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError:
        api_error(400, "INVALID_MODULE_ID", "Module path escapes the module directory")
    if not candidate.is_dir():
        api_error(404, "MODULE_NOT_FOUND", "Module not found")
    return candidate


def load_manifest(module_id: str, modules_dir: Path = MODULES_DIR) -> ModuleManifest:
    directory = module_directory(module_id, modules_dir)
    path = directory / "manifest.yaml"
    if not path.is_file():
        api_error(422, "INVALID_MANIFEST", "Module manifest is missing")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("manifest root must be a mapping")
        raw.setdefault("id", module_id)
        manifest = ModuleManifest.model_validate(raw)
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as error:
        api_error(422, "INVALID_MANIFEST", f"Invalid manifest for {module_id}: {error}")
    if manifest.id != module_id:
        api_error(422, "INVALID_MANIFEST", "Manifest id does not match its directory")
    return manifest


def discover_manifests(modules_dir: Path = MODULES_DIR) -> list[ModuleManifest]:
    manifests: list[ModuleManifest] = []
    if not modules_dir.exists():
        return manifests
    for directory in sorted(modules_dir.iterdir()):
        if not directory.is_dir() or not MODULE_ID_RE.fullmatch(directory.name):
            continue
        # The modules package also contains provider infrastructure. A directory
        # becomes a user-visible module only by explicitly declaring a manifest.
        if not (directory / "manifest.yaml").is_file():
            continue
        manifest = load_manifest(directory.name, modules_dir)
        if not manifest.ui.hidden:
            manifests.append(manifest)
    return manifests


def module_script(module_id: str, action: str, modules_dir: Path = MODULES_DIR) -> Path | None:
    if action not in {"install", "update", "uninstall", "health"}:
        api_error(400, "INVALID_ACTION", "Unsupported module script action")
    directory = module_directory(module_id, modules_dir)
    for suffix in (".py", ".sh"):
        candidate = (directory / f"{action}{suffix}").resolve(strict=False)
        try:
            candidate.relative_to(directory.resolve(strict=False))
        except ValueError:
            api_error(422, "INVALID_MANIFEST", "Module script escapes its directory")
        if candidate.is_file():
            return candidate
    return None
