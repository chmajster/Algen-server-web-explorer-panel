from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from . import __version__
from .activity import ActivityCategory, ActivityStatus, record_activity
from .config import AppConfig, get_config
from .identity.permissions import Permission, require_permission
from .package_center.models import api_error
from .security import SessionUser


FORMAT_VERSION = 1
ARCHIVE_SUFFIX = ".webnas-backup.zip"
MAX_MEMBER_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_AUXILIARY_FILE_BYTES = 16 * 1024 * 1024
SAFE_AUXILIARY_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".conf", ".ini", ".key", ".pem", ".crt", ".cer"}
EXCLUDED_DIRECTORY_NAMES = {"appliance-backups", "repositories", "tmp", "cache", "node_modules"}
_ARCHIVE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.webnas-backup\.zip$")


class BackupCreateRequest(BaseModel):
    label: str = Field(default="manual", min_length=1, max_length=48, pattern=r"^[A-Za-z0-9._-]+$")
    include_config: bool = True
    include_secrets: bool = True


class BackupRestoreRequest(BaseModel):
    archive: str = Field(min_length=1, max_length=160)
    dry_run: bool = True
    confirmation_text: str = Field(default="", max_length=256)


@dataclass(frozen=True, slots=True)
class Resource:
    scope: str
    relative_path: str
    source: Path
    kind: str

    @property
    def member_name(self) -> str:
        return f"payload/{self.scope}/{self.relative_path}"


class BackupValidationError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: str) -> str:
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise BackupValidationError("unsafe backup member path")
    if "\\" in value or "\x00" in value:
        raise BackupValidationError("unsafe backup member path")
    return candidate.as_posix()


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise BackupValidationError("invalid WebNAS version metadata")
    return tuple(int(item) for item in match.groups())  # type: ignore[return-value]


def _minimum_restore_version() -> str:
    major, minor, _patch = _version_tuple(__version__)
    return f"{major}.{minor}.0"


def _config_path() -> Path:
    return Path(os.environ.get("WEBNAS_CONFIG", "/etc/webnas/config.yaml"))


def _sqlite_quick_check(path: Path) -> None:
    connection = sqlite3.connect(path, timeout=10)
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
    finally:
        connection.close()
    if not result or str(result[0]).casefold() != "ok":
        raise BackupValidationError(f"SQLite integrity check failed for {path.name}")


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source, timeout=15)
    destination_connection = sqlite3.connect(destination, timeout=15)
    try:
        source_connection.execute("PRAGMA busy_timeout=15000")
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()
    _sqlite_quick_check(destination)


def _atomic_copy(source: Path, target: Path, mode: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.webnas-restore-{os.getpid()}.tmp")
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class ApplianceBackupService:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or get_config()
        self.data_root = Path(self.config.paths.data_dir).resolve(strict=False)
        self.backup_root = self.data_root / "appliance-backups"
        self.backup_root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.backup_root, 0o700)
        except OSError:
            pass

    def _resources(self, *, include_config: bool, include_secrets: bool) -> list[Resource]:
        resources: list[Resource] = []
        config_path = _config_path()
        if include_config and config_path.is_file():
            resources.append(Resource("config", "config.yaml", config_path, "file"))

        if not self.data_root.exists():
            return resources

        for source in sorted(self.data_root.rglob("*")):
            if not source.is_file():
                continue
            try:
                relative = source.relative_to(self.data_root)
            except ValueError:
                continue
            if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts):
                continue
            if relative.name == "sessions.sqlite3":
                continue
            if relative.parts and relative.parts[0] == "secrets" and not include_secrets:
                continue
            relative_posix = _safe_relative(relative.as_posix())
            if source.suffix in {".sqlite", ".sqlite3", ".db"}:
                resources.append(Resource("data", relative_posix, source, "sqlite"))
                continue
            try:
                size = source.stat().st_size
            except OSError:
                continue
            if size > MAX_AUXILIARY_FILE_BYTES:
                continue
            if source.suffix.casefold() in SAFE_AUXILIARY_SUFFIXES or (relative.parts and relative.parts[0] in {"secrets", "settings"}):
                resources.append(Resource("data", relative_posix, source, "file"))
        return resources

    def _archive_path(self, label: str) -> Path:
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        base = f"webnas-{timestamp}-{label}{ARCHIVE_SUFFIX}"
        candidate = self.backup_root / base
        counter = 1
        while candidate.exists():
            candidate = self.backup_root / f"webnas-{timestamp}-{label}-{counter}{ARCHIVE_SUFFIX}"
            counter += 1
        return candidate

    def list_backups(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in sorted(self.backup_root.glob(f"*{ARCHIVE_SUFFIX}"), reverse=True):
            try:
                stat = path.stat()
                report = self.validate(path)
                result.append({
                    "name": path.name,
                    "size": stat.st_size,
                    "created_at": stat.st_mtime,
                    "sha256": _sha256(path),
                    "source_version": report["source_version"],
                    "member_count": report["member_count"],
                    "valid": True,
                })
            except (OSError, BackupValidationError, zipfile.BadZipFile):
                result.append({"name": path.name, "valid": False})
        return result

    def create(self, *, label: str, include_config: bool = True, include_secrets: bool = True) -> dict[str, Any]:
        destination = self._archive_path(label)
        resources = self._resources(include_config=include_config, include_secrets=include_secrets)
        with tempfile.TemporaryDirectory(prefix="webnas-appliance-backup-", dir=self.backup_root) as temp_name:
            temp_root = Path(temp_name)
            records: list[dict[str, Any]] = []
            for resource in resources:
                staged = temp_root / resource.member_name
                staged.parent.mkdir(parents=True, exist_ok=True)
                if resource.kind == "sqlite":
                    _sqlite_snapshot(resource.source, staged)
                else:
                    shutil.copy2(resource.source, staged)
                mode = resource.source.stat().st_mode & 0o777
                records.append({
                    "member": resource.member_name,
                    "scope": resource.scope,
                    "relative_path": resource.relative_path,
                    "kind": resource.kind,
                    "size": staged.stat().st_size,
                    "sha256": _sha256(staged),
                    "mode": mode,
                })

            manifest = {
                "format": "webnas-appliance-backup",
                "format_version": FORMAT_VERSION,
                "created_at": time.time(),
                "source_version": __version__,
                "minimum_restore_version": _minimum_restore_version(),
                "sessions_included": False,
                "secrets_included": include_secrets,
                "config_included": include_config and _config_path().is_file(),
                "resources": records,
            }
            manifest_path = temp_root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

            temporary_archive = destination.with_suffix(destination.suffix + ".tmp")
            try:
                with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                    archive.write(manifest_path, "manifest.json")
                    for record in records:
                        archive.write(temp_root / record["member"], record["member"])
                os.chmod(temporary_archive, 0o600)
                os.replace(temporary_archive, destination)
            finally:
                try:
                    temporary_archive.unlink()
                except FileNotFoundError:
                    pass

        validation = self.validate(destination)
        return {
            "name": destination.name,
            "size": destination.stat().st_size,
            "sha256": _sha256(destination),
            **validation,
        }

    def _resolve_archive(self, name_or_path: str | Path) -> Path:
        candidate = Path(name_or_path)
        if candidate.is_absolute():
            resolved = candidate.resolve(strict=False)
            if resolved.parent != self.backup_root.resolve(strict=False):
                raise BackupValidationError("backup archive is outside the appliance backup directory")
            return resolved
        name = str(candidate)
        if not _ARCHIVE_NAME.fullmatch(name):
            raise BackupValidationError("invalid backup archive name")
        return self.backup_root / name

    def _read_manifest(self, archive: zipfile.ZipFile) -> dict[str, Any]:
        try:
            info = archive.getinfo("manifest.json")
        except KeyError as error:
            raise BackupValidationError("backup manifest is missing") from error
        if info.file_size > 1024 * 1024:
            raise BackupValidationError("backup manifest is too large")
        try:
            payload = json.loads(archive.read(info).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BackupValidationError("backup manifest is invalid") from error
        if not isinstance(payload, dict) or payload.get("format") != "webnas-appliance-backup" or payload.get("format_version") != FORMAT_VERSION:
            raise BackupValidationError("unsupported backup format")
        resources = payload.get("resources")
        if not isinstance(resources, list):
            raise BackupValidationError("backup resource list is invalid")
        minimum = str(payload.get("minimum_restore_version", ""))
        if _version_tuple(__version__) < _version_tuple(minimum):
            raise BackupValidationError(f"backup requires WebNAS >= {minimum}")
        return payload

    def validate(self, name_or_path: str | Path) -> dict[str, Any]:
        path = self._resolve_archive(name_or_path)
        if not path.is_file():
            raise BackupValidationError("backup archive not found")
        with zipfile.ZipFile(path, "r") as archive, tempfile.TemporaryDirectory(prefix="webnas-backup-validate-") as temp_name:
            manifest = self._read_manifest(archive)
            infos = {info.filename: info for info in archive.infolist()}
            total = 0
            expected = {"manifest.json"}
            for raw_record in manifest["resources"]:
                if not isinstance(raw_record, dict):
                    raise BackupValidationError("invalid backup resource record")
                member = _safe_relative(str(raw_record.get("member", "")))
                relative_path = _safe_relative(str(raw_record.get("relative_path", "")))
                scope = raw_record.get("scope")
                kind = raw_record.get("kind")
                if scope not in {"config", "data"} or kind not in {"file", "sqlite"}:
                    raise BackupValidationError("unsupported backup resource record")
                expected.add(member)
                info = infos.get(member)
                if info is None or info.is_dir():
                    raise BackupValidationError(f"backup member is missing: {member}")
                if info.file_size > MAX_MEMBER_BYTES or int(raw_record.get("size", -1)) != info.file_size:
                    raise BackupValidationError(f"backup member size is invalid: {member}")
                total += info.file_size
                if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise BackupValidationError("backup archive exceeds the uncompressed size limit")
                digest = hashlib.sha256()
                staged = Path(temp_name) / member
                staged.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as reader, staged.open("wb") as writer:
                    while True:
                        chunk = reader.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                        writer.write(chunk)
                if digest.hexdigest() != str(raw_record.get("sha256", "")):
                    raise BackupValidationError(f"backup checksum mismatch: {member}")
                if kind == "sqlite":
                    _sqlite_quick_check(staged)
                if scope == "config" and relative_path != "config.yaml":
                    raise BackupValidationError("unsupported config backup target")
            if set(infos) != expected:
                raise BackupValidationError("backup contains undeclared archive members")
            return {
                "valid": True,
                "source_version": str(manifest.get("source_version", "")),
                "minimum_restore_version": str(manifest.get("minimum_restore_version", "")),
                "member_count": len(manifest["resources"]),
                "uncompressed_size": total,
                "sessions_included": bool(manifest.get("sessions_included", False)),
                "secrets_included": bool(manifest.get("secrets_included", False)),
            }

    def _target_for(self, scope: str, relative_path: str) -> Path:
        relative_path = _safe_relative(relative_path)
        if scope == "config":
            if relative_path != "config.yaml":
                raise BackupValidationError("unsupported config restore target")
            return _config_path()
        if scope != "data":
            raise BackupValidationError("unsupported restore target scope")
        target = (self.data_root / relative_path).resolve(strict=False)
        if self.data_root not in target.parents:
            raise BackupValidationError("restore target escapes the data directory")
        if target == self.data_root / "sessions.sqlite3" or target.name == "sessions.sqlite3":
            raise BackupValidationError("session state cannot be restored from an appliance archive")
        return target

    def restore(self, name_or_path: str | Path, *, apply: bool) -> dict[str, Any]:
        path = self._resolve_archive(name_or_path)
        validation = self.validate(path)
        if not apply:
            return {"dry_run": True, "archive": path.name, **validation}

        safety = self.create(label="pre-restore", include_config=True, include_secrets=True)
        with zipfile.ZipFile(path, "r") as archive, tempfile.TemporaryDirectory(prefix="webnas-appliance-restore-", dir=self.backup_root) as temp_name:
            manifest = self._read_manifest(archive)
            temp_root = Path(temp_name)
            staged_records: list[tuple[dict[str, Any], Path, Path]] = []
            for record in manifest["resources"]:
                member = _safe_relative(str(record["member"]))
                staged = temp_root / member
                staged.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as reader, staged.open("wb") as writer:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
                if _sha256(staged) != str(record["sha256"]):
                    raise BackupValidationError(f"backup checksum changed during restore: {member}")
                if record["kind"] == "sqlite":
                    _sqlite_quick_check(staged)
                target = self._target_for(str(record["scope"]), str(record["relative_path"]))
                staged_records.append((record, staged, target))

            preimages = temp_root / "preimages"
            changed: list[tuple[Path, Path | None, int]] = []
            try:
                for index, (record, staged, target) in enumerate(staged_records):
                    previous: Path | None = None
                    previous_mode = 0o600
                    if target.exists():
                        previous_mode = target.stat().st_mode & 0o777
                        previous = preimages / str(index)
                        previous.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, previous)
                    mode = int(record.get("mode", 0o600)) & 0o777
                    if target.name.endswith(".key") or "secrets" in target.parts:
                        mode = 0o600
                    _atomic_copy(staged, target, mode)
                    if record["kind"] == "sqlite":
                        _sqlite_quick_check(target)
                    changed.append((target, previous, previous_mode))
            except Exception:
                for target, previous, previous_mode in reversed(changed):
                    if previous is None:
                        try:
                            target.unlink()
                        except FileNotFoundError:
                            pass
                    else:
                        _atomic_copy(previous, target, previous_mode)
                raise

        return {
            "dry_run": False,
            "archive": path.name,
            "restored_members": validation["member_count"],
            "safety_backup": safety["name"],
            "source_version": validation["source_version"],
        }


_service: ApplianceBackupService | None = None
_service_root = ""


def service() -> ApplianceBackupService:
    global _service, _service_root
    config = get_config()
    root = str(Path(config.paths.data_dir).resolve(strict=False))
    if _service is None or _service_root != root:
        _service = ApplianceBackupService(config)
        _service_root = root
    return _service


router = APIRouter(prefix="/api/system/appliance-backups", tags=["appliance-backup"])


@router.get("")
def backups(user: SessionUser = Depends(require_permission(Permission.MODULES_BACKUP_CREATE))):
    del user
    return service().list_backups()


@router.post("")
def create_backup(
    payload: BackupCreateRequest,
    user: SessionUser = Depends(require_permission(Permission.MODULES_BACKUP_CREATE)),
):
    try:
        result = service().create(
            label=payload.label,
            include_config=payload.include_config,
            include_secrets=payload.include_secrets,
        )
    except (OSError, sqlite3.Error, BackupValidationError, zipfile.BadZipFile) as error:
        record_activity(ActivityCategory.administration, "appliance_backup_create", user.username, status=ActivityStatus.failure, details={"error_type": type(error).__name__}, source="backup")
        api_error(500, "APPLIANCE_BACKUP_FAILED", "Appliance backup failed", reason=type(error).__name__)
    record_activity(ActivityCategory.administration, "appliance_backup_create", user.username, target=result["name"], details={"members": result["member_count"], "sha256": result["sha256"]}, source="backup")
    return result


@router.post("/validate")
def validate_backup(
    payload: BackupRestoreRequest,
    user: SessionUser = Depends(require_permission(Permission.MODULES_BACKUP_RESTORE)),
):
    del user
    try:
        return service().restore(payload.archive, apply=False)
    except (OSError, BackupValidationError, zipfile.BadZipFile) as error:
        api_error(422, "APPLIANCE_BACKUP_INVALID", "Appliance backup validation failed", reason=type(error).__name__)


@router.post("/restore")
def restore_backup(
    payload: BackupRestoreRequest,
    user: SessionUser = Depends(require_permission(Permission.MODULES_BACKUP_RESTORE)),
):
    expected = f"RESTORE {payload.archive}"
    if not payload.dry_run and payload.confirmation_text != expected:
        api_error(422, "CONFIRMATION_REQUIRED", f"Type {expected} to confirm appliance restore")
    try:
        result = service().restore(payload.archive, apply=not payload.dry_run)
    except (OSError, sqlite3.Error, BackupValidationError, zipfile.BadZipFile) as error:
        record_activity(ActivityCategory.administration, "appliance_backup_restore", user.username, target=payload.archive, status=ActivityStatus.failure, details={"dry_run": payload.dry_run, "error_type": type(error).__name__}, source="backup")
        api_error(422 if isinstance(error, BackupValidationError) else 500, "APPLIANCE_RESTORE_FAILED", "Appliance restore failed", reason=type(error).__name__)
    record_activity(ActivityCategory.administration, "appliance_backup_restore", user.username, target=payload.archive, details={"dry_run": payload.dry_run, "members": result.get("member_count", result.get("restored_members", 0))}, source="backup")
    return result
