from __future__ import annotations

import asyncio
import json
import sqlite3
import shutil
import subprocess
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from ...activity import ActivityCategory, record_activity
from ...audit import logger
from ...identity.permissions import Permission, require_permission
from ...modules.providers.ansible_controller import AnsibleControllerProvider
from ...package_center.jobs import manager
from ...package_center.models import PackageAction, api_error
from ...package_center.service import repository as package_repository
from ...security import SessionUser
from ..router import _provider_plan
from .backup import backup_path, delete_backup, validate_backup
from .inventory import generate_inventory, inventory_records, parse_inventory
from .models import (
    BackupCreateInput,
    ConfirmationInput,
    ControllerConfigInput,
    CredentialInput,
    EnrollmentClaimInput,
    EnrollmentTokenInput,
    FingerprintAcceptInput,
    GroupInput,
    HostInput,
    InventoryImportInput,
    LaunchInput,
    MANAGED_SSH_USERNAME,
    ManagedAccountConfigInput,
    NetworkScanInput,
    OnboardingInput,
    PlaybookInput,
    ProjectInput,
    RestoreInput,
    ScanImportInput,
    ScheduleInput,
    TemplateInput,
)
from .network import scan_addresses
from .playbooks import analyze_playbook
from .repository import repository
from .runner import fingerprint_key, keyscan_args, parse_keyscan, validate_inventory_runtime, validate_playbook_runtime
from .security import redact_text


router = APIRouter(prefix="/api/modules/ansible-controller", tags=["ansible-controller"])


def _require_confirmation(confirm: bool, message: str = "Explicit confirmation is required") -> None:
    if not confirm:
        api_error(400, "CONFIRMATION_REQUIRED", message)


def _require_credential_type(credential_id: str | None, allowed: set[str], managed_host_id: str | None = None) -> None:
    if not credential_id:
        return
    credential = next((item for item in repository().credentials() if item["id"] == credential_id), None)
    if not credential or not credential.get("active"):
        api_error(422, "CREDENTIAL_NOT_FOUND", "Referenced credential is unavailable")
    description = str(credential.get("description") or "")
    if description.startswith("managed-host:") and not description.startswith(f"managed-host:{managed_host_id};"):
        api_error(422, "MANAGED_HOST_CREDENTIAL", "Host-specific managed keys cannot be assigned to another host")
    if credential["type"] not in allowed:
        api_error(422, "CREDENTIAL_TYPE_INVALID", "Referenced credential has the wrong type", allowed_types=sorted(allowed))


def _validate_inventory_with_ansible(content: str, format_hint: str) -> dict[str, Any]:
    try:
        return validate_inventory_runtime(repository(), content, format_hint)
    except RuntimeError:
        api_error(409, "ANSIBLE_NOT_AVAILABLE", "ansible-inventory is unavailable; install the module first")


def _validate_playbook_with_ansible(content: str) -> dict[str, Any]:
    try:
        return validate_playbook_runtime(repository(), content)
    except RuntimeError:
        api_error(409, "ANSIBLE_NOT_AVAILABLE", "ansible-playbook is unavailable; install the module first")


def _enqueue(operation: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
    safe_payload = {**payload, "operation": operation}
    plan = _provider_plan("ansible-controller", PackageAction.manage, safe_payload)
    plan.steps = {
        "network_scan": ["Validate approved address range", "Run fixed TCP nmap scan", "Store selected discovery results"],
        "onboard_host": ["Verify accepted host key", "Test SSH", "Prepare managed account", "Test Ansible ping", "Collect facts"],
        "rotate_host_key": ["Generate a unique Ed25519 key", "Connect with the current host key", "Replace authorized key", "Encrypt the new private key", "Verify Ansible connection"],
        "gather_facts": ["Generate private inventory", "Run Ansible setup", "Store redacted facts"],
        "sync_project": ["Validate repository origin", "Fetch fixed revision", "Verify project boundaries"],
        "launch": ["Create private snapshots", "Drop UID/GID", "Run ansible-playbook", "Parse per-host recap", "Clean credentials"],
        "retry": ["Create linked execution", "Run immutable snapshots", "Parse per-host recap"],
        "backup": ["Create SQLite online snapshot", "Encrypt optional credentials", "Calculate SHA-256"],
        "restore": ["Verify checksum", "Create safety backup", "Validate SQLite", "Restore atomically"],
    }.get(operation, ["Run controlled Ansible controller operation"])
    return manager(package_repository()).enqueue(plan, actor)


def _audit_api(actor: str, action: str, object_type: str, object_id: str, details: dict[str, Any] | None = None) -> None:
    logger.info("ansible_controller actor=%s action=%s object=%s id=%s", actor, action, object_type, object_id)
    record_activity(ActivityCategory.module, action, actor, target=f"ansible-controller:{object_type}:{object_id}", details=details or {}, source="ansible-controller")


@router.get("/dashboard")
def dashboard(user: SessionUser = Depends(require_permission(Permission.ANSIBLE_VIEW))):
    result = repository().dashboard()
    result.update(AnsibleControllerProvider(user.username).get_status().metrics)
    return result


@router.get("/config")
def config(user: SessionUser = Depends(require_permission(Permission.ANSIBLE_VIEW))):
    return AnsibleControllerProvider(user.username).get_config()


@router.put("/config")
def save_config(payload: ControllerConfigInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_CONFIGURE))):
    _require_confirmation(payload.confirm)
    if payload.awx:
        _require_credential_type(payload.awx.credential_id, {"awx_token"})
    value = payload.model_dump(mode="json", exclude={"confirm"}, exclude_none=True)
    if "managed_key_rotation_days" not in payload.model_fields_set:
        value["managed_key_rotation_days"] = AnsibleControllerProvider(user.username).get_config().get("managed_key_rotation_days", 90)
    value["managed_authorized_keys_mode"] = "exclusive"
    job = manager(package_repository()).enqueue(_provider_plan("ansible-controller", PackageAction.apply, {"config": value}), user.username)
    _audit_api(user.username, "configure", "settings", "controller")
    return {"job": job}


@router.put("/managed-account")
def save_managed_account(payload: ManagedAccountConfigInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_CONFIGURE))):
    _require_confirmation(payload.confirm)
    provider = AnsibleControllerProvider(user.username)
    config = provider.get_config()
    if isinstance(config.get("awx"), dict):
        config["awx"].pop("token_configured", None)
    config.update({"managed_username": payload.username, "managed_sudo_profile": payload.sudo_profile, "managed_shell": payload.shell, "managed_comment": payload.comment, "managed_authorized_keys_mode": payload.authorized_keys_mode, "managed_key_rotation_days": payload.key_rotation_days})
    value = provider.save_config(config, user.username)
    _audit_api(user.username, "configure_managed_account", "settings", "managed-account", {"username": payload.username, "sudo_profile": payload.sudo_profile, "shell": payload.shell, "authorized_keys_mode": payload.authorized_keys_mode})
    return {"managed_username": value.get("managed_username"), "managed_sudo_profile": value.get("managed_sudo_profile"), "managed_shell": value.get("managed_shell"), "managed_comment": value.get("managed_comment"), "managed_authorized_keys_mode": value.get("managed_authorized_keys_mode"), "managed_key_rotation_days": value.get("managed_key_rotation_days")}


@router.get("/hosts")
def hosts(active_only: bool = False, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_VIEW))):
    return repository().list_hosts(active_only=active_only)


@router.post("/hosts")
def create_host(payload: HostInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    _require_credential_type(payload.credential_id, {"ssh_private_key", "ssh_password"})
    return repository().save_host(payload, user.username)


@router.post("/enrollment-tokens")
def create_enrollment_token(payload: EnrollmentTokenInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    _require_credential_type(payload.credential_id, {"ssh_private_key", "ssh_password"})
    value = repository().create_enrollment_token(payload, user.username)
    _audit_api(user.username, "create_enrollment_token", "enrollment_token", value["id"], {"hostname_pattern": value["hostname_pattern"], "expires_at": value["expires_at"]})
    return value


@router.post("/enroll")
def enroll_host(payload: EnrollmentClaimInput, authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if len(token) < 32 or len(token) > 128:
        api_error(401, "ENROLLMENT_TOKEN_INVALID", "Enrollment token is invalid, expired, already used, or does not allow this hostname")
    if repository().centralized_hosts:
        from ..hosts_manager.service import registry as host_registry
        saved = host_registry().claim_enrollment_token(token, {"hostname": payload.hostname, "address": payload.address})
        if not saved:
            api_error(401, "ENROLLMENT_TOKEN_INVALID", "Enrollment token is invalid, expired, already used, or does not allow this hostname")
        return {"host": saved, "fingerprint_verification_required": True, "approval_required": not saved["approved"]}
    policy = repository().claim_enrollment_token(token, payload.hostname)
    if not policy:
        api_error(401, "ENROLLMENT_TOKEN_INVALID", "Enrollment token is invalid, expired, already used, or does not allow this hostname")
    host = HostInput(
        name=payload.hostname,
        address=payload.address,
        port=int(policy["port"]),
        ssh_user=str(policy["ssh_user"]),
        credential_id=policy["credential_id"],
        python_interpreter="auto_silent",
        connection_type="ssh",
        environment=str(policy["environment"]),
        location=str(policy["location"]),
        tags=list(policy["tags"]),
        variables={},
        active=True,
    )
    try:
        saved = repository().save_host(host, f"self-enrollment:{payload.hostname}")
    except sqlite3.IntegrityError:
        api_error(409, "HOST_ALREADY_EXISTS", "A host with this hostname is already registered")
    _audit_api(f"self-enrollment:{payload.hostname}", "enroll", "host", saved["id"], {"hostname": payload.hostname})
    return {"host": saved, "fingerprint_verification_required": True}


@router.get("/hosts/{host_id}")
def host(host_id: str, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_VIEW))):
    item = repository().host(host_id)
    if not item:
        api_error(404, "HOST_NOT_FOUND", "Host not found")
    return item


@router.put("/hosts/{host_id}")
def update_host(host_id: str, payload: HostInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    if not repository().host(host_id):
        api_error(404, "HOST_NOT_FOUND", "Host not found")
    _require_credential_type(payload.credential_id, {"ssh_private_key", "ssh_password"}, host_id)
    return repository().save_host(payload, user.username, host_id)


@router.delete("/hosts/{host_id}")
def delete_host(host_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    _require_confirmation(payload.confirm)
    if not repository().delete_host(host_id, user.username):
        api_error(404, "HOST_NOT_FOUND", "Host not found")
    return {"ok": True}


@router.post("/hosts/{host_id}/ssh-key/scan")
def scan_host_key(host_id: str, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    item = repository().host(host_id)
    if not item:
        api_error(404, "HOST_NOT_FOUND", "Host not found")
    executable = shutil.which("ssh-keyscan")
    keygen = shutil.which("ssh-keygen")
    if not executable or not keygen:
        api_error(409, "SSH_TOOLS_UNAVAILABLE", "ssh-keyscan and ssh-keygen are required")
    result = subprocess.run(keyscan_args(item["address"], int(item["port"]), executable), capture_output=True, text=True, timeout=15, check=False, shell=False)
    keys = parse_keyscan(result.stdout)
    if result.returncode != 0 or not keys:
        repository().audit(user.username, "host", host_id, "connection_attempt", {"stage": "keyscan"}, result="failure")
        api_error(502, "SSH_KEYSCAN_FAILED", "Could not read the SSH host key")
    for key in keys:
        key["fingerprint"] = fingerprint_key(f"{key['key_type']} {key['public_key']}", keygen)
    existing = repository().known_key(item["address"], int(item["port"]))
    changed = bool(existing and all(existing["fingerprint"] != key["fingerprint"] for key in keys))
    if changed:
        if repository().centralized_hosts:
            from ..hosts_manager.service import registry as host_registry
            host_registry()._update_host(host_id, user.username, fingerprint_status="changed", last_error="SSH host key changed")
        else:
            with repository()._lock, repository().connect() as connection:
                connection.execute("UPDATE hosts SET fingerprint_status='changed',last_error='SSH host key changed',updated_at=?,updated_by=? WHERE id=?", (time.time(), user.username, host_id))
        repository().audit(user.username, "host_key", host_id, "change_detected", {"address": item["address"]}, result="failure")
    return {"host_id": host_id, "keys": keys, "existing_fingerprint": existing.get("fingerprint") if existing else None, "changed": changed, "requires_acceptance": not existing or changed}


@router.post("/hosts/{host_id}/ssh-key/accept")
def accept_host_key(host_id: str, payload: FingerprintAcceptInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    _require_confirmation(payload.confirm)
    item = repository().host(host_id)
    if not item:
        api_error(404, "HOST_NOT_FOUND", "Host not found")
    key_type = payload.public_key.split(None, 1)[0]
    if key_type not in {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"}:
        api_error(422, "INVALID_HOST_KEY", "Unsupported SSH host key type")
    calculated = fingerprint_key(payload.public_key, shutil.which("ssh-keygen") or "ssh-keygen")
    if calculated != payload.fingerprint:
        api_error(422, "FINGERPRINT_MISMATCH", "Fingerprint does not match the supplied public key")
    try:
        return repository().accept_known_key(host_id, item["address"], int(item["port"]), key_type, payload.public_key.split(None, 1)[1], payload.fingerprint, user.username, payload.replace)
    except RuntimeError as error:
        api_error(409, "HOST_KEY_CHANGED", str(error))


@router.post("/hosts/{host_id}/test")
def test_host(host_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    _require_confirmation(payload.confirm)
    item = repository().host(host_id)
    if not item:
        api_error(404, "HOST_NOT_FOUND", "Host not found")
    if not repository().known_key(item["address"], int(item["port"])):
        api_error(409, "HOST_KEY_NOT_ACCEPTED", "Accept the SSH host fingerprint before connecting")
    # Test and facts run as durable jobs and never carry credential plaintext.
    job = _enqueue("gather_facts", {"host_id": host_id, "test_only": True}, user.username)
    _audit_api(user.username, "connection_attempt", "host", host_id, {"job_id": job["id"]})
    return {"job": job}


@router.post("/hosts/{host_id}/facts")
def gather_facts(host_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    _require_confirmation(payload.confirm)
    if not repository().host(host_id):
        api_error(404, "HOST_NOT_FOUND", "Host not found")
    return {"job": _enqueue("gather_facts", {"host_id": host_id}, user.username)}


@router.post("/hosts/{host_id}/managed-key/rotate")
def rotate_managed_key(host_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_CONFIGURE))):
    _require_confirmation(payload.confirm)
    host = repository().host(host_id)
    if not host or not host.get("active"):
        api_error(404, "HOST_NOT_FOUND", "Host not found")
    if not host.get("managed_user_created") or not host.get("credential_id"):
        api_error(409, "MANAGED_KEY_UNAVAILABLE", "Host must be onboarded before its key can be rotated")
    config = AnsibleControllerProvider(user.username).get_config()
    job = _enqueue("rotate_host_key", {"host_id": host_id, "managed_username": config.get("managed_username") or MANAGED_SSH_USERNAME, "sudo_profile": config.get("managed_sudo_profile") or "none", "sudoers_policy": "", "managed_shell": config.get("managed_shell") or "/bin/bash", "managed_comment": config.get("managed_comment") or "Algen Ansible automation", "authorized_keys_mode": "exclusive"}, user.username)
    _audit_api(user.username, "rotate_managed_key", "host", host_id, {"job_id": job["id"], "key_scope": "per_host"})
    return {"job": job}


@router.post("/onboarding")
def onboarding(payload: OnboardingInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    _require_confirmation(payload.confirm)
    existing_host = next(
        (
            item
            for item in repository().list_hosts()
            if item["name"] == payload.host.name
            or (item["address"] == payload.host.address and int(item["port"]) == payload.host.port)
        ),
        None,
    )
    _require_credential_type(
        payload.credential_id or payload.host.credential_id,
        {"ssh_private_key", "ssh_password"},
        existing_host["id"] if existing_host else None,
    )
    host_record = repository().save_host(payload.host, user.username, existing_host["id"] if existing_host else None)
    existing = repository().known_key(host_record["address"], int(host_record["port"]))
    if not existing:
        api_error(409, "HOST_KEY_NOT_ACCEPTED", "Scan and accept the host fingerprint before onboarding", host_id=host_record["id"])
    controller_config = AnsibleControllerProvider(user.username).get_config()
    managed_username = str(controller_config.get("managed_username") or MANAGED_SSH_USERNAME)
    managed_sudo_profile = str(controller_config.get("managed_sudo_profile") or "none")
    if managed_sudo_profile == "nopasswd" and payload.confirm_host_name != host_record["address"]:
        api_error(422, "HOST_CONFIRMATION_REQUIRED", "Full passwordless sudo requires typing the target host address")
    # Only identifiers and validated policy metadata enter the durable queue.
    job = _enqueue("onboard_host", {"host_id": host_record["id"], "initial_username": payload.initial_username, "credential_id": payload.credential_id, "create_managed_user": True, "managed_username": managed_username, "sudo_profile": managed_sudo_profile, "sudoers_policy": "", "managed_shell": controller_config.get("managed_shell") or "/bin/bash", "managed_comment": controller_config.get("managed_comment") if isinstance(controller_config.get("managed_comment"), str) else "Algen Ansible automation", "authorized_keys_mode": controller_config.get("managed_authorized_keys_mode") or "exclusive"}, user.username)
    repository().audit(user.username, "host", host_record["id"], "onboard", {"job_id": job["id"], "create_managed_user": True, "managed_username": managed_username, "sudo_profile": managed_sudo_profile})
    return {"host": host_record, "job": job, "onboarding_id": host_record["id"]}


@router.get("/groups")
def groups(user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_VIEW))):
    return repository().list_groups()


@router.post("/groups")
def create_group(payload: GroupInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    return repository().save_group(payload, user.username)


@router.put("/groups/{group_id}")
def update_group(group_id: str, payload: GroupInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    if not repository()._get("inventory_groups", group_id):
        api_error(404, "GROUP_NOT_FOUND", "Inventory group not found")
    return repository().save_group(payload, user.username, group_id)


@router.get("/inventory")
def inventory(user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_VIEW))):
    memberships = repository()._list("host_group_memberships", limit=10_000, order="created_at")
    return {"format": "yaml", "content": generate_inventory(repository().list_hosts(active_only=True), repository().list_groups(), memberships)}


@router.post("/inventory/import")
def import_inventory(payload: InventoryImportInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    validation = parse_inventory(payload.content, payload.format)
    runtime = _validate_inventory_with_ansible(payload.content, payload.format)
    if not runtime["ok"]:
        api_error(422, "INVENTORY_ANSIBLE_INVALID", "ansible-inventory rejected the inventory", validation=runtime)
    if not payload.confirm:
        return {"validation": {**validation, "runtime": runtime}, "requires_confirmation": True}
    host_records, group_records = inventory_records(validation)
    created_by_name: dict[str, dict[str, Any]] = {}
    existing_by_name = {item["name"]: item for item in repository().list_hosts()}
    for raw in host_records:
        model = HostInput.model_validate(raw)
        existing = existing_by_name.get(model.name)
        created_by_name[model.name] = repository().save_host(model, user.username, existing["id"] if existing else None)
    existing_groups = {item["name"]: item for item in repository().list_groups()}
    for raw in group_records:
        group = GroupInput(name=raw["name"], variables=raw["variables"], host_ids=[created_by_name[name]["id"] for name in raw["host_names"] if name in created_by_name])
        existing = existing_groups.get(group.name)
        repository().save_group(group, user.username, existing["id"] if existing else None)
    repository().audit(user.username, "inventory", "import", "import", {"format": payload.format, "host_count": len(created_by_name), "group_count": len(group_records)})
    return {"validation": validation, "imported": len(created_by_name), "groups": len(group_records), "hosts": list(created_by_name.values())}


@router.post("/inventory/validate")
def validate_inventory(payload: InventoryImportInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    validation = parse_inventory(payload.content, payload.format)
    runtime = _validate_inventory_with_ansible(payload.content, payload.format)
    return {**validation, "runtime": runtime, "ok": runtime["ok"]}


@router.get("/scans")
def scans(user: SessionUser = Depends(require_permission(Permission.ANSIBLE_DISCOVERY, mutating=False))):
    return repository().scans()


@router.get("/scans/{scan_id}")
def scan(scan_id: str, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_DISCOVERY, mutating=False))):
    item = repository().scan(scan_id)
    if not item:
        api_error(404, "SCAN_NOT_FOUND", "Network scan not found")
    return item


@router.post("/scans")
def start_scan(payload: NetworkScanInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_DISCOVERY))):
    _require_confirmation(payload.confirm)
    config = AnsibleControllerProvider(user.username).get_config()
    try:
        addresses = scan_addresses(payload, config.get("allowed_networks") or [], min(int(config.get("max_scan_addresses") or 4096), 4096))
    except ValueError as error:
        api_error(422, "SCAN_RANGE_NOT_ALLOWED", str(error))
    item = repository().create_scan(payload.model_dump(mode="json", exclude={"confirm"}), user.username)
    try:
        job = _enqueue("network_scan", {"scan_id": item["id"]}, user.username)
    except Exception:
        repository().complete_scan(item["id"], user.username, [], "Could not queue network scan")
        raise
    repository().set_scan_job(item["id"], job["id"])
    return {"scan": repository().scan(item["id"]), "job": job, "address_count": len(addresses)}


@router.post("/scans/{scan_id}/import")
def import_scan(scan_id: str, payload: ScanImportInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_MANAGE))):
    _require_confirmation(payload.confirm)
    item = repository().scan(scan_id)
    if not item:
        api_error(404, "SCAN_NOT_FOUND", "Network scan not found")
    selected = [host for host in item["hosts"] if host["id"] in payload.host_ids]
    if len(selected) != len(set(payload.host_ids)):
        api_error(422, "INVALID_SCAN_SELECTION", "One or more selected hosts do not belong to this scan")
    created = [repository().save_host(HostInput(name=(host["hostname"] or f"host-{str(host['address']).replace(':', '-').replace('.', '-')}")[:128], address=host["address"], port=host["port"]), user.username) for host in selected]
    if payload.group_name:
        repository().save_group(GroupInput(name=payload.group_name, host_ids=[host["id"] for host in created]), user.username)
    repository().audit(user.username, "scan", scan_id, "import", {"host_count": len(created), "host_ids": [host["id"] for host in created]})
    return {"hosts": created, "imported": len(created)}


@router.get("/credentials")
def credentials(user: SessionUser = Depends(require_permission(Permission.ANSIBLE_CREDENTIALS_VIEW))):
    return repository().credentials()


@router.post("/credentials")
def create_credential(payload: CredentialInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_CREDENTIALS_MANAGE))):
    _require_confirmation(payload.confirm)
    item = repository().save_credential(payload, user.username)
    _audit_api(user.username, "credential_create", "credential", item["id"], {"type": item["type"]})
    return item


@router.put("/credentials/{credential_id}")
def update_credential(credential_id: str, payload: CredentialInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_CREDENTIALS_MANAGE))):
    _require_confirmation(payload.confirm)
    existing = next((item for item in repository().credentials() if item["id"] == credential_id), None)
    if not existing:
        api_error(404, "CREDENTIAL_NOT_FOUND", "Credential not found")
    if str(existing.get("description") or "").startswith("managed-host:"):
        api_error(409, "MANAGED_CREDENTIAL_PROTECTED", "Managed host keys are rotated from the automation account page")
    return repository().save_credential(payload, user.username, credential_id)


@router.delete("/credentials/{credential_id}")
def delete_credential(credential_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_CREDENTIALS_MANAGE))):
    _require_confirmation(payload.confirm)
    existing = next((item for item in repository().credentials() if item["id"] == credential_id), None)
    if existing and str(existing.get("description") or "").startswith("managed-host:"):
        api_error(409, "MANAGED_CREDENTIAL_PROTECTED", "Managed host keys cannot be deleted manually")
    if not repository().delete_credential(credential_id, user.username):
        api_error(404, "CREDENTIAL_NOT_FOUND", "Credential not found")
    return {"ok": True}


@router.get("/projects")
def projects(user: SessionUser = Depends(require_permission(Permission.ANSIBLE_PROJECTS_VIEW))):
    return repository().projects()


@router.post("/projects")
def create_project(payload: ProjectInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_PROJECTS_MANAGE))):
    _require_credential_type(payload.credential_id, {"git_private_key"})
    return repository().save_project(payload, user.username)


@router.put("/projects/{project_id}")
def update_project(project_id: str, payload: ProjectInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_PROJECTS_MANAGE))):
    if not repository()._get("projects", project_id):
        api_error(404, "PROJECT_NOT_FOUND", "Project not found")
    _require_credential_type(payload.credential_id, {"git_private_key"})
    return repository().save_project(payload, user.username, project_id)


@router.post("/projects/{project_id}/sync")
def sync_project(project_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_PROJECTS_MANAGE))):
    _require_confirmation(payload.confirm)
    if not repository()._get("projects", project_id):
        api_error(404, "PROJECT_NOT_FOUND", "Project not found")
    return {"job": _enqueue("sync_project", {"project_id": project_id}, user.username)}


@router.get("/playbooks")
def playbooks(project_id: str | None = None, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_PLAYBOOKS_VIEW))):
    return repository().playbooks(project_id)


@router.post("/playbooks/validate")
def validate_playbook(payload: PlaybookInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_PLAYBOOKS_MANAGE))):
    analysis = analyze_playbook(payload.content)
    if not analysis["ok"]:
        return {**analysis, "runtime": {"ok": False, "checks": []}}
    runtime = _validate_playbook_with_ansible(payload.content)
    return {**analysis, "runtime": runtime, "ok": runtime["ok"]}


@router.post("/playbooks")
def create_playbook(payload: PlaybookInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_PLAYBOOKS_MANAGE))):
    analysis = analyze_playbook(payload.content)
    if not analysis["ok"]:
        api_error(422, "PLAYBOOK_BLOCKED", "Playbook contains blocked local-controller operations", analysis=analysis)
    runtime = _validate_playbook_with_ansible(payload.content)
    if not runtime["ok"]:
        api_error(422, "PLAYBOOK_ANSIBLE_INVALID", "ansible-playbook rejected the playbook", validation=runtime)
    return repository().save_playbook(payload, user.username, analysis)


@router.put("/playbooks/{playbook_id}")
def update_playbook(playbook_id: str, payload: PlaybookInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_PLAYBOOKS_MANAGE))):
    if not repository()._get("playbooks", playbook_id):
        api_error(404, "PLAYBOOK_NOT_FOUND", "Playbook not found")
    analysis = analyze_playbook(payload.content)
    if not analysis["ok"]:
        api_error(422, "PLAYBOOK_BLOCKED", "Playbook contains blocked local-controller operations", analysis=analysis)
    runtime = _validate_playbook_with_ansible(payload.content)
    if not runtime["ok"]:
        api_error(422, "PLAYBOOK_ANSIBLE_INVALID", "ansible-playbook rejected the playbook", validation=runtime)
    return repository().save_playbook(payload, user.username, analysis, playbook_id)


@router.delete("/playbooks/{playbook_id}")
def delete_playbook(playbook_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_PLAYBOOKS_MANAGE))):
    _require_confirmation(payload.confirm)
    if repository()._list("job_templates", where="playbook_id=? AND active=1", values=(playbook_id,), limit=1):
        api_error(409, "PLAYBOOK_IN_USE", "Playbook is used by an active job template")
    if not repository().delete_playbook(playbook_id, user.username):
        api_error(404, "PLAYBOOK_NOT_FOUND", "Playbook not found")
    return {"ok": True}


@router.get("/playbooks/{playbook_id}/versions")
def playbook_versions(playbook_id: str, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_PLAYBOOKS_VIEW))):
    return repository().playbook_versions(playbook_id)


@router.get("/templates")
def templates(user: SessionUser = Depends(require_permission(Permission.ANSIBLE_PLAYBOOKS_VIEW))):
    return repository().templates()


@router.post("/templates")
def create_template(payload: TemplateInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_PLAYBOOKS_MANAGE))):
    if payload.ssh_credential_id:
        api_error(422, "PER_HOST_KEYS_REQUIRED", "Template-wide SSH keys are disabled; hosts use their own managed keys")
    _require_credential_type(payload.become_credential_id, {"become_password"})
    _require_credential_type(payload.vault_credential_id, {"vault_secret"})
    return repository().save_template(payload, user.username)


@router.put("/templates/{template_id}")
def update_template(template_id: str, payload: TemplateInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_PLAYBOOKS_MANAGE))):
    if not repository()._get("job_templates", template_id):
        api_error(404, "TEMPLATE_NOT_FOUND", "Job template not found")
    if payload.ssh_credential_id:
        api_error(422, "PER_HOST_KEYS_REQUIRED", "Template-wide SSH keys are disabled; hosts use their own managed keys")
    _require_credential_type(payload.become_credential_id, {"become_password"})
    _require_credential_type(payload.vault_credential_id, {"vault_secret"})
    return repository().save_template(payload, user.username, template_id)


def _template_hosts(template: dict[str, Any]) -> list[str]:
    host_ids = list(template.get("host_ids") or [])
    group_ids = set(template.get("group_ids") or [])
    for group in repository().list_groups():
        if group["id"] in group_ids:
            host_ids.extend(group.get("host_ids") or [])
    return list(dict.fromkeys(host_ids))[:5000]


@router.get("/templates/{template_id}/plan")
def launch_plan(template_id: str, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_JOBS_LAUNCH, mutating=False))):
    template = repository()._get("job_templates", template_id)
    if not template:
        api_error(404, "TEMPLATE_NOT_FOUND", "Job template not found")
    playbook = repository()._get("playbooks", template["playbook_id"])
    if not playbook:
        api_error(409, "PLAYBOOK_NOT_FOUND", "Template playbook is unavailable")
    analysis = analyze_playbook(str(playbook["content"]))
    project = repository()._get("projects", str(template.get("project_id") or ""))
    host_ids = _template_hosts(template)
    target_hosts = [repository().host(host_id) for host_id in host_ids]
    return {"template": template, "playbook": {"id": playbook["id"], "name": playbook["name"], "version": playbook["current_version"]}, "project_commit": (project or {}).get("last_commit") or "", "host_count": len(target_hosts), "hosts": [{"id": item["id"], "name": item["name"], "address": item["address"]} for item in target_hosts if item], "check_mode": template["check_mode"], "diff_mode": template["diff_mode"], "tags": template.get("tags") or [], "credential_ids": [value for key, value in template.items() if key.endswith("_credential_id") and value], "warnings": analysis["warnings"], "blocked": analysis["blocked"], "requires_confirmation": True}


@router.post("/templates/{template_id}/launch")
def launch(template_id: str, payload: LaunchInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_JOBS_LAUNCH))):
    _require_confirmation(payload.confirm, "Review the execution plan and explicitly confirm launch")
    template = repository()._get("job_templates", template_id)
    if not template:
        api_error(404, "TEMPLATE_NOT_FOUND", "Job template not found")
    playbook = repository()._get("playbooks", template["playbook_id"])
    analysis = analyze_playbook(str((playbook or {}).get("content") or ""))
    if not analysis["ok"]:
        api_error(422, "PLAYBOOK_BLOCKED", "Playbook contains blocked operations", analysis=analysis)
    host_ids = _template_hosts(template)
    if not host_ids:
        api_error(422, "NO_TARGET_HOSTS", "Job template has no target hosts")
    execution = repository().create_execution(template_id, user.username, host_ids, analysis["warnings"])
    try:
        job = _enqueue("launch", {"execution_id": execution["id"]}, user.username)
        repository().set_execution_job(execution["id"], job["id"])
    except Exception:
        repository().update_execution(execution["id"], user.username, status="failed", stage="queue_failed", finished_at=time.time())
        raise
    return {"execution": repository().execution(execution["id"]), "job": job}


@router.get("/jobs")
def jobs(status: str | None = None, limit: int = Query(200, ge=1, le=1000), user: SessionUser = Depends(require_permission(Permission.ANSIBLE_VIEW))):
    items = repository().executions()
    if status:
        items = [item for item in items if item["status"] == status]
    return items[:limit]


@router.get("/jobs/{execution_id}")
def job(execution_id: str, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_VIEW))):
    item = repository().execution(execution_id)
    if not item:
        api_error(404, "EXECUTION_NOT_FOUND", "Execution not found")
    return item


@router.get("/jobs/{execution_id}/events")
async def job_events(execution_id: str, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_VIEW))):
    execution = repository().execution(execution_id)
    if not execution or not execution.get("package_job_id"):
        api_error(404, "EXECUTION_NOT_FOUND", "Execution job not found")
    package_job_id = str(execution["package_job_id"])

    async def events():
        last_log_id = 0
        while True:
            package_job = package_repository().get_job(package_job_id)
            if not package_job:
                yield "event: error\ndata: {\"code\":\"JOB_NOT_FOUND\"}\n\n"
                return
            logs = package_repository().logs(package_job_id, limit=500, after=last_log_id)
            if logs:
                last_log_id = max(int(item["id"]) for item in logs)
            current = repository().execution(execution_id)
            data = json.dumps({"job": package_job, "execution": current, "logs": logs}, ensure_ascii=False)
            yield f"event: progress\ndata: {data}\n\n"
            if package_job["status"] in {"completed", "failed", "cancelled"}:
                yield f"event: done\ndata: {data}\n\n"
                return
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/jobs/{execution_id}/cancel")
def cancel_job(execution_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_JOBS_CANCEL))):
    _require_confirmation(payload.confirm)
    execution = repository().execution(execution_id)
    if not execution or not execution.get("package_job_id"):
        api_error(404, "EXECUTION_NOT_FOUND", "Execution job not found")
    result = manager(package_repository()).cancel(str(execution["package_job_id"]))
    repository().audit(user.username, "execution", execution_id, "cancel", {"job_id": execution["package_job_id"]}, result="cancelled")
    return {"job": result}


@router.post("/jobs/{execution_id}/retry")
def retry_job(execution_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_JOBS_LAUNCH))):
    _require_confirmation(payload.confirm)
    previous = repository().execution(execution_id)
    if not previous or previous["status"] not in {"failed", "cancelled", "completed"}:
        api_error(409, "EXECUTION_NOT_RETRYABLE", "Execution cannot be retried")
    execution = repository().create_execution(previous["template_id"], user.username, previous.get("host_ids") or [], previous.get("warnings") or [], retry_of=execution_id)
    repository().update_execution(
        execution["id"],
        user.username,
        inventory_snapshot=previous.get("inventory_snapshot") or "",
        playbook_snapshot=previous.get("playbook_snapshot") or "",
        project_commit=previous.get("project_commit") or "",
    )
    package_job = _enqueue("retry", {"execution_id": execution["id"]}, user.username)
    repository().set_execution_job(execution["id"], package_job["id"])
    return {"execution": repository().execution(execution["id"]), "job": package_job}


@router.get("/schedules")
def schedules(user: SessionUser = Depends(require_permission(Permission.ANSIBLE_VIEW))):
    return repository().schedules()


@router.post("/schedules")
def create_schedule(payload: ScheduleInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_SCHEDULES_MANAGE))):
    from .scheduler import next_run

    return repository().save_schedule(payload, user.username, next_run_at=next_run(payload.kind.value, payload.expression, payload.timezone))


@router.put("/schedules/{schedule_id}")
def update_schedule(schedule_id: str, payload: ScheduleInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_SCHEDULES_MANAGE))):
    if not repository()._get("schedules", schedule_id):
        api_error(404, "SCHEDULE_NOT_FOUND", "Schedule not found")
    from .scheduler import next_run

    return repository().save_schedule(payload, user.username, schedule_id, next_run_at=next_run(payload.kind.value, payload.expression, payload.timezone))


@router.get("/facts")
def facts(host_id: str | None = None, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_HOSTS_VIEW))):
    return repository()._list("saved_facts", where="host_id=?" if host_id else "", values=(host_id,) if host_id else (), order="created_at DESC", limit=1000)


@router.get("/audit")
def audit(limit: int = Query(200, ge=1, le=1000), user: SessionUser = Depends(require_permission(Permission.ANSIBLE_AUDIT_VIEW))):
    return repository().audit_events(limit)


@router.get("/diagnostics")
def diagnostics(user: SessionUser = Depends(require_permission(Permission.ANSIBLE_VIEW))):
    return {"diagnostics": [item.model_dump(mode="json") for item in AnsibleControllerProvider(user.username).run_diagnostics()]}


@router.get("/backups")
def backups(user: SessionUser = Depends(require_permission(Permission.ANSIBLE_BACKUP, mutating=False))):
    return AnsibleControllerProvider(user.username).list_backups()


@router.post("/backups")
def backup(payload: BackupCreateInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_BACKUP))):
    _require_confirmation(payload.confirm)
    return {"job": _enqueue("backup", {"description": payload.description, "include_credentials": payload.include_credentials}, user.username)}


@router.post("/backups/{backup_id}/validate")
def validate_controller_backup(backup_id: str, payload: RestoreInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_RESTORE))):
    return validate_backup(repository(), backup_id, payload.checksum)


@router.post("/backups/{backup_id}/restore")
def restore(backup_id: str, payload: RestoreInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_RESTORE))):
    _require_confirmation(payload.confirm)
    validate_backup(repository(), backup_id, payload.checksum)
    return {"job": _enqueue("restore", {"backup_id": backup_id, "checksum": payload.checksum, "include_credentials": payload.include_credentials}, user.username)}


@router.delete("/backups/{backup_id}")
def delete_controller_backup(backup_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_BACKUP))):
    _require_confirmation(payload.confirm)
    try:
        delete_backup(repository(), backup_id, user.username)
    except FileNotFoundError:
        api_error(404, "BACKUP_NOT_FOUND", "Controller backup not found")
    return {"ok": True}


@router.get("/backups/{backup_id}/download")
def download_backup(backup_id: str, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_BACKUP, mutating=False))):
    from fastapi.responses import FileResponse

    path = backup_path(repository(), backup_id)
    return FileResponse(path, filename=f"ansible-controller-{backup_id}.tar.gz", media_type="application/gzip")


@router.post("/awx/test")
def awx_test(payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_CONFIGURE))):
    _require_confirmation(payload.confirm)
    return AnsibleControllerProvider(user.username).awx_client().ping()


@router.get("/awx/{resource}")
def awx_resources(resource: str, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_VIEW))):
    if resource not in {"organizations", "inventories", "projects", "job_templates"}:
        api_error(404, "AWX_RESOURCE_NOT_FOUND", "Unsupported AWX resource")
    return AnsibleControllerProvider(user.username).awx_client().list_resource(resource)


@router.post("/awx/job-templates/{template_id}/launch")
def launch_awx_template(template_id: int, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_JOBS_LAUNCH))):
    _require_confirmation(payload.confirm)
    result = AnsibleControllerProvider(user.username).awx_client().launch(template_id)
    repository().audit(user.username, "awx_job_template", str(template_id), "launch", {"job": result.get("id")})
    return result


@router.get("/awx/jobs/{job_id}")
def awx_job(job_id: int, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_VIEW))):
    return AnsibleControllerProvider(user.username).awx_client().job(job_id)


@router.get("/awx/jobs/{job_id}/stdout")
def awx_stdout(job_id: int, user: SessionUser = Depends(require_permission(Permission.ANSIBLE_VIEW))):
    return {"stdout": redact_text(AnsibleControllerProvider(user.username).awx_client().stdout(job_id))}


from .host_capabilities import register_host_capabilities  # noqa: E402

register_host_capabilities(_enqueue, repository, lambda actor: AnsibleControllerProvider(actor).get_config())
