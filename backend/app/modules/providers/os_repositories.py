from __future__ import annotations

from typing import Literal

from ...package_center.models import ModuleDiagnostic
from ..os_repositories.models import BackupInput
from ..os_repositories.service import service
from .base import ModuleProvider


class OsRepositoriesProvider(ModuleProvider):
    def __init__(self, module_id: str = "os-repositories") -> None:
        super().__init__(module_id)

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        def severity(value: str) -> Literal["ok", "info", "warning", "critical"]:
            if value in {"error", "critical"}:
                return "critical"
            if value == "ok":
                return "ok"
            if value == "info":
                return "info"
            return "warning"

        return [
            ModuleDiagnostic(
                status=severity(item["status"]),
                title=item["id"],
                description=item["message"],
                details=item["message"],
                severity=severity(item["status"]),
                recommended_action="Review this check" if item["status"] != "ok" else "",
            )
            for item in service().diagnostics()["checks"]
        ]

    def list_backups(self):
        return service().backups()

    def create_backup(self, actor: str, description: str = "", automatic: bool = False):
        return service().create_backup(BackupInput(description=description, confirm=True), actor) | {"automatic": automatic}
