from __future__ import annotations

import json
from pathlib import Path

import yaml

from .models import PluginManifest
from .validator import PluginValidator


def load_manifest(path: Path) -> PluginManifest:
    if not path.exists() or not path.is_file():
        raise ValueError("plugin manifest not found")
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("plugin manifest must be an object")
    return PluginValidator().validate_manifest(PluginManifest.model_validate(raw))
