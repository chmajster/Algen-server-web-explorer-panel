from __future__ import annotations

import hashlib
import contextlib
import json
import os
import secrets
import shutil
import sqlite3
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any

from .repository import SCHEMA_VERSION, AnsibleRepository
from .security import atomic_private_write


BACKUP_VERSION = 1
MAX_BACKUP_FILES = 10_000
MAX_BACKUP_BYTES = 512 * 1024 * 1024


def create_backup(repository: AnsibleRepository, actor: str, description: str = "", include_credentials: bool = False) -> dict[str, Any]:
    backup_id = secrets.token_hex(12)
    backup_dir = repository.root / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    target = backup_dir / f"{backup_id}.tar.gz"
    with tempfile.TemporaryDirectory(dir=repository.root) as raw_staging:
        staging = Path(raw_staging)
        snapshot = staging / "controller.sqlite3"
        with repository._lock, contextlib.closing(repository.connect()) as source, contextlib.closing(sqlite3.connect(snapshot)) as destination:
            source.backup(destination)
            if not include_credentials:
                destination.execute("UPDATE credentials SET encrypted_secret='' WHERE encrypted_secret<>''")
            destination.commit()
        manifest: dict[str, Any] = {"version": BACKUP_VERSION, "created_at": time.time(), "created_by": actor, "description": description[:200], "credentials_included": include_credentials}
        if include_credentials:
            credentials: list[dict[str, Any]] = []
            for item in repository._list("credentials", limit=5000):
                credentials.append({"id": item["id"], "encrypted_secret": item["encrypted_secret"]})
            atomic_private_write(staging / "credentials.enc", repository.cipher.export_encrypted({"credentials": credentials}).encode())
        atomic_private_write(staging / "manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode())
        project_files: list[tuple[Path, str]] = []
        project_size = 0
        projects_root = repository.root / "projects"
        if projects_root.is_dir():
            for project_file in projects_root.rglob("*"):
                if project_file.is_symlink() or not project_file.is_file():
                    continue
                project_size += project_file.stat().st_size
                if len(project_files) >= MAX_BACKUP_FILES or project_size > MAX_BACKUP_BYTES:
                    raise ValueError("managed projects exceed backup size or file-count limits")
                project_files.append((project_file, f"projects/{project_file.relative_to(projects_root).as_posix()}"))
        with tarfile.open(target, "w:gz") as archive:
            _add_private_file(archive, snapshot, "controller.sqlite3")
            _add_private_file(archive, staging / "manifest.json", "manifest.json")
            projects_info = tarfile.TarInfo("projects")
            projects_info.type = tarfile.DIRTYPE
            projects_info.mode = 0o700
            projects_info.mtime = int(time.time())
            archive.addfile(projects_info)
            for project_file, member_name in project_files:
                _add_private_file(archive, project_file, member_name)
            if include_credentials:
                _add_private_file(archive, staging / "credentials.enc", "credentials.enc")
    os.chmod(target, 0o600)
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    metadata = {"id": backup_id, "module_id": "ansible-controller", "created_at": target.stat().st_mtime, "created_by": actor, "description": description[:200], "automatic": False, "checksum": checksum, "package_version": "1.0.0", "size": target.stat().st_size, "files": ["controller.sqlite3", "manifest.json", *[name for _path, name in project_files]] + (["credentials.enc"] if include_credentials else [])}
    atomic_private_write(target.with_suffix(".json"), json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode())
    repository.audit(actor, "backup", backup_id, "create", {"include_credentials": include_credentials, "checksum": checksum})
    return metadata


def _add_private_file(archive: tarfile.TarFile, path: Path, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.size = path.stat().st_size
    info.mode = 0o600
    info.mtime = int(path.stat().st_mtime)
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    with path.open("rb") as handle:
        archive.addfile(info, handle)


def list_backups(repository: AnsibleRepository) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    backup_dir = repository.root / "backups"
    if not backup_dir.exists():
        return result
    for path in backup_dir.glob("*.tar.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                result.append(value)
        except (OSError, ValueError):
            continue
    return sorted(result, key=lambda item: item.get("created_at", 0), reverse=True)


def backup_path(repository: AnsibleRepository, backup_id: str) -> Path:
    if not backup_id or any(char not in "0123456789abcdef" for char in backup_id) or len(backup_id) != 24:
        raise ValueError("invalid backup id")
    path = repository.root / "backups" / f"{backup_id}.tar.gz"
    if not path.is_file():
        raise FileNotFoundError("backup not found")
    return path


def delete_backup(repository: AnsibleRepository, backup_id: str, actor: str) -> None:
    path = backup_path(repository, backup_id)
    path.unlink()
    path.with_suffix(".json").unlink(missing_ok=True)
    repository.audit(actor, "backup", backup_id, "delete")


def validate_backup(repository: AnsibleRepository, backup_id: str, checksum: str) -> dict[str, Any]:
    path = backup_path(repository, backup_id)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != checksum:
        raise ValueError("backup checksum mismatch")
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        if not {"controller.sqlite3", "manifest.json"} <= names or any(name.startswith("/") or ".." in Path(name).parts for name in names):
            raise ValueError("invalid backup contents")
        regular = [member for member in members if member.isfile()]
        if len(regular) > MAX_BACKUP_FILES + 3 or sum(member.size for member in regular) > MAX_BACKUP_BYTES:
            raise ValueError("backup exceeds size or file-count limits")
        if any(not member.isfile() and not member.isdir() for member in members):
            raise ValueError("backup contains links or unsupported member types")
        manifest_file = archive.extractfile("manifest.json")
        if manifest_file is None:
            raise ValueError("backup manifest is missing")
        manifest = json.loads(manifest_file.read().decode("utf-8"))
    if manifest.get("version") != BACKUP_VERSION:
        raise ValueError("unsupported backup version")
    return manifest


def restore_backup(repository: AnsibleRepository, backup_id: str, checksum: str, actor: str, include_credentials: bool = False) -> dict[str, Any]:
    manifest = validate_backup(repository, backup_id, checksum)
    if include_credentials and not manifest.get("credentials_included"):
        raise ValueError("backup does not contain encrypted credential envelopes")
    safety = create_backup(repository, actor, "Automatic safety backup before restore", include_credentials=True)
    path = backup_path(repository, backup_id)
    with tempfile.TemporaryDirectory(dir=repository.root) as raw_staging:
        staging = Path(raw_staging)
        with tarfile.open(path, "r:gz") as archive:
            archive_names = archive.getnames()
            has_projects = "projects" in archive_names or any(name.startswith("projects/") for name in archive_names)
            selected_names = [name for name in archive_names if name in {"controller.sqlite3", "manifest.json", "credentials.enc"} or name.startswith("projects/")]
            for name in selected_names:
                if name not in archive.getnames():
                    continue
                source = archive.extractfile(name)
                if source is None:
                    raise ValueError("backup member is not a regular file")
                atomic_private_write(staging / name, source.read())
        candidate = staging / "controller.sqlite3"
        with contextlib.closing(sqlite3.connect(candidate)) as connection:
            if not include_credentials:
                connection.execute("UPDATE credentials SET encrypted_secret='' WHERE encrypted_secret<>''")
                connection.commit()
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise ValueError("backup database integrity check failed")
            schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if schema_version > SCHEMA_VERSION:
                raise ValueError("backup database schema is newer than this controller")
        replacement = repository.path.with_suffix(".restore")
        shutil.copy2(candidate, replacement)
        os.chmod(replacement, 0o600)
        with repository._lock:
            for suffix in ("-wal", "-shm"):
                Path(str(repository.path) + suffix).unlink(missing_ok=True)
            os.replace(replacement, repository.path)
            restored_projects = staging / "projects"
            if has_projects:
                restored_projects.mkdir(mode=0o700, exist_ok=True)
                current_projects = repository.root / "projects"
                previous_projects = repository.root / f".projects-pre-restore-{backup_id}"
                shutil.rmtree(previous_projects, ignore_errors=True)
                if current_projects.exists():
                    os.replace(current_projects, previous_projects)
                try:
                    os.replace(restored_projects, current_projects)
                except OSError:
                    if previous_projects.exists():
                        os.replace(previous_projects, current_projects)
                    raise
                shutil.rmtree(previous_projects, ignore_errors=True)
    repository.audit(actor, "backup", backup_id, "restore", {"safety_backup_id": safety["id"]})
    return {"ok": True, "backup_id": backup_id, "safety_backup": safety, "manifest": manifest}
