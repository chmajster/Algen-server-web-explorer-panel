from __future__ import annotations

import csv
import io
import socket
import ssl
import time
from functools import lru_cache
from typing import Any, Callable

from .connection import DirectoryConnectionError, bind, close
from .models import BulkOperationRequest, ConnectionInput, CsvImportRequest, DirectoryCreateRequest, DirectoryMoveRequest, DirectoryUpdateRequest, LdifImportRequest, SearchRequest
from .providers import ProviderOperationError, provider_for
from .repository import LdapManagerRepository, repository
from .security import validate_dn


_SENSITIVE_EXPORT_ATTRIBUTES = {"userpassword", "unicodepwd", "authpassword", "krbprincipalkey", "sambantpassword", "sambalmpassword"}

_ENTRY_KIND_CLASSES = {
    "user": {"person", "organizationalperson", "inetorgperson", "user", "posixaccount"},
    "group": {"group", "groupofnames", "groupofuniquenames", "posixgroup"},
    "ou": {"organizationalunit", "container"},
}


class LdapManagerService:
    def __init__(self, store: LdapManagerRepository) -> None:
        self.store = store

    def connections(self) -> list[dict[str, Any]]:
        return self.store.list()

    def connection(self, connection_id: str) -> dict[str, Any]:
        return self.store.get(connection_id)

    def save_connection(self, payload: ConnectionInput, actor: str, connection_id: str | None = None) -> dict[str, Any]:
        return self.store.save(payload, actor, connection_id)

    def delete_connection(self, connection_id: str, actor: str) -> dict[str, Any]:
        return self.store.delete(connection_id, actor)

    def _config(self, connection_id: str) -> dict[str, Any]:
        return self.store.get(connection_id, include_secret_id=True)

    def _provider(self, connection_id: str):
        return provider_for(self._config(connection_id))

    @staticmethod
    def _object_classes(entry: dict[str, Any]) -> set[str]:
        attributes = entry.get("attributes") if isinstance(entry.get("attributes"), dict) else {}
        raw = next((value for name, value in attributes.items() if str(name).casefold() == "objectclass"), [])
        values = raw if isinstance(raw, list) else [raw]
        return {str(value).casefold() for value in values if str(value).strip()}

    @classmethod
    def _assert_entry_kind(cls, provider: Any, dn: str, kind: str) -> None:
        expected = _ENTRY_KIND_CLASSES[kind]
        if not (cls._object_classes(provider.entry(dn)) & expected):
            raise ValueError(f"LDAP entry is not a {kind} object")

    @staticmethod
    def _assert_payload_kind(payload: DirectoryCreateRequest, kind: str) -> None:
        classes = {str(value).casefold() for value in payload.object_classes}
        if not (classes & _ENTRY_KIND_CLASSES[kind]):
            raise ValueError(f"LDAP objectClass set is not valid for {kind} creation")

    @staticmethod
    def _collect_pages(fetch_page: Callable[[str], dict[str, Any]], *, initial_cookie: str = "") -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cookie = initial_cookie
        seen = {cookie} if cookie else set()
        while True:
            page = fetch_page(cookie)
            page_items = page.get("items")
            if not isinstance(page_items, list):
                raise ProviderOperationError("LDAP_PAGING_FAILED", "LDAP provider returned an invalid page")
            items.extend(item for item in page_items if isinstance(item, dict))
            if len(items) > 100_000:
                raise ValueError("LDAP export is limited to 100000 entries")
            next_cookie = str(page.get("cookie") or "")
            if not next_cookie:
                return items
            if next_cookie in seen:
                raise ProviderOperationError("LDAP_PAGING_FAILED", "LDAP provider repeated a paging cookie")
            seen.add(next_cookie)
            cookie = next_cookie

    def dashboard(self, connection_id: str) -> dict[str, Any]:
        config = self._config(connection_id)
        started = time.monotonic()
        bound = None
        try:
            bound = bind(config, purpose="ldap-manager-dashboard")
            latency_ms = round((time.monotonic() - started) * 1000, 1)
            endpoint = bound.endpoint
            status = "online"
        except DirectoryConnectionError as error:
            latency_ms = None
            endpoint = error.endpoint
            status = "offline"
        finally:
            close(bound)
        result: dict[str, Any] = {
            "connection": self.store.get(connection_id),
            "status": status,
            "primary_server": endpoint,
            "latency_ms": latency_ms,
            "users": None,
            "groups": None,
            "organizational_units": None,
            "disabled_users": None,
            "locked_users": None,
            "password_expired_users": None,
            "capabilities": provider_for(config).capabilities,
            "recent_operations": [],
        }
        if status != "online":
            return result
        provider = provider_for(config)
        try:
            users = provider.users(page_size=1000)
            groups = provider.groups(page_size=1000)
            ous = provider.ous(page_size=1000)
            result["users"] = len(users["items"])
            result["groups"] = len(groups["items"])
            result["organizational_units"] = len(ous["items"])
            if config.get("directory_type") == "active_directory":
                disabled = locked = expired = 0
                for item in users["items"]:
                    attrs = item.get("attributes", {})
                    try:
                        uac = int(attrs.get("userAccountControl") or 0)
                    except (TypeError, ValueError):
                        uac = 0
                    disabled += int(bool(uac & 0x0002))
                    try:
                        locked += int(int(attrs.get("lockoutTime") or 0) > 0)
                        expired += int(int(attrs.get("pwdLastSet") or 1) == 0)
                    except (TypeError, ValueError):
                        pass
                result.update({"disabled_users": disabled, "locked_users": locked, "password_expired_users": expired})
        except Exception:
            # Dashboard counts are advisory. An unsupported subtree or ACL must
            # not turn a healthy connection into an application error.
            pass
        return result

    def search(self, connection_id: str, payload: SearchRequest) -> dict[str, Any]:
        return self._provider(connection_id).search(
            base_dn=payload.base_dn,
            scope=payload.scope,
            ldap_filter=payload.ldap_filter,
            attributes=payload.attributes,
            page_size=payload.page_size,
            cookie=payload.cookie,
        )

    def directory_entry(self, connection_id: str, dn: str) -> dict[str, Any]:
        return self._provider(connection_id).entry(dn)

    def users(self, connection_id: str, search: str, page_size: int, cookie: str) -> dict[str, Any]:
        return self._provider(connection_id).users(search=search, page_size=page_size, cookie=cookie)

    def groups(self, connection_id: str, search: str, page_size: int, cookie: str) -> dict[str, Any]:
        return self._provider(connection_id).groups(search=search, page_size=page_size, cookie=cookie)

    def ous(self, connection_id: str, page_size: int, cookie: str) -> dict[str, Any]:
        return self._provider(connection_id).ous(page_size=page_size, cookie=cookie)

    def create_entry(self, connection_id: str, payload: DirectoryCreateRequest, *, kind: str) -> dict[str, Any]:
        self._assert_payload_kind(payload, kind)
        return self._provider(connection_id).create(payload.dn, payload.object_classes, payload.attributes)

    def update_entry(self, connection_id: str, dn: str, payload: DirectoryUpdateRequest, *, kind: str) -> dict[str, Any]:
        provider = self._provider(connection_id)
        self._assert_entry_kind(provider, dn, kind)
        return provider.update(dn, payload.attributes, payload.delete_attributes)

    def delete_entry(self, connection_id: str, dn: str, *, kind: str) -> None:
        provider = self._provider(connection_id)
        self._assert_entry_kind(provider, dn, kind)
        provider.delete(dn)

    def move_entry(self, connection_id: str, dn: str, payload: DirectoryMoveRequest, *, kind: str) -> str:
        provider = self._provider(connection_id)
        self._assert_entry_kind(provider, dn, kind)
        return provider.move(dn, payload.new_rdn, payload.new_superior)

    def reset_password(self, connection_id: str, dn: str, password: str, force_change: bool) -> None:
        provider = self._provider(connection_id)
        self._assert_entry_kind(provider, dn, "user")
        provider.reset_password(dn, password, force_change)

    def set_enabled(self, connection_id: str, dn: str, enabled: bool) -> None:
        provider = self._provider(connection_id)
        self._assert_entry_kind(provider, dn, "user")
        provider.set_enabled(dn, enabled)

    def unlock(self, connection_id: str, dn: str) -> None:
        provider = self._provider(connection_id)
        self._assert_entry_kind(provider, dn, "user")
        provider.unlock(dn)

    def add_member(self, connection_id: str, group_dn: str, member_dn: str) -> None:
        provider = self._provider(connection_id)
        self._assert_entry_kind(provider, group_dn, "group")
        provider.add_member(group_dn, member_dn)

    def remove_member(self, connection_id: str, group_dn: str, member_dn: str) -> None:
        provider = self._provider(connection_id)
        self._assert_entry_kind(provider, group_dn, "group")
        provider.remove_member(group_dn, member_dn)

    def schema(self, connection_id: str) -> dict[str, Any]:
        return self._provider(connection_id).schema()

    @staticmethod
    def _certificate(config: dict[str, Any], host: str, port: int) -> dict[str, Any]:
        if config.get("security_mode") != "ldaps":
            return {"available": False, "reason": "Certificate details are collected directly for LDAPS; StartTLS is verified by the LDAP bind."}
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        ca = str(config.get("ca_certificate") or "")
        if ca:
            context.load_verify_locations(cadata=ca)
        if not bool(config.get("verify_tls", True)):
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=float(config.get("connect_timeout") or 5.0)) as raw:
            with context.wrap_socket(raw, server_hostname=host if context.check_hostname else None) as secure:
                cert = secure.getpeercert()
        if not cert:
            return {"available": False}
        not_after = str(cert.get("notAfter") or "")
        days_remaining = None
        if not_after:
            try:
                days_remaining = int((ssl.cert_time_to_seconds(not_after) - time.time()) // 86400)
            except ValueError:
                pass
        return {
            "available": True,
            "subject": cert.get("subject", []),
            "issuer": cert.get("issuer", []),
            "valid_from": cert.get("notBefore", ""),
            "valid_until": not_after,
            "san": cert.get("subjectAltName", []),
            "days_remaining": days_remaining,
        }

    def diagnostics(self, connection_id: str) -> dict[str, Any]:
        config = self._config(connection_id)
        steps: list[dict[str, Any]] = []
        selected = ""
        certificate: dict[str, Any] = {"available": False}
        for item in sorted(config.get("servers") or [], key=lambda value: int(value.get("priority") or 10)):
            host = str(item.get("host") or "")
            port = int(item.get("port") or 389)
            label = f"{host}:{port}"
            try:
                addresses = sorted({str(answer[4][0]).split("%", 1)[0] for answer in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
                steps.append({"name": "dns", "status": "ok", "detail": f"{host} -> {', '.join(addresses)}"})
            except OSError:
                steps.append({"name": "dns", "status": "error", "detail": label})
                continue
            try:
                with socket.create_connection((host, port), timeout=float(config.get("connect_timeout") or 5.0)):
                    pass
                steps.append({"name": "tcp", "status": "ok", "detail": label})
            except OSError:
                steps.append({"name": "tcp", "status": "error", "detail": label})
                continue
            try:
                certificate = self._certificate(config, host, port)
                if config.get("security_mode") in {"ldaps", "starttls"}:
                    steps.append({"name": "tls", "status": "ok", "detail": str(config.get("security_mode"))})
                    steps.append({"name": "certificate", "status": "ok" if config.get("verify_tls", True) else "warning", "detail": "verification enabled" if config.get("verify_tls", True) else "verification disabled"})
            except ssl.SSLError:
                steps.append({"name": "certificate", "status": "error", "detail": label})
                continue
            selected = label
            break
        try:
            root = provider_for(config).root_dse()
            selected = str(root.get("endpoint") or selected)
            attrs = root.get("entry", {}).get("attributes", {})
            steps.append({"name": "bind", "status": "ok", "detail": selected})
            steps.append({"name": "rootDSE", "status": "ok" if attrs else "warning", "detail": "available" if attrs else "empty"})
            base = provider_for(config).search(base_dn=str(config["base_dn"]), scope="base", ldap_filter="(objectClass=*)", attributes=["objectClass"], page_size=1)
            steps.append({"name": "base_dn", "status": "ok" if base["items"] else "warning", "detail": str(config["base_dn"])})
            supported = {
                "supported_controls": attrs.get("supportedControl", []),
                "supported_ldap_versions": attrs.get("supportedLDAPVersion", []),
                "vendor_name": attrs.get("vendorName", ""),
                "vendor_version": attrs.get("vendorVersion", ""),
                "naming_contexts": attrs.get("namingContexts", []),
            }
            if config.get("directory_type") == "active_directory":
                supported["domain"] = attrs.get("defaultNamingContext", "")
                supported["forest"] = attrs.get("rootDomainNamingContext", "")
        except DirectoryConnectionError as error:
            steps.append({"name": error.stage, "status": "error", "detail": error.code})
            supported = {}
        except (ProviderOperationError, LookupError, ValueError) as error:
            steps.append({"name": "search", "status": "error", "detail": getattr(error, "code", type(error).__name__)})
            supported = {}
        overall = "healthy" if steps and all(item["status"] in {"ok", "warning"} for item in steps) else "unhealthy"
        return {"overall": overall, "endpoint": selected, "directory_type": config.get("directory_type"), "steps": steps, "certificate": certificate, **supported}

    def export_csv(self, connection_id: str, kind: str) -> str:
        provider = self._provider(connection_id)
        fetch_page = (
            (lambda cookie: provider.users(page_size=1000, cookie=cookie))
            if kind == "users"
            else (lambda cookie: provider.groups(page_size=1000, cookie=cookie))
        )
        items = self._collect_pages(fetch_page)
        attribute_names = sorted({name for item in items for name in item.get("attributes", {}) if name.casefold() not in _SENSITIVE_EXPORT_ATTRIBUTES})
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["dn", *attribute_names])
        for item in items:
            attrs = item.get("attributes", {})
            row: list[str] = [str(item.get("dn") or "")]
            for name in attribute_names:
                value = attrs.get(name, "")
                row.append(";".join(str(part) for part in value) if isinstance(value, list) else str(value or ""))
            writer.writerow(row)
        return buffer.getvalue()

    def export_ldif(self, connection_id: str, payload: SearchRequest) -> str:
        provider = self._provider(connection_id)
        items = self._collect_pages(
            lambda cookie: provider.search(
                base_dn=payload.base_dn,
                scope=payload.scope,
                ldap_filter=payload.ldap_filter,
                attributes=payload.attributes,
                page_size=payload.page_size,
                cookie=cookie,
            ),
            initial_cookie=payload.cookie,
        )
        lines: list[str] = []
        for item in items:
            lines.append(f"dn: {item['dn']}")
            for name, raw in item.get("attributes", {}).items():
                if name.casefold() in _SENSITIVE_EXPORT_ATTRIBUTES:
                    continue
                values = raw if isinstance(raw, list) else [raw]
                for value in values:
                    if isinstance(value, dict):
                        continue
                    text = str(value or "").replace("\r", "").replace("\n", " ")
                    lines.append(f"{name}: {text}")
            lines.append("")
        return "\n".join(lines)

    def import_csv(self, connection_id: str, payload: CsvImportRequest) -> dict[str, Any]:
        reader = csv.DictReader(io.StringIO(payload.csv_text))
        plan: list[dict[str, Any]] = []
        for index, row in enumerate(reader, start=2):
            dn = str(row.pop("dn", "") or "").strip()
            if not dn and payload.default_parent_dn:
                uid = str(row.get("uid") or row.get("cn") or "").strip()
                if uid:
                    dn = f"uid={uid},{payload.default_parent_dn}"
            validate_dn(dn)
            classes = [item for item in str(row.pop("objectClass", "inetOrgPerson") or "inetOrgPerson").split(";") if item]
            attrs = {name: value.split(";") if ";" in value else value for name, value in row.items() if value not in (None, "")}
            plan.append({"row": index, "dn": dn, "object_classes": classes, "attributes": attrs})
            if len(plan) > 5000:
                raise ValueError("CSV import is limited to 5000 entries")
        if payload.dry_run:
            return {"dry_run": True, "planned": len(plan), "items": plan[:200]}
        created = 0
        errors: list[dict[str, Any]] = []
        provider = self._provider(connection_id)
        for item in plan:
            try:
                provider.create(item["dn"], item["object_classes"], item["attributes"])
                created += 1
            except Exception as error:
                errors.append({"row": item["row"], "dn": item["dn"], "error": getattr(error, "code", type(error).__name__)})
        return {"dry_run": False, "planned": len(plan), "created": created, "failed": len(errors), "errors": errors[:200]}

    def import_ldif(self, connection_id: str, payload: LdifImportRequest) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        current: dict[str, Any] = {"attributes": {}}
        for raw in [*payload.ldif_text.splitlines(), ""]:
            line = raw.rstrip("\r")
            if not line:
                if current.get("dn"):
                    records.append(current)
                current = {"attributes": {}}
                continue
            if line.startswith(" "):
                raise ValueError("Folded LDIF lines are not supported by the safe importer")
            name, separator, value = line.partition(":")
            if not separator or name in {"changetype", "control"}:
                if name in {"changetype", "control"}:
                    raise ValueError("LDIF change records are not accepted by this importer")
                continue
            value = value.lstrip()
            if name.casefold() == "dn":
                current["dn"] = validate_dn(value)
            elif name.casefold() == "objectclass":
                current.setdefault("object_classes", []).append(value)
            elif name.casefold() not in _SENSITIVE_EXPORT_ATTRIBUTES:
                attrs = current["attributes"]
                attrs.setdefault(name, []).append(value)
            if len(records) > 5000:
                raise ValueError("LDIF import is limited to 5000 entries")
        if payload.dry_run:
            return {"dry_run": True, "planned": len(records), "items": records[:200]}
        provider = self._provider(connection_id)
        created = 0
        errors: list[dict[str, Any]] = []
        for item in records:
            try:
                provider.create(item["dn"], item.get("object_classes") or ["top"], item["attributes"])
                created += 1
            except Exception as error:
                errors.append({"dn": item.get("dn", ""), "error": getattr(error, "code", type(error).__name__)})
        return {"dry_run": False, "planned": len(records), "created": created, "failed": len(errors), "errors": errors[:200]}

    def bulk(self, connection_id: str, payload: BulkOperationRequest) -> dict[str, Any]:
        plan = [{"dn": validate_dn(dn), "action": payload.action} for dn in payload.target_dns]
        if payload.action in {"add_to_group", "remove_from_group"}:
            validate_dn(payload.group_dn)
        if payload.action == "move":
            validate_dn(payload.new_parent_dn)
        if payload.dry_run:
            return {"dry_run": True, "planned": len(plan), "items": plan[:500]}
        provider = self._provider(connection_id)
        succeeded = 0
        errors: list[dict[str, Any]] = []
        for item in plan:
            dn = item["dn"]
            try:
                if payload.action == "add_to_group":
                    provider.add_member(payload.group_dn, dn)
                elif payload.action == "remove_from_group":
                    provider.remove_member(payload.group_dn, dn)
                elif payload.action == "enable":
                    provider.set_enabled(dn, True)
                elif payload.action == "disable":
                    provider.set_enabled(dn, False)
                elif payload.action == "move":
                    rdn = dn.split(",", 1)[0]
                    provider.move(dn, rdn, payload.new_parent_dn)
                elif payload.action == "export":
                    provider.entry(dn)
                succeeded += 1
            except Exception as error:
                errors.append({"dn": dn, "error": getattr(error, "code", type(error).__name__)})
        return {"dry_run": False, "planned": len(plan), "succeeded": succeeded, "failed": len(errors), "errors": errors[:500]}


@lru_cache(maxsize=1)
def service() -> LdapManagerService:
    return LdapManagerService(repository())
