from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from .activity import ActivityCategory, ActivityStatus, record_activity
from .identity.service import access_profile
from .ldap_authentication import (
    LdapAccessPolicyInput,
    LdapAuthenticationSettingsInput,
    LdapDiagnosticsRequest,
    LdapGroupMappingInput,
    LdapRefreshRequest,
    diagnostics,
    refresh_identity_policy,
    repository,
)
from .security import SessionUser, get_session_user, invalidate_provider_sessions, require_csrf


router = APIRouter(prefix="/api/settings/authentication/ldap", tags=["settings", "authentication"])


def _admin_user(request: Request, *, mutate: bool) -> SessionUser:
    user = get_session_user(request)
    if mutate:
        require_csrf(request, user)
    profile = access_profile(user.username)
    if not bool(profile.get("is_admin")):
        raise HTTPException(HTTPStatus.FORBIDDEN, "Administrator access required")
    return user


def admin_read(request: Request) -> SessionUser:
    return _admin_user(request, mutate=False)


def admin_write(request: Request) -> SessionUser:
    return _admin_user(request, mutate=True)


def _audit(user: SessionUser, action: str, *, status: ActivityStatus = ActivityStatus.success, details: dict | None = None, target: str = "ldap-authentication") -> None:
    record_activity(
        ActivityCategory.administration,
        action,
        user.username,
        target=target,
        status=status,
        details=details or {},
        source="settings",
    )


@router.get("")
def get_ldap_settings(user: SessionUser = Depends(admin_read)):
    _ = user
    return repository().settings()


@router.put("")
def save_ldap_settings(payload: LdapAuthenticationSettingsInput, user: SessionUser = Depends(admin_write)):
    store = repository()
    try:
        if payload.enabled:
            # Persist the candidate disabled, validate the exact persisted state,
            # and only then flip the activation bit. A bad LDAP edit can never
            # lock the administrator out by becoming active without preflight.
            store.save(payload, user.username, enabled=False)
            policy = store.access_policy()
            if policy.get("mode") == "mapped_groups" and not store.mappings():
                raise ValueError("At least one LDAP group mapping is required by the current access policy")
            result = diagnostics("")
            if result.get("overall") == "unhealthy":
                _audit(user, "ldap.authentication.preflight", status=ActivityStatus.failure, details={"overall": "unhealthy"})
                raise ValueError("LDAP Authentication preflight failed; configuration was saved disabled")
            saved = store.set_enabled(True, user.username)
        else:
            saved = store.save(payload, user.username, enabled=False)
            invalidate_provider_sessions("ldap")
    except (ValueError, ValidationError) as error:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
    _audit(
        user,
        "ldap.authentication.settings.updated",
        details={
            "enabled": bool(saved.get("enabled")),
            "security_mode": saved.get("security_mode"),
            "server_count": len(saved.get("servers") or []),
            "failover_strategy": saved.get("failover_strategy"),
        },
    )
    return saved


@router.get("/servers")
def get_servers(user: SessionUser = Depends(admin_read)):
    _ = user
    return {"items": repository().servers()}


@router.get("/group-mappings")
def get_group_mappings(user: SessionUser = Depends(admin_read)):
    _ = user
    return {"items": repository().mappings()}


@router.post("/group-mappings")
def create_group_mapping(payload: LdapGroupMappingInput, user: SessionUser = Depends(admin_write)):
    try:
        result = repository().save_mapping(payload, user.username)
    except (ValueError, ValidationError) as error:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
    invalidate_provider_sessions("ldap")
    _audit(user, "ldap.authentication.group_mapping.created", target=result["group_dn"], details={"role": result["role"]})
    return result


@router.put("/group-mappings/{mapping_id}")
def update_group_mapping(mapping_id: str, payload: LdapGroupMappingInput, user: SessionUser = Depends(admin_write)):
    try:
        result = repository().save_mapping(payload, user.username, mapping_id)
    except LookupError as error:
        raise HTTPException(HTTPStatus.NOT_FOUND, str(error)) from error
    except (ValueError, ValidationError) as error:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
    invalidate_provider_sessions("ldap")
    _audit(user, "ldap.authentication.group_mapping.updated", target=result["group_dn"], details={"role": result["role"]})
    return result


@router.delete("/group-mappings/{mapping_id}")
def delete_group_mapping(mapping_id: str, user: SessionUser = Depends(admin_write)):
    if not repository().delete_mapping(mapping_id):
        raise HTTPException(HTTPStatus.NOT_FOUND, "LDAP group mapping not found")
    invalidate_provider_sessions("ldap")
    _audit(user, "ldap.authentication.group_mapping.deleted", target=mapping_id)
    return {"ok": True}


@router.get("/access-policy")
def get_access_policy(user: SessionUser = Depends(admin_read)):
    _ = user
    return repository().access_policy()


@router.put("/access-policy")
def save_access_policy(payload: LdapAccessPolicyInput, user: SessionUser = Depends(admin_write)):
    if payload.mode == "mapped_groups" and not repository().mappings():
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, "Mapped-groups access requires at least one LDAP group mapping")
    result = repository().save_access_policy(payload, user.username)
    invalidate_provider_sessions("ldap")
    _audit(user, "ldap.authentication.access_policy.updated", details={"mode": result["mode"], "allow_groups": len(result["allow_groups"]), "deny_groups": len(result["deny_groups"])})
    return result


@router.post("/diagnostics")
def run_diagnostics(payload: LdapDiagnosticsRequest, user: SessionUser = Depends(admin_write)):
    result = diagnostics(payload.username.strip())
    _audit(user, "ldap.authentication.diagnostics", status=ActivityStatus.success if result.get("overall") == "healthy" else ActivityStatus.failure, details={"overall": result.get("overall"), "server": result.get("server")})
    return result


@router.post("/test")
def test_saved_ldap_settings(user: SessionUser = Depends(admin_write)):
    result = diagnostics("")
    ok = result.get("overall") != "unhealthy"
    _audit(user, "ldap.connection.tested", status=ActivityStatus.success if ok else ActivityStatus.failure, details={"overall": result.get("overall"), "server": result.get("server")})
    if not ok:
        raise HTTPException(
            HTTPStatus.BAD_GATEWAY,
            {"code": "LDAP_PREFLIGHT_FAILED", "message": "LDAP Authentication connection test failed.", "diagnostics": result},
        )
    return {"ok": True, "message": "LDAP Authentication connection is healthy.", "diagnostics": result}


@router.post("/refresh")
def refresh_mapping(payload: LdapRefreshRequest, user: SessionUser = Depends(admin_write)):
    try:
        result = refresh_identity_policy(payload.username)
    except LookupError as error:
        raise HTTPException(HTTPStatus.NOT_FOUND, str(error)) from error
    _audit(user, "ldap.authentication.identity_refreshed", target=payload.username, details={"allowed": bool(result.get("allowed"))})
    return result
