from __future__ import annotations

from http import HTTPStatus
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ...activity import ActivityCategory, ActivityStatus, record_activity
from ...identity.permissions import authorize
from ...rbac import current_user, mutating_user
from ...security import SessionUser
from .connection import DirectoryConnectionError
from .models import (
    BulkOperationRequest,
    ConnectionInput,
    CsvImportRequest,
    DirectoryCreateRequest,
    DirectoryMoveRequest,
    DirectoryUpdateRequest,
    LdifImportRequest,
    MembershipRequest,
    PasswordResetRequest,
    SearchRequest,
)
from .providers import ProviderOperationError, UnsupportedDirectoryOperation
from .rbac import *  # noqa: F403
from .service import service


router = APIRouter(prefix="/api/modules/ldap-manager", tags=["ldap-manager"])


def _allow(user: SessionUser, permission: str) -> None:
    authorize(user, permission)


def _audit(user: SessionUser, connection_id: str, action: str, target: str = "", *, ok: bool = True, details: dict[str, Any] | None = None) -> None:
    record_activity(
        ActivityCategory.module,
        action,
        user.username,
        target=target or connection_id,
        status=ActivityStatus.success if ok else ActivityStatus.failure,
        details={"connection": connection_id, **(details or {})},
        source="ldap-manager",
    )


def _translated(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except LookupError as error:
        raise HTTPException(HTTPStatus.NOT_FOUND, str(error)) from error
    except UnsupportedDirectoryOperation as error:
        raise HTTPException(HTTPStatus.NOT_IMPLEMENTED, {"code": error.code, "message": str(error)}) from error
    except ProviderOperationError as error:
        raise HTTPException(HTTPStatus.CONFLICT, {"code": error.code, "message": str(error)}) from error
    except DirectoryConnectionError as error:
        raise HTTPException(HTTPStatus.BAD_GATEWAY, {"code": error.code, "stage": error.stage, "message": "LDAP directory is unavailable"}) from error
    except ValueError as error:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error


@router.get("/connections")
def connections(user: SessionUser = Depends(current_user)):
    _allow(user, LDAP_CONNECTIONS_READ)  # noqa: F405
    return {"items": service().connections()}


@router.post("/connections")
def create_connection(payload: ConnectionInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_CONNECTIONS_MANAGE)  # noqa: F405
    try:
        result = service().save_connection(payload, user.username)
    except ValueError as error:
        raise HTTPException(HTTPStatus.UNPROCESSABLE_ENTITY, str(error)) from error
    _audit(user, result["id"], "ldap.connection.create", result["name"], details={"directory_type": result["directory_type"]})
    return result


@router.get("/connections/{connection_id}")
def connection(connection_id: str, user: SessionUser = Depends(current_user)):
    _allow(user, LDAP_CONNECTIONS_READ)  # noqa: F405
    return _translated(lambda: service().connection(connection_id))


@router.put("/connections/{connection_id}")
def update_connection(connection_id: str, payload: ConnectionInput, user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_CONNECTIONS_MANAGE)  # noqa: F405
    result = _translated(lambda: service().save_connection(payload, user.username, connection_id))
    _audit(user, connection_id, "ldap.connection.update", result["name"], details={"directory_type": result["directory_type"]})
    return result


@router.delete("/connections/{connection_id}")
def delete_connection(connection_id: str, user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_CONNECTIONS_MANAGE)  # noqa: F405
    result = _translated(lambda: service().delete_connection(connection_id, user.username))
    _audit(user, connection_id, "ldap.connection.delete", result["name"])
    return {"ok": True}


@router.get("/connections/{connection_id}/overview")
def overview(connection_id: str, user: SessionUser = Depends(current_user)):
    _allow(user, LDAP_CONNECTIONS_READ)  # noqa: F405
    return _translated(lambda: service().dashboard(connection_id))


@router.post("/connections/{connection_id}/search")
def search(connection_id: str, payload: SearchRequest, user: SessionUser = Depends(current_user)):
    _allow(user, LDAP_DIRECTORY_READ)  # noqa: F405
    return _translated(lambda: service().search(connection_id, payload))


@router.get("/connections/{connection_id}/directory")
def directory_entry(connection_id: str, dn: str = Query(..., max_length=2048), user: SessionUser = Depends(current_user)):
    _allow(user, LDAP_DIRECTORY_READ)  # noqa: F405
    return _translated(lambda: service().directory_entry(connection_id, dn))


@router.get("/connections/{connection_id}/users")
def users(connection_id: str, search: str = Query(default="", max_length=256), page_size: int = Query(default=100, ge=1, le=1000), cookie: str = Query(default="", max_length=8192), user: SessionUser = Depends(current_user)):
    _allow(user, LDAP_USERS_READ)  # noqa: F405
    return _translated(lambda: service().users(connection_id, search, page_size, cookie))


@router.post("/connections/{connection_id}/users")
def create_user(connection_id: str, payload: DirectoryCreateRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_USERS_CREATE)  # noqa: F405
    result = _translated(lambda: service().create_entry(connection_id, payload))
    _audit(user, connection_id, "ldap.user.create", payload.dn)
    return result


@router.put("/connections/{connection_id}/users")
def update_user(connection_id: str, payload: DirectoryUpdateRequest, dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_USERS_UPDATE)  # noqa: F405
    result = _translated(lambda: service().update_entry(connection_id, dn, payload))
    _audit(user, connection_id, "ldap.user.update", dn, details={"attributes": sorted(payload.attributes), "deleted_attributes": sorted(payload.delete_attributes)})
    return result


@router.delete("/connections/{connection_id}/users")
def delete_user(connection_id: str, dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_USERS_DELETE)  # noqa: F405
    _translated(lambda: service().delete_entry(connection_id, dn))
    _audit(user, connection_id, "ldap.user.delete", dn)
    return {"ok": True}


@router.post("/connections/{connection_id}/users/password-reset")
def reset_user_password(connection_id: str, payload: PasswordResetRequest, dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_USERS_PASSWORD_RESET)  # noqa: F405
    _translated(lambda: service().reset_password(connection_id, dn, payload.new_password, payload.force_change))
    _audit(user, connection_id, "ldap.user.password_reset", dn, details={"force_change": payload.force_change})
    return {"ok": True}


@router.post("/connections/{connection_id}/users/enable")
def enable_user(connection_id: str, dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_USERS_UPDATE)  # noqa: F405
    _translated(lambda: service().set_enabled(connection_id, dn, True))
    _audit(user, connection_id, "ldap.user.enable", dn)
    return {"ok": True}


@router.post("/connections/{connection_id}/users/disable")
def disable_user(connection_id: str, dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_USERS_UPDATE)  # noqa: F405
    _translated(lambda: service().set_enabled(connection_id, dn, False))
    _audit(user, connection_id, "ldap.user.disable", dn)
    return {"ok": True}


@router.post("/connections/{connection_id}/users/unlock")
def unlock_user(connection_id: str, dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_USERS_UPDATE)  # noqa: F405
    _translated(lambda: service().unlock(connection_id, dn))
    _audit(user, connection_id, "ldap.user.unlock", dn)
    return {"ok": True}


@router.post("/connections/{connection_id}/users/move")
def move_user(connection_id: str, payload: DirectoryMoveRequest, dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_USERS_UPDATE)  # noqa: F405
    result = _translated(lambda: service().move_entry(connection_id, dn, payload))
    _audit(user, connection_id, "ldap.user.move", dn, details={"new_dn": result})
    return {"dn": result}


@router.get("/connections/{connection_id}/groups")
def groups(connection_id: str, search: str = Query(default="", max_length=256), page_size: int = Query(default=100, ge=1, le=1000), cookie: str = Query(default="", max_length=8192), user: SessionUser = Depends(current_user)):
    _allow(user, LDAP_GROUPS_READ)  # noqa: F405
    return _translated(lambda: service().groups(connection_id, search, page_size, cookie))


@router.post("/connections/{connection_id}/groups")
def create_group(connection_id: str, payload: DirectoryCreateRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_GROUPS_CREATE)  # noqa: F405
    result = _translated(lambda: service().create_entry(connection_id, payload))
    _audit(user, connection_id, "ldap.group.create", payload.dn)
    return result


@router.put("/connections/{connection_id}/groups")
def update_group(connection_id: str, payload: DirectoryUpdateRequest, dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_GROUPS_UPDATE)  # noqa: F405
    result = _translated(lambda: service().update_entry(connection_id, dn, payload))
    _audit(user, connection_id, "ldap.group.update", dn, details={"attributes": sorted(payload.attributes)})
    return result


@router.delete("/connections/{connection_id}/groups")
def delete_group(connection_id: str, dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_GROUPS_DELETE)  # noqa: F405
    _translated(lambda: service().delete_entry(connection_id, dn))
    _audit(user, connection_id, "ldap.group.delete", dn)
    return {"ok": True}


@router.post("/connections/{connection_id}/groups/members")
def add_group_member(connection_id: str, payload: MembershipRequest, group_dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_GROUPS_UPDATE)  # noqa: F405
    _translated(lambda: service().add_member(connection_id, group_dn, payload.member_dn))
    _audit(user, connection_id, "ldap.group.membership.add", group_dn, details={"member": payload.member_dn})
    return {"ok": True}


@router.delete("/connections/{connection_id}/groups/members")
def remove_group_member(connection_id: str, member_dn: str = Query(..., max_length=2048), group_dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_GROUPS_UPDATE)  # noqa: F405
    _translated(lambda: service().remove_member(connection_id, group_dn, member_dn))
    _audit(user, connection_id, "ldap.group.membership.remove", group_dn, details={"member": member_dn})
    return {"ok": True}


@router.get("/connections/{connection_id}/ous")
def ous(connection_id: str, page_size: int = Query(default=200, ge=1, le=1000), cookie: str = Query(default="", max_length=8192), user: SessionUser = Depends(current_user)):
    _allow(user, LDAP_OU_READ)  # noqa: F405
    return _translated(lambda: service().ous(connection_id, page_size, cookie))


@router.post("/connections/{connection_id}/ous")
def create_ou(connection_id: str, payload: DirectoryCreateRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_OU_MANAGE)  # noqa: F405
    result = _translated(lambda: service().create_entry(connection_id, payload))
    _audit(user, connection_id, "ldap.ou.create", payload.dn)
    return result


@router.put("/connections/{connection_id}/ous")
def update_ou(connection_id: str, payload: DirectoryUpdateRequest, dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_OU_MANAGE)  # noqa: F405
    result = _translated(lambda: service().update_entry(connection_id, dn, payload))
    _audit(user, connection_id, "ldap.ou.update", dn)
    return result


@router.post("/connections/{connection_id}/ous/move")
def move_ou(connection_id: str, payload: DirectoryMoveRequest, dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_OU_MANAGE)  # noqa: F405
    result = _translated(lambda: service().move_entry(connection_id, dn, payload))
    _audit(user, connection_id, "ldap.ou.move", dn, details={"new_dn": result})
    return {"dn": result}


@router.delete("/connections/{connection_id}/ous")
def delete_ou(connection_id: str, dn: str = Query(..., max_length=2048), user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_OU_MANAGE)  # noqa: F405
    _translated(lambda: service().delete_entry(connection_id, dn))
    _audit(user, connection_id, "ldap.ou.delete", dn)
    return {"ok": True}


@router.get("/connections/{connection_id}/schema")
def schema(connection_id: str, user: SessionUser = Depends(current_user)):
    _allow(user, LDAP_SCHEMA_READ)  # noqa: F405
    return _translated(lambda: service().schema(connection_id))


@router.get("/connections/{connection_id}/diagnostics")
def diagnostics(connection_id: str, user: SessionUser = Depends(current_user)):
    _allow(user, LDAP_DIAGNOSTICS_READ)  # noqa: F405
    result = _translated(lambda: service().diagnostics(connection_id))
    _audit(user, connection_id, "ldap.diagnostics.read", details={"overall": result.get("overall"), "endpoint": result.get("endpoint")})
    return result


@router.get("/connections/{connection_id}/export/csv", response_class=PlainTextResponse)
def export_csv(connection_id: str, kind: str = Query(default="users", pattern="^(users|groups)$"), user: SessionUser = Depends(current_user)):
    _allow(user, LDAP_EXPORT)  # noqa: F405
    result = _translated(lambda: service().export_csv(connection_id, kind))
    _audit(user, connection_id, "ldap.export.csv", details={"kind": kind})
    return result


@router.post("/connections/{connection_id}/export/ldif", response_class=PlainTextResponse)
def export_ldif(connection_id: str, payload: SearchRequest, user: SessionUser = Depends(current_user)):
    _allow(user, LDAP_EXPORT)  # noqa: F405
    result = _translated(lambda: service().export_ldif(connection_id, payload))
    _audit(user, connection_id, "ldap.export.ldif", details={"base_dn": payload.base_dn or "connection-base", "scope": payload.scope})
    return result


@router.post("/connections/{connection_id}/import/csv")
def import_csv(connection_id: str, payload: CsvImportRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_IMPORT)  # noqa: F405
    result = _translated(lambda: service().import_csv(connection_id, payload))
    _audit(user, connection_id, "ldap.import.csv", details={"dry_run": payload.dry_run, "planned": result.get("planned", 0), "created": result.get("created", 0), "failed": result.get("failed", 0)})
    return result


@router.post("/connections/{connection_id}/import/ldif")
def import_ldif(connection_id: str, payload: LdifImportRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_IMPORT)  # noqa: F405
    result = _translated(lambda: service().import_ldif(connection_id, payload))
    _audit(user, connection_id, "ldap.import.ldif", details={"dry_run": payload.dry_run, "planned": result.get("planned", 0), "created": result.get("created", 0), "failed": result.get("failed", 0)})
    return result


@router.post("/connections/{connection_id}/bulk")
def bulk(connection_id: str, payload: BulkOperationRequest, user: SessionUser = Depends(mutating_user)):
    _allow(user, LDAP_BULK_EXECUTE)  # noqa: F405
    result = _translated(lambda: service().bulk(connection_id, payload))
    _audit(user, connection_id, "ldap.bulk.execute", details={"action": payload.action, "dry_run": payload.dry_run, "planned": result.get("planned", 0), "succeeded": result.get("succeeded", 0), "failed": result.get("failed", 0)})
    return result
