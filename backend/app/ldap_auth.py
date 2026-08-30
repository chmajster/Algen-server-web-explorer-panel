from __future__ import annotations

import os
import pwd
import re
import sqlite3
import ssl
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from ldap3 import NONE, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException, LDAPInvalidCredentialsResult, LDAPStartTLSError
from ldap3.utils.conv import escape_filter_chars
from pydantic import BaseModel, Field, field_validator, model_validator

from .audit import logger
from .config import get_config
from .identity.repository import repository as identity_repository
from .modules.secrets_manager.models import SecretInput
from .modules.secrets_manager.service import service as secrets_service
from .sqlite_utils import ClosingConnection


LDAP_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}\$?$", re.IGNORECASE)
LDAP_BIND_SECRET_NAME = "__webnas_ldap_bind_password__"
LDAP_SECRET_MODULE = "settings"

LdapSecurityMode = Literal["ldap", "starttls", "ldaps"]
AuthProvider = Literal["pam", "ldap"]


class LdapSettingsInput(BaseModel):
    enabled: bool = False
    server: str = Field(default="", max_length=512)
    port: int = Field(default=389, ge=1, le=65535)
    security_mode: LdapSecurityMode = "starttls"
    verify_tls: bool = True
    connect_timeout: float = Field(default=5.0, ge=0.5, le=60.0)
    operation_timeout: float = Field(default=10.0, ge=0.5, le=120.0)
    base_dn: str = Field(default="", max_length=2048)
    user_search_base: str = Field(default="", max_length=2048)
    user_search_filter: str = Field(default="(uid={username})", max_length=2048)
    username_attribute: str = Field(default="uid", max_length=128)
    bind_dn: str = Field(default="", max_length=2048)
    bind_password: str = Field(default="", max_length=32768)
    clear_bind_password: bool = False
    display_name_attribute: str = Field(default="displayName", max_length=128)
    email_attribute: str = Field(default="mail", max_length=128)

    @field_validator(
        "server",
        "base_dn",
        "user_search_base",
        "user_search_filter",
        "username_attribute",
        "bind_dn",
        "display_name_attribute",
        "email_attribute",
    )
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_configuration(self) -> "LdapSettingsInput":
        if self.server:
            parsed = urlparse(self.server if "://" in self.server else f"//{self.server}")
            if parsed.scheme and parsed.scheme not in {"ldap", "ldaps"}:
                raise ValueError("LDAP server URI must use ldap:// or ldaps://")
            if parsed.scheme == "ldaps" and self.security_mode != "ldaps":
                raise ValueError("ldaps:// requires LDAPS security mode")
            if parsed.scheme == "ldap" and self.security_mode == "ldaps":
                raise ValueError("ldap:// cannot be used with LDAPS security mode")
            if not parsed.hostname:
                raise ValueError("LDAP server is invalid")
        if "{username}" not in self.user_search_filter:
            raise ValueError("LDAP user search filter must contain {username}")
        if self.user_search_filter.count("{username}") != 1:
            raise ValueError("LDAP user search filter must contain {username} exactly once")
        if self.clear_bind_password and self.bind_password:
            raise ValueError("bind_password and clear_bind_password cannot be used together")
        if self.enabled:
            required = {
                "server": self.server,
                "base_dn": self.base_dn,
                "user_search_base": self.user_search_base,
                "user_search_filter": self.user_search_filter,
                "username_attribute": self.username_attribute,
                "bind_dn": self.bind_dn,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(f"LDAP configuration is incomplete: {', '.join(missing)}")
        return self


@dataclass(frozen=True, slots=True)
class LdapSettings:
    enabled: bool
    server: str
    port: int
    security_mode: LdapSecurityMode
    verify_tls: bool
    connect_timeout: float
    operation_timeout: float
    base_dn: str
    user_search_base: str
    user_search_filter: str
    username_attribute: str
    bind_dn: str
    bind_secret_id: str
    display_name_attribute: str
    email_attribute: str

    @property
    def bind_password_configured(self) -> bool:
        return bool(self.bind_secret_id)

    def public_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "server": self.server,
            "port": self.port,
            "security_mode": self.security_mode,
            "verify_tls": self.verify_tls,
            "connect_timeout": self.connect_timeout,
            "operation_timeout": self.operation_timeout,
            "base_dn": self.base_dn,
            "user_search_base": self.user_search_base,
            "user_search_filter": self.user_search_filter,
            "username_attribute": self.username_attribute,
            "bind_dn": self.bind_dn,
            "bind_password_configured": self.bind_password_configured,
            "display_name_attribute": self.display_name_attribute,
            "email_attribute": self.email_attribute,
        }


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    username: str
    provider: AuthProvider
    home: str
    display_name: str = ""
    email: str = ""


class LdapAuthenticationError(Exception):
    pass


class LdapInvalidCredentials(LdapAuthenticationError):
    pass


class LdapServiceUnavailable(LdapAuthenticationError):
    def __init__(self, stage: str, code: str = "LDAP_UNAVAILABLE") -> None:
        super().__init__(stage)
        self.stage = stage
        self.code = code


class LdapConfigurationError(LdapAuthenticationError):
    pass


class LdapSettingsRepository:
    def __init__(self, path: Path | None = None) -> None:
        root = Path(get_config().paths.data_dir).resolve(strict=False)
        self.path = path or root / "ldap-auth.sqlite3"
        self._lock = threading.RLock()
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ldap_settings(
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    enabled INTEGER NOT NULL DEFAULT 0,
                    server TEXT NOT NULL DEFAULT '',
                    port INTEGER NOT NULL DEFAULT 389,
                    security_mode TEXT NOT NULL DEFAULT 'starttls',
                    verify_tls INTEGER NOT NULL DEFAULT 1,
                    connect_timeout REAL NOT NULL DEFAULT 5,
                    operation_timeout REAL NOT NULL DEFAULT 10,
                    base_dn TEXT NOT NULL DEFAULT '',
                    user_search_base TEXT NOT NULL DEFAULT '',
                    user_search_filter TEXT NOT NULL DEFAULT '(uid={username})',
                    username_attribute TEXT NOT NULL DEFAULT 'uid',
                    bind_dn TEXT NOT NULL DEFAULT '',
                    bind_secret_id TEXT NOT NULL DEFAULT '',
                    display_name_attribute TEXT NOT NULL DEFAULT 'displayName',
                    email_attribute TEXT NOT NULL DEFAULT 'mail',
                    updated_at REAL NOT NULL DEFAULT 0,
                    updated_by TEXT NOT NULL DEFAULT ''
                );
                INSERT OR IGNORE INTO ldap_settings(id) VALUES(1);
                CREATE TABLE IF NOT EXISTS ldap_identities(
                    username_key TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    dn TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    home TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_login_at REAL NOT NULL
                );
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _settings(row: sqlite3.Row) -> LdapSettings:
        return LdapSettings(
            enabled=bool(row["enabled"]),
            server=str(row["server"]),
            port=int(row["port"]),
            security_mode=str(row["security_mode"]),  # type: ignore[arg-type]
            verify_tls=bool(row["verify_tls"]),
            connect_timeout=float(row["connect_timeout"]),
            operation_timeout=float(row["operation_timeout"]),
            base_dn=str(row["base_dn"]),
            user_search_base=str(row["user_search_base"]),
            user_search_filter=str(row["user_search_filter"]),
            username_attribute=str(row["username_attribute"]),
            bind_dn=str(row["bind_dn"]),
            bind_secret_id=str(row["bind_secret_id"]),
            display_name_attribute=str(row["display_name_attribute"]),
            email_attribute=str(row["email_attribute"]),
        )

    def get(self) -> LdapSettings:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM ldap_settings WHERE id=1").fetchone()
        if not row:
            raise RuntimeError("LDAP settings row is unavailable")
        return self._settings(row)

    def save(self, payload: LdapSettingsInput, actor: str) -> LdapSettings:
        current = self.get()
        secret_id = current.bind_secret_id
        if payload.clear_bind_password:
            if payload.enabled:
                raise ValueError("Disable LDAP before clearing the bind password")
            if secret_id:
                secrets_service().delete(secret_id, actor)
                secret_id = ""
        elif payload.bind_password:
            secret = secrets_service().save(
                SecretInput(
                    name=LDAP_BIND_SECRET_NAME,
                    type="generic_secret",
                    secret=payload.bind_password,
                    description="WebNAS LDAP service-account bind credential",
                    shared_with=[LDAP_SECRET_MODULE],
                ),
                actor,
                secret_id or None,
            )
            secret_id = str(secret["id"])
        elif secret_id:
            # Secrets Manager preserves the existing encrypted value when an
            # update omits ``secret``. This lets the UI save other LDAP fields
            # without ever round-tripping the bind password through the browser.
            secrets_service().save(
                SecretInput(
                    name=LDAP_BIND_SECRET_NAME,
                    type="generic_secret",
                    description="WebNAS LDAP service-account bind credential",
                    shared_with=[LDAP_SECRET_MODULE],
                ),
                actor,
                secret_id,
            )

        if payload.enabled and not secret_id:
            raise ValueError("LDAP bind password is required before LDAP can be enabled")

        with self._lock, self.connect() as connection:
            connection.execute(
                """
                UPDATE ldap_settings SET
                    enabled=?,server=?,port=?,security_mode=?,verify_tls=?,
                    connect_timeout=?,operation_timeout=?,base_dn=?,user_search_base=?,
                    user_search_filter=?,username_attribute=?,bind_dn=?,bind_secret_id=?,
                    display_name_attribute=?,email_attribute=?,updated_at=?,updated_by=?
                WHERE id=1
                """,
                (
                    int(payload.enabled),
                    payload.server,
                    payload.port,
                    payload.security_mode,
                    int(payload.verify_tls),
                    payload.connect_timeout,
                    payload.operation_timeout,
                    payload.base_dn,
                    payload.user_search_base,
                    payload.user_search_filter,
                    payload.username_attribute,
                    payload.bind_dn,
                    secret_id,
                    payload.display_name_attribute,
                    payload.email_attribute,
                    time.time(),
                    actor,
                ),
            )
        return self.get()

    @staticmethod
    def _key(username: str) -> str:
        return username.casefold()

    def identity(self, username: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM ldap_identities WHERE username_key=?",
                (self._key(username),),
            ).fetchone()
        return dict(row) if row else None

    def remember_identity(
        self,
        username: str,
        dn: str,
        *,
        home: str,
        display_name: str = "",
        email: str = "",
    ) -> str:
        now = time.time()
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO ldap_identities(
                    username_key,username,dn,display_name,email,home,created_at,last_login_at
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(username_key) DO UPDATE SET
                    username=excluded.username,dn=excluded.dn,
                    display_name=excluded.display_name,email=excluded.email,
                    home=excluded.home,last_login_at=excluded.last_login_at
                """,
                (self._key(username), username, dn, display_name, email, home, now, now),
            )
        return home

    def home(self, username: str) -> str | None:
        row = self.identity(username)
        return str(row["home"]) if row else None


@lru_cache(maxsize=1)
def settings_repository() -> LdapSettingsRepository:
    return LdapSettingsRepository()


def ldap_enabled() -> bool:
    try:
        return settings_repository().get().enabled
    except Exception as error:
        logger.error("ldap_settings_unavailable error=%s", type(error).__name__)
        return False


def ldap_home(username: str) -> str | None:
    try:
        return settings_repository().home(username)
    except Exception:
        return None


def is_ldap_identity(username: str) -> bool:
    try:
        return settings_repository().identity(username) is not None
    except Exception:
        return False


def _server_coordinates(settings: LdapSettings) -> tuple[str, int]:
    raw = settings.server.strip()
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    host = parsed.hostname or ""
    if not host:
        raise LdapConfigurationError("LDAP server is invalid")
    port = parsed.port or settings.port
    return host, port


def _tls(settings: LdapSettings) -> Tls:
    return Tls(validate=ssl.CERT_REQUIRED if settings.verify_tls else ssl.CERT_NONE)


def _connection(
    settings: LdapSettings,
    *,
    user: str,
    password: str,
) -> Connection:
    host, port = _server_coordinates(settings)
    server = Server(
        host,
        port=port,
        use_ssl=settings.security_mode == "ldaps",
        tls=_tls(settings),
        connect_timeout=settings.connect_timeout,
        get_info=NONE,
    )
    connection = Connection(
        server,
        user=user,
        password=password,
        receive_timeout=settings.operation_timeout,
        raise_exceptions=True,
    )
    connection.open()
    if settings.security_mode == "starttls":
        connection.start_tls()
    connection.bind()
    return connection


def _bind_password(settings: LdapSettings, *, purpose: str) -> str:
    if not settings.bind_secret_id:
        raise LdapConfigurationError("LDAP bind password is not configured")
    try:
        secret = secrets_service().verified_secret(
            settings.bind_secret_id,
            module_id=LDAP_SECRET_MODULE,
            purpose=purpose,
        )
    except Exception as error:
        raise LdapConfigurationError("LDAP bind password is unavailable") from error
    password = str(secret.get("secret") or "")
    if not password:
        raise LdapConfigurationError("LDAP bind password is empty")
    return password


def _attribute(entry: dict[str, Any], name: str) -> str:
    if not name:
        return ""
    attributes = entry.get("attributes")
    if not isinstance(attributes, dict):
        return ""
    value = attributes.get(name)
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "")


def _assert_identity_namespace_available(username: str) -> None:
    # ``pwd.getpwnam`` includes NSS identities, so it cannot distinguish a
    # genuine local PAM account from an LDAP/SSSD account. Only /etc/passwd is
    # authoritative for the local PAM namespace.
    from .auth import is_local_passwd_user

    if is_local_passwd_user(username):
        raise LdapInvalidCredentials("local identity collision")

    known_ldap_identity = is_ldap_identity(username)
    # A policy that predates the first LDAP login belongs to the local/PAM
    # namespace. Once the LDAP identity is known, administrators may explicitly
    # assign WebNAS RBAC policy to it without preventing subsequent logins.
    if identity_repository().user_policy(username) is not None and not known_ldap_identity:
        raise LdapInvalidCredentials("local RBAC identity collision")


def _posix_identity(username: str) -> pwd.struct_passwd:
    """Resolve an authenticated LDAP identity through NSS/SSSD/nslcd/winbind.

    WebNAS filesystem operations impersonate the authenticated Unix UID/GID.
    Therefore a directory identity must have a POSIX mapping before a session is
    created; a synthetic application-only home would authenticate successfully
    but fail later at the worker privilege boundary.
    """

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


def ldap_user_search_filter(template: str, username: str) -> str:
    """Build a search filter with RFC4515 escaping for the user-controlled value."""
    return template.replace("{username}", escape_filter_chars(username))


def _validate_login_username(username: str) -> str:
    value = username.strip()
    if not LDAP_USERNAME_RE.fullmatch(value):
        raise LdapInvalidCredentials("invalid username")
    return value


def authenticate_ldap(username: str, password: str) -> AuthenticatedIdentity:
    username = _validate_login_username(username)
    if not password:
        raise LdapInvalidCredentials("invalid credentials")

    settings = settings_repository().get()
    if not settings.enabled:
        raise LdapConfigurationError("LDAP authentication is disabled")
    bind_password = _bind_password(settings, purpose="ldap-authentication")

    service_connection: Connection | None = None
    user_connection: Connection | None = None
    try:
        try:
            service_connection = _connection(settings, user=settings.bind_dn, password=bind_password)
        except LDAPInvalidCredentialsResult as error:
            raise LdapServiceUnavailable("bind", "LDAP_BIND_FAILED") from error

        search_filter = ldap_user_search_filter(settings.user_search_filter, username)
        attributes = list(
            dict.fromkeys(
                [
                    settings.username_attribute,
                    settings.display_name_attribute,
                    settings.email_attribute,
                ]
            )
        )
        if not service_connection.search(
            search_base=settings.user_search_base,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=[item for item in attributes if item],
            size_limit=2,
            time_limit=max(1, int(settings.operation_timeout)),
        ):
            raise LdapServiceUnavailable("search", "LDAP_SEARCH_FAILED")
        entries = [
            item
            for item in service_connection.response
            if isinstance(item, dict) and item.get("type") == "searchResEntry"
        ]
        if len(entries) != 1:
            raise LdapInvalidCredentials("LDAP identity was not unique")
        entry = entries[0]
        dn = str(entry.get("dn") or "")
        if not dn:
            raise LdapInvalidCredentials("LDAP identity has no DN")
        returned_username = _attribute(entry, settings.username_attribute)
        if not returned_username or returned_username.casefold() != username.casefold():
            raise LdapInvalidCredentials("LDAP identity does not match requested username")

        try:
            user_connection = _connection(settings, user=dn, password=password)
        except LDAPInvalidCredentialsResult as error:
            raise LdapInvalidCredentials("invalid credentials") from error

        _assert_identity_namespace_available(username)
        account = _posix_identity(username)
        display_name = _attribute(entry, settings.display_name_attribute)
        email = _attribute(entry, settings.email_attribute)
        home = settings_repository().remember_identity(
            username,
            dn,
            home=str(account.pw_dir),
            display_name=display_name,
            email=email,
        )
        return AuthenticatedIdentity(
            username=username,
            provider="ldap",
            home=home,
            display_name=display_name,
            email=email,
        )
    except (LdapInvalidCredentials, LdapConfigurationError, LdapServiceUnavailable):
        raise
    except LDAPStartTLSError as error:
        logger.warning("ldap_authentication_failed stage=tls error=%s", type(error).__name__)
        raise LdapServiceUnavailable("tls", "LDAP_TLS_FAILED") from error
    except ssl.SSLError as error:
        logger.warning("ldap_authentication_failed stage=tls error=%s", type(error).__name__)
        raise LdapServiceUnavailable("tls", "LDAP_TLS_FAILED") from error
    except LDAPException as error:
        logger.warning("ldap_authentication_failed stage=directory error=%s", type(error).__name__)
        raise LdapServiceUnavailable("directory") from error
    except OSError as error:
        logger.warning("ldap_authentication_failed stage=connect error=%s", type(error).__name__)
        raise LdapServiceUnavailable("connect") from error
    finally:
        for connection in (user_connection, service_connection):
            if connection is not None:
                try:
                    connection.unbind()
                except Exception as error:
                    logger.debug("ldap_unbind_failed error=%s", type(error).__name__)


def test_ldap_connection() -> dict[str, Any]:
    settings = settings_repository().get()
    if not settings.server:
        raise LdapConfigurationError("LDAP server is not configured")
    bind_password = _bind_password(settings, purpose="ldap-connection-test")
    connection: Connection | None = None
    try:
        try:
            connection = _connection(settings, user=settings.bind_dn, password=bind_password)
        except LDAPInvalidCredentialsResult as error:
            raise LdapServiceUnavailable("bind", "LDAP_BIND_FAILED") from error

        # A zero-result search is valid here: the purpose is to verify that the
        # configured search base/filter can be executed without exposing users.
        search_filter = ldap_user_search_filter(
            settings.user_search_filter,
            "__webnas_connection_test__",
        )
        try:
            searched = connection.search(
                search_base=settings.user_search_base,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=[settings.username_attribute],
                size_limit=1,
                time_limit=max(1, int(settings.operation_timeout)),
            )
        except LDAPException as error:
            raise LdapServiceUnavailable("search", "LDAP_SEARCH_FAILED") from error
        if not searched:
            raise LdapServiceUnavailable("search", "LDAP_SEARCH_FAILED")
        return {"ok": True, "stage": "search"}
    except (LdapConfigurationError, LdapServiceUnavailable):
        raise
    except LDAPStartTLSError as error:
        logger.warning("ldap_connection_test_failed stage=tls error=%s", type(error).__name__)
        raise LdapServiceUnavailable("tls", "LDAP_TLS_FAILED") from error
    except ssl.SSLError as error:
        logger.warning("ldap_connection_test_failed stage=tls error=%s", type(error).__name__)
        raise LdapServiceUnavailable("tls", "LDAP_TLS_FAILED") from error
    except LDAPException as error:
        logger.warning("ldap_connection_test_failed stage=directory error=%s", type(error).__name__)
        raise LdapServiceUnavailable("directory") from error
    except OSError as error:
        logger.warning("ldap_connection_test_failed stage=connect error=%s", type(error).__name__)
        raise LdapServiceUnavailable("connect") from error
    finally:
        if connection is not None:
            try:
                connection.unbind()
            except Exception as error:
                logger.debug("ldap_unbind_failed error=%s", type(error).__name__)
