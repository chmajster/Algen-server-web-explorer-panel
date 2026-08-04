from __future__ import annotations

import time
from typing import Any, Callable

from ...identity.permissions import Permission
from ...package_center.models import api_error
from ..hosts_manager.public import HostCapabilityProvider, registry
from .models import MANAGED_SSH_USERNAME
from .playbooks import analyze_playbook


def register_host_capabilities(enqueue: Callable[[str, dict[str, Any], str], dict[str, Any]], repository_factory: Callable[[], Any], config_factory: Callable[[str], dict[str, Any]]) -> None:
    def supports(host: dict[str, Any]) -> bool:
        return bool(host.get("active") and host.get("approved"))

    def plan(capability_id: str, dangerous: bool = False):
        return lambda host, parameters, actor: {"host_id": host["id"], "host_name": host["name"], "capability_id": capability_id, "parameters": parameters, "dangerous": dangerous, "confirmations_required": ["confirm", "host_name"] if dangerous else ["confirm"]}

    def queued(operation: str, payload_factory: Callable[[dict[str, Any], dict[str, Any], str], dict[str, Any]]):
        def execute(host: dict[str, Any], parameters: dict[str, Any], actor: str) -> dict[str, Any]:
            if not parameters.get("confirm"):
                api_error(422, "CONFIRMATION_REQUIRED", "Review and confirm the host action")
            job = enqueue(operation, payload_factory(host, parameters, actor), actor)
            operation_record = registry().operation(host["id"], f"ansible.{operation}", actor, module_id="ansible-controller", package_job_id=job["id"])
            return {"job": job, "operation": operation_record}
        return execute

    def facts_payload(host: dict[str, Any], parameters: dict[str, Any], actor: str) -> dict[str, Any]:
        return {"host_id": host["id"]}

    def test_payload(host: dict[str, Any], parameters: dict[str, Any], actor: str) -> dict[str, Any]:
        if host.get("fingerprint_status") != "accepted":
            api_error(409, "HOST_KEY_NOT_ACCEPTED", "Accept the SSH host fingerprint before connecting")
        return {"host_id": host["id"], "test_only": True}

    def rotate_payload(host: dict[str, Any], parameters: dict[str, Any], actor: str) -> dict[str, Any]:
        if not host.get("managed_user_created") or not host.get("credential_id"):
            api_error(409, "MANAGED_KEY_UNAVAILABLE", "Host must be onboarded before key rotation")
        config = config_factory(actor)
        return {"host_id": host["id"], "managed_username": config.get("managed_username") or MANAGED_SSH_USERNAME, "sudo_profile": config.get("managed_sudo_profile") or "none", "sudoers_policy": "", "managed_shell": config.get("managed_shell") or "/bin/bash", "managed_comment": config.get("managed_comment") or "Algen Ansible automation", "authorized_keys_mode": "exclusive"}

    def playbook_plan(host: dict[str, Any], parameters: dict[str, Any], actor: str) -> dict[str, Any]:
        template_id = str(parameters.get("template_id") or "")
        template = repository_factory()._get("job_templates", template_id)
        playbook = repository_factory()._get("playbooks", str((template or {}).get("playbook_id") or ""))
        if not template or not playbook:
            api_error(404, "TEMPLATE_NOT_FOUND", "Job template not found")
        analysis = analyze_playbook(str(playbook["content"]))
        return {"host_id": host["id"], "host_name": host["name"], "capability_id": "ansible.run_playbook", "template_id": template_id, "playbook": playbook["name"], "warnings": analysis["warnings"], "blocked": analysis["blocked"], "confirmations_required": ["confirm"]}

    def playbook_execute(host: dict[str, Any], parameters: dict[str, Any], actor: str) -> dict[str, Any]:
        if not parameters.get("confirm"):
            api_error(422, "CONFIRMATION_REQUIRED", "Playbook launch requires confirmation")
        template_id = str(parameters.get("template_id") or "")
        template = repository_factory()._get("job_templates", template_id)
        playbook = repository_factory()._get("playbooks", str((template or {}).get("playbook_id") or ""))
        analysis = analyze_playbook(str((playbook or {}).get("content") or ""))
        if not template or not analysis["ok"]:
            api_error(422, "PLAYBOOK_BLOCKED", "Template or playbook is unavailable")
        execution = repository_factory().create_execution(template_id, actor, [host["id"]], analysis["warnings"])
        try:
            job = enqueue("launch", {"execution_id": execution["id"]}, actor)
            repository_factory().set_execution_job(execution["id"], job["id"])
        except Exception:
            repository_factory().update_execution(execution["id"], actor, status="failed", stage="queue_failed", finished_at=time.time())
            raise
        operation_record = registry().operation(host["id"], "ansible.run_playbook", actor, module_id="ansible-controller", package_job_id=job["id"], details={"template_id": template_id, "execution_id": execution["id"]})
        return {"job": job, "execution": repository_factory().execution(execution["id"]), "operation": operation_record}

    providers = [
        HostCapabilityProvider("ansible.test_connection", "Test connection", "plug", Permission.HOSTS_MANAGER_ACTIONS_EXECUTE.value, "ansible", supports, plan("ansible.test_connection"), queued("gather_facts", test_payload), "/modules/ansible-controller"),
        HostCapabilityProvider("ansible.gather_facts", "Gather facts", "info", Permission.HOSTS_MANAGER_ACTIONS_EXECUTE.value, "ansible", supports, plan("ansible.gather_facts"), queued("gather_facts", facts_payload), "/modules/ansible-controller"),
        HostCapabilityProvider("ansible.rotate_managed_key", "Rotate managed SSH key", "key-round", Permission.ANSIBLE_CONFIGURE.value, "ansible", supports, plan("ansible.rotate_managed_key", True), queued("rotate_host_key", rotate_payload), "/modules/ansible-controller"),
        HostCapabilityProvider("ansible.run_playbook", "Run playbook", "play", Permission.ANSIBLE_JOBS_LAUNCH.value, "ansible", supports, playbook_plan, playbook_execute, "/modules/ansible-controller"),
    ]
    for provider in providers:
        registry().register_capability(provider)
