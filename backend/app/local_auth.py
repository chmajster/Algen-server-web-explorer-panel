from __future__ import annotations

import base64
import hashlib
import hmac
import os
import pwd
import re
import secrets
import sqlite3
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from .config import get_config
from .privileged_broker.runtime import broker_command, broker_required
from .sqlite_utils import ClosingConnection


AuthMode = Literal["local", "system"]
LocalRole = Literal["admin", "operator", "auditor", "user"]
LOCAL_ROLES = {"admin", "operator", "auditor", "user"}
# Keep the application username inside the privileged broker's Linux account
# policy grammar so a local WebNAS account can receive a locked POSIX mapping.
LOCAL_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}\$?$", re.IGNORECASE)
SCRYPT_N = 1 << 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


class LocalAuthenticationError(Exception):
    pass


class LocalInvalidCredentials(LocalAuthenticationError):
    pass


class LocalAuthConfigurationError(LocalAuthenticationError):
    pass


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _hash_password_unchecked(password: str) -> str:
    if not password or len(password) > 1024 or "\x00" in password:
        raise ValueError("Local account password must contain between 1 and 1024 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 1024 or "\x00" in password:
        raise ValueError("Local account password must contain between 12 and 1024 characters")
    return _hash_password_unchecked(password)


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    # Unknown usernames still execute one scrypt verification without generating
    # a fresh expensive hash for every failed request.
    return hash_password("webnas-invalid-password-placeholder")


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_n, raw_r, raw_p, raw_salt, raw_digest = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        n, r, p = int(raw_n), int(raw_r), int(raw_p)
        if n < 2**14 or n > 2**20 or r < 1 or r > 32 or p < 1 or p > 16:
            return False
        salt = _unb64(raw_salt)
        expected = _unb64(raw_digest)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, OverflowError):
        return False


def validate_local_username(username: str) -> str:
    value = username.strip()
    if not LOCAL_USERNAME_RE.fullmatch(value) or "/" in value or "\x00" in value:
        raise ValueError("Invalid local WebNAS username")
    return value


def validate_local_role(role: str) -> LocalRole:
    value = role.strip().lower()
    if value not in LOCAL_ROLES:
        raise ValueError("Invalid local WebNAS role")
    return value  # type: ignore[return-value]


def _posix_mapping(username: str) -> dict[str, Any] | None:
    try:
        account = pwd.getpwnam(username)
    except KeyError:
        return None
    cfg = get_config()
    if account.pw_uid == 0 or account.pw_uid < cfg.security.system_uid_threshold:
        return None
    if not account.pw_dir or not Path(account.pw_dir).is_absolute():
        return None
    return {
        "uid": int(account.pw_uid),
        "gid": int(account.pw_gid),
        "home": str(account.pw_dir),
    }


def _ensure_posix_mapping(username: str) -> dict[str, Any] | None:
    mapping = _posix_mapping(username)
    if mapping is not None:
        return mapping
    if not broker_required():
        return None

    # Standard installations run the application as the unprivileged `webnas`
    # account and expose a typed root broker. Create a locked, non-interactive
    # POSIX companion solely for UID/GID/home semantics; WebNAS never places the
    # application password into /etc/shadow.
    home = f"/home/{username}"
    result = broker_command(
        [
            "useradd",
            "--user-group",
            "--create-home",
            "--home-dir",
            home,
            "--shell",
            "/usr/sbin/nologin",
            username,
        ],
        actor="local-auth",
    )
    if result is None or result.returncode != 0:
        # Some distributions install nologin under /sbin. Retry only when the
        # first account was not created; useradd fails closed if the user exists.
        result = broker_command(
            [
                "useradd",
                "--user-group",
                "--create-home",
                "--home-dir",
                home,
                "--shell",
                "/sbin/nologin",
                username,
            ],
            actor="local-auth",
        )
    if result is None or result.returncode != 0:
        return _posix_mapping(username)

    locked = broker_command(["usermod", "--lock", username], actor="local-auth")
    if locked is None or locked.returncode != 0:
        return None
    return _posix_mapping(username)


class LocalAuthRepository:
    def __init__(self, path: Path | None = None) -> None:
        root = Path(get_config().paths.data_dir).resolve(strict=False)
        self.path = path or root / "local-auth.sqlite3"
        self.homes_root = root / "local-homes"
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
                CREATE TABLE IF NOT EXISTS local_auth_settings(
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    auth_mode TEXT NOT NULL DEFAULT 'local',
                    updated_at REAL NOT NULL DEFAULT 0,
                    updated_by TEXT NOT NULL DEFAULT ''
                );
                INSERT OR IGNORE INTO local_auth_settings(id,auth_mode) VALUES(1,'local');

                CREATE TABLE IF NOT EXISTS local_users(
                    username_key TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    display_name TEXT NOT NULL DEFAULT '',
                    home TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_login_at REAL NOT NULL DEFAULT 0,
                    password_changed_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_local_users_enabled_role
                    ON local_users(enabled,role);
                """
            )
        self.homes_root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path, 0o600)
            os.chmod(self.homes_root, 0o700)
        except OSError:
            pass

    @staticmethod
    def _key(username: str) -> str:
        return username.casefold()

    def auth_mode(self) -> AuthMode:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT auth_mode FROM local_auth_settings WHERE id=1"
            ).fetchone()
        return "system" if row and str(row["auth_mode"]) == "system" else "local"

    def set_auth_mode(self, mode: AuthMode, actor: str) -> AuthMode:
        if mode not in {"local", "system"}:
            raise ValueError("Invalid authentication mode")
        if mode == "local" and self.enabled_admin_count() < 1:
            raise ValueError("Local database mode requires at least one enabled local administrator")
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE local_auth_settings SET auth_mode=?,updated_at=?,updated_by=? WHERE id=1",
                (mode, time.time(), actor),
            )
        return mode

    def _home_for(self, username: str) -> str:
        mapping = _ensure_posix_mapping(username)
        if mapping:
            return str(mapping["home"])
        digest = hashlib.sha256(username.casefold().encode("utf-8")).hexdigest()[:24]
        home = self.homes_root / digest
        home.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(home, 0o700)
        except OSError:
            pass
        return str(home)

    @staticmethod
    def _public(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        mapping = _posix_mapping(str(item["username"]))
        return {
            "username": str(item["username"]),
            "role": str(item["role"]),
            "enabled": bool(item["enabled"]),
            "display_name": str(item.get("display_name") or ""),
            "home": str(mapping["home"] if mapping else item.get("home") or ""),
            "posix_mapped": mapping is not None,
            "created_at": float(item.get("created_at") or 0),
            "updated_at": float(item.get("updated_at") or 0),
            "last_login_at": float(item.get("last_login_at") or 0),
            "password_changed_at": float(item.get("password_changed_at") or 0),
        }

    def user(self, username: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM local_users WHERE username_key=?",
                (self._key(username),),
            ).fetchone()
        return self._public(row) if row else None

    def _private_user(self, username: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM local_users WHERE username_key=?",
                (self._key(username),),
            ).fetchone()

    def users(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM local_users ORDER BY username COLLATE NOCASE"
            ).fetchall()
        return [self._public(row) for row in rows]

    def count(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS amount FROM local_users").fetchone()
        return int(row["amount"] if row else 0)

    def enabled_admin_count(self, *, excluding: str = "") -> int:
        with self.connect() as connection:
            if excluding:
                row = connection.execute(
                    "SELECT COUNT(*) AS amount FROM local_users WHERE enabled=1 AND role='admin' AND username_key<>?",
                    (self._key(excluding),),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) AS amount FROM local_users WHERE enabled=1 AND role='admin'"
                ).fetchone()
        return int(row["amount"] if row else 0)

    def create_user(
        self,
        username: str,
        password: str,
        *,
        role: str = "user",
        display_name: str = "",
        _allow_short_password: bool = False,
    ) -> dict[str, Any]:
        username = validate_local_username(username)
        role_value = validate_local_role(role)
        if self.user(username) is not None:
            raise ValueError("A local WebNAS user with this username already exists")
        password_hash = _hash_password_unchecked(password) if _allow_short_password else hash_password(password)
        now = time.time()
        home = self._home_for(username)
        with self._lock, self.connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO local_users(
                        username_key,username,password_hash,role,enabled,display_name,home,
                        created_at,updated_at,last_login_at,password_changed_at
                    ) VALUES(?,?,?,?,1,?,?,?,?,0,?)
                    """,
                    (
                        self._key(username),
                        username,
                        password_hash,
                        role_value,
                        display_name.strip()[:256],
                        home,
                        now,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("A local WebNAS user with this username already exists") from error
        user = self.user(username)
        if not user:
            raise RuntimeError("Created local user is unavailable")
        return user

    def bootstrap_admin(self, username: str, password: str) -> tuple[dict[str, Any] | None, str]:
        with self._lock:
            if self.count() > 0:
                return None, ""
            username = validate_local_username(username)
            if not password or len(password) > 1024 or "\x00" in password:
                raise ValueError("Bootstrap password must contain between 1 and 1024 characters")
            user = self.create_user(
                username,
                password,
                role="admin",
                display_name="WebNAS Administrator",
                _allow_short_password=True,
            )
            return user, password

    def authenticate(self, username: str, password: str) -> dict[str, Any]:
        username = validate_local_username(username)
        row = self._private_user(username)
        encoded = str(row["password_hash"]) if row else _dummy_password_hash()
        valid = bool(password) and verify_password(password, encoded)
        if not row or not valid or not bool(row["enabled"]):
            raise LocalInvalidCredentials("Invalid username or password")
        mapping = _ensure_posix_mapping(username)
        if mapping is None:
            raise LocalAuthConfigurationError("Local user POSIX mapping is unavailable")
        with self.connect() as connection:
            connection.execute(
                "UPDATE local_users SET home=?,last_login_at=? WHERE username_key=?",
                (str(mapping["home"]), time.time(), self._key(username)),
            )
        user = self.user(username)
        if not user:
            raise LocalInvalidCredentials("Invalid username or password")
        return user

    def update_user(
        self,
        username: str,
        *,
        role: str | None = None,
        enabled: bool | None = None,
        display_name: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        current = self.user(username)
        if not current:
            raise LookupError("Local WebNAS user not found")
        next_role = validate_local_role(role) if role is not None else str(current["role"])
        next_enabled = bool(enabled) if enabled is not None else bool(current["enabled"])
        if current["role"] == "admin" and current["enabled"] and (next_role != "admin" or not next_enabled):
            if self.enabled_admin_count(excluding=username) < 1:
                raise ValueError("The last enabled local administrator cannot be disabled or downgraded")
        updates = ["role=?", "enabled=?", "updated_at=?"]
        values: list[Any] = [next_role, int(next_enabled), time.time()]
        if display_name is not None:
            updates.append("display_name=?")
            values.append(display_name.strip()[:256])
        if password is not None:
            updates.extend(["password_hash=?", "password_changed_at=?"])
            values.extend([hash_password(password), time.time()])
        values.append(self._key(username))
        with self._lock, self.connect() as connection:
            connection.execute(
                f"UPDATE local_users SET {','.join(updates)} WHERE username_key=?",  # noqa: S608 - fixed column list
                tuple(values),
            )
        user = self.user(username)
        if not user:
            raise RuntimeError("Updated local user is unavailable")
        return user

    def delete_user(self, username: str) -> None:
        current = self.user(username)
        if not current:
            raise LookupError("Local WebNAS user not found")
        if current["role"] == "admin" and current["enabled"] and self.enabled_admin_count(excluding=username) < 1:
            raise ValueError("The last enabled local administrator cannot be deleted")
        with self._lock, self.connect() as connection:
            connection.execute("DELETE FROM local_users WHERE username_key=?", (self._key(username),))
        # Keep an existing POSIX identity intentionally. It may predate WebNAS or
        # be shared with other services; deleting it automatically would be a
        # destructive cross-boundary action.


@lru_cache(maxsize=1)
def repository() -> LocalAuthRepository:
    return LocalAuthRepository()


def auth_mode() -> AuthMode:
    try:
        return repository().auth_mode()
    except Exception:
        return "local"


def local_user(username: str) -> dict[str, Any] | None:
    try:
        return repository().user(username)
    except Exception:
        return None


def local_home(username: str) -> str | None:
    user = local_user(username)
    return str(user["home"]) if user else None


def authenticate_local(username: str, password: str) -> dict[str, Any]:
    if auth_mode() != "local":
        raise LocalAuthConfigurationError("Local database authentication is disabled")
    return repository().authenticate(username, password)


def local_posix_mapping(username: str) -> dict[str, Any] | None:
    return _posix_mapping(username)


def bootstrap_initial_admin(username: str, password: str) -> tuple[dict[str, Any] | None, str]:
    return repository().bootstrap_admin(username, password)
