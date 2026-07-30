from __future__ import annotations

import sqlite3

from ..apmid.service import SCHEMA_VERSION, service
from .base import ModuleProvider
from ...package_center.models import ModuleDiagnostic


class ApmidProvider(ModuleProvider):
    def __init__(self, module_id: str = "apmid") -> None:
        super().__init__(module_id)

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        self.assert_capability("diagnostics")
        checks: list[ModuleDiagnostic] = []
        try:
            with service().connect() as connection:
                integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            checks.append(ModuleDiagnostic(
                status="ok" if integrity == "ok" else "error", title="SQLite integrity",
                description="APMID private database integrity", details=integrity,
                severity="ok" if integrity == "ok" else "critical",
                recommended_action="" if integrity == "ok" else "Restore a verified APMID backup",
            ))
            checks.append(ModuleDiagnostic(
                status="ok" if version == SCHEMA_VERSION else "warning", title="Schema version",
                description="Installed APMID schema", details=f"{version}/{SCHEMA_VERSION}",
                severity="ok" if version == SCHEMA_VERSION else "warning",
                recommended_action="" if version == SCHEMA_VERSION else "Run the module update",
            ))
        except (OSError, sqlite3.Error) as error:
            checks.append(ModuleDiagnostic(status="error", title="APMID database", description="Database cannot be opened", details=str(error), severity="critical", recommended_action="Review data directory permissions"))
        return checks

    def list_backups(self) -> list[dict]:
        return service().list_backups()

    def create_backup(self, actor: str, description: str = "", automatic: bool = False) -> dict:
        return service().create_backup(actor, description)

    def cleanup_after_uninstall(self, actor: str, remove_config: bool) -> dict:
        # The normal module uninstall always preserves authoritative APMID data.
        return {"managed_config_removed": False, "data_preserved": True}

