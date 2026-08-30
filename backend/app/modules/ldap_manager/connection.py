from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from typing import Any

from ldap3 import ALL, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException, LDAPInvalidCredentialsResult, LDAPStartTLSError

from ...modules.secrets_manager.service import service as secrets_service
from .repository import SECRET_MODULE
from .security import assert_safe_target, normalize_host


@dataclass(frozen=True, slots=True)
class BoundDirectory:
    connection: Connection
    endpoint: str


class DirectoryConnectionError(RuntimeError):
    def __init__(self, stage: str, code: str, endpoint: str = "") -> None:
        super().__init__(stage)
        self.stage = stage
        self.code = code
        self.endpoint = endpoint


def _bind_password(config: dict[str, Any], purpose: str) -> str:
    secret_id = str(config.get("bind_secret_id") or "")
    if not secret_id:
        raise DirectoryConnectionError("configuration", "LDAP_MANAGER_BIND_SECRET_MISSING")
    try:
        secret = secrets_service().verified_secret(secret_id, module_id=SECRET_MODULE, purpose=purpose)
    except Exception as error:
        raise DirectoryConnectionError("configuration", "LDAP_MANAGER_BIND_SECRET_UNAVAILABLE") from error
    value = str(secret.get("secret") or "")
    if not value:
        raise DirectoryConnectionError("configuration", "LDAP_MANAGER_BIND_SECRET_EMPTY")
    return value


def bind(config: dict[str, Any], *, purpose: str = "ldap-manager-operation", get_info: Any = ALL) -> BoundDirectory:
    password = _bind_password(config, purpose)
    servers = sorted(config.get("servers") or [], key=lambda item: (int(item.get("priority") or 10), str(item.get("host") or "")))
    if not servers:
        raise DirectoryConnectionError("configuration", "LDAP_MANAGER_SERVER_MISSING")
    last: DirectoryConnectionError | None = None
    for item in servers:
        host = normalize_host(str(item.get("host") or ""))
        assert_safe_target(host)
        port = int(item.get("port") or 389)
        endpoint = f"{host}:{port}"
        try:
            # Resolve before handing the hostname to ldap3 so link-local or
            # metadata addresses hidden behind DNS are rejected as well.
            for answer in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
                assert_safe_target(str(answer[4][0]).split("%", 1)[0])
            tls = Tls(
                validate=ssl.CERT_REQUIRED if bool(config.get("verify_tls", True)) else ssl.CERT_NONE,
                ca_certs_data=str(config.get("ca_certificate") or "") or None,
            )
            server = Server(
                host,
                port=port,
                use_ssl=config.get("security_mode") == "ldaps",
                tls=tls,
                connect_timeout=float(config.get("connect_timeout") or 5.0),
                get_info=get_info,
            )
            connection = Connection(
                server,
                user=str(config.get("bind_dn") or ""),
                password=password,
                receive_timeout=float(config.get("operation_timeout") or 15.0),
                raise_exceptions=True,
            )
            connection.open()
            if config.get("security_mode") == "starttls":
                connection.start_tls()
            connection.bind()
            return BoundDirectory(connection, endpoint)
        except LDAPInvalidCredentialsResult as error:
            last = DirectoryConnectionError("bind", "LDAP_MANAGER_BIND_FAILED", endpoint)
            last.__cause__ = error
        except (LDAPStartTLSError, ssl.SSLError) as error:
            last = DirectoryConnectionError("tls", "LDAP_MANAGER_TLS_FAILED", endpoint)
            last.__cause__ = error
        except (LDAPException, OSError, socket.error) as error:
            last = DirectoryConnectionError("connect", "LDAP_MANAGER_CONNECT_FAILED", endpoint)
            last.__cause__ = error
    raise last or DirectoryConnectionError("connect", "LDAP_MANAGER_CONNECT_FAILED")


def close(bound: BoundDirectory | None) -> None:
    if bound is None:
        return
    try:
        bound.connection.unbind()
    except Exception:
        pass
