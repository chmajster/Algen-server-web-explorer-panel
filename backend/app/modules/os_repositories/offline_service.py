from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import time
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from .adapters import AptRepositoryAdapter, RpmRepositoryAdapter
from .models import ChannelName, RepositoryFormat
from .offline_models import (
    BundlePinInput,
    OfflineBundleType,
    OfflineExportInput,
    OfflineImportInput,
    OfflineSettingsInput,
    OfflineTargetInput,
)
from .repository import object_id
from .security import atomic_write, managed_path, run_tool
from .service import RepositoryService, service as repository_service

BUNDLE_FORMAT_VERSION = 1
MAX_ARCHIVE_FILES = 200_000
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_EXTRACTED_BYTES = 512 * 1024**3
ALLOWED_ARCHIVE_SUFFIXES = (".tar.zst", ".tzst", ".tar.gz", ".tgz")
DEPENDENCY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+_.-]*")
DEPENDENCY_VERSION = re.compile(r"\((>=|<=|=|>>|<<|>|<)\s*([^)]+)\)|\s(>=|<=|=|>|<)\s*([^\s,|]+)")


class OfflineRepositoryService:
    def __init__(self, base: RepositoryService | None = None) -> None:
        self.base = base or repository_service()
        self.store = self.base.store
        self.root = self.base.root
        self.bundle_root = self.root / "offline-bundles"
        self.staging_root = self.root / "incoming" / "offline-bundles"
        self.temporary_root = self.root / "temporary" / "offline"
        for path in (self.bundle_root, self.staging_root, self.temporary_root):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass
        self._initialize()

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS offline_targets(
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL UNIQUE COLLATE NOCASE,
          repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
          snapshot_id TEXT REFERENCES snapshots(id) ON DELETE SET NULL,
          channel TEXT,
          distribution TEXT NOT NULL,
          distribution_version TEXT NOT NULL,
          architecture TEXT NOT NULL,
          package_names_json TEXT NOT NULL,
          include_dependencies INTEGER NOT NULL,
          signing_key_id TEXT REFERENCES signing_keys(id) ON DELETE SET NULL,
          host_group_id TEXT,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          created_by TEXT NOT NULL,
          updated_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS offline_bundles(
          id TEXT PRIMARY KEY,
          repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE RESTRICT,
          snapshot_id TEXT,
          base_snapshot_id TEXT,
          target_id TEXT REFERENCES offline_targets(id) ON DELETE SET NULL,
          bundle_type TEXT NOT NULL,
          status TEXT NOT NULL,
          architecture TEXT NOT NULL,
          package_count INTEGER NOT NULL,
          size_bytes INTEGER NOT NULL,
          sha256 TEXT NOT NULL,
          filename TEXT NOT NULL,
          manifest_json TEXT NOT NULL,
          signed INTEGER NOT NULL DEFAULT 0,
          signature_status TEXT NOT NULL DEFAULT 'unsigned',
          signing_fingerprint TEXT NOT NULL DEFAULT '',
          pinned INTEGER NOT NULL DEFAULT 0,
          error TEXT NOT NULL DEFAULT '',
          created_at REAL NOT NULL,
          created_by TEXT NOT NULL,
          imported_at REAL,
          imported_by TEXT
        );
        CREATE TABLE IF NOT EXISTS offline_imports(
          id TEXT PRIMARY KEY,
          bundle_id TEXT NOT NULL,
          repository_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE RESTRICT,
          snapshot_id TEXT REFERENCES snapshots(id) ON DELETE SET NULL,
          status TEXT NOT NULL,
          details_json TEXT NOT NULL,
          created_at REAL NOT NULL,
          created_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS offline_snapshot_origins(
          snapshot_id TEXT PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
          bundle_id TEXT NOT NULL,
          source_snapshot_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS snapshot_freezes(
          snapshot_id TEXT PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
          frozen_at REAL NOT NULL,
          frozen_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS offline_settings(
          id INTEGER PRIMARY KEY CHECK(id=1),
          air_gapped_mode INTEGER NOT NULL,
          keep_last INTEGER NOT NULL,
          delete_after_days INTEGER NOT NULL,
          keep_production INTEGER NOT NULL,
          keep_signed INTEGER NOT NULL,
          updated_at REAL NOT NULL,
          updated_by TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS offline_targets_repository ON offline_targets(repository_id, name);
        CREATE INDEX IF NOT EXISTS offline_bundles_repository_created ON offline_bundles(repository_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS offline_bundles_status_created ON offline_bundles(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS offline_imports_created ON offline_imports(created_at DESC);
        CREATE INDEX IF NOT EXISTS offline_snapshot_origins_source ON offline_snapshot_origins(source_snapshot_id);
        """
        with self.store.connect() as connection:
            connection.executescript(schema)
            connection.execute(
                "INSERT OR IGNORE INTO offline_settings(id,air_gapped_mode,keep_last,delete_after_days,keep_production,keep_signed,updated_at,updated_by) "
                "VALUES(1,0,5,90,1,1,?,?)",
                (time.time(), "system"),
            )

    @staticmethod
    def _bools(item: dict[str, Any] | None, *names: str) -> dict[str, Any] | None:
        if item is None:
            return None
        result = dict(item)
        for name in names:
            if name in result:
                result[name] = bool(result[name])
        return result

    def settings(self) -> dict[str, Any]:
        item = self.store.one("SELECT * FROM offline_settings WHERE id=1") or {}
        return self._bools(item, "air_gapped_mode", "keep_production", "keep_signed") or {}

    def save_settings(self, payload: OfflineSettingsInput, actor: str) -> dict[str, Any]:
        self.store.execute(
            "UPDATE offline_settings SET air_gapped_mode=?,keep_last=?,delete_after_days=?,keep_production=?,keep_signed=?,updated_at=?,updated_by=? WHERE id=1",
            (
                int(payload.air_gapped_mode),
                payload.keep_last,
                payload.delete_after_days,
                int(payload.keep_production),
                int(payload.keep_signed),
                time.time(),
                actor,
            ),
        )
        self.base._audit(
            actor,
            "offline_airgap_enabled" if payload.air_gapped_mode else "offline_airgap_disabled",
            "offline-settings",
            {"air_gapped_mode": payload.air_gapped_mode},
        )
        return self.settings()

    def air_gapped_mode(self) -> bool:
        return bool(self.settings().get("air_gapped_mode"))

    def dashboard(self) -> dict[str, Any]:
        with self.store.connect() as connection:
            counts = {
                "repositories": connection.execute("SELECT COUNT(*) FROM repositories").fetchone()[0],
                "targets": connection.execute("SELECT COUNT(*) FROM offline_targets").fetchone()[0],
                "packages": connection.execute("SELECT COUNT(*) FROM packages").fetchone()[0],
                "snapshots": connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
                "bundles": connection.execute("SELECT COUNT(*) FROM offline_bundles WHERE status!='deleted'").fetchone()[0],
            }
        counts["storage"] = self.storage()
        counts["air_gapped_mode"] = self.air_gapped_mode()
        counts["last_export"] = self._bundle_row(
            self.store.one("SELECT * FROM offline_bundles WHERE status IN ('ready','verified','imported') ORDER BY created_at DESC LIMIT 1")
        )
        return counts

    def targets(self) -> list[dict[str, Any]]:
        return [
            self._bools(item, "include_dependencies") or {}
            for item in self.store.all("SELECT * FROM offline_targets ORDER BY name COLLATE NOCASE")
        ]

    def target(self, target_id: str) -> dict[str, Any] | None:
        return self._bools(self.store.one("SELECT * FROM offline_targets WHERE id=?", (target_id,)), "include_dependencies")

    def save_target(self, payload: OfflineTargetInput, actor: str, target_id: str | None = None) -> dict[str, Any]:
        repository = self.base.repository(payload.repository_id)
        if not repository:
            raise KeyError("repository not found")
        if repository["distribution"] != payload.distribution or repository["distribution_version"] != payload.distribution_version:
            raise ValueError("target distribution does not match repository")
        if payload.architecture not in repository["architectures"]:
            raise ValueError("target architecture is not supported by repository")
        if payload.snapshot_id:
            snapshot = self.base.snapshot(payload.snapshot_id)
            if not snapshot or snapshot["repository_id"] != payload.repository_id:
                raise ValueError("target snapshot does not belong to repository")
        if payload.signing_key_id and not self.base.key(payload.signing_key_id):
            raise KeyError("signing key not found")
        now, item_id = time.time(), target_id or object_id()
        if target_id:
            changed = self.store.execute(
                "UPDATE offline_targets SET name=?,repository_id=?,snapshot_id=?,channel=?,distribution=?,distribution_version=?,architecture=?,"
                "package_names_json=?,include_dependencies=?,signing_key_id=?,host_group_id=?,updated_at=?,updated_by=? WHERE id=?",
                (
                    payload.name,
                    payload.repository_id,
                    payload.snapshot_id,
                    payload.channel.value if payload.channel else None,
                    payload.distribution,
                    payload.distribution_version,
                    payload.architecture,
                    json.dumps(payload.package_names, ensure_ascii=False),
                    int(payload.include_dependencies),
                    payload.signing_key_id,
                    payload.host_group_id,
                    now,
                    actor,
                    target_id,
                ),
            )
            if not changed:
                raise KeyError("offline target not found")
        else:
            self.store.execute(
                "INSERT INTO offline_targets(id,name,repository_id,snapshot_id,channel,distribution,distribution_version,architecture,package_names_json,"
                "include_dependencies,signing_key_id,host_group_id,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item_id,
                    payload.name,
                    payload.repository_id,
                    payload.snapshot_id,
                    payload.channel.value if payload.channel else None,
                    payload.distribution,
                    payload.distribution_version,
                    payload.architecture,
                    json.dumps(payload.package_names, ensure_ascii=False),
                    int(payload.include_dependencies),
                    payload.signing_key_id,
                    payload.host_group_id,
                    now,
                    now,
                    actor,
                    actor,
                ),
            )
        self.base._audit(actor, "offline_target_update" if target_id else "offline_target_create", item_id)
        result = self.target(item_id)
        assert result is not None
        return result

    def delete_target(self, target_id: str, actor: str) -> bool:
        changed = self.store.execute("DELETE FROM offline_targets WHERE id=?", (target_id,))
        if changed:
            self.base._audit(actor, "offline_target_delete", target_id)
        return bool(changed)

    def _resolve_snapshot_id(self, payload: OfflineExportInput) -> str:
        if payload.snapshot_id:
            return payload.snapshot_id
        channel = self.store.one(
            "SELECT snapshot_id FROM channels WHERE repository_id=? AND name=?",
            (payload.repository_id, payload.channel.value if payload.channel else ""),
        )
        if not channel or not channel.get("snapshot_id"):
            raise ValueError("selected channel is not published")
        return str(channel["snapshot_id"])

    @staticmethod
    def _dependency_parts(value: str) -> list[tuple[str, str | None, str | None]]:
        result: list[tuple[str, str | None, str | None]] = []
        for alternative in value.split("|"):
            text = alternative.strip()
            match = DEPENDENCY_NAME.match(text)
            if not match:
                continue
            name = match.group(0).split(":", 1)[0]
            version = DEPENDENCY_VERSION.search(text)
            if version:
                operator = version.group(1) or version.group(3)
                wanted = version.group(2) or version.group(4)
                result.append((name, operator, wanted))
            else:
                result.append((name, None, None))
        return result

    def _version_matches(self, actual: str, operator: str | None, wanted: str | None) -> bool:
        if not operator or not wanted:
            return True
        left, right = self.base._version_key(actual), self.base._version_key(wanted)
        return {
            "=": left == right,
            ">=": left >= right,
            ">": left > right,
            ">>": left > right,
            "<=": left <= right,
            "<": left < right,
            "<<": left < right,
        }.get(operator, False)

    def resolve_dependencies(
        self,
        snapshot_id: str,
        architecture: str,
        package_names: list[str],
        *,
        include_dependencies: bool = True,
    ) -> dict[str, Any]:
        snapshot = self.base.snapshot(snapshot_id)
        if not snapshot:
            raise KeyError("snapshot not found")
        packages = [item for item in snapshot["packages"] if item["architecture"] in {architecture, "all", "noarch"}]
        by_name: dict[str, list[dict[str, Any]]] = {}
        for package in packages:
            by_name.setdefault(str(package["name"]), []).append(package)
        for versions in by_name.values():
            versions.sort(key=lambda item: self.base._version_key(str(item["version"])), reverse=True)

        selected: dict[str, dict[str, Any]] = {}
        missing: list[str] = []
        queue = list(dict.fromkeys(package_names))
        if not queue:
            selected = {str(item["id"]): item for item in packages}
        while queue:
            requested = queue.pop(0)
            alternatives = self._dependency_parts(requested) or [(requested.strip(), None, None)]
            candidate: dict[str, Any] | None = None
            for name, operator, wanted in alternatives:
                for item in by_name.get(name, []):
                    if self._version_matches(str(item["version"]), operator, wanted):
                        candidate = item
                        break
                if candidate:
                    break
            if not candidate:
                if requested not in missing:
                    missing.append(requested)
                continue
            package_id = str(candidate["id"])
            if package_id in selected:
                continue
            selected[package_id] = candidate
            if include_dependencies:
                queue.extend(str(dep) for dep in candidate.get("dependencies", []) if str(dep).strip())

        conflicts: list[dict[str, str]] = []
        selected_names = {str(item["name"]) for item in selected.values()}
        for package in selected.values():
            for conflict in package.get("conflicts", []):
                for name, _operator, _wanted in self._dependency_parts(str(conflict)):
                    if name in selected_names:
                        conflicts.append({"package": str(package["name"]), "conflict": name})

        ordered = sorted(
            selected.values(),
            key=lambda item: (str(item["name"]).casefold(), str(item["architecture"]), self.base._version_key(str(item["version"]))),
        )
        return {
            "packages": ordered,
            "missing": missing,
            "conflicts": conflicts,
            "complete": not missing and not conflicts,
            "package_count": len(ordered),
            "size_bytes": sum(int(item["size_bytes"]) for item in ordered),
        }

    @staticmethod
    def _package_identity(item: dict[str, Any]) -> tuple[str, str]:
        return str(item["name"]), str(item["architecture"])

    def _delta(self, base_snapshot_id: str, target_snapshot_id: str, architecture: str) -> dict[str, Any]:
        first = self.base.snapshot(base_snapshot_id)
        second = self.base.snapshot(target_snapshot_id)
        if not first or not second:
            raise KeyError("snapshot not found")
        if first["repository_id"] != second["repository_id"]:
            raise ValueError("delta snapshots must belong to the same repository")
        allowed = {architecture, "all", "noarch"}
        left = {self._package_identity(item): item for item in first["packages"] if item["architecture"] in allowed}
        right = {self._package_identity(item): item for item in second["packages"] if item["architecture"] in allowed}
        added = [right[key] for key in right.keys() - left.keys()]
        removed = [left[key] for key in left.keys() - right.keys()]
        updated: list[dict[str, Any]] = []
        changed_payload = list(added)
        for key in left.keys() & right.keys():
            if left[key]["sha256"] != right[key]["sha256"]:
                updated.append({"from": left[key], "to": right[key]})
                changed_payload.append(right[key])
        return {
            "added": added,
            "removed": removed,
            "updated": updated,
            "unchanged": len(right) - len(added) - len(updated),
            "payload_packages": changed_payload,
            "target_packages": list(right.values()),
            "payload_size_bytes": sum(int(item["size_bytes"]) for item in changed_payload),
        }

    def plan_export(self, payload: OfflineExportInput) -> dict[str, Any]:
        repository = self.base.repository(payload.repository_id)
        if not repository:
            raise KeyError("repository not found")
        if payload.architecture not in repository["architectures"]:
            raise ValueError("architecture is not supported by repository")
        snapshot_id = self._resolve_snapshot_id(payload)
        snapshot = self.base.snapshot(snapshot_id)
        if not snapshot or snapshot["repository_id"] != payload.repository_id:
            raise ValueError("snapshot does not belong to repository")

        if payload.bundle_type == OfflineBundleType.delta:
            delta = self._delta(str(payload.base_snapshot_id), snapshot_id, payload.architecture)
            selected = delta["payload_packages"]
            missing: list[str] = []
            conflicts: list[dict[str, str]] = []
            target_packages = delta["target_packages"]
            detail = {
                "added": len(delta["added"]),
                "updated": len(delta["updated"]),
                "removed": len(delta["removed"]),
                "unchanged": delta["unchanged"],
            }
        else:
            names = [] if payload.bundle_type == OfflineBundleType.full else payload.package_names
            resolved = self.resolve_dependencies(snapshot_id, payload.architecture, names, include_dependencies=payload.include_dependencies)
            selected = resolved["packages"]
            target_packages = selected
            missing = resolved["missing"]
            conflicts = resolved["conflicts"]
            detail = {}

        available = shutil.disk_usage(self.root).free
        estimated = sum(int(item["size_bytes"]) for item in selected) + max(8 * 1024 * 1024, len(selected) * 4096)
        return {
            "repository_id": payload.repository_id,
            "snapshot_id": snapshot_id,
            "base_snapshot_id": payload.base_snapshot_id,
            "bundle_type": payload.bundle_type.value,
            "architecture": payload.architecture,
            "selected_packages": len(selected),
            "target_packages": len(target_packages),
            "estimated_size_bytes": estimated,
            "available_bytes": available,
            "free_space_ok": available >= estimated * 2,
            "dependency_closure": "COMPLETE" if not missing and not conflicts else "INCOMPLETE",
            "missing": missing,
            "conflicts": conflicts,
            "delta": detail,
            "requires_confirmation": True,
        }

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        atomic_write(path, (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"), 0o640)

    @staticmethod
    def _package_bundle_path(repository: dict[str, Any], package: dict[str, Any]) -> str:
        filename = Path(str(package["relative_path"])).name
        if repository["format"] == "apt":
            initial = str(package["name"])[0].lower() if package["name"] else "_"
            return (Path("repository") / "pool" / "main" / initial / str(package["name"]) / filename).as_posix()
        architecture = str(package["architecture"])
        if architecture == "noarch":
            architecture = str(repository["architectures"][0])
        return (Path("repository") / architecture / "Packages" / filename).as_posix()

    @staticmethod
    def _manifest_package(item: dict[str, Any], bundle_path: str) -> dict[str, Any]:
        keys = (
            "name",
            "version",
            "release",
            "epoch",
            "architecture",
            "format",
            "distribution",
            "size_bytes",
            "sha256",
            "signed",
            "signature_status",
            "maintainer",
            "vendor",
            "description",
            "license",
            "dependencies",
            "conflicts",
            "source",
        )
        result = {key: item.get(key) for key in keys}
        result["bundle_path"] = bundle_path
        return result

    def _file_manifest(self, root: Path) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
            relative = path.relative_to(root).as_posix()
            if relative in {"manifest.json", "manifest.json.asc"}:
                continue
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    digest.update(block)
                    size += len(block)
            files.append({"path": relative, "size": size, "sha256": digest.hexdigest()})
        return files

    @staticmethod
    def _tar_add(tar: tarfile.TarFile, root: Path, path: Path) -> None:
        relative = path.relative_to(root).as_posix()
        info = tar.gettarinfo(str(path), arcname=relative)
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        if info.isdir():
            info.mode = 0o755
            tar.addfile(info)
            return
        info.mode = 0o644
        with path.open("rb") as stream:
            tar.addfile(info, stream)

    def _create_archive(self, root: Path, destination: Path) -> None:
        temporary = destination.with_name(f".{destination.name}-{object_id()}.tmp")
        try:
            with tarfile.open(temporary, mode="w:zst", format=tarfile.PAX_FORMAT) as archive:
                directories = sorted((path for path in root.rglob("*") if path.is_dir()), key=lambda p: p.relative_to(root).as_posix())
                files = sorted((path for path in root.rglob("*") if path.is_file()), key=lambda p: p.relative_to(root).as_posix())
                for path in [*directories, *files]:
                    self._tar_add(archive, root, path)
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
        finally:
            temporary.unlink(missing_ok=True)

    def _sign_manifest(self, manifest: Path, key_id: str) -> tuple[str, str]:
        key = self.store.one("SELECT * FROM signing_keys WHERE id=?", (key_id,))
        if not key or not key["secret_configured"]:
            raise RuntimeError("bundle signing key has no private material")
        if not shutil.which("gpg"):
            raise RuntimeError("gpg is unavailable")
        secret = json.loads(self.base.cipher.decrypt(str(key["encrypted_private_key"]), associated_data=str(key["id"])))
        with tempfile.TemporaryDirectory(dir=self.temporary_root, prefix="sign-") as directory:
            home = Path(directory)
            os.chmod(home, 0o700)
            key_file = home / "key.asc"
            atomic_write(key_file, str(secret["private_key"]).encode("utf-8"), 0o600)
            imported = run_tool(["gpg", "--homedir", str(home), "--batch", "--import", str(key_file)], timeout=60)
            if imported.returncode:
                raise RuntimeError("GPG private key import failed")
            signature = manifest.with_name("manifest.json.asc")
            result = run_tool(
                [
                    "gpg",
                    "--homedir",
                    str(home),
                    "--batch",
                    "--yes",
                    "--armor",
                    "--pinentry-mode",
                    "loopback",
                    "--passphrase-fd",
                    "0",
                    "--local-user",
                    str(key["fingerprint"]),
                    "--detach-sign",
                    "--output",
                    str(signature),
                    str(manifest),
                ],
                timeout=60,
                input_text=str(secret.get("passphrase", "")),
            )
            if result.returncode:
                raise RuntimeError("GPG bundle manifest signing failed")
        return str(key["fingerprint"]), str(key["public_key"])

    def create_bundle(self, payload: OfflineExportInput, actor: str) -> dict[str, Any]:
        if not payload.confirm:
            raise ValueError("offline bundle export requires confirmation")
        plan = self.plan_export(payload)
        if not plan["free_space_ok"]:
            raise RuntimeError("insufficient free space for offline bundle staging")
        if plan["dependency_closure"] != "COMPLETE":
            raise ValueError("dependency closure is incomplete")
        repository = self.base.repository(payload.repository_id)
        snapshot = self.base.snapshot(str(plan["snapshot_id"]))
        assert repository and snapshot

        if payload.bundle_type == OfflineBundleType.delta:
            delta = self._delta(str(payload.base_snapshot_id), str(plan["snapshot_id"]), payload.architecture)
            packages = delta["payload_packages"]
            target_packages = delta["target_packages"]
            removed = [{"name": item["name"], "architecture": item["architecture"], "sha256": item["sha256"]} for item in delta["removed"]]
        else:
            names = [] if payload.bundle_type == OfflineBundleType.full else payload.package_names
            resolved = self.resolve_dependencies(str(plan["snapshot_id"]), payload.architecture, names, include_dependencies=payload.include_dependencies)
            packages = resolved["packages"]
            target_packages = packages
            removed = []

        bundle_id = object_id()
        filename = f"webnas-offline-{repository['distribution']}-{repository['distribution_version']}-{payload.architecture}-{bundle_id[:8]}.tar.zst"
        destination = managed_path(self.bundle_root, filename)
        now = time.time()
        self.store.execute(
            "INSERT INTO offline_bundles(id,repository_id,snapshot_id,base_snapshot_id,target_id,bundle_type,status,architecture,package_count,size_bytes,"
            "sha256,filename,manifest_json,signed,signature_status,signing_fingerprint,pinned,error,created_at,created_by) "
            "VALUES(?,?,?,?,?,?, 'creating', ?,0,0,'',?,'{}',0,'unsigned','',0,'',?,?)",
            (bundle_id, payload.repository_id, plan["snapshot_id"], payload.base_snapshot_id, payload.target_id, payload.bundle_type.value, payload.architecture, filename, now, actor),
        )
        work = Path(tempfile.mkdtemp(dir=self.temporary_root, prefix=f"export-{bundle_id}-"))
        try:
            repository_root = work / "repository"
            adapter = AptRepositoryAdapter(self.root) if repository["format"] == "apt" else RpmRepositoryAdapter(self.root)
            metadata_paths = adapter.publish(repository_root, repository, payload.channel.value if payload.channel else "offline", packages)
            if repository.get("signing_key_id"):
                self.base._sign_generation(metadata_paths, repository)

            package_documents = [self._manifest_package(item, self._package_bundle_path(repository, item)) for item in packages]
            target_documents = [
                {"name": item["name"], "version": item["version"], "architecture": item["architecture"], "sha256": item["sha256"], "size_bytes": item["size_bytes"]}
                for item in target_packages
            ]
            self._write_json(
                work / "metadata" / "repository.json",
                {
                    "id": repository["id"],
                    "name": repository["name"],
                    "format": repository["format"],
                    "distribution": repository["distribution"],
                    "distribution_version": repository["distribution_version"],
                    "architectures": repository["architectures"],
                },
            )
            self._write_json(
                work / "metadata" / "snapshot.json",
                {"id": snapshot["id"], "name": snapshot["name"], "created_at": snapshot["created_at"], "package_count": snapshot["package_count"]},
            )
            self._write_json(work / "metadata" / "packages.json", package_documents)
            if repository.get("signing_key_id"):
                key = self.base.key(str(repository["signing_key_id"]))
                if key:
                    atomic_write(work / "keys" / "repository.asc", str(key["public_key"]).encode("utf-8"), 0o644)

            manifest = {
                "bundle_id": bundle_id,
                "bundle_format_version": BUNDLE_FORMAT_VERSION,
                "repository_id": repository["id"],
                "repository_name": repository["name"],
                "format": repository["format"],
                "distribution": repository["distribution"],
                "distribution_version": repository["distribution_version"],
                "snapshot_id": snapshot["id"],
                "snapshot_name": snapshot["name"],
                "base_snapshot_id": payload.base_snapshot_id,
                "channel": payload.channel.value if payload.channel else None,
                "architecture": payload.architecture,
                "bundle_type": payload.bundle_type.value,
                "package_count": len(packages),
                "target_package_count": len(target_packages),
                "packages": package_documents,
                "target_packages": target_documents,
                "removed_packages": removed,
                "created_at": now,
                "compression": "zstd",
                "metadata_version": 1,
                "signing_fingerprint": "",
                "files": self._file_manifest(work),
            }
            manifest_path = work / "manifest.json"
            self._write_json(manifest_path, manifest)
            fingerprint = ""
            signed = False
            if payload.sign_manifest and repository.get("signing_key_id"):
                fingerprint, public_key = self._sign_manifest(manifest_path, str(repository["signing_key_id"]))
                manifest["signing_fingerprint"] = fingerprint
                self._write_json(manifest_path, manifest)
                manifest_path.with_name("manifest.json.asc").unlink(missing_ok=True)
                self._sign_manifest(manifest_path, str(repository["signing_key_id"]))
                if not (work / "keys" / "repository.asc").exists():
                    atomic_write(work / "keys" / "repository.asc", public_key.encode("utf-8"), 0o644)
                signed = True

            self._create_archive(work, destination)
            archive_digest = hashlib.sha256()
            archive_size = 0
            with destination.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    archive_digest.update(block)
                    archive_size += len(block)
            self.store.execute(
                "UPDATE offline_bundles SET status='ready',package_count=?,size_bytes=?,sha256=?,manifest_json=?,signed=?,signature_status=?,signing_fingerprint=? WHERE id=?",
                (len(packages), archive_size, archive_digest.hexdigest(), json.dumps(manifest, ensure_ascii=False), int(signed), "signed" if signed else "unsigned", fingerprint, bundle_id),
            )
            self.base._audit(
                actor,
                "offline_bundle_created",
                bundle_id,
                {"repository_id": repository["id"], "snapshot_id": snapshot["id"], "bundle_type": payload.bundle_type.value, "packages": len(packages), "size_bytes": archive_size},
            )
            self.apply_retention(actor="retention")
            return self.bundle(bundle_id) or {}
        except Exception as error:
            self.store.execute("UPDATE offline_bundles SET status='failed',error=? WHERE id=?", (str(error)[:2000], bundle_id))
            destination.unlink(missing_ok=True)
            raise
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def bundles(self, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        result = self.store.page("offline_bundles", page=page, page_size=page_size, order="created_at DESC")
        result["items"] = [self._bundle_row(item) for item in result["items"]]
        return result

    def _bundle_row(self, item: dict[str, Any] | None) -> dict[str, Any] | None:
        return self._bools(item, "signed", "pinned")

    def bundle(self, bundle_id: str) -> dict[str, Any] | None:
        return self._bundle_row(self.store.one("SELECT * FROM offline_bundles WHERE id=?", (bundle_id,)))

    def bundle_path(self, bundle_id: str) -> Path:
        item = self.bundle(bundle_id)
        if not item or item["status"] == "deleted":
            raise KeyError("offline bundle not found")
        path = managed_path(self.bundle_root, str(item["filename"]))
        if not path.is_file():
            raise KeyError("offline bundle artifact is missing")
        return path

    def pin_bundle(self, bundle_id: str, payload: BundlePinInput, actor: str) -> dict[str, Any]:
        if not self.bundle(bundle_id):
            raise KeyError("offline bundle not found")
        self.store.execute("UPDATE offline_bundles SET pinned=? WHERE id=?", (int(payload.pinned), bundle_id))
        self.base._audit(actor, "offline_bundle_pin" if payload.pinned else "offline_bundle_unpin", bundle_id)
        return self.bundle(bundle_id) or {}

    def delete_bundle(self, bundle_id: str, actor: str, *, force: bool = False) -> bool:
        item = self.bundle(bundle_id)
        if not item:
            return False
        if item["pinned"] and not force:
            raise ValueError("pinned bundle requires explicit force deletion")
        path = managed_path(self.bundle_root, str(item["filename"]))
        path.unlink(missing_ok=True)
        self.store.execute("UPDATE offline_bundles SET status='deleted' WHERE id=?", (bundle_id,))
        self.base._audit(actor, "offline_bundle_deleted", bundle_id)
        return True

    def apply_retention(self, actor: str = "retention") -> int:
        settings = self.settings()
        keep_last = int(settings["keep_last"])
        cutoff = time.time() - int(settings["delete_after_days"]) * 86400
        candidates = self.store.all("SELECT * FROM offline_bundles WHERE status IN ('ready','verified','imported') ORDER BY created_at DESC")
        removed = 0
        for index, item in enumerate(candidates):
            if index < keep_last or bool(item.get("pinned")):
                continue
            manifest = item.get("manifest") or {}
            if settings["keep_production"] and manifest.get("channel") == "production":
                continue
            if settings["keep_signed"] and bool(item.get("signed")):
                continue
            if float(item["created_at"]) >= cutoff:
                continue
            if self.delete_bundle(str(item["id"]), actor, force=True):
                removed += 1
        return removed

    @staticmethod
    def _staged_id(path: Path) -> str:
        return hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:32]

    def discover_staged(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in sorted(self.staging_root.iterdir()):
            if not path.is_file() or path.is_symlink() or not path.name.endswith(ALLOWED_ARCHIVE_SUFFIXES):
                continue
            result.append({"id": self._staged_id(path), "filename": path.name, "size_bytes": path.stat().st_size, "modified_at": path.stat().st_mtime})
        return result

    def _staged_path(self, staged_id: str) -> Path:
        for item in self.discover_staged():
            if item["id"] == staged_id:
                return managed_path(self.staging_root, str(item["filename"]))
        raise KeyError("staged offline bundle not found")

    def stage_upload(self, filename: str, stream: BinaryIO) -> dict[str, Any]:
        safe_name = Path(filename).name
        if not safe_name.endswith(ALLOWED_ARCHIVE_SUFFIXES):
            raise ValueError("offline bundle must be a .tar.zst, .tzst, .tar.gz or .tgz archive")
        limit = int(self.base.settings()["upload_limit_mb"]) * 1024 * 1024
        stored_name = f"{object_id()}-{safe_name}"
        destination = managed_path(self.staging_root, stored_name)
        size = 0
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            with temporary.open("wb") as target:
                while block := stream.read(1024 * 1024):
                    size += len(block)
                    if size > limit:
                        raise ValueError("offline bundle exceeds configured upload limit")
                    target.write(block)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
        finally:
            temporary.unlink(missing_ok=True)
        return next(item for item in self.discover_staged() if item["filename"] == stored_name)

    @staticmethod
    def _validate_member(member: tarfile.TarInfo, seen: set[str]) -> int:
        name = member.name
        if "\x00" in name or "\\" in name:
            raise ValueError("archive contains an invalid path")
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ValueError("archive path escapes the bundle root")
        folded = name.casefold()
        if folded in seen:
            raise ValueError("archive contains duplicate or case-colliding paths")
        seen.add(folded)
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise ValueError("archive contains a forbidden special entry")
        if not member.isfile() and not member.isdir():
            raise ValueError("archive contains an unsupported entry type")
        if member.size < 0:
            raise ValueError("archive contains an invalid file size")
        return int(member.size) if member.isfile() else 0

    def _safe_extract(self, archive_path: Path, destination: Path) -> None:
        total = 0
        seen: set[str] = set()
        with tarfile.open(archive_path, mode="r:*") as archive:
            members = archive.getmembers()
            if len(members) > MAX_ARCHIVE_FILES:
                raise ValueError("archive contains too many files")
            for member in members:
                total += self._validate_member(member, seen)
                if total > MAX_EXTRACTED_BYTES:
                    raise ValueError("archive exceeds the maximum extracted size")
            for member in members:
                target = managed_path(destination, PurePosixPath(member.name))
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    continue
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("archive file payload is missing")
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with target.open("wb") as output:
                    while block := source.read(1024 * 1024):
                        output.write(block)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(target, 0o600)

    def _verify_signature(self, root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        signature = root / "manifest.json.asc"
        public_key = root / "keys" / "repository.asc"
        expected = str(manifest.get("signing_fingerprint") or "").replace(" ", "").upper()
        if not signature.exists():
            return {"status": "unsigned", "trust": "unsigned", "fingerprint": expected}
        if not public_key.exists():
            return {"status": "invalid", "trust": "unknown", "fingerprint": expected, "error": "public key is missing"}
        if not shutil.which("gpg"):
            return {"status": "unavailable", "trust": "unknown", "fingerprint": expected, "error": "gpg is unavailable"}
        with tempfile.TemporaryDirectory(dir=self.temporary_root, prefix="verify-gpg-") as directory:
            home = Path(directory)
            os.chmod(home, 0o700)
            imported = run_tool(["gpg", "--homedir", str(home), "--batch", "--import", str(public_key)], timeout=60)
            if imported.returncode:
                return {"status": "invalid", "trust": "unknown", "fingerprint": expected, "error": "public key import failed"}
            listing = run_tool(["gpg", "--homedir", str(home), "--batch", "--with-colons", "--list-keys"], timeout=30)
            fingerprints = [line.split(":")[9].upper() for line in listing.stdout.splitlines() if line.startswith("fpr:")]
            if expected and expected not in fingerprints:
                return {"status": "invalid", "trust": "unknown", "fingerprint": expected, "error": "signing fingerprint mismatch"}
            verified = run_tool(["gpg", "--homedir", str(home), "--batch", "--verify", str(signature), str(root / "manifest.json")], timeout=60)
            if verified.returncode:
                return {"status": "invalid", "trust": "unknown", "fingerprint": expected, "error": "manifest signature is invalid"}
        known = bool(expected and self.store.one("SELECT 1 AS present FROM signing_keys WHERE fingerprint=?", (expected,)))
        return {"status": "verified", "trust": "trusted" if known else "unknown", "fingerprint": expected}

    def _verify_extracted(self, root: Path) -> dict[str, Any]:
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file() or manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError("bundle manifest is missing or oversized")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or int(manifest.get("bundle_format_version", 0)) != BUNDLE_FORMAT_VERSION:
            raise ValueError("unsupported offline bundle format version")
        if manifest.get("format") not in {"apt", "rpm"}:
            raise ValueError("bundle repository format is invalid")
        files = manifest.get("files")
        if not isinstance(files, list) or len(files) > MAX_ARCHIVE_FILES:
            raise ValueError("bundle file manifest is invalid")

        declared: set[str] = set()
        errors: list[str] = []
        verified_files = 0
        for item in files:
            if not isinstance(item, dict):
                raise ValueError("bundle file manifest entry is invalid")
            relative = str(item.get("path") or "")
            pure = PurePosixPath(relative)
            if pure.is_absolute() or ".." in pure.parts or "\\" in relative or not relative:
                raise ValueError("bundle file manifest contains an unsafe path")
            if relative.casefold() in declared:
                raise ValueError("bundle file manifest contains duplicate paths")
            declared.add(relative.casefold())
            path = managed_path(root, pure)
            if not path.is_file() or path.is_symlink():
                errors.append(f"missing file: {relative}")
                continue
            expected_size = int(item.get("size", -1))
            if path.stat().st_size != expected_size:
                errors.append(f"size mismatch: {relative}")
                continue
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    digest.update(block)
            if digest.hexdigest() != item.get("sha256"):
                errors.append(f"checksum mismatch: {relative}")
                continue
            verified_files += 1

        actual = {
            path.relative_to(root).as_posix().casefold()
            for path in root.rglob("*")
            if path.is_file() and path.name not in {"manifest.json", "manifest.json.asc"}
        }
        unexpected = sorted(actual - declared)
        if unexpected:
            errors.extend(f"unexpected file: {name}" for name in unexpected[:100])

        packages = manifest.get("packages")
        if not isinstance(packages, list):
            raise ValueError("bundle package metadata is invalid")
        package_errors: list[str] = []
        for package in packages:
            if not isinstance(package, dict):
                package_errors.append("invalid package metadata")
                continue
            relative = str(package.get("bundle_path") or "")
            path = managed_path(root, PurePosixPath(relative))
            if not path.is_file():
                package_errors.append(f"package payload missing: {relative}")
                continue
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    digest.update(block)
            if digest.hexdigest() != package.get("sha256"):
                package_errors.append(f"package checksum mismatch: {relative}")
                continue
            try:
                inspected = self.base._inspect_package(path, RepositoryFormat(str(manifest["format"])))
                if inspected.get("name") != package.get("name") or inspected.get("version") != package.get("version") or inspected.get("architecture") != package.get("architecture"):
                    package_errors.append(f"package metadata mismatch: {relative}")
            except RuntimeError as error:
                package_errors.append(f"package validation unavailable: {error}")
            except ValueError as error:
                package_errors.append(f"invalid package {relative}: {error}")

        signature = self._verify_signature(root, manifest)
        safe = not errors and not package_errors and signature["status"] in {"verified", "unsigned"}
        return {
            "manifest": manifest,
            "manifest_ok": True,
            "files_total": len(files),
            "files_verified": verified_files,
            "packages_total": len(packages),
            "package_errors": package_errors,
            "errors": errors,
            "signature": signature,
            "safe_to_import": safe,
        }

    def verify_staged(self, staged_id: str) -> dict[str, Any]:
        path = self._staged_path(staged_id)
        with tempfile.TemporaryDirectory(dir=self.temporary_root, prefix="verify-") as directory:
            root = Path(directory)
            self._safe_extract(path, root)
            result = self._verify_extracted(root)
        self.base._audit("system", "offline_bundle_verified" if result["safe_to_import"] else "offline_bundle_verification_failed", staged_id, {"filename": path.name, "safe_to_import": result["safe_to_import"]})
        return result

    def inspect_staged(self, staged_id: str) -> dict[str, Any]:
        result = self.verify_staged(staged_id)
        manifest = result["manifest"]
        return {
            "staged_id": staged_id,
            "bundle_id": manifest.get("bundle_id"),
            "repository_name": manifest.get("repository_name"),
            "format": manifest.get("format"),
            "distribution": manifest.get("distribution"),
            "distribution_version": manifest.get("distribution_version"),
            "snapshot_id": manifest.get("snapshot_id"),
            "bundle_type": manifest.get("bundle_type"),
            "architecture": manifest.get("architecture"),
            "package_count": manifest.get("package_count"),
            "created_at": manifest.get("created_at"),
            "signature": result["signature"],
            "safe_to_import": result["safe_to_import"],
            "errors": [*result["errors"], *result["package_errors"]],
        }

    def _create_import_snapshot(self, repository_id: str, source_snapshot_id: str, bundle_id: str, package_ids: list[str], actor: str) -> dict[str, Any]:
        snapshot_id, now = object_id(), time.time()
        name = f"offline-{bundle_id[:12]}-{time.strftime('%Y%m%d%H%M%S', time.gmtime(now))}"
        rows = [self.store.one("SELECT * FROM packages WHERE id=? AND repository_id=?", (package_id, repository_id)) for package_id in package_ids]
        packages = [row for row in rows if row]
        if len(packages) != len(set(package_ids)):
            raise ValueError("imported snapshot references missing package content")
        logical = sum(int(item["size_bytes"]) for item in packages)
        with self.store.connect() as connection:
            connection.execute(
                "INSERT INTO snapshots(id,repository_id,name,description,package_count,logical_size,physical_size,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
                (snapshot_id, repository_id, name, f"Imported from offline bundle {bundle_id}", len(packages), logical, 0, now, actor),
            )
            connection.executemany("INSERT INTO snapshot_packages(snapshot_id,package_id) VALUES(?,?)", [(snapshot_id, package_id) for package_id in sorted(set(package_ids))])
            connection.execute("INSERT INTO offline_snapshot_origins(snapshot_id,bundle_id,source_snapshot_id) VALUES(?,?,?)", (snapshot_id, bundle_id, source_snapshot_id))
        self._write_json(
            self.root / "snapshots" / snapshot_id / "manifest.json",
            {"id": snapshot_id, "repository_id": repository_id, "name": name, "source_bundle_id": bundle_id, "source_snapshot_id": source_snapshot_id, "packages": sorted(set(package_ids))},
        )
        return self.base.snapshot(snapshot_id) or {}

    def import_staged(self, staged_id: str, payload: OfflineImportInput, actor: str) -> dict[str, Any]:
        if not payload.confirm:
            raise ValueError("offline bundle import requires confirmation")
        destination = self.base.repository(payload.repository_id)
        if not destination:
            raise KeyError("destination repository not found")
        path = self._staged_path(staged_id)
        with tempfile.TemporaryDirectory(dir=self.temporary_root, prefix="import-") as directory:
            root = Path(directory)
            self._safe_extract(path, root)
            verification = self._verify_extracted(root)
            if not verification["safe_to_import"]:
                raise ValueError("offline bundle failed integrity verification")
            manifest = verification["manifest"]
            if destination["format"] != manifest["format"] or destination["distribution"] != manifest["distribution"] or destination["distribution_version"] != manifest["distribution_version"]:
                raise ValueError("offline bundle is not compatible with destination repository")
            if manifest["architecture"] not in destination["architectures"]:
                raise ValueError("offline bundle architecture is not supported by destination repository")

            imported_by_sha: dict[str, str] = {}
            for package in manifest["packages"]:
                source = managed_path(root, PurePosixPath(str(package["bundle_path"])))
                with source.open("rb") as stream:
                    imported = self.base.upload_package(payload.repository_id, source.name, stream, actor)
                if imported["sha256"] != package["sha256"]:
                    raise ValueError("package changed while importing")
                imported_by_sha[str(imported["sha256"])] = str(imported["id"])

            target_package_ids: list[str] = []
            for descriptor in manifest.get("target_packages", []):
                checksum = str(descriptor.get("sha256") or "")
                package_id = imported_by_sha.get(checksum)
                if not package_id:
                    existing = self.store.one("SELECT id FROM packages WHERE repository_id=? AND sha256=?", (payload.repository_id, checksum))
                    package_id = str(existing["id"]) if existing else ""
                if not package_id:
                    raise ValueError(f"delta base content is missing for {descriptor.get('name')}")
                target_package_ids.append(package_id)

            if manifest.get("bundle_type") == OfflineBundleType.delta.value:
                base_origin = self.store.one(
                    "SELECT snapshot_id FROM offline_snapshot_origins WHERE source_snapshot_id=? AND snapshot_id IN (SELECT id FROM snapshots WHERE repository_id=?) ORDER BY rowid DESC LIMIT 1",
                    (manifest.get("base_snapshot_id"), payload.repository_id),
                )
                if not base_origin:
                    raise ValueError("delta bundle base snapshot has not been imported on this repository")

            snapshot = self._create_import_snapshot(payload.repository_id, str(manifest["snapshot_id"]), str(manifest["bundle_id"]), target_package_ids, actor)
            if payload.publish_channel:
                if payload.publish_channel == ChannelName.production and payload.confirmation_text != "Production":
                    raise ValueError("Production publication requires typing Production")
                self.base.publish(payload.repository_id, payload.publish_channel, str(snapshot["id"]), actor)

            bundle_id = str(manifest["bundle_id"])
            existing_bundle = self.bundle(bundle_id)
            archive_hash = hashlib.sha256()
            with path.open("rb") as archive_stream:
                while block := archive_stream.read(1024 * 1024):
                    archive_hash.update(block)
            archive_digest = archive_hash.hexdigest()
            if existing_bundle:
                self.store.execute("UPDATE offline_bundles SET status='imported',imported_at=?,imported_by=? WHERE id=?", (time.time(), actor, bundle_id))
            else:
                self.store.execute(
                    "INSERT INTO offline_bundles(id,repository_id,snapshot_id,base_snapshot_id,target_id,bundle_type,status,architecture,package_count,size_bytes,sha256,filename,manifest_json,signed,signature_status,signing_fingerprint,pinned,error,created_at,created_by,imported_at,imported_by) "
                    "VALUES(?,?,?,?,NULL,?,'imported',?,?,?,?,?,?,?, ?,?,?,0,'',?,?,?,?)",
                    (
                        bundle_id,
                        payload.repository_id,
                        manifest.get("snapshot_id"),
                        manifest.get("base_snapshot_id"),
                        manifest.get("bundle_type"),
                        manifest.get("architecture"),
                        int(manifest.get("package_count", 0)),
                        path.stat().st_size,
                        archive_digest,
                        path.name,
                        json.dumps(manifest, ensure_ascii=False),
                        int(verification["signature"]["status"] == "verified"),
                        verification["signature"]["status"],
                        verification["signature"].get("fingerprint", ""),
                        float(manifest.get("created_at") or time.time()),
                        actor,
                        time.time(),
                        actor,
                    ),
                )
            import_id = object_id()
            self.store.execute(
                "INSERT INTO offline_imports(id,bundle_id,repository_id,snapshot_id,status,details_json,created_at,created_by) VALUES(?,?,?,?,?,?,?,?)",
                (
                    import_id,
                    bundle_id,
                    payload.repository_id,
                    snapshot["id"],
                    "completed",
                    json.dumps({"staged_id": staged_id, "packages": len(target_package_ids), "published_channel": payload.publish_channel.value if payload.publish_channel else None}, ensure_ascii=False),
                    time.time(),
                    actor,
                ),
            )
            self.base._audit(actor, "offline_bundle_imported", bundle_id, {"repository_id": payload.repository_id, "snapshot_id": snapshot["id"]})
            return {"import_id": import_id, "bundle_id": bundle_id, "snapshot": snapshot, "published_channel": payload.publish_channel.value if payload.publish_channel else None, "verification": verification}

    def freeze_snapshot(self, snapshot_id: str, actor: str) -> dict[str, Any]:
        snapshot = self.base.snapshot(snapshot_id)
        if not snapshot:
            raise KeyError("snapshot not found")
        self.store.execute("INSERT OR IGNORE INTO snapshot_freezes(snapshot_id,frozen_at,frozen_by) VALUES(?,?,?)", (snapshot_id, time.time(), actor))
        self.base._audit(actor, "snapshot_frozen", snapshot_id)
        frozen = self.store.one("SELECT * FROM snapshot_freezes WHERE snapshot_id=?", (snapshot_id,)) or {}
        return {"snapshot": snapshot, "freeze": frozen}

    def delta_plan(self, base_snapshot_id: str, target_snapshot_id: str, architecture: str) -> dict[str, Any]:
        delta = self._delta(base_snapshot_id, target_snapshot_id, architecture)
        target = self.base.snapshot(target_snapshot_id)
        full_size = sum(int(item["size_bytes"]) for item in (target["packages"] if target else []) if item["architecture"] in {architecture, "all", "noarch"})
        return {
            "base_snapshot_id": base_snapshot_id,
            "target_snapshot_id": target_snapshot_id,
            "architecture": architecture,
            "added": len(delta["added"]),
            "updated": len(delta["updated"]),
            "removed": len(delta["removed"]),
            "unchanged": delta["unchanged"],
            "full_size_bytes": full_size,
            "delta_size_bytes": delta["payload_size_bytes"],
        }

    def storage(self) -> dict[str, Any]:
        package_bytes = int((self.store.one("SELECT COALESCE(SUM(size_bytes),0) AS value FROM packages") or {"value": 0})["value"])
        bundle_bytes = sum(path.stat().st_size for path in self.bundle_root.iterdir() if path.is_file() and not path.is_symlink())
        temporary_bytes = 0
        for root in (self.staging_root, self.temporary_root):
            for path in root.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    try:
                        temporary_bytes += path.stat().st_size
                    except OSError:
                        pass
        logical = int((self.store.one("SELECT COALESCE(SUM(logical_size),0) AS value FROM snapshots") or {"value": 0})["value"])
        physical_content = 0
        for path in (self.root / "content").rglob("*"):
            if path.is_file() and not path.is_symlink():
                try:
                    physical_content += path.stat().st_size
                except OSError:
                    pass
        free = shutil.disk_usage(self.root).free
        return {
            "packages_bytes": package_bytes,
            "bundle_bytes": bundle_bytes,
            "temporary_bytes": temporary_bytes,
            "logical_snapshot_bytes": logical,
            "physical_content_bytes": physical_content,
            "deduplicated_bytes": max(0, logical - physical_content),
            "free_bytes": free,
        }


@lru_cache
def offline_service() -> OfflineRepositoryService:
    return OfflineRepositoryService()
