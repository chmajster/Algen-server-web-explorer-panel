from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import shlex
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import PlainTextResponse, StreamingResponse

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...identity.permissions import Permission, authorize, require_permission
from ...package_center.models import api_error
from ...security import SessionUser
from ..ansible_controller.inventory import generate_inventory, inventory_records, parse_inventory
from ..ansible_controller.runner import (
    SSH_COMMANDS,
    build_ssh_args,
    controller_identity,
    demote_preexec,
    fingerprint_key,
    keyscan_args,
    parse_keyscan,
)
from ..ansible_controller.security import atomic_private_write, redact_text
from .models import (
    AgentHeartbeatInput, AgentReportInput, ApmidInput, BackupInput, CapabilityActionInput, ConfirmationInput, CredentialInput,
    BootstrapOS, EnrollmentClaimInput, EnrollmentTokenInput, EnrollmentTokenMode, EnvironmentInput, FingerprintAcceptInput, GroupInput, HostInput,
    HostnamePatternInput, HostnamePatternSkipInput, HostsManagerSettingsUpdate, InventoryInput, PowerActionInput,
    PowerProfileInput, RepositoryInput, RestoreInput, ScanImportInput, ScanInput, SshOnboardingInstallInput,
    SshOnboardingProbeInput,
)
from .service import (
    SCHEMA_VERSION,
    ApmidInUseError,
    ManagedGroupConflictError,
    ManagedGroupProtectedError,
    registry,
    stable_id,
)


router = APIRouter(prefix="/api/modules/hosts-manager", tags=["hosts-manager"])

SSH_PROBE_COMMAND = """
set -eu
. /etc/os-release 2>/dev/null || true
printf '__HM_DISTRIBUTION__=%s\\n' "${ID:-unknown}"
printf '__HM_VERSION__=%s\\n' "${VERSION_ID:-}"
printf '__HM_PYTHON__=%s\\n' "$(command -v python3 || command -v python || true)"
manager=unknown
for item in apt-get dnf yum zypper pacman apk; do
  if command -v "$item" >/dev/null 2>&1; then manager="${item%-get}"; break; fi
done
printf '__HM_PACKAGE_MANAGER__=%s\\n' "$manager"
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  printf '__HM_INIT__=systemd\\n'
elif command -v rc-service >/dev/null 2>&1; then
  printf '__HM_INIT__=openrc\\n'
else
  printf '__HM_INIT__=other\\n'
fi
if [ "$(id -u)" -eq 0 ]; then
  printf '__HM_PRIVILEGE__=root\\n'
elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
  printf '__HM_PRIVILEGE__=sudo\\n'
elif command -v sudo >/dev/null 2>&1; then
  printf '__HM_PRIVILEGE__=sudo-password\\n'
else
  printf '__HM_PRIVILEGE__=user\\n'
fi
"""


def _service():
    return registry()


def _require(value: Any, code: str, message: str) -> Any:
    if not value:
        api_error(404, code, message)
    return value


def _activity(actor: str, action: str, target: str = "", details: dict[str, Any] | None = None, status: ActivityStatus = ActivityStatus.success) -> None:
    safe_details = details or {}
    record_activity(ActivityCategory.module, action, actor, target=target, details=safe_details, status=status, source="hosts-manager")
    host_id = target if target and _service()._get("hosts", target) else None
    _service().operation(
        host_id,
        f"audit.{action}",
        actor,
        status="completed" if status == ActivityStatus.success else status.value,
        stage="audit",
        progress=100,
        details={"target": target, **safe_details},
    )


@router.get("/dashboard")
def dashboard(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_VIEW))):
    return _service().dashboard()


@router.get("/settings")
def hosts_manager_settings(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_VIEW))):
    return _service().settings()


@router.put("/settings")
def update_hosts_manager_settings(
    payload: HostsManagerSettingsUpdate,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE)),
):
    try:
        previous, updated = _service().save_settings(payload, user.username)
    except OverflowError:
        api_error(409, "HOSTNAME_SEQUENCE_EXHAUSTED", "The hostname sequence is exhausted")
    except KeyError:
        api_error(422, "HOSTNAME_PATTERN_NOT_FOUND", "The default hostname pattern does not exist or is disabled")
    _activity(
        user.username,
        "hosts_manager_settings_update",
        "hostname-template",
        {
            "old": {key: previous[key] for key in ("hostname_template", "bootstrap_default_os", "bootstrap_apply_hostname")},
            "new": {key: updated[key] for key in ("hostname_template", "bootstrap_default_os", "bootstrap_apply_hostname")},
        },
    )
    return updated


@router.get("/environments")
def environments(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_VIEW))):
    return _service().environments()


@router.get("/apmids")
def apmids(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_VIEW))):
    return _service().apmids()


@router.post("/apmids")
def create_apmid(
    payload: ApmidInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        item = _service().save_apmid(payload, user.username)
    except ManagedGroupConflictError as error:
        api_error(409, "APMID_GROUP_CONFLICT", str(error))
    _activity(user.username, "apmid_create", item["id"], {"code": item["code"], "active": item["active"]})
    return item


@router.put("/apmids/{apmid_id}")
def update_apmid(
    apmid_id: str,
    payload: ApmidInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    _require(_service().apmid_service.get(apmid_id), "APMID_NOT_FOUND", "APMID not found")
    try:
        item = _service().save_apmid(payload, user.username, apmid_id)
    except ManagedGroupConflictError as error:
        api_error(409, "APMID_GROUP_CONFLICT", str(error))
    _activity(user.username, "apmid_update", apmid_id, {"code": item["code"], "active": item["active"]})
    return item


@router.delete("/apmids/{apmid_id}")
def delete_apmid(
    apmid_id: str,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        removed = _service().delete_apmid(apmid_id)
    except ApmidInUseError as error:
        api_error(409, "APMID_IN_USE", str(error))
    _require(removed, "APMID_NOT_FOUND", "APMID not found")
    _activity(user.username, "apmid_delete", apmid_id)
    return {"ok": True}


@router.post("/apmids/sync-groups")
def sync_apmid_groups(
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        result = _service().sync_apmid_environment_groups(user.username)
    except (ManagedGroupConflictError, ManagedGroupProtectedError) as error:
        api_error(409, "APMID_GROUP_SYNC_FAILED", str(error))
    _activity(user.username, "apmid_groups_sync", "all", result)
    return result


@router.post("/environments")
def create_environment(
    payload: EnvironmentInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        item = _service().save_environment(payload, user.username)
    except KeyError as error:
        api_error(422, "ENVIRONMENT_DEFAULT_NOT_FOUND", str(error))
    except ManagedGroupConflictError as error:
        api_error(409, "APMID_GROUP_CONFLICT", str(error))
    _activity(user.username, "environment_create", item["id"])
    return item


@router.put("/environments/{environment_id}")
def update_environment(
    environment_id: str,
    payload: EnvironmentInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    _require(_service()._get("environments", environment_id), "ENVIRONMENT_NOT_FOUND", "Environment not found")
    try:
        item = _service().save_environment(payload, user.username, environment_id)
    except KeyError as error:
        api_error(422, "ENVIRONMENT_DEFAULT_NOT_FOUND", str(error))
    except ManagedGroupConflictError as error:
        api_error(409, "APMID_GROUP_CONFLICT", str(error))
    _activity(user.username, "environment_update", environment_id)
    return item


@router.delete("/environments/{environment_id}")
def delete_environment(
    environment_id: str,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    try:
        removed = _service().delete_environment(environment_id)
    except ValueError:
        api_error(409, "ENVIRONMENT_NOT_EMPTY", "Remove assigned hosts and enrollment token references before deleting this environment")
    _require(removed, "ENVIRONMENT_NOT_FOUND", "Environment not found")
    _activity(user.username, "environment_delete", environment_id)
    return {"ok": True}


@router.get("/hostname-patterns")
def hostname_patterns(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_VIEW))):
    return _service().hostname_patterns()


@router.post("/hostname-patterns")
def create_hostname_pattern(
    payload: HostnamePatternInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE)),
):
    item = _service().save_hostname_pattern(payload, user.username)
    _activity(user.username, "hostname_pattern_create", item["id"])
    return item


@router.put("/hostname-patterns/{pattern_id}")
def update_hostname_pattern(
    pattern_id: str,
    payload: HostnamePatternInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE)),
):
    _require(_service()._get("hostname_patterns", pattern_id), "HOSTNAME_PATTERN_NOT_FOUND", "Hostname pattern not found")
    item = _service().save_hostname_pattern(payload, user.username, pattern_id)
    _activity(user.username, "hostname_pattern_update", pattern_id)
    return item


@router.delete("/hostname-patterns/{pattern_id}")
def delete_hostname_pattern(
    pattern_id: str,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE)),
):
    try:
        removed = _service().delete_hostname_pattern(pattern_id)
    except ValueError:
        api_error(409, "HOSTNAME_PATTERN_IN_USE", "The hostname pattern is assigned to an environment")
    _require(removed, "HOSTNAME_PATTERN_NOT_FOUND", "Hostname pattern not found")
    _activity(user.username, "hostname_pattern_delete", pattern_id)
    return {"ok": True}


@router.post("/hostname-patterns/{pattern_id}/skip")
def skip_hostname_pattern(
    pattern_id: str,
    payload: HostnamePatternSkipInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE)),
):
    try:
        result = _service().skip_hostname_pattern(pattern_id, payload.count, payload.reason, user.username)
    except KeyError:
        api_error(404, "HOSTNAME_PATTERN_NOT_FOUND", "Hostname pattern not found")
    except OverflowError:
        api_error(409, "HOSTNAME_SEQUENCE_EXHAUSTED", "The hostname sequence is exhausted")
    _activity(user.username, "hostname_pattern_skip", pattern_id, {"count": payload.count, "reason": payload.reason})
    return result


@router.get("/hosts")
def hosts(
    search: str = Query("", max_length=128), status: str = Query("", max_length=32), tag: str = Query("", max_length=40),
    group_id: str = Query("", max_length=64), environment: str = Query("", max_length=64), location: str = Query("", max_length=128),
    active_only: bool = False, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0, le=5000),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW)),
):
    return _service().list_hosts(active_only=active_only, search=search, status=status, tag=tag, group_id=group_id, environment=environment, location=location, limit=limit, offset=offset)


@router.get("/hosts-export.csv")
def export_hosts_csv(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW))):
    import csv
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow([
        "status", "hostname", "address", "distribution", "system_version", "environment",
        "agent_version", "agent_status", "last_connection", "available_updates", "created_at",
    ])
    for item in _service().list_hosts():
        agent = item.get("agent") or {}
        writer.writerow([
            item.get("status", ""), item.get("hostname") or item.get("name", ""), item.get("address", ""),
            item.get("distribution", ""), item.get("system_version", ""), item.get("environment", ""),
            item.get("agent_version", ""), item.get("agent_status", ""), agent.get("last_heartbeat_at") or "",
            item.get("available_updates", 0), item.get("created_at", ""),
        ])
    return PlainTextResponse(
        stream.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="hosts-manager-hosts.csv"', "Cache-Control": "no-store"},
    )


@router.post("/hosts")
def create_host(payload: HostInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    item = _service().save_host(payload, user.username)
    _activity(user.username, "host_create", item["id"])
    return item


@router.get("/hosts/{host_id}")
def host(host_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW))):
    return _require(_service().host(host_id), "HOST_NOT_FOUND", "Host not found")


@router.put("/hosts/{host_id}")
def update_host(host_id: str, payload: HostInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    _require(_service().host(host_id), "HOST_NOT_FOUND", "Host not found")
    item = _service().save_host(payload, user.username, host_id)
    _activity(user.username, "host_update", host_id)
    return item


@router.delete("/hosts/{host_id}")
def delete_host(host_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    if not payload.confirm or payload.confirmation_text != (_service().host(host_id) or {}).get("name"):
        api_error(422, "CONFIRMATION_REQUIRED", "Type the host name to confirm deletion")
    _require(_service().delete_host(host_id, user.username), "HOST_NOT_FOUND", "Host not found")
    _activity(user.username, "host_delete", host_id)
    return {"ok": True}


@router.post("/hosts/{host_id}/approve")
def approve_host(host_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_APPROVE))):
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Host approval requires confirmation")
    try:
        item = _service().approve_host(host_id, user.username)
    except KeyError:
        api_error(404, "HOST_NOT_FOUND", "Host not found")
    _activity(user.username, "host_approve", host_id)
    return item


@router.post("/hosts/{host_id}/disable")
def disable_host(host_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Host disable requires confirmation")
    try:
        return _service().disable_host(host_id, user.username)
    except KeyError:
        api_error(404, "HOST_NOT_FOUND", "Host not found")


@router.post("/hosts/{host_id}/ssh-key/scan")
def scan_host_key(host_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    item = _require(_service().host(host_id), "HOST_NOT_FOUND", "Host not found")
    try:
        result = subprocess.run(keyscan_args(item["address"], int(item["port"])), capture_output=True, text=True, timeout=12, check=False, shell=False)
        keys = parse_keyscan(result.stdout[:128 * 1024])
        for key in keys:
            key["fingerprint"] = fingerprint_key(f'{key["key_type"]} {key["public_key"]}')
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as error:
        api_error(502, "SSH_KEYSCAN_FAILED", "SSH host key scan failed", reason=type(error).__name__)
    if not keys:
        api_error(502, "SSH_KEYSCAN_EMPTY", "No supported SSH host key was returned")
    changed = any(_service().mark_scanned_key(host_id, key["fingerprint"], user.username) for key in keys)
    _activity(user.username, "ssh_fingerprint_scan", host_id, {"changed": changed})
    return {"host_id": host_id, "keys": keys, "changed": changed, "requires_acceptance": True}


@router.post("/hosts/{host_id}/ssh-key/accept")
def accept_host_key(host_id: str, payload: FingerprintAcceptInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Fingerprint acceptance requires confirmation")
    fields = payload.public_key.split()
    key_type = fields[0] if fields and fields[0].startswith(("ssh-", "ecdsa-")) else "ssh-ed25519"
    public_key = " ".join(fields[-2:]) if len(fields) >= 2 else payload.public_key
    try:
        item = _service().accept_host_key(host_id, key_type, public_key, payload.fingerprint, user.username, payload.replace)
    except PermissionError:
        api_error(409, "SSH_HOST_KEY_CHANGED", "Host key changed; explicit replacement is required")
    _activity(user.username, "ssh_fingerprint_accept", host_id, {"fingerprint": payload.fingerprint, "replacement": payload.replace})
    return item


def _capability_proxy(host_id: str, capability_id: str, payload: CapabilityActionInput, user: SessionUser, execute: bool):
    try:
        provider = _service().capability(host_id, capability_id)
    except KeyError:
        api_error(404, "CAPABILITY_UNAVAILABLE", "Capability is not available for this host")
    authorize(user, provider.permission)
    item = _require(_service().host(host_id), "HOST_NOT_FOUND", "Host not found")
    if execute:
        result = provider.execute(item, payload.parameters | {"confirm": payload.confirm, "confirmation_text": payload.confirmation_text}, user.username)
        _activity(user.username, "host_capability_execute", host_id, {"capability_id": capability_id}, ActivityStatus.queued)
        return result
    return provider.plan(item, payload.parameters, user.username)


@router.post("/hosts/{host_id}/test")
def test_host(host_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_ACTIONS_EXECUTE))):
    return _capability_proxy(host_id, "ansible.test_connection", CapabilityActionInput(confirm=payload.confirm), user, True)


@router.post("/hosts/{host_id}/facts")
def gather_facts(host_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_ACTIONS_EXECUTE))):
    return _capability_proxy(host_id, "ansible.gather_facts", CapabilityActionInput(confirm=payload.confirm), user, True)


@router.get("/hosts/{host_id}/capabilities")
def capabilities(host_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW))):
    try:
        return _service().capabilities(host_id)
    except KeyError:
        api_error(404, "HOST_NOT_FOUND", "Host not found")


@router.post("/hosts/{host_id}/actions/{capability_id}/plan")
def action_plan(host_id: str, capability_id: str, payload: CapabilityActionInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW))):
    return _capability_proxy(host_id, capability_id, payload, user, False)


@router.post("/hosts/{host_id}/actions/{capability_id}/execute")
def action_execute(host_id: str, capability_id: str, payload: CapabilityActionInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_ACTIONS_EXECUTE))):
    return _capability_proxy(host_id, capability_id, payload, user, True)


@router.get("/groups")
def groups(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW))):
    return _service().list_groups()


@router.post("/groups")
def create_group(payload: GroupInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    try:
        item = _service().save_group(payload, user.username)
    except ManagedGroupConflictError as error:
        api_error(409, "GROUP_NAME_CONFLICT", str(error))
    _activity(user.username, "group_create", item["id"])
    return item


@router.put("/groups/{group_id}")
def update_group(group_id: str, payload: GroupInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    try:
        item = _service().save_group(payload, user.username, group_id)
    except ManagedGroupProtectedError as error:
        api_error(409, "MANAGED_GROUP_PROTECTED", str(error))
    except ManagedGroupConflictError as error:
        api_error(409, "GROUP_NAME_CONFLICT", str(error))
    _activity(user.username, "group_update", group_id)
    return item


@router.delete("/groups/{group_id}")
def delete_group(group_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    try:
        removed = _service().delete_group(group_id)
    except ManagedGroupProtectedError as error:
        api_error(409, "MANAGED_GROUP_PROTECTED", str(error))
    if removed:
        _activity(user.username, "group_delete", group_id)
    return {"ok": removed}


@router.get("/inventory")
def inventory(format: str = Query("yaml", pattern=r"^(yaml|json)$"), user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW))):
    memberships = _service()._list("memberships", order="created_at")
    value = generate_inventory(_service().active_hosts(), _service().list_groups(), memberships)
    return PlainTextResponse(json.dumps(yaml.safe_load(value), indent=2) if format == "json" else value, media_type="application/json" if format == "json" else "application/yaml")


@router.post("/inventory/validate")
def validate_inventory(payload: InventoryInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_INVENTORY_MANAGE))):
    try:
        return parse_inventory(payload.content, "ini" if payload.format.endswith("ini") else "yaml")
    except ValueError as error:
        api_error(422, "INVENTORY_INVALID", str(error))


@router.post("/inventory/import")
def import_inventory(payload: InventoryInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_INVENTORY_MANAGE))):
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Inventory import requires confirmation after validation")
    validation = validate_inventory(payload, user)
    host_records, group_records = inventory_records(validation)
    saved = []
    by_name: dict[str, str] = {}
    for record in host_records:
        item = _service().save_host(HostInput(**record), user.username, source="inventory")
        saved.append(item)
        by_name[item["name"]] = item["id"]
    for group in group_records:
        _service().save_group(GroupInput(name=group["name"], variables=group["variables"], host_ids=[by_name[name] for name in group["host_names"] if name in by_name]), user.username)
    _activity(user.username, "inventory_import", details={"hosts": len(saved), "groups": len(group_records)})
    return {"hosts": saved, "host_count": len(saved), "group_count": len(group_records)}


@router.get("/inventory/export")
def export_inventory(format: str = Query("yaml", pattern=r"^(yaml|json)$"), user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW))):
    return inventory(format, user)


def _onboarding_target_keys(address: str, port: int) -> list[dict[str, str]]:
    try:
        result = subprocess.run(
            keyscan_args(address, port),
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
            shell=False,
        )
        keys = parse_keyscan(result.stdout[:128 * 1024])
        for key in keys:
            key["fingerprint"] = fingerprint_key(f'{key["key_type"]} {key["public_key"]}')
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as error:
        api_error(502, "SSH_KEYSCAN_FAILED", "SSH host key scan failed", reason=type(error).__name__)
    if not keys:
        api_error(502, "SSH_KEYSCAN_EMPTY", "No supported SSH host key was returned")
    return keys


def _onboarding_key(payload: SshOnboardingProbeInput) -> dict[str, str]:
    keys = _onboarding_target_keys(payload.address, payload.port)
    selected = next(
        (item for item in keys if item["fingerprint"] == payload.accepted_fingerprint),
        None,
    )
    if not selected:
        api_error(409, "SSH_FINGERPRINT_CHANGED", "The accepted SSH fingerprint is no longer offered by the host")
    return selected


def _onboarding_ssh(
    payload: SshOnboardingProbeInput,
    selected_key: dict[str, str],
    remote_args: list[str],
    *,
    process_input: str = "",
    sudo_password: bool = False,
) -> subprocess.CompletedProcess[str]:
    if not shutil.which("ssh"):
        api_error(409, "SSH_CLIENT_UNAVAILABLE", "The SSH client is not installed on the Hosts Manager server")
    credential = _service().verified_credential(
        payload.credential_id,
        module_id="hosts-manager",
        purpose="ssh-onboarding",
    )
    if credential["type"] not in {"ssh_password", "ssh_private_key"}:
        api_error(422, "SSH_CREDENTIAL_REQUIRED", "SSH onboarding requires a password or private-key credential")
    with tempfile.TemporaryDirectory(prefix="hosts-manager-onboarding-") as temporary_name:
        directory = Path(temporary_name)
        known_hosts = directory / "known_hosts"
        key_path = directory / "identity"
        secret_path = directory / "askpass-secret"
        askpass_path = directory / "ssh-askpass"
        atomic_private_write(known_hosts, (selected_key["line"] + "\n").encode())
        password_mode = credential["type"] == "ssh_password"
        prompt_secret = credential["secret"] if password_mode else credential.get("passphrase", "")
        if not password_mode:
            atomic_private_write(key_path, credential["secret"].encode())
        if prompt_secret:
            atomic_private_write(secret_path, prompt_secret.encode())
            atomic_private_write(
                askpass_path,
                f"#!/bin/sh\nexec /bin/cat -- {shlex.quote(str(secret_path))}\n".encode(),
                0o700,
            )
        uid, gid, _home = controller_identity()
        private_paths = [directory, known_hosts]
        if not password_mode:
            private_paths.append(key_path)
        if prompt_secret:
            private_paths.extend([secret_path, askpass_path])
        if os.name != "nt":
            for path in private_paths:
                os.chown(path, uid, gid)
        host = {
            "address": payload.address,
            "port": payload.port,
            "ssh_user": payload.ssh_user,
        }
        args = build_ssh_args(
            host,
            known_hosts,
            key_file=None if password_mode else key_path,
            probe="true",
            batch_mode=not bool(prompt_secret),
        )
        args = args[: -len(SSH_COMMANDS["true"])] + remote_args
        environment = {
            "PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"),
            "LANG": "C",
            "HOME": str(directory),
        }
        if prompt_secret:
            environment.update(
                {
                    "SSH_ASKPASS": str(askpass_path),
                    "SSH_ASKPASS_REQUIRE": "force",
                    "DISPLAY": "hosts-manager:0",
                }
            )
        stdin = process_input
        if sudo_password and password_mode:
            stdin = f"{credential['secret']}\n{process_input}"
        result = subprocess.run(
            args,
            input=stdin or None,
            capture_output=True,
            text=True,
            timeout=max(30, int(_service().settings()["ssh_timeout_seconds"]) * 6),
            check=False,
            shell=False,
            cwd=directory,
            env=environment,
            preexec_fn=demote_preexec(uid, gid) if os.name != "nt" else None,
        )
    result.stdout = redact_text(result.stdout, [credential["secret"], credential.get("passphrase", "")])
    result.stderr = redact_text(result.stderr, [credential["secret"], credential.get("passphrase", "")])
    return result


def _parse_onboarding_probe(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        if line.startswith("__HM_") and "=" in line:
            key, value = line.split("=", 1)
            fields[key[5:-2].lower()] = value.strip()
    return fields


@router.post("/onboarding/ssh/probe")
def probe_ssh_onboarding(
    payload: SshOnboardingProbeInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    keys = _onboarding_target_keys(payload.address, payload.port)
    if not payload.accepted_fingerprint:
        _activity(user.username, "onboarding_fingerprint_scan", details={"address": payload.address, "port": payload.port})
        return {
            "address": payload.address,
            "port": payload.port,
            "port_open": True,
            "login_available": False,
            "requires_fingerprint_confirmation": True,
            "keys": keys,
        }
    selected = next((item for item in keys if item["fingerprint"] == payload.accepted_fingerprint), None)
    if not selected:
        api_error(409, "SSH_FINGERPRINT_CHANGED", "The accepted SSH fingerprint is no longer offered by the host")
    result = _onboarding_ssh(payload, selected, ["sh", "-c", SSH_PROBE_COMMAND])
    facts = _parse_onboarding_probe(result.stdout)
    response = {
        "address": payload.address,
        "port": payload.port,
        "port_open": True,
        "login_available": result.returncode == 0,
        "requires_fingerprint_confirmation": False,
        "accepted_key": selected,
        "distribution": facts.get("distribution", ""),
        "system_version": facts.get("version", ""),
        "package_manager": facts.get("package_manager", "unknown"),
        "python": facts.get("python", ""),
        "init_system": facts.get("init", "other"),
        "privilege": facts.get("privilege", "user"),
        "sudo_available": facts.get("privilege") in {"root", "sudo", "sudo-password"},
        "error": result.stderr[-2_000:] if result.returncode else "",
    }
    _activity(
        user.username,
        "onboarding_connection_test",
        details={
            "address": payload.address,
            "port": payload.port,
            "ok": response["login_available"],
            "fingerprint": payload.accepted_fingerprint,
        },
        status=ActivityStatus.success if response["login_available"] else ActivityStatus.failure,
    )
    return response


@router.post("/onboarding/ssh/install")
def install_agent_over_ssh(
    payload: SshOnboardingInstallInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    if not payload.confirm or not payload.accepted_fingerprint:
        api_error(422, "CONFIRMATION_REQUIRED", "SSH installation requires confirmation and an accepted host fingerprint")
    selected_key = _onboarding_key(payload)
    probe = _onboarding_ssh(payload, selected_key, ["sh", "-c", SSH_PROBE_COMMAND])
    probe_facts = _parse_onboarding_probe(probe.stdout)
    if probe.returncode != 0:
        api_error(502, "SSH_LOGIN_FAILED", "SSH login failed during the final pre-installation test")
    privilege = probe_facts.get("privilege", "user")
    credential_metadata = _service()._get("credentials", payload.credential_id) or {}
    password_mode = credential_metadata.get("type") == "ssh_password"
    if (
        privilege == "user"
        or (payload.ssh_user != "root" and not payload.use_sudo)
        or (privilege == "sudo-password" and not password_mode)
    ):
        api_error(409, "SSH_PRIVILEGE_REQUIRED", "Root or supported sudo access is required to install the agent")
    settings = _service().settings()
    endpoint = _public_hosts_manager_endpoint()
    try:
        token_item = _service().create_enrollment_token(
            EnrollmentTokenInput(
                mode=EnrollmentTokenMode.one_time,
                bootstrap_os=BootstrapOS.linux,
                apply_hostname=payload.apply_hostname,
                expires_minutes=int(settings["token_ttl_minutes"]),
                apmid_id=payload.apmid_id,
                environment_id=payload.environment_id,
                hostname_pattern_id=payload.hostname_pattern_id,
                bound_address=payload.address,
                agent_port=payload.agent_port,
                report_interval_seconds=payload.report_interval_seconds,
                require_approval=True,
            ),
            user.username,
        )
    except KeyError:
        api_error(422, "ONBOARDING_DEFAULT_NOT_FOUND", "The selected APMID, environment, or pattern is unavailable")
    operation = _service().operation(
        None,
        "agent.install",
        user.username,
        status="running",
        stage="ssh_install",
        progress=25,
        details={"address": payload.address, "hostname": token_item["assigned_hostname"]},
    )
    try:
        script, _token_data = _service().enrollment_script(token_item["token"], endpoint)
        if payload.ssh_user == "root":
            remote_args = ["sh", "-s"]
            sudo_password = False
        elif password_mode:
            remote_args = ["sudo", "-S", "-p", "", "sh", "-s"]
            sudo_password = True
        else:
            remote_args = ["sudo", "-n", "sh", "-s"]
            sudo_password = False
        result = _onboarding_ssh(
            payload,
            selected_key,
            remote_args,
            process_input=script,
            sudo_password=sudo_password,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr[-2_000:] or "remote installer returned a non-zero status")
        token_record = next(item for item in _service().enrollment_tokens() if item["id"] == token_item["id"])
        hostname = str(token_record.get("used_hostname") or token_item["assigned_hostname"])
        host = next((item for item in _service().list_hosts() if item["name"].casefold() == hostname.casefold()), None)
        if not host:
            raise RuntimeError("agent installation completed but the host did not register")
        _service().accept_host_key(
            host["id"],
            selected_key["key_type"],
            selected_key["public_key"],
            selected_key["fingerprint"],
            user.username,
        )
        log = (result.stdout + "\n" + result.stderr).strip()[-10_000:]
        _service().update_operation(
            operation["id"],
            user.username,
            status="completed",
            stage="registered",
            progress=100,
            details={
                "address": payload.address,
                "hostname": hostname,
                "host_id": host["id"],
                "log": log,
            },
        )
        _activity(
            user.username,
            "agent_install_ssh",
            host["id"],
            {"hostname": hostname, "fingerprint": selected_key["fingerprint"]},
        )
        return {"status": "completed", "host": _service().host(host["id"]), "log": log, "operation_id": operation["id"]}
    except (KeyError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        _service().revoke_enrollment_token(token_item["id"], user.username)
        _service().update_operation(
            operation["id"],
            user.username,
            status="failed",
            stage="failed",
            progress=100,
            error=redact_text(error)[:2_000],
        )
        api_error(502, "AGENT_INSTALLATION_FAILED", "Remote agent installation failed", reason=type(error).__name__)


@router.get("/enrollment-tokens")
def enrollment_tokens(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    return _service().enrollment_tokens()


def _public_hosts_manager_endpoint() -> str:
    configured = str(_service().settings().get("server_url") or "").rstrip("/")
    if not configured.startswith("https://"):
        api_error(
            422,
            "HTTPS_ENDPOINT_REQUIRED",
            "Configure the public HTTPS Hosts Manager server URL before generating an installer",
        )
    return configured


@router.post("/enrollment-tokens")
def create_enrollment_token(payload: EnrollmentTokenInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    endpoint = _public_hosts_manager_endpoint()
    try:
        item = _service().create_enrollment_token(payload, user.username)
    except OverflowError:
        api_error(409, "HOSTNAME_SEQUENCE_EXHAUSTED", "The hostname sequence is exhausted")
    except KeyError as error:
        detail = str(error).casefold()
        if "apmid" in detail:
            api_error(422, "APMID_INACTIVE", "The selected APMID does not exist or is inactive", field="apmid_id")
        if "environment" in detail:
            api_error(422, "ENVIRONMENT_INACTIVE", "The selected environment does not exist or is inactive", field="environment_id")
        if "hostname pattern" in detail:
            api_error(422, "HOSTNAME_PATTERN_INACTIVE", "The selected hostname pattern does not exist or is inactive", field="hostname_pattern_id")
        if "group" in detail:
            api_error(422, "ENROLLMENT_GROUP_INACTIVE", "A selected additional group does not exist or is inactive", field="group_ids")
        api_error(422, "ENROLLMENT_DEFAULT_NOT_FOUND", "An enrollment selection is unavailable")
    except ManagedGroupProtectedError as error:
        api_error(409, "MANAGED_GROUP_PROTECTED", str(error))
    except ManagedGroupConflictError as error:
        api_error(409, "APMID_GROUP_CONFLICT", str(error))
    token = item["token"]
    item["script_url"] = "/api/modules/hosts-manager/enrollment-script"
    if item["bootstrap_os"] == "windows":
        item["filename"] = f"webnas-enroll-{item['assigned_hostname']}.ps1"
        item["command"] = (
            f"$h=@{{Authorization='Bearer {token}'}}; "
            f"Invoke-WebRequest -UseBasicParsing -Headers $h -Uri '{endpoint}{item['script_url']}' "
            f"-OutFile '.\\{item['filename']}'; powershell -ExecutionPolicy Bypass -File '.\\{item['filename']}'"
        )
    else:
        item["filename"] = f"webnas-enroll-{item['assigned_hostname']}.sh"
        item["command"] = (
            "curl --fail --silent --show-error "
            f"-H 'Authorization: Bearer {token}' '{endpoint}{item['script_url']}' | sudo bash"
        )
    _activity(user.username, "enrollment_token_create", item["id"], {
        "expires_at": item["expires_at"], "assigned_hostname": item["assigned_hostname"],
        "bootstrap_os": item["bootstrap_os"], "apply_hostname": item["apply_hostname"],
        "apmid_id": item["apmid_id"], "apmid_code": item["apmid_code"],
        "environment_id": item["environment_id"], "environment_slug": item["environment_slug"],
        "managed_group_id": item["managed_group_id"], "managed_group_name": item["managed_group_name"],
    })
    return item


@router.delete("/enrollment-tokens/{token_id}")
def revoke_enrollment_token(token_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    removed = _service().revoke_enrollment_token(token_id, user.username)
    if removed:
        _activity(user.username, "enrollment_token_revoke", token_id)
    return {"ok": removed}


@router.get("/enrollment-tokens/{token_id}/script")
def legacy_enrollment_script(token_id: str, authorization: str = Header(default="", max_length=512)):
    return _enrollment_script_response(authorization, token_id)


@router.get("/enrollment-script")
def enrollment_script(authorization: str = Header(default="", max_length=512)):
    return _enrollment_script_response(authorization)


def _enrollment_script_response(authorization: str, expected_token_id: str = ""):
    if not authorization.startswith("Bearer ") or len(authorization) > 512:
        api_error(401, "ENROLLMENT_TOKEN_REQUIRED", "A valid enrollment token is required")
    token = authorization[7:]
    try:
        script, item = _service().enrollment_script(token, _public_hosts_manager_endpoint())
    except KeyError:
        api_error(401, "ENROLLMENT_TOKEN_INVALID", "Enrollment token is invalid, expired, used or revoked")
    if expected_token_id and item["id"] != expected_token_id:
        api_error(401, "ENROLLMENT_TOKEN_INVALID", "Enrollment token does not match this script")
    extension = "ps1" if item["bootstrap_os"] == "windows" else "sh"
    media_type = "text/plain" if extension == "ps1" else "text/x-shellscript"
    filename = f"webnas-enroll-{item['assigned_hostname'] or item['id']}.{extension}"
    return PlainTextResponse(
        script,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@router.post("/enroll")
def enroll(payload: EnrollmentClaimInput, authorization: str = Header(default="", max_length=512)):
    if not authorization.startswith("Bearer ") or len(authorization) > 512:
        api_error(401, "ENROLLMENT_TOKEN_REQUIRED", "A valid enrollment token is required")
    item = _service().claim_enrollment_token(authorization[7:], payload.model_dump())
    if not item:
        api_error(401, "ENROLLMENT_TOKEN_INVALID", "Enrollment token is invalid, expired, used or does not allow this hostname")
    return {
        "id": item["id"],
        "hostname": item["hostname"],
        "registration_status": item["registration_status"],
        "approved": item["approved"],
        "fingerprint_status": item["fingerprint_status"],
        "agent_credentials": item.get("agent_credentials"),
    }


def _bearer(authorization: str) -> str:
    if not authorization.startswith("Bearer ") or not 32 <= len(authorization[7:]) <= 512:
        api_error(401, "AGENT_AUTHENTICATION_REQUIRED", "A valid agent token is required")
    return authorization[7:]


@router.post("/agent/heartbeat")
def agent_heartbeat(payload: AgentHeartbeatInput, authorization: str = Header(default="", max_length=640)):
    result = _service().agent_heartbeat(payload.agent_id, _bearer(authorization), payload.model_dump(mode="json"))
    if not result:
        api_error(401, "AGENT_AUTHENTICATION_FAILED", "Agent identity is invalid or requires pairing")
    return result


@router.post("/agent/report")
def agent_report(payload: AgentReportInput, authorization: str = Header(default="", max_length=640)):
    report = payload.model_dump(mode="json")
    agent_id = str(report.pop("agent_id"))
    result = _service().save_agent_report(agent_id, _bearer(authorization), report)
    if not result:
        api_error(401, "AGENT_AUTHENTICATION_FAILED", "Agent identity is invalid or requires pairing")
    return result


@router.get("/agent/source")
def agent_source():
    path = Path(__file__).with_name("agent.py")
    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        media_type="text/x-python",
        headers={
            "Content-Disposition": 'attachment; filename="hosts-manager-agent.py"',
            "Cache-Control": "public, max-age=300",
        },
    )


@router.get("/hosts/{host_id}/agent/history")
def host_agent_history(
    host_id: str,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_AUDIT_VIEW)),
):
    _require(_service().host(host_id), "HOST_NOT_FOUND", "Host not found")
    return _service().agent_history(host_id)


@router.post("/hosts/{host_id}/agent/identity/regenerate")
def regenerate_host_identity(
    host_id: str,
    payload: ConfirmationInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Identity regeneration requires confirmation")
    try:
        result = _service().rotate_agent_identity(host_id, user.username)
    except KeyError:
        api_error(404, "AGENT_NOT_FOUND", "Agent is not installed on this host")
    _activity(user.username, "host_identity_regenerate", host_id, {"agent_id": result["agent_id"]})
    return result


@router.post("/hosts/{host_id}/agent/identity/invalidate")
def invalidate_host_identity(
    host_id: str,
    payload: ConfirmationInput,
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE)),
):
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Identity invalidation requires confirmation")
    _require(_service().invalidate_agent_identity(host_id, user.username), "AGENT_NOT_FOUND", "Agent not found")
    _activity(user.username, "host_identity_invalidate", host_id)
    return {"ok": True, "pairing_required": True}


def _probe(address: str, port: int, timeout: float, reverse_dns: bool) -> dict[str, Any] | None:
    started = time.monotonic()
    try:
        with socket.create_connection((address, port), timeout=timeout):
            hostname = socket.gethostbyaddr(address)[0][:253] if reverse_dns else ""
            return {"id": stable_id(), "address": address, "hostname": hostname, "port": port, "latency_ms": round((time.monotonic() - started) * 1000, 2), "ssh_status": "open"}
    except OSError:
        return None


@router.get("/scans")
def scans(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_DISCOVERY, mutating=False))):
    return _service()._list("scans")


@router.post("/scans")
def create_scan(payload: ScanInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_DISCOVERY))):
    import ipaddress
    addresses = [str(item) for item in (ipaddress.ip_network(payload.cidr, strict=False).hosts() if payload.cidr else (ipaddress.ip_address(value) for value in range(int(ipaddress.ip_address(payload.start_address or "")), int(ipaddress.ip_address(payload.end_address or "")) + 1)))]
    results = []
    with ThreadPoolExecutor(max_workers=payload.concurrency) as pool:
        futures = [pool.submit(_probe, address, payload.port, payload.timeout_seconds, payload.reverse_dns) for address in addresses]
        for future in as_completed(futures):
            item = future.result()
            if item:
                results.append(item)
    now, scan_id = time.time(), stable_id()
    with _service().connect() as connection:
        connection.execute("INSERT INTO scans(id,request_json,status,results_json,created_at,updated_at,created_by,updated_by) VALUES(?,?, 'completed',?,?,?,?,?)", (scan_id, json.dumps(payload.model_dump(mode="json")), json.dumps(results), now, now, user.username, user.username))
    _activity(user.username, "network_scan", scan_id, {"addresses": len(addresses), "discovered": len(results)})
    return {"id": scan_id, "status": "completed", "results": results, "discovered": len(results)}


@router.get("/scans/{scan_id}")
def scan(scan_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_DISCOVERY, mutating=False))):
    item = _require(_service()._get("scans", scan_id), "SCAN_NOT_FOUND", "Discovery scan not found")
    item["results"] = json.loads(item.pop("results_json", "[]"))
    return item


@router.post("/scans/{scan_id}/import")
def import_scan(scan_id: str, payload: ScanImportInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Discovery import requires confirmation")
    item = scan(scan_id, user)
    selected = [record for record in item["results"] if record["id"] in payload.host_ids]
    saved = [_service().save_host(HostInput(name=record["hostname"] or record["address"].replace(":", "-"), hostname=record["hostname"], address=record["address"], port=record["port"], tags=payload.tags, group_ids=payload.group_ids), user.username, source="discovery") for record in selected]
    _activity(user.username, "network_scan_import", scan_id, {"imported": len(saved)})
    return {"hosts": saved, "imported": len(saved)}


@router.get("/credentials")
def credentials(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CREDENTIALS_VIEW))):
    return _service().credentials()


@router.post("/credentials")
def create_credential(payload: CredentialInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CREDENTIALS_MANAGE))):
    item = _service().save_credential(payload, user.username)
    _activity(user.username, "credential_create", item["id"], {"type": item["type"]})
    return item


@router.put("/credentials/{credential_id}")
def update_credential(credential_id: str, payload: CredentialInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CREDENTIALS_MANAGE))):
    item = _service().save_credential(payload, user.username, credential_id)
    _activity(user.username, "credential_update", credential_id, {"type": item["type"]})
    return item


@router.delete("/credentials/{credential_id}")
def delete_credential(credential_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CREDENTIALS_MANAGE))):
    try:
        removed = _service().delete_credential(credential_id)
    except ValueError:
        api_error(409, "CREDENTIAL_IN_USE", "Move assigned hosts and environment defaults before deleting this credential")
    if removed:
        _activity(user.username, "credential_delete", credential_id)
    return {"ok": removed}


@router.get("/repositories")
def repositories(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_REPOSITORIES_VIEW))):
    return _service().repositories()


@router.post("/repositories")
def create_repository(payload: RepositoryInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_REPOSITORIES_MANAGE))):
    item = _service().save_repository(payload, user.username)
    _activity(user.username, "repository_create", item["id"])
    return item


@router.put("/repositories/{repository_id}")
def update_repository(repository_id: str, payload: RepositoryInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_REPOSITORIES_MANAGE))):
    item = _service().save_repository(payload, user.username, repository_id)
    _activity(user.username, "repository_update", repository_id)
    return item


@router.delete("/repositories/{repository_id}")
def delete_repository(repository_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_REPOSITORIES_MANAGE))):
    removed = _service().delete_repository(repository_id)
    if removed:
        _activity(user.username, "repository_delete", repository_id)
    return {"ok": removed}


@router.post("/repositories/{repository_id}/sync")
def sync_repository(repository_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_REPOSITORIES_MANAGE))):
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Repository sync requires confirmation")
    item = _require(_service()._get("repositories", repository_id), "REPOSITORY_NOT_FOUND", "Repository not found")
    target = (_service().repositories_root / repository_id).resolve()
    if target.parent != _service().repositories_root.resolve() or target.is_symlink():
        api_error(409, "REPOSITORY_PATH_UNSAFE", "Managed repository path is unsafe")
    try:
        if not target.exists():
            subprocess.run(["git", "clone", "--no-recurse-submodules", "--", item["url"], str(target)], capture_output=True, text=True, timeout=300, check=True, shell=False)
        subprocess.run(["git", "-C", str(target), "fetch", "--prune", "--no-recurse-submodules", "origin"], capture_output=True, text=True, timeout=300, check=True, shell=False)
        subprocess.run(["git", "-C", str(target), "checkout", "--detach", item["revision"]], capture_output=True, text=True, timeout=120, check=True, shell=False)
        commit = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20, check=True, shell=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        api_error(502, "REPOSITORY_SYNC_FAILED", "Repository synchronization failed")
    now = time.time()
    with _service().connect() as connection:
        connection.execute("UPDATE repositories SET last_commit=?,last_sync_at=?,last_sync_status='completed',checksum=?,updated_at=?,updated_by=? WHERE id=?", (commit, now, commit, now, user.username, repository_id))
        connection.execute("INSERT INTO repository_syncs(id,repository_id,status,commit_hash,message,created_at,created_by) VALUES(?,?, 'completed',?,'',?,?)", (stable_id(), repository_id, commit, now, user.username))
    _activity(user.username, "repository_sync", repository_id, {"commit": commit})
    return {"repository": _service()._get("repositories", repository_id), "commit": commit}


@router.get("/power-profiles")
def power_profiles(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_POWER_VIEW))):
    return _service().power_profiles()


@router.post("/power-profiles")
def create_power_profile(payload: PowerProfileInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE))):
    item = _service().save_power_profile(payload, user.username)
    _activity(user.username, "power_profile_create", item["id"], {"provider": item["provider"]})
    return item


@router.put("/power-profiles/{profile_id}")
def update_power_profile(profile_id: str, payload: PowerProfileInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE))):
    item = _service().save_power_profile(payload, user.username, profile_id)
    _activity(user.username, "power_profile_update", profile_id, {"provider": item["provider"]})
    return item


@router.delete("/power-profiles/{profile_id}")
def delete_power_profile(profile_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE))):
    removed = _service().delete_power_profile(profile_id)
    if removed:
        _activity(user.username, "power_profile_delete", profile_id)
    return {"ok": removed}


def _power_plan(host_id: str, payload: PowerActionInput) -> dict[str, Any]:
    item = _require(_service().host(host_id), "HOST_NOT_FOUND", "Host not found")
    profile = _service()._get("power_profiles", str(item.get("power_profile_id") or ""))
    if not profile or not profile["active"]:
        api_error(409, "POWER_NOT_CONFIGURED", "Power management is not configured for this host")
    supported = {"none": [], "wol": ["on"], "redfish": ["refresh", "on", "off", "shutdown", "reboot"], "ipmi": ["refresh", "on", "off", "reboot"], "proxmox": ["refresh", "on", "off", "shutdown", "reboot"]}[profile["provider"]]
    if payload.action not in supported:
        api_error(409, "POWER_ACTION_UNSUPPORTED", "Power action is unsupported by this provider")
    dangerous = payload.action in {"off", "shutdown", "reboot"}
    return {"host_id": host_id, "host_name": item["name"], "action": payload.action, "provider": profile["provider"], "dangerous": dangerous, "confirmations_required": ["confirm", "host_name"] if dangerous else ["confirm"], "profile": profile}


@router.get("/hosts/{host_id}/power")
def host_power(host_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_POWER_VIEW))):
    item = _require(_service().host(host_id), "HOST_NOT_FOUND", "Host not found")
    return {"status": item["power_status"], "profile": _service()._get("power_profiles", str(item.get("power_profile_id") or ""))}


@router.post("/hosts/{host_id}/power/plan")
def power_plan(host_id: str, payload: PowerActionInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_POWER_VIEW))):
    return _power_plan(host_id, payload)


@router.post("/hosts/{host_id}/power/execute")
def power_execute(host_id: str, payload: PowerActionInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_POWER_VIEW))):
    plan = _power_plan(host_id, payload)
    permission = {"on": Permission.HOSTS_MANAGER_POWER_ON, "off": Permission.HOSTS_MANAGER_POWER_SHUTDOWN, "shutdown": Permission.HOSTS_MANAGER_POWER_SHUTDOWN, "reboot": Permission.HOSTS_MANAGER_POWER_REBOOT, "refresh": Permission.HOSTS_MANAGER_POWER_VIEW}[payload.action]
    authorize(user, permission)
    if not payload.confirm or (plan["dangerous"] and payload.confirmation_text != plan["host_name"]):
        api_error(422, "CONFIRMATION_REQUIRED", "Power action requires explicit confirmation and the host name")
    profile = plan["profile"]
    if profile["provider"] == "wol":
        mac = bytes.fromhex(profile["mac_address"].replace(":", ""))
        packet = b"\xff" * 6 + mac * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(3)
            sock.sendto(packet, (profile["broadcast_address"] or "255.255.255.255", 9))
        status, details = "request_sent", {"message": "Wake-on-LAN request sent; boot is not confirmed"}
    else:
        api_error(501, "POWER_PROVIDER_UNAVAILABLE", "This power provider is configured but its runtime client is unavailable")
    operation = _service().operation(host_id, f"power.{payload.action}", user.username, status="completed", stage="completed", progress=100, details=details)
    _service()._update_host(host_id, user.username, power_status=status, last_power_action_at=time.time())
    _activity(user.username, f"power_{payload.action}", host_id, {"provider": profile["provider"]})
    return {"operation": operation, "status": status}


@router.get("/operations")
def operations(host_id: str = Query("", max_length=64), limit: int = Query(200, ge=1, le=1000), user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_AUDIT_VIEW))):
    return _service().operations(host_id or None, limit)


@router.get("/operations/{operation_id}")
def operation(operation_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_AUDIT_VIEW))):
    return _require(_service()._get("operations", operation_id), "OPERATION_NOT_FOUND", "Operation not found")


@router.get("/operations/{operation_id}/events")
async def operation_events(operation_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_AUDIT_VIEW))):
    async def events():
        last = ""
        while True:
            item = _service()._get("operations", operation_id)
            if not item:
                yield 'event: error\ndata: {"error":"Operation not found"}\n\n'
                return
            encoded = json.dumps(item)
            if encoded != last:
                yield f"data: {encoded}\n\n"
                last = encoded
            if item["status"] in {"completed", "failed", "cancelled"}:
                return
            await asyncio.sleep(.5)
    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/operations/{operation_id}/cancel")
def cancel_operation(operation_id: str, payload: ConfirmationInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_ACTIONS_EXECUTE))):
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Cancellation requires confirmation")
    with _service().connect() as connection:
        changed = connection.execute("UPDATE operations SET status='cancelled',stage='cancelled',updated_at=?,updated_by=? WHERE id=? AND status IN ('queued','running')", (time.time(), user.username, operation_id)).rowcount
    return {"ok": bool(changed)}


@router.get("/diagnostics")
def diagnostics(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE, mutating=False))):
    checks = []
    try:
        with _service().connect() as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        checks.extend([{"id": "schema", "status": "ok" if version == 1 else "error", "message": f"schema version {version}"}, {"id": "sqlite", "status": "ok" if integrity == "ok" else "error", "message": integrity}])
    except sqlite3.Error as error:
        checks.append({"id": "sqlite", "status": "error", "message": type(error).__name__})
    mode = os.stat(_service().path).st_mode & 0o777
    checks.append({"id": "permissions", "status": "ok" if mode & 0o077 == 0 else "error", "message": oct(mode)})
    checks.append({"id": "credential_key", "status": "ok" if _service().cipher.key_path.is_file() else "warning", "message": "configured" if _service().cipher.key_path.is_file() else "not created"})
    hosts = _service().list_hosts()
    checks.append({"id": "references", "status": "ok", "message": f"{len(hosts)} hosts"})
    checks.append({"id": "fingerprints", "status": "warning" if any(item["fingerprint_status"] == "changed" for item in hosts) else "ok", "message": f"{sum(item['fingerprint_status'] == 'changed' for item in hosts)} changed"})
    return {"schema_version": SCHEMA_VERSION, "checks": checks}


def _backup_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@router.get("/backups")
def backups(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_BACKUP, mutating=False))):
    return [{"id": path.stem, "filename": path.name, "size": path.stat().st_size, "created_at": path.stat().st_mtime, "checksum": _backup_checksum(path)} for path in sorted(_service().backups_root.glob("hosts-manager-*.tar.gz"), reverse=True)]


@router.post("/backups")
def create_backup(payload: BackupInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_BACKUP))):
    if not payload.confirm:
        api_error(422, "CONFIRMATION_REQUIRED", "Backup creation requires confirmation")
    backup_id = f"hosts-manager-{int(time.time())}-{stable_id()[:8]}"
    target = _service().backups_root / f"{backup_id}.tar.gz"
    snapshot = _service().backups_root / f".{backup_id}.sqlite3"
    with _service().connect() as source, sqlite3.connect(snapshot) as destination:
        source.backup(destination)
    if not payload.include_credentials:
        with sqlite3.connect(snapshot) as connection:
            connection.execute("UPDATE credentials SET encrypted_secret=''")
    manifest = json.dumps({"module": "hosts-manager", "schema_version": SCHEMA_VERSION, "created_at": time.time(), "description": payload.description, "includes_credentials": payload.include_credentials})
    with tarfile.open(target, "w:gz") as archive:
        info = tarfile.TarInfo("manifest.json")
        encoded = manifest.encode()
        info.size = len(encoded)
        archive.addfile(info, io.BytesIO(encoded))
        archive.add(snapshot, arcname="hosts.sqlite3")
        if payload.include_repositories:
            for repository_path in _service().repositories_root.iterdir():
                if repository_path.is_dir() and not repository_path.is_symlink():
                    archive.add(repository_path, arcname=f"repositories/{repository_path.name}", recursive=True, filter=lambda item: None if item.issym() or item.islnk() else item)
    snapshot.unlink(missing_ok=True)
    os.chmod(target, 0o600)
    item = {"id": backup_id, "filename": target.name, "size": target.stat().st_size, "created_at": target.stat().st_mtime, "checksum": _backup_checksum(target)}
    _activity(user.username, "hosts_backup_create", backup_id, {"include_credentials": payload.include_credentials})
    return item


def _backup_path(backup_id: str) -> Path:
    if not backup_id.startswith("hosts-manager-") or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in backup_id):
        api_error(400, "BACKUP_ID_INVALID", "Invalid backup identifier")
    return _service().backups_root / f"{backup_id}.tar.gz"


@router.post("/backups/{backup_id}/validate")
def validate_backup(backup_id: str, payload: RestoreInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_RESTORE))):
    path = _backup_path(backup_id)
    _require(path.is_file(), "BACKUP_NOT_FOUND", "Backup not found")
    if _backup_checksum(path) != payload.checksum:
        api_error(422, "BACKUP_CHECKSUM_INVALID", "Backup checksum mismatch")
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        if any(member.name.startswith(("/", "\\")) or ".." in Path(member.name).parts or member.size > 2 * 1024 * 1024 * 1024 for member in members):
            api_error(422, "BACKUP_UNSAFE", "Backup contains an unsafe path or oversized member")
        names = {member.name for member in members}
    return {"ok": {"manifest.json", "hosts.sqlite3"} <= names, "members": sorted(names)}


@router.post("/backups/{backup_id}/restore")
def restore_backup(backup_id: str, payload: RestoreInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_RESTORE))):
    if not payload.confirm or payload.confirmation_text != "Hosts Manager":
        api_error(422, "CONFIRMATION_REQUIRED", "Restore requires typing Hosts Manager")
    validate_backup(backup_id, payload, user)
    path = _backup_path(backup_id)
    safety = create_backup(BackupInput(description="Automatic safety backup before restore", confirm=True), user)
    temporary = _service().root / f".restore-{stable_id()}.sqlite3"
    try:
        with tarfile.open(path, "r:gz") as archive:
            source = archive.extractfile("hosts.sqlite3")
            if source is None:
                api_error(422, "BACKUP_INVALID", "Database snapshot is missing")
            with temporary.open("wb") as output:
                shutil.copyfileobj(source, output)
        with sqlite3.connect(temporary) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                api_error(422, "BACKUP_DATABASE_INVALID", "Restored database failed integrity check")
        os.replace(temporary, _service().path)
        os.chmod(_service().path, 0o600)
        _service()._initialize()
    finally:
        temporary.unlink(missing_ok=True)
    _activity(user.username, "hosts_backup_restore", backup_id, {"safety_backup_id": safety["id"]})
    return {"ok": True, "safety_backup": safety}


@router.get("/backups/{backup_id}/download")
def download_backup(backup_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_BACKUP, mutating=False))):
    path = _backup_path(backup_id)
    _require(path.is_file(), "BACKUP_NOT_FOUND", "Backup not found")
    return StreamingResponse(path.open("rb"), media_type="application/gzip", headers={"Content-Disposition": f'attachment; filename="{path.name}"'})


@router.delete("/backups/{backup_id}")
def delete_backup(backup_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_BACKUP))):
    path = _backup_path(backup_id)
    _require(path.is_file(), "BACKUP_NOT_FOUND", "Backup not found")
    path.unlink()
    _activity(user.username, "hosts_backup_delete", backup_id)
    return {"ok": True}
