from __future__ import annotations

import pwd
import socket
import ssl
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ldap3 import BASE, SUBTREE, Connection
from ldap3.core.exceptions import LDAPException, LDAPInvalidCredentialsResult, LDAPStartTLSError
from ldap3.utils.conv import escape_filter_chars

from ..audit import logger
from ..auth import is_local_passwd_user
from ..config import get_config
from ..identity.models import Role, UserPolicy
from ..identity.permissions import normalize_permissions
from ..identity.repository import repository as identity_repository
from ..modules.secrets_manager import service as secrets_service
from .connection import LdapEndpoint, connect, endpoints, resolve_host
from .repository import AUTH_SECRET_MODULE, LdapAuthenticationRepository, repository


LDAP_USERNAME_MAX = 64


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    username: str
    provider: Literal["ldap"]
    identity_id: str
    home: str
    display_name: str = ""
    email: str = ""


class LdapAuthenticationError(Exception):
    pass


class LdapInvalidCredentials(LdapAuthenticationError):
    pass


class LdapServiceUnavailable(LdapAuthenticationError):
    def __init__(self, stage: str, code: str = "LDAP_UNAVAILABLE", server: str = "") -> None:
        super().__init__(stage)
        self.stage = stage
        self.code = code
        self.server = server


class LdapConfigurationError(LdapAuthenticationError):
    pass


def _attribute(entry: dict[str, Any], name: str) -> Any:
    if not name:
        return ""
    attributes = entry.get("attributes")
    value: Any = None
    if isinstance(attributes, dict):
        value = attributes.get(name)
        if value is None:
            folded = name.casefold()
            value = next((candidate for key, candidate in attributes.items() if str(key).casefold() == folded), None)
    if value is None:
        raw_attributes = entry.get("raw_attributes")
        if isinstance(raw_attributes, dict):
            value = raw_attributes.get(name)
            if value is None:
                folded = name.casefold()
                value = next((candidate for key, candidate in raw_attributes.items() if str(key).casefold() == folded), None)
    if isinstance(value, (list, tuple, set)) and len(value) == 1:
        return next(iter(value))
    return value


def _text_attribute(entry: dict[str, Any], name: str) -> str:
    value = _attribute(entry, name)
    if isinstance(value, (list, tuple, set)):
        value = next(iter(value), "")
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8").strip()
        except UnicodeDecodeError:
            return value.hex()
    return str(value or "").strip()


def _values(entry: dict[str, Any], name: str) -> list[str]:
    value = _attribute(entry, name)
    raw = value if isinstance(value, list) else [value] if value not in (None, "") else []
    return [str(item) for item in raw if str(item).strip()]


def ldap_user_search_filter(template: str, username: str) -> str:
    return template.replace("{username}", escape_filter_chars(username))


def ldap_group_search_filter(template: str, username: str, dn: str) -> str:
    return template.replace("{username}", escape_filter_chars(username)).replace("{dn}", escape_filter_chars(dn))


def _validate_username(username: str) -> str:
    value = username.strip()
    if not value or len(value) > LDAP_USERNAME_MAX or any(character in value for character in ("\x00", "/", "\\", "\n", "\r")):
        raise LdapInvalidCredentials("invalid username")
    return value


def _bind_password(settings: dict[str, Any], *, purpose: str) -> str:
    secret_id = str(settings.get("bind_secret_id") or "")
    if not secret_id:
        raise LdapConfigurationError("LDAP Authentication bind password is not configured")
    try:
        secret = secrets_service().verified_secret(secret_id, module_id=AUTH_SECRET_MODULE, purpose=purpose)
    except Exception as error:
        raise LdapConfigurationError("LDAP Authentication bind password is unavailable") from error
    password = str(secret.get("secret") or "")
    if not password:
        raise LdapConfigurationError("LDAP Authentication bind password is empty")
    return password


def _close(connection: Connection | None) -> None:
    if connection is None:
        return
    try:
        connection.unbind()
    except Exception as error:
        logger.debug("ldap_auth_unbind_failed error=%s", type(error).__name__)


def _immutable_id(settings: dict[str, Any], entry: dict[str, Any]) -> str:
    configured = str(settings.get("immutable_id_attribute") or "").strip()
    directory_type = str(settings.get("directory_type") or "auto")
    candidates = [configured] if configured else []
    if directory_type in {"active_directory", "auto"}:
        candidates.append("objectGUID")
    if directory_type in {"freeipa", "auto"}:
        candidates.extend(["ipaUniqueID", "entryUUID"])
    candidates.append("entryUUID")
    seen: set[str] = set()
    for name in candidates:
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        raw = _attribute(entry, name)
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        if isinstance(raw, bytes):
            if name.casefold() == "objectguid" and len(raw) == 16:
                return str(uuid.UUID(bytes_le=raw))
            return raw.hex()
        value = str(raw or "").strip()
        if value:
            return value
    raise LdapConfigurationError("LDAP identity has no stable immutable identifier (objectGUID/entryUUID)")


def _posix_identity(username: str) -> pwd.struct_passwd:
    try:
        account = pwd.getpwnam(username)
    except KeyError as error:
        raise LdapServiceUnavailable("identity", "LDAP_POSIX_IDENTITY_UNAVAILABLE") from error
    cfg = get_config()
    if account.pw_uid == 0 or account.pw_uid < cfg.security.system_uid_threshold:
        raise LdapServiceUnavailable("identity", "LDAP_POSIX_IDENTITY_UNSAFE")
    home = str(account.pw_dir or "").strip()
    if not home or not Path(home).is_absolute():
        raise LdapServiceUnavailable("identity", "LDAP_POSIX_HOME_INVALID")
    return account


def _assert_namespace_available(store: LdapAuthenticationRepository, username: str, immutable_id: str) -> None:
    if is_local_passwd_user(username):
        raise LdapInvalidCredentials("local/PAM identity collision")
    known = store.identity_by_username(username)
    if known and str(known["immutable_id"]) != immutable_id and not str(known["immutable_id"]).startswith("legacy:"):
        raise LdapInvalidCredentials("LDAP identity collision")
    if identity_repository().user_policy(username) is not None and known is None:
        raise LdapInvalidCredentials("local RBAC identity collision")


def _search_user(connection: Connection, settings: dict[str, Any], username: str) -> dict[str, Any]:
    attributes = list(dict.fromkeys(filter(None, [
        str(settings.get("username_attribute") or "uid"),
        str(settings.get("immutable_id_attribute") or ""),
        "objectGUID",
        "entryUUID",
        "ipaUniqueID",
        str(settings.get("display_name_attribute") or "displayName"),
        str(settings.get("email_attribute") or "mail"),
        str(settings.get("group_membership_attribute") or "memberOf"),
        "uidNumber",
        "gidNumber",
        "homeDirectory",
    ])))
    try:
        searched = connection.search(
            search_base=str(settings.get("user_search_base") or settings.get("base_dn") or ""),
            search_filter=ldap_user_search_filter(str(settings.get("user_search_filter") or "(uid={username})"), username),
            search_scope=SUBTREE,
            attributes=attributes,
            size_limit=2,
            time_limit=max(1, int(float(settings.get("operation_timeout") or 10))),
        )
    except LDAPException as error:
        raise LdapServiceUnavailable("search", "LDAP_SEARCH_FAILED") from error
    if not searched:
        raise LdapServiceUnavailable("search", "LDAP_SEARCH_FAILED")
    entries = [item for item in connection.response if isinstance(item, dict) and item.get("type") == "searchResEntry"]
    if len(entries) != 1:
        raise LdapInvalidCredentials("LDAP identity was not unique")
    entry = entries[0]
    username_attribute = str(settings.get("username_attribute") or "uid")
    returned = _text_attribute(entry, username_attribute)
    if returned:
        if returned.casefold() != username.casefold():
            raise LdapInvalidCredentials("LDAP identity does not match requested username")
    else:
        template = str(settings.get("user_search_filter") or "(uid={username})").strip()
        exact_filter = f"({username_attribute}={{username}})"
        if template.casefold() != exact_filter.casefold():
            raise LdapInvalidCredentials("LDAP identity does not match requested username")
    if not str(entry.get("dn") or ""):
        raise LdapInvalidCredentials("LDAP identity has no DN")
    return entry


def _groups_for_entry(connection: Connection, settings: dict[str, Any], username: str, entry: dict[str, Any]) -> list[str]:
    group_attribute = str(settings.get("group_membership_attribute") or "memberOf")
    groups = _values(entry, group_attribute)
    base = str(settings.get("group_search_base") or "").strip()
    template = str(settings.get("group_search_filter") or "").strip()
    dn = str(entry.get("dn") or "")
    if base and template:
        try:
            searched = connection.search(
                search_base=base,
                search_filter=ldap_group_search_filter(template, username, dn),
                search_scope=SUBTREE,
                attributes=["distinguishedName", "cn"],
                size_limit=1000,
                time_limit=max(1, int(float(settings.get("operation_timeout") or 10))),
            )
        except LDAPException as error:
            raise LdapServiceUnavailable("groups", "LDAP_GROUP_SEARCH_FAILED") from error
        if searched:
            groups.extend(
                str(item.get("dn"))
                for item in connection.response
                if isinstance(item, dict) and item.get("type") == "searchResEntry" and item.get("dn")
            )
    result: list[str] = []
    seen: set[str] = set()
    for raw in groups:
        value = raw.strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _evaluate_access(store: LdapAuthenticationRepository, groups: list[str]) -> tuple[bool, list[dict[str, Any]]]:
    group_keys = {item.casefold() for item in groups}
    policy = store.access_policy()
    deny = {str(item).casefold() for item in policy.get("deny_groups") or []}
    if group_keys & deny:
        return False, []
    allowed_groups = {str(item).casefold() for item in policy.get("allow_groups") or []}
    if allowed_groups and not (group_keys & allowed_groups):
        return False, []
    mappings = [item for item in store.mappings() if str(item["group_dn"]).casefold() in group_keys]
    if policy.get("mode") == "mapped_groups" and not mappings:
        return False, []
    return True, mappings


def _apply_rbac(username: str, mappings: list[dict[str, Any]]) -> dict[str, Any]:
    policies = identity_repository()
    if not mappings:
        existing = policies.user_policy(username)
        if existing and str(existing.updated_by or "") == "ldap-group-mapping":
            policies.delete_user_policy(username, "ldap-group-mapping")
            existing = None
        if existing:
            return existing.model_dump(mode="json")
        return UserPolicy(username=username).model_dump(mode="json")
    ordered = sorted(mappings, key=lambda item: (int(item.get("priority") or 100), str(item.get("group_dn") or "").casefold()))
    role = Role(str(ordered[0].get("role") or Role.user.value))
    allow = normalize_permissions([str(permission) for item in ordered for permission in item.get("allow") or []])
    deny = normalize_permissions([str(permission) for item in ordered for permission in item.get("deny") or []])
    deny_set = set(deny)
    allow = [permission for permission in allow if permission not in deny_set]
    policy = UserPolicy(username=username, role=role, allow=allow, deny=deny)
    return policies.save_user_policy(policy, "ldap-group-mapping", action="ldap_group_mapping_refresh").model_dump(mode="json")


def _service_connection(settings: dict[str, Any], bind_password: str) -> tuple[Connection, LdapEndpoint]:
    candidates = endpoints(settings)
    if not candidates:
        raise LdapConfigurationError("No LDAP Authentication server is configured")
    failures: list[LdapServiceUnavailable] = []
    for endpoint in candidates:
        try:
            return connect(settings, endpoint, user=str(settings.get("bind_dn") or ""), password=bind_password), endpoint
        except LDAPInvalidCredentialsResult:
            failures.append(LdapServiceUnavailable("bind", "LDAP_BIND_FAILED", endpoint.label))
            logger.warning("ldap_auth_service_bind_failed server=%s", endpoint.label)
        except (LDAPStartTLSError, ssl.SSLError) as error:
            failures.append(LdapServiceUnavailable("tls", "LDAP_TLS_FAILED", endpoint.label))
            logger.warning("ldap_auth_tls_failed server=%s error=%s", endpoint.label, type(error).__name__)
        except (LDAPException, OSError, socket.error) as error:
            failures.append(LdapServiceUnavailable("connect", "LDAP_CONNECT_FAILED", endpoint.label))
            logger.warning("ldap_auth_connect_failed server=%s error=%s", endpoint.label, type(error).__name__)
    if failures:
        raise failures[-1]
    raise LdapServiceUnavailable("connect", "LDAP_CONNECT_FAILED")


def authenticate_ldap(username: str, password: str) -> AuthenticatedIdentity:
    username = _validate_username(username)
    if not password:
        raise LdapInvalidCredentials("invalid credentials")
    store = repository()
    settings = store.settings(include_secret_id=True)
    if not bool(settings.get("enabled")):
        raise LdapConfigurationError("LDAP Authentication is disabled")
    bind_password = _bind_password(settings, purpose="ldap-authentication")
    service_connection: Connection | None = None
    user_connection: Connection | None = None
    try:
        service_connection, endpoint = _service_connection(settings, bind_password)
        entry = _search_user(service_connection, settings, username)
        dn = str(entry.get("dn") or "")
        immutable_id = _immutable_id(settings, entry)
        _assert_namespace_available(store, username, immutable_id)
        groups = _groups_for_entry(service_connection, settings, username, entry)
        allowed, mappings = _evaluate_access(store, groups)
        if not allowed:
            raise LdapInvalidCredentials("LDAP access policy denied login")
        try:
            user_connection = connect(settings, endpoint, user=dn, password=password)
        except LDAPInvalidCredentialsResult as error:
            raise LdapInvalidCredentials("invalid credentials") from error
        except (LDAPStartTLSError, ssl.SSLError) as error:
            raise LdapServiceUnavailable("tls", "LDAP_TLS_FAILED", endpoint.label) from error
        except (LDAPException, OSError) as error:
            raise LdapServiceUnavailable("connect", "LDAP_CONNECT_FAILED", endpoint.label) from error

        account = _posix_identity(username)
        _apply_rbac(username, mappings)
        identity = store.remember_identity(
            immutable_id,
            username,
            dn,
            display_name=_text_attribute(entry, str(settings.get("display_name_attribute") or "displayName")),
            email=_text_attribute(entry, str(settings.get("email_attribute") or "mail")),
            uid=int(account.pw_uid),
            gid=int(account.pw_gid),
            home=str(account.pw_dir),
            groups=groups,
            logged_in=True,
        )
        return AuthenticatedIdentity(
            username=username,
            provider="ldap",
            identity_id=immutable_id,
            home=str(identity.get("home") or account.pw_dir),
            display_name=str(identity.get("display_name") or ""),
            email=str(identity.get("email") or ""),
        )
    finally:
        _close(user_connection)
        _close(service_connection)


def ldap_enabled() -> bool:
    try:
        return bool(repository().settings().get("enabled"))
    except Exception as error:
        logger.error("ldap_auth_settings_unavailable error=%s", type(error).__name__)
        return False


def ldap_home(username: str) -> str | None:
    try:
        return repository().home(username)
    except Exception:
        return None


def is_ldap_identity(username: str) -> bool:
    try:
        return repository().identity_by_username(username) is not None
    except Exception:
        return False


def _refresh_groups(identity: dict[str, Any], settings: dict[str, Any]) -> list[str]:
    bind_password = _bind_password(settings, purpose="ldap-group-refresh")
    connection: Connection | None = None
    try:
        connection, _endpoint = _service_connection(settings, bind_password)
        dn = str(identity.get("dn") or "")
        attributes = [str(settings.get("group_membership_attribute") or "memberOf"), str(settings.get("username_attribute") or "uid")]
        searched = connection.search(
            search_base=dn,
            search_filter="(objectClass=*)",
            search_scope=BASE,
            attributes=attributes,
            size_limit=1,
            time_limit=max(1, int(float(settings.get("operation_timeout") or 10))),
        )
        entries = [item for item in connection.response if isinstance(item, dict) and item.get("type") == "searchResEntry"] if searched else []
        if len(entries) != 1:
            raise LdapServiceUnavailable("groups", "LDAP_IDENTITY_REFRESH_FAILED")
        return _groups_for_entry(connection, settings, str(identity.get("username") or ""), entries[0])
    except LdapAuthenticationError:
        raise
    except LDAPException as error:
        raise LdapServiceUnavailable("groups", "LDAP_GROUP_SEARCH_FAILED") from error
    finally:
        _close(connection)


def validate_ldap_session(identity_id: str, username: str, *, force_refresh: bool = False) -> bool:
    store = repository()
    identity = store.identity_by_id(identity_id) if identity_id else store.identity_by_username(username)
    if not identity or str(identity.get("username") or "").casefold() != username.casefold():
        return False
    settings = store.settings(include_secret_id=True)
    if not bool(settings.get("enabled")):
        return False
    groups = [str(item) for item in identity.get("groups") or []]
    ttl = int(settings.get("group_cache_ttl_seconds") or 0)
    stale = force_refresh or ttl == 0 or float(identity.get("groups_refreshed_at") or 0) + ttl <= time.time()
    if stale:
        try:
            groups = _refresh_groups(identity, settings)
        except LdapAuthenticationError:
            return False
        store.update_groups(str(identity["immutable_id"]), groups)
    allowed, mappings = _evaluate_access(store, groups)
    if not allowed:
        return False
    _apply_rbac(username, mappings)
    return True


def refresh_identity_policy(username: str) -> dict[str, Any]:
    identity = repository().identity_by_username(username)
    if not identity:
        raise LookupError("LDAP identity not found")
    allowed = validate_ldap_session(str(identity["immutable_id"]), username, force_refresh=True)
    return {"username": username, "identity_id": str(identity["immutable_id"]), "allowed": allowed}


def diagnostics(username: str = "") -> dict[str, Any]:
    store = repository()
    settings = store.settings(include_secret_id=True)
    steps: list[dict[str, Any]] = []
    selected = ""
    candidates = endpoints(settings)
    if not candidates:
        return {"overall": "unhealthy", "server": "", "steps": [{"name": "configuration", "status": "error", "detail": "No LDAP server configured"}], "identity": {}}
    connection: Connection | None = None
    bind_password: str
    try:
        bind_password = _bind_password(settings, purpose="ldap-diagnostics")
    except LdapConfigurationError:
        return {"overall": "unhealthy", "server": "", "steps": [{"name": "service_bind", "status": "error", "detail": "Bind password is not configured"}], "identity": {}}

    for endpoint in candidates:
        try:
            addresses = resolve_host(endpoint)
            steps.append({"name": "dns_resolution", "status": "ok", "detail": f"{endpoint.host} -> {', '.join(addresses)}"})
        except Exception:
            steps.append({"name": "dns_resolution", "status": "error", "detail": endpoint.host})
            continue
        try:
            with socket.create_connection((endpoint.host, endpoint.port), timeout=float(settings.get("connect_timeout") or 5.0)):
                pass
            steps.append({"name": "tcp_connection", "status": "ok", "detail": endpoint.label})
        except OSError:
            steps.append({"name": "tcp_connection", "status": "error", "detail": endpoint.label})
            continue
        try:
            connection = connect(settings, endpoint, user=str(settings.get("bind_dn") or ""), password=bind_password)
            selected = endpoint.label
            steps.append({"name": "tls_handshake", "status": "ok", "detail": str(settings.get("security_mode"))})
            steps.append({"name": "certificate_verification", "status": "ok" if settings.get("verify_tls", True) else "warning", "detail": "enabled" if settings.get("verify_tls", True) else "disabled"})
            steps.append({"name": "service_bind", "status": "ok", "detail": str(settings.get("bind_dn") or "")})
            break
        except LDAPInvalidCredentialsResult:
            steps.append({"name": "service_bind", "status": "error", "detail": endpoint.label})
        except (LDAPStartTLSError, ssl.SSLError):
            steps.append({"name": "tls_handshake", "status": "error", "detail": endpoint.label})
        except (LDAPException, OSError):
            steps.append({"name": "service_bind", "status": "error", "detail": endpoint.label})
        finally:
            if not selected:
                _close(connection)
                connection = None
    if connection is None:
        return {"overall": "unhealthy", "server": selected, "steps": steps, "identity": {}}

    identity_info: dict[str, Any] = {}
    try:
        base_ok = connection.search(
            search_base=str(settings.get("base_dn") or ""), search_filter="(objectClass=*)", search_scope=BASE,
            attributes=["objectClass"], size_limit=1, time_limit=max(1, int(float(settings.get("operation_timeout") or 10))),
        )
        steps.append({"name": "base_dn_search", "status": "ok" if base_ok else "error", "detail": str(settings.get("base_dn") or "")})
        if username:
            entry = _search_user(connection, settings, _validate_username(username))
            steps.append({"name": "user_search", "status": "ok", "detail": str(entry.get("dn") or "")})
            groups = _groups_for_entry(connection, settings, username, entry)
            steps.append({"name": "group_lookup", "status": "ok", "detail": f"{len(groups)} groups"})
            allowed, mappings = _evaluate_access(store, groups)
            steps.append({"name": "rbac_mapping", "status": "ok" if allowed else "error", "detail": str(mappings[0]["role"] if mappings else "user")})
            try:
                account = _posix_identity(username)
                identity_info = {"uid": int(account.pw_uid), "gid": int(account.pw_gid), "home": str(account.pw_dir)}
                steps.append({"name": "nss_user_resolution", "status": "ok", "detail": username})
                steps.append({"name": "posix_uid_gid", "status": "ok", "detail": f"{account.pw_uid}:{account.pw_gid}"})
                steps.append({"name": "home", "status": "ok", "detail": str(account.pw_dir)})
            except LdapServiceUnavailable as error:
                steps.append({"name": "nss_user_resolution", "status": "error", "detail": error.code})
    except LdapInvalidCredentials:
        steps.append({"name": "user_search", "status": "error", "detail": "No unique matching user"})
    except LdapServiceUnavailable as error:
        steps.append({"name": error.stage, "status": "error", "detail": error.code})
    finally:
        _close(connection)
    overall = "healthy" if all(step["status"] in {"ok", "skipped"} for step in steps) else "degraded" if any(step["status"] == "ok" for step in steps) else "unhealthy"
    return {"overall": overall, "server": selected, "steps": steps, "identity": identity_info}
