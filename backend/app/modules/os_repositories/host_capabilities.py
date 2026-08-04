from __future__ import annotations

from typing import Any

from ...identity.permissions import Permission
from ...package_center.models import api_error
from ..hosts_manager.public import HostCapabilityProvider, registry
from .service import service


def register_host_capability() -> None:
    def supports(host: dict[str, Any]) -> bool:
        return bool(host.get("active") and host.get("approved"))

    def plan(host: dict[str, Any], parameters: dict[str, Any], actor: str) -> dict[str, Any]:
        assignment_id = str(parameters.get("assignment_id") or "")
        assignment = service().store.one(
            "SELECT a.*,r.format,r.distribution,r.distribution_version,r.architectures_json FROM host_assignments a JOIN repositories r ON r.id=a.repository_id WHERE a.id=?",
            (assignment_id,),
        )
        if not assignment:
            api_error(404, "ASSIGNMENT_NOT_FOUND", "Repository assignment not found")
        facts = host.get("facts") or {}
        architecture = str(facts.get("architecture") or host.get("architecture") or "")
        distribution = str(facts.get("distribution") or host.get("distribution") or "").lower()
        compatible = (not architecture or architecture in assignment["architectures"]) and (not distribution or distribution == assignment["distribution"])
        return {
            "host_id": host["id"],
            "host_name": host["name"],
            "assignment_id": assignment_id,
            "compatible": compatible,
            "distribution": assignment["distribution"],
            "architectures": assignment["architectures"],
            "changes_host": False,
            "confirmations_required": ["confirm"],
        }

    def execute(host: dict[str, Any], parameters: dict[str, Any], actor: str) -> dict[str, Any]:
        result = plan(host, parameters, actor)
        if not result["compatible"]:
            api_error(409, "HOST_REPOSITORY_INCOMPATIBLE", "Host distribution or architecture is incompatible with the repository")
        if not parameters.get("confirm"):
            api_error(422, "CONFIRMATION_REQUIRED", "Configuration generation requires confirmation")
        return {"plan": result, "configuration": service().host_configuration(result["assignment_id"])}

    registry().register_capability(
        HostCapabilityProvider(
            "os-repositories.generate-config",
            "Generate repository configuration",
            "package-open",
            Permission.OS_REPOSITORIES_HOSTS_ASSIGN.value,
            "os-repositories",
            supports,
            plan,
            execute,
            "/modules/os-repositories",
        )
    )
