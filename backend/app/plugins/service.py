from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from fastapi import HTTPException

from ..activity import ActivityCategory, record_activity
from ..audit import logger
from ..config import get_config
from .models import StorePlugin
from .repository import PluginRepository
from .validator import PluginValidator


PLUGIN_CODEX_TEMPLATE = """Codex task: install or update an Algen Web Explorer Panel plugin from GitHub.

Repository:
{github_url}

Branch/ref:
{branch}

Rules:
- Inspect the repository before changing files.
- Read its README and manifest first.
- Do not run destructive commands.
- Verify the plugin fits the current Algen plugin/module conventions.
- Copy or generate only the files required by the plugin.
- Add or update tests when the plugin changes backend or frontend behavior.
- Run the relevant validation commands and report results.
"""


def plugin_id(name: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_.-]+", "-", name.lower()).strip("-.") or "plugin"
    base = base[:50]
    candidate = base
    counter = 2
    while candidate in existing:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


class PluginService:
    def __init__(self, repository: PluginRepository, validator: PluginValidator | None = None) -> None:
        self.repository = repository
        self.validator = validator or PluginValidator()

    def list(self) -> list[StorePlugin]:
        return self.repository.list()

    def create(self, payload: StorePlugin, actor: str) -> StorePlugin:
        existing = {item.id for item in self.list()}
        payload.id = payload.id or plugin_id(payload.name, existing)
        if payload.id in existing:
            raise HTTPException(409, "Plugin id already exists")
        payload.created_at = payload.created_at or time.time()
        payload.updated_at = time.time()
        payload.source_ref = payload.source_ref or payload.branch
        payload.codex_instructions = payload.codex_instructions.strip() or PLUGIN_CODEX_TEMPLATE.format(github_url=payload.github_url, branch=payload.branch)
        stored = self.repository.upsert(self.validator.validate_store_plugin(payload))
        self._audit(actor, "plugin installed", stored, {"repository": stored.github_url, "trust": stored.trust.value})
        return stored

    def update(self, plugin_id_value: str, payload: StorePlugin, actor: str) -> StorePlugin:
        previous = self.repository.get(plugin_id_value)
        if previous is None:
            raise HTTPException(404, "Plugin entry not found")
        payload.id = plugin_id_value
        payload.created_at = previous.created_at
        payload.updated_at = time.time()
        payload.codex_instructions = payload.codex_instructions.strip() or PLUGIN_CODEX_TEMPLATE.format(github_url=payload.github_url, branch=payload.branch)
        stored = self.repository.upsert(self.validator.validate_store_plugin(payload))
        if previous.enabled != stored.enabled:
            self._audit(actor, "plugin enabled" if stored.enabled else "plugin disabled", stored)
        if previous.trust != stored.trust:
            self._audit(actor, "plugin trust changed", stored, {"from": previous.trust.value, "to": stored.trust.value})
        if previous.resolved_commit != stored.resolved_commit or previous.installed_version != stored.installed_version:
            self._audit(actor, "plugin updated", stored, {"installed_version": stored.installed_version, "resolved_commit": stored.resolved_commit})
        logger.info("plugin_update actor=%s plugin=%s", actor, stored.id)
        return stored

    def delete(self, plugin_id_value: str, actor: str) -> None:
        existing = self.repository.get(plugin_id_value)
        if existing is None or not self.repository.delete(plugin_id_value):
            raise HTTPException(404, "Plugin entry not found")
        self._audit(actor, "plugin removed", existing)

    @staticmethod
    def _audit(actor: str, action: str, plugin: StorePlugin, details: dict | None = None) -> None:
        record_activity(ActivityCategory.module, action, actor, target=plugin.id, details=details or {}, source="plugins")
        logger.info("plugin_audit actor=%s action=%s plugin=%s", actor, action.replace(" ", "_"), plugin.id)


_service: PluginService | None = None
_service_lock = threading.Lock()


def service() -> PluginService:
    global _service
    with _service_lock:
        expected = Path(get_config().paths.data_dir)
        if _service is None or _service.repository.path != expected / "plugins.sqlite3":
            _service = PluginService(PluginRepository(expected / "plugins.sqlite3", legacy_path=expected / "apps" / "store_plugins.json"))
        return _service
