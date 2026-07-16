from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from ...package_center.executor import redact
from ...package_center.distro import detect_distribution
from ...package_center.models import ModuleDiagnostic, ModuleHealth, ModuleService, ModuleStatus, api_error
from .base import CancelCallback, LogCallback, ProgressCallback
from .infrastructure import PrivateBackupProvider


def _rows(output: str, columns: list[str]) -> list[dict[str, Any]]:
    result = []
    for line in output.splitlines():
        values = line.split("\t")
        if len(values) == len(columns):
            result.append(dict(zip(columns, values, strict=True)))
    return result


class StreamingDatabaseProvider(PrivateBackupProvider):
    def _dump_to_backup(self, command: list[str], actor: str, description: str, suffix: str, *, automatic: bool = False) -> dict[str, Any]:
        if not command or command[0] not in self.allowed_tools:
            api_error(400, "COMMAND_NOT_ALLOWED", "Database backup command is not allowed")
        executable = shutil.which(command[0])
        if not executable:
            raise RuntimeError(f"{command[0]} is unavailable")
        backup_id = secrets.token_hex(12)
        target = self.backup_dir / f"{backup_id}{suffix}"
        tmp = self.backup_dir / f"{backup_id}.tmp"
        clean_env = {"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        with tmp.open("wb") as output:
            result = subprocess.run([executable, *command[1:]], stdout=output, stderr=subprocess.PIPE, timeout=3600, check=False, shell=False, env=clean_env)
            output.flush()
            os.fsync(output.fileno())
        if result.returncode != 0:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(redact(result.stderr.decode("utf-8", errors="replace") or "Database backup failed"))
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
        return self._register_backup(actor, description, target, automatic=automatic)

    def _restore_stream(self, command: list[str], backup_id: str) -> None:
        source, _ = self._backup_metadata(backup_id)
        if not command or command[0] not in self.allowed_tools:
            api_error(400, "COMMAND_NOT_ALLOWED", "Database restore command is not allowed")
        executable = shutil.which(command[0])
        if not executable:
            raise RuntimeError(f"{command[0]} is unavailable")
        clean_env = {"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        with source.open("rb") as input_file:
            result = subprocess.run([executable, *command[1:]], stdin=input_file, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3600, check=False, shell=False, env=clean_env)
        if result.returncode != 0:
            raise RuntimeError(redact(result.stderr.decode("utf-8", errors="replace") or "Database restore failed"))


class PostgreSQLProvider(StreamingDatabaseProvider):
    allowed_tools = {"psql", "pg_dumpall", "runuser"}

    def _as_postgres(self, tool: str, args: list[str]) -> list[str]:
        if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0 and shutil.which("runuser"):
            return ["runuser", "-u", "postgres", "--", tool, *args]
        return [tool, "-U", "postgres", *args]

    def _query(self, sql: str) -> str:
        command = self._as_postgres("psql", ["-X", "-A", "-t", "-F", "\t", "-d", "postgres", "-c", sql])
        return self._result(self._run(command, timeout=30), "PostgreSQL query failed")

    def get_status(self) -> ModuleStatus:
        installed = bool(shutil.which("psql"))
        result = self._run(self._as_postgres("psql", ["--version"]), timeout=10) if installed else None
        version = result.stdout.strip().removeprefix("psql (PostgreSQL) ") if result and result.returncode == 0 else None
        try:
            self._query("SELECT 1")
            active = True
        except RuntimeError:
            active = False
        return ModuleStatus(installed=installed, package_version=version, service_state="active" if active else "inactive" if installed else "not_installed", services={"postgresql": {"state": "active" if active else "inactive", "enabled": self._systemctl("postgresql", "is-enabled").returncode == 0, "required": True}}, health=ModuleHealth.healthy if active else ModuleHealth.degraded if installed else ModuleHealth.not_installed, health_message="PostgreSQL is accepting local connections" if active else "PostgreSQL local connection is unavailable")

    def list_resources(self, resource: str, *, limit: int = 200, search: str = "") -> dict[str, Any]:
        queries = {
            "databases": ("SELECT d.datname,pg_database_size(d.datname),pg_get_userbyid(d.datdba),(SELECT count(*) FROM pg_stat_activity a WHERE a.datname=d.datname) FROM pg_database d WHERE NOT d.datistemplate ORDER BY d.datname", ["name", "size", "owner", "connections"]),
            "users": ("SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolcanlogin,rolconnlimit FROM pg_roles ORDER BY rolname", ["name", "superuser", "create_db", "create_role", "can_login", "connection_limit"]),
            "connections": ("SELECT pid,usename,datname,COALESCE(client_addr::text,''),state,backend_start FROM pg_stat_activity ORDER BY backend_start DESC LIMIT 1000", ["pid", "user", "database", "client", "state", "started_at"]),
        }
        if resource not in queries:
            return super().list_resources(resource, limit=limit, search=search)
        sql, columns = queries[resource]
        items = _rows(self._query(sql), columns)
        needle = search.lower().strip()
        if needle:
            items = [item for item in items if needle in json.dumps(item).lower()]
        return {"resource": resource, "items": items[:limit], "total": len(items)}

    def create_backup(self, actor: str, description: str = "", automatic: bool = False) -> dict[str, Any]:
        return self._dump_to_backup(self._as_postgres("pg_dumpall", ["--clean", "--if-exists"]), actor, description, ".sql", automatic=automatic)

    def restore_backup(self, backup_id: str, actor: str, log: LogCallback) -> dict[str, Any]:
        self._restore_stream(self._as_postgres("psql", ["-X", "-v", "ON_ERROR_STOP=1", "-d", "postgres"]), backup_id)
        log("stdout", "PostgreSQL backup restored; SQL and credentials were not written to the operation log")
        return {"restored": backup_id}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        status = self.get_status()
        connections = self.list_resources("connections", limit=100)["total"] if status.health == ModuleHealth.healthy else 0
        return [ModuleDiagnostic(status="ok" if status.health == ModuleHealth.healthy else "critical", title="PostgreSQL service", description=status.health_message, severity="ok" if status.health == ModuleHealth.healthy else "critical"), ModuleDiagnostic(status="info", title="Active connections", description=str(connections), severity="info")]


class MariaDBProvider(StreamingDatabaseProvider):
    allowed_tools = {"mariadb", "mysql", "mariadb-dump", "mysqldump"}

    def _client(self) -> str:
        return "mariadb" if shutil.which("mariadb") else "mysql"

    def _dump_tool(self) -> str:
        return "mariadb-dump" if shutil.which("mariadb-dump") else "mysqldump"

    def _query(self, sql: str) -> str:
        return self._result(self._run([self._client(), "--batch", "--skip-column-names", "--execute", sql], timeout=30), "MariaDB query failed")

    def get_status(self) -> ModuleStatus:
        installed = bool(shutil.which("mariadb") or shutil.which("mysql"))
        try:
            version = self._query("SELECT VERSION() ").strip()
            active = True
        except RuntimeError:
            version, active = "", False
        return ModuleStatus(installed=installed, package_version=version or None, service_state="active" if active else "inactive" if installed else "not_installed", services={"mariadb": {"state": "active" if active else "inactive", "enabled": self._systemctl("mariadb", "is-enabled").returncode == 0, "required": True}}, health=ModuleHealth.healthy if active else ModuleHealth.degraded if installed else ModuleHealth.not_installed, health_message="MariaDB is accepting local socket connections" if active else "MariaDB local socket is unavailable")

    def list_resources(self, resource: str, *, limit: int = 200, search: str = "") -> dict[str, Any]:
        queries = {
            "databases": ("SELECT SCHEMA_NAME,DEFAULT_CHARACTER_SET_NAME,DEFAULT_COLLATION_NAME FROM information_schema.SCHEMATA ORDER BY SCHEMA_NAME", ["name", "charset", "collation"]),
            "users": ("SELECT User,Host,account_locked FROM mysql.user ORDER BY User,Host", ["user", "host", "locked"]),
            "permissions": ("SELECT GRANTEE,TABLE_SCHEMA,PRIVILEGE_TYPE,IS_GRANTABLE FROM information_schema.SCHEMA_PRIVILEGES ORDER BY GRANTEE,TABLE_SCHEMA LIMIT 1000", ["grantee", "database", "privilege", "grantable"]),
            "replication": ("SHOW REPLICA STATUS", []),
        }
        if resource not in queries:
            return super().list_resources(resource, limit=limit, search=search)
        sql, columns = queries[resource]
        output = self._query(sql)
        if resource == "replication":
            items = [{"status": "not_configured"}] if not output.strip() else [{"status": "configured", "summary": "Replication metadata is available; credentials are hidden"}]
        else:
            items = _rows(output, columns)
        needle = search.lower().strip()
        if needle:
            items = [item for item in items if needle in json.dumps(item).lower()]
        return {"resource": resource, "items": items[:limit], "total": len(items)}

    def create_backup(self, actor: str, description: str = "", automatic: bool = False) -> dict[str, Any]:
        command = [self._dump_tool(), "--all-databases", "--single-transaction", "--routines", "--events", "--hex-blob"]
        return self._dump_to_backup(command, actor, description, ".sql", automatic=automatic)

    def restore_backup(self, backup_id: str, actor: str, log: LogCallback) -> dict[str, Any]:
        self._restore_stream([self._client()], backup_id)
        log("stdout", "MariaDB backup restored; SQL and credentials were not written to the operation log")
        return {"restored": backup_id}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        status = self.get_status()
        replication = self.list_resources("replication", limit=1)["items"] if status.health == ModuleHealth.healthy else []
        return [ModuleDiagnostic(status="ok" if status.health == ModuleHealth.healthy else "critical", title="MariaDB service", description=status.health_message, severity="ok" if status.health == ModuleHealth.healthy else "critical"), ModuleDiagnostic(status="info", title="Replication", description=str(replication[0].get("status") if replication else "unavailable"), severity="info")]


class RedisProvider(PrivateBackupProvider):
    allowed_tools = {"redis-cli"}

    def __init__(self, module_id: str) -> None:
        super().__init__(module_id)
        service = "redis-server" if detect_distribution().package_manager == "apt-get" else "redis"
        self.manifest.services = [ModuleService(name=service, required=True)]
        self.manifest.systemd_services = [service]

    def _redis(self, args: list[str], *, timeout: int = 30) -> str:
        return self._result(self._run(["redis-cli", "--raw", *args], timeout=timeout), "Redis operation failed")

    @staticmethod
    def _info(output: str) -> dict[str, str]:
        return {key: value for line in output.splitlines() if line and not line.startswith("#") and ":" in line for key, value in [line.split(":", 1)]}

    def _config(self, name: str) -> str:
        lines = self._redis(["CONFIG", "GET", name]).splitlines()
        return lines[1] if len(lines) > 1 else ""

    def get_status(self) -> ModuleStatus:
        installed = bool(shutil.which("redis-cli"))
        try:
            active = self._redis(["PING"]).strip() == "PONG"
            info = self._info(self._redis(["INFO", "server"])) if active else {}
        except RuntimeError:
            active, info = False, {}
        service = self.manifest.services[0].name
        return ModuleStatus(installed=installed, package_version=info.get("redis_version"), service_state="active" if active else "inactive" if installed else "not_installed", services={service: {"state": "active" if active else "inactive", "enabled": self._systemctl(service, "is-enabled").returncode == 0, "required": True}}, health=ModuleHealth.healthy if active else ModuleHealth.degraded if installed else ModuleHealth.not_installed, health_message="Redis responded to PING" if active else "Redis is unavailable")

    def list_resources(self, resource: str, *, limit: int = 200, search: str = "") -> dict[str, Any]:
        sections = {"memory": "memory", "persistence": "persistence", "stats": "stats", "clients": "clients"}
        if resource in sections:
            info = self._info(self._redis(["INFO", sections[resource]]))
            if resource == "clients":
                client_lines = self._redis(["CLIENT", "LIST"]).splitlines()[:limit]
                items = [{key: value for token in line.split() if "=" in token for key, value in [token.split("=", 1)] if key not in {"cmd"}} for line in client_lines]
            else:
                items = [info]
            return {"resource": resource, "items": items, "total": len(items)}
        if resource in {"limits", "security"}:
            values = {
                "maxmemory": self._config("maxmemory"), "maxmemory_policy": self._config("maxmemory-policy"), "protected_mode": self._config("protected-mode"),
                "bind": self._config("bind"), "aclfile": self._config("aclfile"), "password_configured": bool(self._config("requirepass")),
            }
            if resource == "security":
                values.pop("maxmemory", None)
                values.pop("maxmemory_policy", None)
            return {"resource": resource, "items": [values], "total": 1}
        return super().list_resources(resource, limit=limit, search=search)

    def manage(self, operation: str, payload: dict[str, Any], actor: str, log: LogCallback, progress: ProgressCallback, cancelled: CancelCallback) -> dict[str, Any]:
        if operation == "configure_memory":
            maximum = payload.get("maxmemory")
            policy = str(payload.get("policy") or "noeviction")
            if not isinstance(maximum, int) or not 0 <= maximum <= 1024**4 or policy not in {"noeviction", "allkeys-lru", "allkeys-lfu", "volatile-lru", "volatile-lfu", "allkeys-random", "volatile-random", "volatile-ttl"}:
                api_error(422, "INVALID_REDIS_MEMORY", "Redis memory settings are invalid")
            commands = [["CONFIG", "SET", "maxmemory", str(maximum)], ["CONFIG", "SET", "maxmemory-policy", policy]]
        elif operation == "configure_persistence":
            appendonly = payload.get("appendonly")
            if not isinstance(appendonly, bool):
                api_error(422, "INVALID_REDIS_PERSISTENCE", "appendonly must be a boolean")
            commands = [["CONFIG", "SET", "appendonly", "yes" if appendonly else "no"]]
        else:
            return super().manage(operation, payload, actor, log, progress, cancelled)
        for index, command in enumerate(commands):
            if cancelled():
                raise InterruptedError("Redis configuration cancelled")
            progress(20 + index * 50, "Applying Redis configuration")
            self._redis(command)
        log("stdout", "Redis configuration updated without logging secrets")
        return {"operation": operation, "status": self.get_status().model_dump(mode="json")}

    def _rdb_path(self) -> Path:
        path = (Path(self._config("dir")) / self._config("dbfilename")).resolve(strict=False)
        allowed = [Path("/var/lib/redis"), Path("/var/lib/valkey")]
        if not any(path == root or root in path.parents for root in allowed):
            api_error(409, "REDIS_DATA_PATH_UNSAFE", "Redis data file is outside approved data directories")
        return path

    def create_backup(self, actor: str, description: str = "", automatic: bool = False) -> dict[str, Any]:
        before = int(self._redis(["LASTSAVE"]).strip() or "0")
        self._redis(["BGSAVE"])
        for _ in range(60):
            if int(self._redis(["LASTSAVE"]).strip() or "0") > before:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Redis background save did not complete in time")
        source = self._rdb_path()
        if not source.is_file():
            raise RuntimeError("Redis RDB file is not available yet")
        target = self.backup_dir / f"{secrets.token_hex(12)}.rdb"
        shutil.copyfile(source, target)
        os.chmod(target, 0o600)
        return self._register_backup(actor, description, target, automatic=automatic)

    def restore_backup(self, backup_id: str, actor: str, log: LogCallback) -> dict[str, Any]:
        source, _ = self._backup_metadata(backup_id)
        target = self._rdb_path()
        if not target.is_file():
            raise RuntimeError("Redis target RDB file does not exist")
        previous = target.with_suffix(".webnas.previous")
        shutil.copy2(target, previous)
        previous_stat = target.stat()
        service = self.manifest.services[0].name
        if self._systemctl(service, "stop").returncode != 0:
            previous.unlink(missing_ok=True)
            raise RuntimeError("Redis service could not be stopped for restore")
        tmp = target.with_suffix(".webnas.tmp")
        try:
            shutil.copyfile(source, tmp)
            os.chmod(tmp, previous_stat.st_mode & 0o777)
            if hasattr(os, "chown"):
                os.chown(tmp, previous_stat.st_uid, previous_stat.st_gid)
            os.replace(tmp, target)
            if self._systemctl(service, "start").returncode != 0:
                raise RuntimeError("Redis service failed to start after restore")
            previous.unlink(missing_ok=True)
        except Exception:
            os.replace(previous, target)
            self._systemctl(service, "start")
            raise
        log("stdout", "Redis RDB restored from a verified private backup")
        return {"restored": backup_id}

    def run_diagnostics(self) -> list[ModuleDiagnostic]:
        status = self.get_status()
        security = self.list_resources("security", limit=1)["items"][0] if status.health == ModuleHealth.healthy else {}
        exposed = security.get("protected_mode") != "yes" and not security.get("password_configured")
        return [ModuleDiagnostic(status="ok" if status.health == ModuleHealth.healthy else "critical", title="Redis service", description=status.health_message, severity="ok" if status.health == ModuleHealth.healthy else "critical"), ModuleDiagnostic(status="critical" if exposed else "ok", title="Redis access control", description="Protected mode is disabled without a password" if exposed else "Protected mode or authentication is enabled", severity="critical" if exposed else "ok", recommended_action="Enable protected mode and configure ACL authentication" if exposed else "")]
