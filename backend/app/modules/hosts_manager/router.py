from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...identity.permissions import Permission, authorize, require_permission
from ...package_center.models import api_error
from ...security import SessionUser
from ..ansible_controller.inventory import generate_inventory, inventory_records, parse_inventory
from ..ansible_controller.runner import fingerprint_key, keyscan_args, parse_keyscan
from .models import (
    BackupInput, CapabilityActionInput, ConfirmationInput, CredentialInput, EnrollmentClaimInput,
    EnrollmentTokenInput, FingerprintAcceptInput, GroupInput, HostInput, InventoryInput,
    PowerActionInput, PowerProfileInput, RepositoryInput, RestoreInput, ScanImportInput, ScanInput,
)
from .service import registry, stable_id


router = APIRouter(prefix="/api/modules/hosts-manager", tags=["hosts-manager"])
_ephemeral_tokens: dict[str, tuple[str, float]] = {}


def _service():
    return registry()


def _require(value: Any, code: str, message: str) -> Any:
    if not value:
        api_error(404, code, message)
    return value


def _activity(actor: str, action: str, target: str = "", details: dict[str, Any] | None = None, status: ActivityStatus = ActivityStatus.success) -> None:
    record_activity(ActivityCategory.module, action, actor, target=target, details=details or {}, status=status, source="hosts-manager")


@router.get("/dashboard")
def dashboard(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_VIEW))):
    return _service().dashboard()


@router.get("/hosts")
def hosts(
    search: str = Query("", max_length=128), status: str = Query("", max_length=32), tag: str = Query("", max_length=40),
    group_id: str = Query("", max_length=64), environment: str = Query("", max_length=64), location: str = Query("", max_length=128),
    active_only: bool = False, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0, le=5000),
    user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_VIEW)),
):
    return _service().list_hosts(active_only=active_only, search=search, status=status, tag=tag, group_id=group_id, environment=environment, location=location, limit=limit, offset=offset)


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
    return _service().save_group(payload, user.username)


@router.put("/groups/{group_id}")
def update_group(group_id: str, payload: GroupInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    return _service().save_group(payload, user.username, group_id)


@router.delete("/groups/{group_id}")
def delete_group(group_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    return {"ok": _service().delete_group(group_id)}


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


@router.get("/enrollment-tokens")
def enrollment_tokens(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    return _service().enrollment_tokens()


@router.post("/enrollment-tokens")
def create_enrollment_token(payload: EnrollmentTokenInput, request: Request, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    item = _service().create_enrollment_token(payload, user.username)
    token = item.pop("token")
    _ephemeral_tokens[item["id"]] = (token, item["expires_at"])
    endpoint = str(request.base_url).rstrip("/")
    item["script_url"] = f"/api/modules/hosts-manager/enrollment-tokens/{item['id']}/script"
    item["command"] = f"curl --fail --silent --show-error '{endpoint}{item['script_url']}' | sudo sh"
    _activity(user.username, "enrollment_token_create", item["id"], {"expires_at": item["expires_at"], "hostname_pattern": item["hostname_pattern"]})
    return item


@router.delete("/enrollment-tokens/{token_id}")
def revoke_enrollment_token(token_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    _ephemeral_tokens.pop(token_id, None)
    return {"ok": _service().revoke_enrollment_token(token_id, user.username)}


@router.get("/enrollment-tokens/{token_id}/script")
def enrollment_script(token_id: str, request: Request, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_HOSTS_MANAGE))):
    cached = _ephemeral_tokens.get(token_id)
    if not cached or cached[1] < time.time():
        api_error(410, "ENROLLMENT_SECRET_UNAVAILABLE", "The one-time script secret is no longer available; create a new token")
    return PlainTextResponse(_service().enrollment_script(token_id, cached[0], str(request.base_url).rstrip("/")), media_type="text/x-shellscript", headers={"Content-Disposition": f'attachment; filename="webnas-enroll-{token_id}.sh"', "Cache-Control": "no-store"})


@router.post("/enroll")
def enroll(payload: EnrollmentClaimInput, authorization: str = Header(default="", max_length=512)):
    if not authorization.startswith("Bearer ") or len(authorization) > 512:
        api_error(401, "ENROLLMENT_TOKEN_REQUIRED", "A valid enrollment token is required")
    item = _service().claim_enrollment_token(authorization[7:], payload.model_dump())
    if not item:
        api_error(401, "ENROLLMENT_TOKEN_INVALID", "Enrollment token is invalid, expired, used or does not allow this hostname")
    return {"id": item["id"], "registration_status": item["registration_status"], "approved": item["approved"], "fingerprint_status": item["fingerprint_status"]}


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
    return {"hosts": saved, "imported": len(saved)}


@router.get("/credentials")
def credentials(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CREDENTIALS_VIEW))):
    return _service().credentials()


@router.post("/credentials")
def create_credential(payload: CredentialInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CREDENTIALS_MANAGE))):
    return _service().save_credential(payload, user.username)


@router.put("/credentials/{credential_id}")
def update_credential(credential_id: str, payload: CredentialInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CREDENTIALS_MANAGE))):
    return _service().save_credential(payload, user.username, credential_id)


@router.delete("/credentials/{credential_id}")
def delete_credential(credential_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CREDENTIALS_MANAGE))):
    return {"ok": _service().delete_credential(credential_id)}


@router.get("/repositories")
def repositories(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_REPOSITORIES_VIEW))):
    return _service().repositories()


@router.post("/repositories")
def create_repository(payload: RepositoryInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_REPOSITORIES_MANAGE))):
    return _service().save_repository(payload, user.username)


@router.put("/repositories/{repository_id}")
def update_repository(repository_id: str, payload: RepositoryInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_REPOSITORIES_MANAGE))):
    return _service().save_repository(payload, user.username, repository_id)


@router.delete("/repositories/{repository_id}")
def delete_repository(repository_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_REPOSITORIES_MANAGE))):
    return {"ok": _service().delete_repository(repository_id)}


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
    return {"repository": _service()._get("repositories", repository_id), "commit": commit}


@router.get("/power-profiles")
def power_profiles(user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_POWER_VIEW))):
    return _service().power_profiles()


@router.post("/power-profiles")
def create_power_profile(payload: PowerProfileInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE))):
    return _service().save_power_profile(payload, user.username)


@router.put("/power-profiles/{profile_id}")
def update_power_profile(profile_id: str, payload: PowerProfileInput, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE))):
    return _service().save_power_profile(payload, user.username, profile_id)


@router.delete("/power-profiles/{profile_id}")
def delete_power_profile(profile_id: str, user: SessionUser = Depends(require_permission(Permission.HOSTS_MANAGER_CONFIGURE))):
    return {"ok": _service().delete_power_profile(profile_id)}


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
    return {"schema_version": 1, "checks": checks}


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
    manifest = json.dumps({"module": "hosts-manager", "schema_version": 1, "created_at": time.time(), "description": payload.description, "includes_credentials": payload.include_credentials})
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
    return {"ok": True}
