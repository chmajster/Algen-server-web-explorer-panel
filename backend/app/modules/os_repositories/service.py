from __future__ import annotations

import fnmatch
import base64
import hashlib
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import tarfile
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO

from ...activity import ActivityCategory, record_activity
from ...config import get_config
from ..ansible_controller.public_security import CredentialCipher
from .adapters import AptRepositoryAdapter, RpmRepositoryAdapter
from .models import (
    BackupInput,
    ChannelName,
    FilterRuleInput,
    HostAssignmentInput,
    PackageBuildInput,
    RepositoryFormat,
    RepositoryInput,
    SettingsInput,
    SigningKeyGenerateInput,
    SigningKeyInput,
    SnapshotInput,
)
from .repository import RepositoryStore, object_id
from .security import atomic_write, decrypt_backup_payload, encrypt_backup_payload, managed_path, run_tool, validate_mirror_url


class RepositoryService:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(get_config().paths.data_dir) / "os-repositories"
        self.store = RepositoryStore(self.root)
        self.cipher = CredentialCipher(self.root.parent / "secrets" / "os-repositories.key")

    def dashboard(self) -> dict[str, Any]:
        with self.store.connect() as connection:
            counts = {
                "repositories": connection.execute("SELECT COUNT(*) FROM repositories").fetchone()[0],
                "packages": connection.execute("SELECT COUNT(*) FROM packages").fetchone()[0],
                "snapshots": connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
                "published_channels": connection.execute("SELECT COUNT(*) FROM channels WHERE snapshot_id IS NOT NULL").fetchone()[0],
                "hosts": connection.execute("SELECT COUNT(*) FROM host_assignments").fetchone()[0],
                "pending_packages": connection.execute(
                    "SELECT COUNT(*) FROM packages p WHERE NOT EXISTS(SELECT 1 FROM snapshot_packages sp WHERE sp.package_id=p.id)"
                ).fetchone()[0],
                "running_jobs": connection.execute("SELECT COUNT(*) FROM repository_sync_jobs WHERE status IN ('queued','running')").fetchone()[0],
                "errors": connection.execute(
                    "SELECT COUNT(*) FROM repository_sync_jobs WHERE status='failed' AND created_at> ?", (time.time() - 86400,)
                ).fetchone()[0],
                "size_bytes": connection.execute("SELECT COALESCE(SUM(size_bytes),0) FROM packages").fetchone()[0],
            }
        counts["recent_jobs"] = self.store.all("SELECT * FROM repository_sync_jobs ORDER BY created_at DESC LIMIT 8")
        counts["expiring_keys"] = self.store.all(
            "SELECT id,name,fingerprint,expires_at,status FROM signing_keys WHERE expires_at IS NOT NULL AND expires_at < ? ORDER BY expires_at",
            (time.time() + 30 * 86400,),
        )
        return counts

    def repositories(self, page: int = 1, page_size: int = 50, search: str = "") -> dict[str, Any]:
        result = self.store.page("repositories", page=page, page_size=page_size, search=search, order="name COLLATE NOCASE")
        result["items"] = [self._public_repository(item) for item in result["items"]]
        return result

    @staticmethod
    def _public_repository(item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        result["auth_secret_configured"] = bool(result.pop("encrypted_auth_secret", ""))
        return result

    def repository(self, repository_id: str) -> dict[str, Any] | None:
        item = self.store.one("SELECT * FROM repositories WHERE id=?", (repository_id,))
        if item:
            item["channels"] = self.store.all("SELECT * FROM channels WHERE repository_id=? ORDER BY name", (repository_id,))
            item["filters"] = self.store.all("SELECT * FROM repository_filters WHERE repository_id=? ORDER BY version DESC", (repository_id,))
        return self._public_repository(item) if item else None

    def mirror_authorization(self, repository_id: str) -> str:
        item = self.store.one("SELECT auth_type,auth_username,encrypted_auth_secret FROM repositories WHERE id=?", (repository_id,))
        if not item or item["auth_type"] == "none":
            return ""
        secret = self.cipher.decrypt(str(item["encrypted_auth_secret"]), associated_data=repository_id)
        if item["auth_type"] == "bearer":
            return f"Bearer {secret}"
        encoded = base64.b64encode(f"{item['auth_username']}:{secret}".encode()).decode()
        return f"Basic {encoded}"

    def save_repository(self, payload: RepositoryInput, actor: str, repository_id: str | None = None) -> dict[str, Any]:
        resolved: list[str] = []
        if payload.source_url:
            resolved = validate_mirror_url(
                payload.source_url, allow_private_network=payload.allow_private_network, allow_private_http=payload.allow_private_http
            )
        now, item_id = time.time(), repository_id or object_id()
        current = self.store.one("SELECT encrypted_auth_secret FROM repositories WHERE id=?", (item_id,)) if repository_id else None
        encrypted_secret = str(current["encrypted_auth_secret"] or "") if current else ""
        if payload.auth_type.value == "none":
            encrypted_secret = ""
        elif payload.auth_secret:
            encrypted_secret = self.cipher.encrypt(payload.auth_secret, associated_data=item_id)
        elif not encrypted_secret:
            raise ValueError("mirror authentication secret is required")
        auth_username = payload.auth_username if payload.auth_type.value == "basic" else ""
        values = (
            payload.name,
            payload.description,
            payload.kind.value,
            payload.format.value,
            payload.distribution,
            payload.distribution_version,
            json.dumps(payload.architectures),
            payload.source_url,
            int(payload.active),
            payload.schedule,
            payload.retention_count,
            payload.signing_key_id,
            int(payload.allow_private_network),
            int(payload.allow_private_http),
            payload.auth_type.value,
            auth_username,
            encrypted_secret,
            now,
            actor,
        )
        with self.store.connect() as connection:
            if repository_id:
                changed = connection.execute(
                    "UPDATE repositories SET name=?,description=?,kind=?,format=?,distribution=?,distribution_version=?,architectures_json=?,source_url=?,active=?,schedule=?,retention_count=?,signing_key_id=?,allow_private_network=?,allow_private_http=?,auth_type=?,auth_username=?,encrypted_auth_secret=?,updated_at=?,updated_by=? WHERE id=?",
                    (*values, item_id),
                ).rowcount
                if not changed:
                    raise KeyError("repository not found")
            else:
                connection.execute(
                    "INSERT INTO repositories(id,name,description,kind,format,distribution,distribution_version,architectures_json,source_url,active,schedule,retention_count,signing_key_id,allow_private_network,allow_private_http,auth_type,auth_username,encrypted_auth_secret,created_at,updated_at,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (item_id, *values[:-2], now, now, actor, actor),
                )
                for channel in ChannelName:
                    connection.execute(
                        "INSERT INTO channels(id,repository_id,name,updated_at,updated_by) VALUES(?,?,?,?,?)", (object_id(), item_id, channel.value, now, actor)
                    )
            connection.execute("DELETE FROM repository_architectures WHERE repository_id=?", (item_id,))
            connection.executemany(
                "INSERT INTO repository_architectures(repository_id,architecture) VALUES(?,?)",
                [(item_id, architecture) for architecture in payload.architectures],
            )
            connection.execute("DELETE FROM repository_sources WHERE repository_id=?", (item_id,))
            if payload.source_url:
                connection.execute(
                    "INSERT INTO repository_sources(id,repository_id,url,resolved_addresses_json,validated_at) VALUES(?,?,?,?,?)",
                    (object_id(), item_id, payload.source_url, json.dumps(resolved), now),
                )
        self._audit(actor, "repository_update" if repository_id else "repository_create", item_id, {"format": payload.format.value, "kind": payload.kind.value})
        result = self.repository(item_id)
        assert result
        return result

    def delete_repository(self, repository_id: str, actor: str) -> bool:
        if self.store.one("SELECT 1 AS present FROM host_assignments WHERE repository_id=? LIMIT 1", (repository_id,)):
            raise ValueError("repository is assigned to hosts")
        changed = self.store.execute("DELETE FROM repositories WHERE id=?", (repository_id,))
        if changed:
            self._audit(actor, "repository_delete", repository_id)
        return bool(changed)

    def save_filter(self, repository_id: str, payload: FilterRuleInput, actor: str) -> dict[str, Any]:
        if not self.repository(repository_id):
            raise KeyError("repository not found")
        version = int(
            (self.store.one("SELECT COALESCE(MAX(version),0)+1 AS version FROM repository_filters WHERE repository_id=?", (repository_id,)) or {"version": 1})[
                "version"
            ]
        )
        item_id = object_id()
        self.store.execute("UPDATE repository_filters SET active=0 WHERE repository_id=?", (repository_id,))
        self.store.execute(
            "INSERT INTO repository_filters(id,repository_id,version,name,rules_json,active,created_at,created_by) VALUES(?,?,?,?,?,1,?,?)",
            (item_id, repository_id, version, payload.name, json.dumps(payload.model_dump(mode="json")), time.time(), actor),
        )
        self._audit(actor, "filter_create", repository_id, {"filter_id": item_id, "version": version})
        return self.store.one("SELECT * FROM repository_filters WHERE id=?", (item_id,)) or {}

    def filter_preview(self, repository_id: str, payload: FilterRuleInput) -> dict[str, Any]:
        packages = self.store.all("SELECT * FROM packages WHERE repository_id=? ORDER BY name LIMIT 5000", (repository_id,))
        included, rejected = self._filter_packages(packages, payload)
        return {
            "included": len(included),
            "rejected": len(rejected),
            "examples": [{"name": item["name"], "version": item["version"]} for item in (included[:5] + rejected[:5])],
            "estimated_size": sum(int(item["size_bytes"]) for item in included),
            "sample_limited": len(packages) == 5000,
        }

    def _filter_packages(self, packages: list[dict[str, Any]], payload: FilterRuleInput) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        included: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        include_re = re.compile(payload.include_regex) if payload.include_regex else None
        exclude_re = re.compile(payload.exclude_regex) if payload.exclude_regex else None
        for package in packages:
            name = package["name"]
            accepted = True
            if payload.include_names and name not in payload.include_names:
                accepted = False
            if payload.exclude_names and name in payload.exclude_names:
                accepted = False
            if payload.include_globs and not any(fnmatch.fnmatchcase(name, pattern) for pattern in payload.include_globs):
                accepted = False
            if payload.exclude_globs and any(fnmatch.fnmatchcase(name, pattern) for pattern in payload.exclude_globs):
                accepted = False
            if include_re and not include_re.search(name):
                accepted = False
            if exclude_re and exclude_re.search(name):
                accepted = False
            if payload.architectures and package["architecture"] not in payload.architectures:
                accepted = False
            if payload.minimum_version and self._version_key(package["version"]) < self._version_key(payload.minimum_version):
                accepted = False
            if payload.maximum_version and self._version_key(package["version"]) > self._version_key(payload.maximum_version):
                accepted = False
            if payload.maximum_size and package["size_bytes"] > payload.maximum_size:
                accepted = False
            published = package.get("published_at") or package["created_at"]
            if payload.minimum_published_at and published < payload.minimum_published_at:
                accepted = False
            if payload.maximum_published_at and published > payload.maximum_published_at:
                accepted = False
            if payload.exclude_source and package["architecture"] in {"source", "src", "nosrc"}:
                accepted = False
            if payload.exclude_debug and (name.endswith("-dbg") or name.endswith("-debuginfo")):
                accepted = False
            if payload.exclude_devel and (name.endswith("-dev") or name.endswith("-devel")):
                accepted = False
            (included if accepted else rejected).append(package)
        if payload.latest_versions:
            retained: list[dict[str, Any]] = []
            groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for package in included:
                groups.setdefault((package["name"], package["architecture"]), []).append(package)
            for versions in groups.values():
                retained.extend(sorted(versions, key=lambda item: self._version_key(item["version"]), reverse=True)[: payload.latest_versions])
            retained_ids = {item["id"] for item in retained}
            rejected.extend(item for item in included if item["id"] not in retained_ids)
            included = retained
        return included, rejected

    @staticmethod
    def _version_key(value: str) -> tuple[tuple[int, int | str], ...]:
        return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.findall(r"\d+|[^\d]+", value))

    def _inspect_package(self, path: Path, expected: RepositoryFormat) -> dict[str, Any]:
        header = path.read_bytes()[:8]
        actual = RepositoryFormat.apt if header.startswith(b"!<arch>\n") else RepositoryFormat.rpm if header.startswith(b"\xed\xab\xee\xdb") else None
        if actual != expected:
            raise ValueError("package extension or declared format does not match its content")
        if actual == RepositoryFormat.apt:
            if not shutil.which("dpkg-deb"):
                raise RuntimeError("dpkg-deb is unavailable")
            result = run_tool(
                [
                    "dpkg-deb",
                    "--show",
                    "--showformat=${Package}\t${Version}\t${Architecture}\t${Maintainer}\t${Description}\t${Depends}\t${Conflicts}\n",
                    str(path),
                ],
                timeout=60,
            )
            if result.returncode:
                raise ValueError("invalid DEB package")
            values = result.stdout.strip().split("\t", 6)
            if len(values) < 7:
                raise ValueError("DEB metadata is incomplete")
            return {
                "name": values[0],
                "version": values[1],
                "release": "",
                "epoch": "",
                "architecture": values[2],
                "maintainer": values[3],
                "description": values[4],
                "dependencies": [v.strip() for v in values[5].split(",") if v.strip()],
                "conflicts": [v.strip() for v in values[6].split(",") if v.strip()],
                "vendor": "",
                "license": "",
            }
        if not shutil.which("rpm"):
            raise RuntimeError("rpm is unavailable")
        result = run_tool(
            ["rpm", "-qp", "--qf", "%{NAME}\t%{VERSION}\t%{RELEASE}\t%{EPOCHNUM}\t%{ARCH}\t%{PACKAGER}\t%{SUMMARY}\t%{VENDOR}\t%{LICENSE}\n", str(path)],
            timeout=60,
        )
        if result.returncode:
            raise ValueError("invalid RPM package")
        values = result.stdout.strip().split("\t")
        if len(values) < 9:
            raise ValueError("RPM metadata is incomplete")
        return {
            "name": values[0],
            "version": values[1],
            "release": values[2],
            "epoch": values[3],
            "architecture": values[4],
            "maintainer": values[5],
            "description": values[6],
            "vendor": values[7],
            "license": values[8],
            "dependencies": [],
            "conflicts": [],
        }

    def upload_package(self, repository_id: str, filename: str, stream: BinaryIO, actor: str) -> dict[str, Any]:
        repository = self.repository(repository_id)
        if not repository:
            raise KeyError("repository not found")
        expected = RepositoryFormat(repository["format"])
        suffix = ".deb" if expected == RepositoryFormat.apt else ".rpm"
        if Path(filename).suffix.lower() != suffix:
            raise ValueError(f"only {suffix} packages are accepted")
        limit = int(self.settings()["upload_limit_mb"]) * 1024 * 1024
        digest, size = hashlib.sha256(), 0
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root / "temporary", prefix="upload-", suffix=suffix, delete=False) as handle:
                temporary = Path(handle.name)
                while block := stream.read(1024 * 1024):
                    size += len(block)
                    if size > limit:
                        raise ValueError("package exceeds the configured upload limit")
                    digest.update(block)
                    handle.write(block)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            if temporary:
                temporary.unlink(missing_ok=True)
            raise
        assert temporary is not None
        try:
            metadata = self._inspect_package(temporary, expected)
            signature_status = "not_checked"
            if expected == RepositoryFormat.rpm and shutil.which("rpm"):
                signature = run_tool(["rpm", "--checksig", str(temporary)], timeout=30)
                signature_status = (
                    "valid"
                    if signature.returncode == 0 and any(marker in signature.stdout.casefold() for marker in ("pgp", "rsa", "signature"))
                    else "unsigned"
                    if signature.returncode == 0
                    else "invalid"
                )
            elif expected == RepositoryFormat.apt and shutil.which("dpkg-sig"):
                signature = run_tool(["dpkg-sig", "--verify", str(temporary)], timeout=30)
                signature_status = "valid" if signature.returncode == 0 else "invalid"
            checksum = digest.hexdigest()
            existing = self.store.one("SELECT * FROM packages WHERE repository_id=? AND sha256=?", (repository_id, checksum))
            if existing:
                return existing
            destination = managed_path(self.root / "content", Path(checksum[:2]) / checksum / f"{metadata['name']}{suffix}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                temporary.unlink()
            else:
                os.replace(temporary, destination)
            os.chmod(destination, 0o640)
            item_id, now = object_id(), time.time()
            self.store.execute(
                "INSERT INTO packages(id,repository_id,name,version,release,epoch,architecture,format,distribution,size_bytes,sha256,relative_path,signed,signature_status,maintainer,vendor,description,license,dependencies_json,conflicts_json,source,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    item_id,
                    repository_id,
                    metadata["name"],
                    metadata["version"],
                    metadata["release"],
                    metadata["epoch"],
                    metadata["architecture"],
                    expected.value,
                    repository["distribution"],
                    size,
                    checksum,
                    str(destination.relative_to(self.root)),
                    int(signature_status == "valid"),
                    signature_status,
                    metadata["maintainer"],
                    metadata["vendor"],
                    metadata["description"],
                    metadata["license"],
                    json.dumps(metadata["dependencies"]),
                    json.dumps(metadata["conflicts"]),
                    "upload",
                    now,
                    actor,
                ),
            )
            self.store.execute(
                "UPDATE repositories SET package_count=(SELECT COUNT(*) FROM packages WHERE repository_id=?),size_bytes=(SELECT COALESCE(SUM(size_bytes),0) FROM packages WHERE repository_id=?),updated_at=?,updated_by=? WHERE id=?",
                (repository_id, repository_id, now, actor, repository_id),
            )
            self._audit(actor, "package_upload", item_id, {"repository_id": repository_id, "sha256": checksum, "size": size})
            return self.store.one("SELECT * FROM packages WHERE id=?", (item_id,)) or {}
        finally:
            temporary.unlink(missing_ok=True)

    def packages(self, page: int = 1, page_size: int = 50, search: str = "", repository_id: str = "") -> dict[str, Any]:
        where, values = ("repository_id=?", (repository_id,)) if repository_id else ("", ())
        return self.store.page("packages", page=page, page_size=page_size, search=search, order="name COLLATE NOCASE,version DESC", where=where, values=values)

    def package(self, package_id: str) -> dict[str, Any] | None:
        return self.store.one("SELECT * FROM packages WHERE id=?", (package_id,))

    def delete_package(self, package_id: str, actor: str) -> bool:
        if self.store.one("SELECT 1 AS present FROM snapshot_packages WHERE package_id=? LIMIT 1", (package_id,)):
            raise ValueError("packages contained in immutable snapshots cannot be deleted")
        item = self.package(package_id)
        if not item:
            return False
        changed = self.store.execute("DELETE FROM packages WHERE id=?", (package_id,))
        if changed:
            self._audit(actor, "package_delete", package_id)
        return bool(changed)

    def create_snapshot(self, repository_id: str, payload: SnapshotInput, actor: str) -> dict[str, Any]:
        repository = self.repository(repository_id)
        if not repository:
            raise KeyError("repository not found")
        now = time.time()
        name = payload.name or time.strftime("snapshot-%Y%m%d-%H%M%S", time.gmtime(now))
        snapshot_id = object_id()
        packages = self.store.all("SELECT * FROM packages WHERE repository_id=? AND blocked=0", (repository_id,))
        active_filter = self.store.one("SELECT * FROM repository_filters WHERE repository_id=? AND active=1 ORDER BY version DESC LIMIT 1", (repository_id,))
        if active_filter:
            packages, _ = self._filter_packages(packages, FilterRuleInput.model_validate(active_filter["rules"]))
        with self.store.connect() as connection:
            logical = sum(int(row["size_bytes"]) for row in packages)
            connection.execute(
                "INSERT INTO snapshots(id,repository_id,name,description,package_count,logical_size,physical_size,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
                (snapshot_id, repository_id, name, payload.description, len(packages), logical, 0, now, actor),
            )
            connection.executemany("INSERT INTO snapshot_packages(snapshot_id,package_id) VALUES(?,?)", [(snapshot_id, row["id"]) for row in packages])
        atomic_write(
            self.root / "snapshots" / snapshot_id / "manifest.json",
            json.dumps(
                {"id": snapshot_id, "repository_id": repository_id, "name": name, "packages": [row["id"] for row in packages]}, ensure_ascii=False
            ).encode(),
        )
        self._audit(actor, "snapshot_create", snapshot_id, {"repository_id": repository_id, "packages": len(packages)})
        retained = self.store.all(
            "SELECT id FROM snapshots WHERE repository_id=? ORDER BY created_at DESC LIMIT -1 OFFSET ?",
            (repository_id, int(repository["retention_count"])),
        )
        for old_snapshot in retained:
            try:
                self.delete_snapshot(old_snapshot["id"], "retention")
            except ValueError:
                # Published snapshots remain protected even when they exceed the
                # configured automatic retention window.
                continue
        return self.snapshot(snapshot_id) or {}

    def snapshots(self, page: int = 1, page_size: int = 50, repository_id: str = "") -> dict[str, Any]:
        return self.store.page(
            "snapshots",
            page=page,
            page_size=page_size,
            order="created_at DESC",
            where="repository_id=?" if repository_id else "",
            values=(repository_id,) if repository_id else (),
        )

    def snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        item = self.store.one("SELECT * FROM snapshots WHERE id=?", (snapshot_id,))
        if item:
            item["packages"] = self.store.all(
                "SELECT p.* FROM packages p JOIN snapshot_packages sp ON sp.package_id=p.id WHERE sp.snapshot_id=? ORDER BY p.name,p.architecture,p.version",
                (snapshot_id,),
            )
        return item

    def compare_snapshots(self, first_id: str, second_id: str) -> dict[str, Any]:
        first, second = self.snapshot(first_id), self.snapshot(second_id)
        if not first or not second:
            raise KeyError("snapshot not found")

        def keyed(items: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
            return {(item["name"], item["architecture"]): item for item in items}

        left, right = keyed(first["packages"]), keyed(second["packages"])
        added = [right[key] for key in right.keys() - left.keys()]
        removed = [left[key] for key in left.keys() - right.keys()]
        updated: list[dict[str, Any]] = []
        downgraded: list[dict[str, Any]] = []
        checksums: list[dict[str, Any]] = []
        for key in left.keys() & right.keys():
            if left[key]["version"] != right[key]["version"]:
                (updated if self._version_key(right[key]["version"]) > self._version_key(left[key]["version"]) else downgraded).append(
                    {"from": left[key], "to": right[key]}
                )
            elif left[key]["sha256"] != right[key]["sha256"]:
                checksums.append({"from": left[key], "to": right[key]})
        return {
            "first": first_id,
            "second": second_id,
            "added": added,
            "removed": removed,
            "updated": updated,
            "downgraded": downgraded,
            "checksum_changes": checksums,
        }

    def publish(self, repository_id: str, channel: ChannelName, snapshot_id: str, actor: str, *, action: str = "publish") -> dict[str, Any]:
        repository, snapshot = self.repository(repository_id), self.snapshot(snapshot_id)
        if not repository or not snapshot or snapshot["repository_id"] != repository_id:
            raise KeyError("repository or snapshot not found")
        channel_row = self.store.one("SELECT * FROM channels WHERE repository_id=? AND name=?", (repository_id, channel.value))
        assert channel_row
        if channel is ChannelName.production and action == "publish":
            testing = self.store.one("SELECT snapshot_id FROM channels WHERE repository_id=? AND name='testing'", (repository_id,))
            if not testing or testing.get("snapshot_id") != snapshot_id:
                raise ValueError("Production can only promote the snapshot currently published in Testing")
        generation = self.root / "published" / ".generations" / object_id()
        generation.mkdir(parents=True, mode=0o755)
        try:
            adapter = AptRepositoryAdapter(self.root) if repository["format"] == "apt" else RpmRepositoryAdapter(self.root)
            metadata = adapter.publish(generation, repository, channel.value, snapshot["packages"])
            if repository.get("signing_key_id"):
                self._sign_generation(metadata, repository)
        except Exception:
            shutil.rmtree(generation, ignore_errors=True)
            raise
        pointer = self.root / "published" / repository_id / channel.value
        pointer.parent.mkdir(parents=True, exist_ok=True)
        previous = channel_row.get("snapshot_id")
        temporary = pointer.with_name(f".{pointer.name}-{object_id()}")
        os.symlink(generation, temporary, target_is_directory=True)
        try:
            os.replace(temporary, pointer)
        except PermissionError:
            if os.name != "nt" or not pointer.exists():
                raise
            previous_pointer = pointer.with_name(f".{pointer.name}-previous-{object_id()}")
            os.replace(pointer, previous_pointer)
            try:
                os.replace(temporary, pointer)
            except Exception:
                os.replace(previous_pointer, pointer)
                raise
            if previous_pointer.is_dir() and not previous_pointer.is_symlink():
                shutil.rmtree(previous_pointer)
            else:
                previous_pointer.unlink(missing_ok=True)
        publication_id, now = object_id(), time.time()
        self.store.execute(
            "UPDATE channels SET previous_snapshot_id=snapshot_id,snapshot_id=?,updated_at=?,updated_by=? WHERE id=?",
            (snapshot_id, now, actor, channel_row["id"]),
        )
        self.store.execute(
            "INSERT INTO channel_publications(id,channel_id,snapshot_id,previous_snapshot_id,action,created_at,created_by) VALUES(?,?,?,?,?,?,?)",
            (publication_id, channel_row["id"], snapshot_id, previous, action, now, actor),
        )
        self._audit(actor, f"channel_{action}", channel_row["id"], {"snapshot_id": snapshot_id, "previous_snapshot_id": previous})
        return self.store.one("SELECT * FROM channels WHERE id=?", (channel_row["id"],)) or {}

    def rollback_channel(self, channel_id: str, actor: str) -> dict[str, Any]:
        channel = self.store.one("SELECT * FROM channels WHERE id=?", (channel_id,))
        if not channel:
            raise KeyError("channel not found")
        previous = channel.get("previous_snapshot_id")
        if not previous:
            raise ValueError("channel has no previous snapshot")
        return self.publish(channel["repository_id"], ChannelName(channel["name"]), previous, actor, action="rollback")

    def channel_plan(self, channel_id: str, snapshot_id: str) -> dict[str, Any]:
        channel = self.store.one("SELECT * FROM channels WHERE id=?", (channel_id,))
        snapshot = self.snapshot(snapshot_id)
        if not channel or not snapshot or snapshot["repository_id"] != channel["repository_id"]:
            raise KeyError("channel or snapshot not found")
        differences = (
            self.compare_snapshots(channel["snapshot_id"], snapshot_id)
            if channel.get("snapshot_id")
            else {"added": snapshot["packages"], "removed": [], "updated": [], "downgraded": [], "checksum_changes": []}
        )
        return {
            "channel_id": channel_id,
            "channel": channel["name"],
            "current_snapshot_id": channel.get("snapshot_id"),
            "target_snapshot_id": snapshot_id,
            "differences": differences,
            "requires_confirmation": True,
            "confirmation_text": "Production" if channel["name"] == "production" else "",
        }

    def _sign_generation(self, metadata: list[Path], repository: dict[str, Any]) -> None:
        key = self.store.one("SELECT * FROM signing_keys WHERE id=?", (repository["signing_key_id"],))
        if not key or not key["secret_configured"]:
            raise RuntimeError("repository signing key has no private material")
        secret = json.loads(self.cipher.decrypt(key["encrypted_private_key"], associated_data=key["id"]))
        with tempfile.TemporaryDirectory(dir=self.root / "temporary", prefix="gnupg-") as directory:
            home = Path(directory)
            os.chmod(home, 0o700)
            key_file = home / "key.asc"
            atomic_write(key_file, secret["private_key"].encode())
            imported = run_tool(["gpg", "--homedir", str(home), "--batch", "--import", str(key_file)], timeout=60)
            if imported.returncode:
                raise RuntimeError("GPG private key import failed")
            listing = run_tool(["gpg", "--homedir", str(home), "--batch", "--with-colons", "--list-secret-keys", key["fingerprint"]], timeout=30)
            if listing.returncode or key["fingerprint"].casefold() not in listing.stdout.casefold():
                raise RuntimeError("GPG fingerprint verification failed")
            common = [
                "gpg",
                "--homedir",
                str(home),
                "--batch",
                "--yes",
                "--pinentry-mode",
                "loopback",
                "--passphrase-fd",
                "0",
                "--local-user",
                key["fingerprint"],
            ]
            for source in metadata:
                detached = source.with_name("Release.gpg") if repository["format"] == "apt" else source.with_suffix(source.suffix + ".asc")
                signed = run_tool(
                    [*common, "--armor", "--detach-sign", "--output", str(detached), str(source)], timeout=60, input_text=secret.get("passphrase", "")
                )
                if signed.returncode:
                    raise RuntimeError("GPG metadata signing failed")
                if repository["format"] == "apt":
                    inrelease = run_tool(
                        [*common, "--armor", "--clearsign", "--output", str(source.with_name("InRelease")), str(source)],
                        timeout=60,
                        input_text=secret.get("passphrase", ""),
                    )
                    if inrelease.returncode:
                        raise RuntimeError("GPG InRelease signing failed")

    def channels(self) -> list[dict[str, Any]]:
        return self.store.all(
            "SELECT c.*,r.name AS repository_name,r.format,r.distribution,r.distribution_version FROM channels c JOIN repositories r ON r.id=c.repository_id ORDER BY r.name,c.name"
        )

    def delete_snapshot(self, snapshot_id: str, actor: str) -> bool:
        if self.store.one("SELECT 1 AS present FROM channels WHERE snapshot_id=? OR previous_snapshot_id=? LIMIT 1", (snapshot_id, snapshot_id)):
            raise ValueError("snapshot is used by a publication channel")
        changed = self.store.execute("DELETE FROM snapshots WHERE id=?", (snapshot_id,))
        if changed:
            shutil.rmtree(self.root / "snapshots" / snapshot_id, ignore_errors=True)
            self._audit(actor, "snapshot_delete", snapshot_id)
        return bool(changed)

    def save_key(self, payload: SigningKeyInput, actor: str) -> dict[str, Any]:
        fingerprint = payload.fingerprint.replace(" ", "").upper()
        if shutil.which("gpg"):
            with tempfile.TemporaryDirectory(dir=self.root / "temporary", prefix="key-check-") as directory:
                public = Path(directory) / "public.asc"
                atomic_write(public, payload.public_key.encode("utf-8"))
                result = run_tool(["gpg", "--batch", "--with-colons", "--import-options", "show-only", "--import", str(public)], timeout=30)
                found = [line.split(":")[9].upper() for line in result.stdout.splitlines() if line.startswith("fpr:")]
                if result.returncode or fingerprint not in found:
                    raise ValueError("public key fingerprint does not match the supplied fingerprint")
        item_id = object_id()
        encrypted = (
            self.cipher.encrypt(json.dumps({"private_key": payload.private_key, "passphrase": payload.passphrase}), associated_data=item_id)
            if payload.private_key
            else ""
        )
        self.store.execute(
            "INSERT INTO signing_keys(id,name,fingerprint,public_key,encrypted_private_key,secret_configured,expires_at,status,created_at,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                item_id,
                payload.name,
                fingerprint,
                payload.public_key,
                encrypted,
                int(bool(payload.private_key)),
                payload.expires_at,
                "active",
                time.time(),
                actor,
            ),
        )
        atomic_write(self.root / "published" / "keys" / f"{fingerprint}.asc", payload.public_key.encode("utf-8"), 0o644)
        self._audit(actor, "key_import", item_id, {"fingerprint": fingerprint, "secret_configured": bool(payload.private_key)})
        return self.key(item_id) or {}

    def generate_key(self, payload: SigningKeyGenerateInput, actor: str) -> dict[str, Any]:
        if not payload.confirm:
            raise ValueError("key generation requires confirmation")
        if not shutil.which("gpg"):
            raise RuntimeError("gpg is unavailable")
        with tempfile.TemporaryDirectory(dir=self.root / "temporary", prefix="key-generate-") as directory:
            home = Path(directory)
            os.chmod(home, 0o700)
            common = ["gpg", "--homedir", str(home), "--batch", "--yes", "--pinentry-mode", "loopback", "--passphrase-fd", "0"]
            generated = run_tool(
                [*common, "--quick-generate-key", payload.identity, "rsa3072", "sign", payload.expires], timeout=120, input_text=payload.passphrase
            )
            if generated.returncode:
                raise RuntimeError("GPG key generation failed")
            listed = run_tool(["gpg", "--homedir", str(home), "--batch", "--with-colons", "--list-secret-keys", payload.identity], timeout=30)
            fingerprints = [line.split(":")[9] for line in listed.stdout.splitlines() if line.startswith("fpr:")]
            if not fingerprints:
                raise RuntimeError("generated GPG fingerprint is unavailable")
            fingerprint = fingerprints[0]
            public = run_tool(["gpg", "--homedir", str(home), "--batch", "--armor", "--export", fingerprint], timeout=30)
            private = run_tool([*common, "--armor", "--export-secret-keys", fingerprint], timeout=60, input_text=payload.passphrase)
            if public.returncode or private.returncode or not private.stdout:
                raise RuntimeError("generated GPG key could not be exported")
        return self.save_key(
            SigningKeyInput(name=payload.name, public_key=public.stdout, private_key=private.stdout, passphrase=payload.passphrase, fingerprint=fingerprint),
            actor,
        )

    def keys(self) -> list[dict[str, Any]]:
        return self.store.all("SELECT id,name,fingerprint,public_key,secret_configured,expires_at,status,created_at,created_by FROM signing_keys ORDER BY name")

    def key(self, key_id: str) -> dict[str, Any] | None:
        return self.store.one(
            "SELECT id,name,fingerprint,public_key,secret_configured,expires_at,status,created_at,created_by FROM signing_keys WHERE id=?", (key_id,)
        )

    def delete_key(self, key_id: str, actor: str) -> bool:
        key = self.key(key_id)
        if not key:
            return False
        if self.store.one("SELECT 1 AS present FROM repositories WHERE signing_key_id=? LIMIT 1", (key_id,)):
            raise ValueError("signing key is assigned to a repository")
        changed = self.store.execute("DELETE FROM signing_keys WHERE id=?", (key_id,))
        if changed:
            (self.root / "published" / "keys" / f"{key['fingerprint']}.asc").unlink(missing_ok=True)
            self._audit(actor, "key_delete", key_id, {"fingerprint": key["fingerprint"]})
        return bool(changed)

    def save_assignment(self, payload: HostAssignmentInput, actor: str) -> dict[str, Any]:
        if not self.repository(payload.repository_id):
            raise KeyError("repository not found")
        item_id = object_id()
        self.store.execute(
            "INSERT INTO host_assignments(id,repository_id,channel,host_id,group_id,created_at,created_by) VALUES(?,?,?,?,?,?,?)",
            (item_id, payload.repository_id, payload.channel.value, payload.host_id, payload.group_id, time.time(), actor),
        )
        self._audit(actor, "host_assignment_create", item_id)
        return self.store.one("SELECT * FROM host_assignments WHERE id=?", (item_id,)) or {}

    def assignments(self) -> list[dict[str, Any]]:
        return self.store.all(
            "SELECT a.*,r.name AS repository_name,r.format,r.distribution,r.distribution_version,r.architectures_json FROM host_assignments a JOIN repositories r ON r.id=a.repository_id ORDER BY a.created_at DESC"
        )

    def delete_assignment(self, assignment_id: str, actor: str) -> bool:
        changed = self.store.execute("DELETE FROM host_assignments WHERE id=?", (assignment_id,))
        if changed:
            self._audit(actor, "host_assignment_delete", assignment_id)
        return bool(changed)

    def host_configuration(self, assignment_id: str) -> dict[str, str]:
        item = self.store.one(
            "SELECT a.*,r.name AS repository_name,r.format,r.distribution,r.distribution_version,r.signing_key_id,k.fingerprint FROM host_assignments a JOIN repositories r ON r.id=a.repository_id LEFT JOIN signing_keys k ON k.id=r.signing_key_id WHERE a.id=?",
            (assignment_id,),
        )
        if not item:
            raise KeyError("assignment not found")
        settings = self.settings()
        base = settings["public_base_url"].rstrip("/") or f"http://{settings['listen_address']}:{settings['port']}"
        path = f"{base}/{item['repository_id']}/{item['channel']}"
        if item["format"] == "apt":
            signed = " [signed-by=/usr/share/keyrings/webnas-repository.gpg]" if item.get("fingerprint") else ""
            return {
                "format": "apt",
                "filename": f"webnas-{item['repository_id'][:8]}.list",
                "content": f"deb{signed} {path} {item['distribution_version']} main\n",
                "public_key_url": f"{base}/keys/{item['fingerprint']}.asc" if item.get("fingerprint") else "",
            }
        repo_name = re.sub(r"[^A-Za-z0-9_-]", "-", item["repository_name"]).lower()
        gpg = f"gpgcheck=1\ngpgkey={base}/keys/{item['fingerprint']}.asc\n" if item.get("fingerprint") else "gpgcheck=0\n"
        return {
            "format": "rpm",
            "filename": f"webnas-{repo_name}.repo",
            "content": f"[{repo_name}-{item['channel']}]\nname={item['repository_name']} {item['channel']}\nbaseurl={path}/$basearch/\nenabled=1\n{gpg}",
            "public_key_url": f"{base}/keys/{item['fingerprint']}.asc" if item.get("fingerprint") else "",
        }

    def settings(self) -> dict[str, Any]:
        return (self.store.one("SELECT * FROM settings WHERE id=1") or {"value": {}})["value"]

    def save_settings(self, payload: SettingsInput, actor: str) -> dict[str, Any]:
        try:
            with socket.socket(socket.AF_INET6 if ":" in payload.listen_address else socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((payload.listen_address, payload.port))
        except OSError as error:
            raise ValueError("repository server address or port is already in use") from error
        self.store.execute(
            "UPDATE settings SET value_json=?,updated_at=?,updated_by=? WHERE id=1", (json.dumps(payload.model_dump(mode="json")), time.time(), actor)
        )
        default_root = Path(get_config().paths.data_dir) / "os-repositories"
        if self.root == default_root:
            config = Path(os.environ.get("WEBNAS_OS_REPOSITORIES_CONFIG", "/etc/webnas/os-repositories.yaml"))
            atomic_write(config, f"listen_address: {payload.listen_address}\nport: {payload.port}\n".encode("utf-8"), 0o644)
            if shutil.which("systemctl"):
                restarted = run_tool(["systemctl", "restart", "webnas-repository-server.service"], timeout=60)
                if restarted.returncode:
                    raise RuntimeError("repository server configuration was saved but the service restart failed")
        self._audit(actor, "settings_update", "settings")
        return self.settings()

    def diagnostics(self) -> dict[str, Any]:
        tools: dict[str, dict[str, str]] = {}
        for name in ("dpkg-deb", "aptly", "rpm", "rpmbuild", "createrepo_c", "gpg", "reposync"):
            tool_path = shutil.which(name)
            version = ""
            if tool_path:
                try:
                    result = run_tool([tool_path, "--version"], timeout=5)
                    version = (result.stdout or result.stderr).splitlines()[0][:256]
                except (OSError, subprocess.SubprocessError, ValueError):
                    version = "version unavailable"
            tools[name] = {"path": tool_path or "", "version": version}
        with self.store.connect() as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        usage = shutil.disk_usage(self.root)
        packages = self.store.all("SELECT id,relative_path,sha256 FROM packages")
        missing, corrupt = 0, 0
        for package in packages:
            try:
                package_path = managed_path(self.root, package["relative_path"])
            except ValueError:
                missing += 1
                continue
            if not package_path.is_file():
                missing += 1
            elif hashlib.sha256(package_path.read_bytes()).hexdigest() != package["sha256"]:
                corrupt += 1
        orphaned_snapshots = int(
            (
                self.store.one("SELECT COUNT(*) AS count FROM snapshot_packages sp LEFT JOIN packages p ON p.id=sp.package_id WHERE p.id IS NULL")
                or {"count": 0}
            )["count"]
        )
        expired_keys = int(
            (self.store.one("SELECT COUNT(*) AS count FROM signing_keys WHERE expires_at IS NOT NULL AND expires_at<?", (time.time(),)) or {"count": 0})[
                "count"
            ]
        )
        settings = self.settings()
        host = settings["listen_address"]
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1" if host == "0.0.0.0" else "::1"
        try:
            with socket.create_connection((host, int(settings["port"])), timeout=2):
                http_status = "ok"
        except OSError:
            http_status = "warning"
        checks = [
            {"id": "sqlite", "status": "ok" if integrity == "ok" else "error", "message": integrity},
            {"id": "schema", "status": "ok" if version == 1 else "error", "message": str(version)},
            {"id": "free_space", "status": "ok" if usage.free > 1024**3 else "warning", "message": str(usage.free)},
            {
                "id": "root_permissions",
                "status": "ok" if os.name == "nt" or self.root.stat().st_mode & 0o077 == 0 else "error",
                "message": oct(self.root.stat().st_mode & 0o777),
            },
            {"id": "package_files", "status": "ok" if not missing and not corrupt else "error", "message": f"missing={missing} checksum_errors={corrupt}"},
            {"id": "snapshot_consistency", "status": "ok" if not orphaned_snapshots else "error", "message": f"orphaned={orphaned_snapshots}"},
            {"id": "gpg_keys", "status": "ok" if not expired_keys else "warning", "message": f"expired={expired_keys}"},
            {"id": "http_service", "status": http_status, "message": f"{settings['listen_address']}:{settings['port']}"},
        ]
        checks += [
            {"id": f"tool_{name}", "status": "ok" if item["path"] else "warning", "message": f"{item['path']} {item['version']}".strip() or "not installed"}
            for name, item in tools.items()
        ]
        return {"checks": checks, "tools": tools, "root": str(self.root), "settings": self.settings()}

    def history(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.store.all("SELECT * FROM audit_metadata ORDER BY created_at DESC LIMIT ?", (limit,))

    def builds(self) -> list[dict[str, Any]]:
        return self.store.all("SELECT * FROM package_builds ORDER BY created_at DESC LIMIT 200")

    def build_package(self, payload: PackageBuildInput, actor: str) -> dict[str, Any]:
        repository = self.repository(payload.repository_id)
        if not repository or repository["format"] != payload.format.value:
            raise ValueError("build format must match the destination repository")
        if not payload.confirm:
            raise ValueError("package build requires confirmation")
        build_id, now = object_id(), time.time()
        workspace = self.root / "builds" / build_id
        workspace.mkdir(mode=0o700)
        log_path = workspace / "build.log"
        self.store.execute(
            "INSERT INTO package_builds(id,repository_id,format,definition_json,status,log_path,error,created_at,created_by) VALUES(?,?,?,?,? ,?,'',?,?)",
            (
                build_id,
                payload.repository_id,
                payload.format.value,
                json.dumps(payload.model_dump(mode="json")),
                "running",
                str(log_path.relative_to(self.root)),
                now,
                actor,
            ),
        )
        try:
            if payload.format == RepositoryFormat.apt:
                if not shutil.which("dpkg-deb"):
                    raise RuntimeError("dpkg-deb is unavailable")
                root = workspace / "root"
                control = root / "DEBIAN"
                control.mkdir(parents=True)
                fields = f"Package: {payload.name}\nVersion: {payload.version}\nArchitecture: {payload.architecture}\nMaintainer: {payload.maintainer or actor}\nDescription: {payload.description}\n"
                if payload.dependencies:
                    fields += f"Depends: {', '.join(payload.dependencies)}\n"
                if payload.conflicts:
                    fields += f"Conflicts: {', '.join(payload.conflicts)}\n"
                if payload.homepage:
                    fields += f"Homepage: {payload.homepage}\n"
                atomic_write(control / "control", fields.encode())
                names = {"pre_install": "preinst", "post_install": "postinst", "pre_remove": "prerm", "post_remove": "postrm"}
                for key, script in payload.maintainer_scripts.items():
                    atomic_write(control / names[key], script.encode(), 0o700)
                config_paths: list[str] = []
                for item in payload.files:
                    target = managed_path(root, item.target_path.lstrip("/"))
                    atomic_write(target, base64.b64decode(item.content_base64), int(item.mode, 8))
                    if item.config_file:
                        config_paths.append(item.target_path)
                if config_paths:
                    atomic_write(control / "conffiles", ("\n".join(config_paths) + "\n").encode("utf-8"))
                output = workspace / f"{payload.name}_{payload.version}_{payload.architecture}.deb"
                result = run_tool(["dpkg-deb", "--build", "--root-owner-group", str(root), str(output)], timeout=300)
            else:
                if not shutil.which("rpmbuild"):
                    raise RuntimeError("rpmbuild is unavailable")
                top = workspace / "rpmbuild"
                for name in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
                    (top / name).mkdir(parents=True)
                install_lines, file_lines = ["rm -rf %{buildroot}", "mkdir -p %{buildroot}"], []
                for index, item in enumerate(payload.files):
                    source_name = f"file-{index}"
                    atomic_write(top / "SOURCES" / source_name, base64.b64decode(item.content_base64), 0o600)
                    install_lines.append(f"install -D -m {item.mode} %{{_sourcedir}}/{source_name} %{{buildroot}}{item.target_path}")
                    prefix = "%config(noreplace) " if item.config_file else ""
                    file_lines.append(f"{prefix}%attr({item.mode},{item.owner},{item.group}) {item.target_path}")
                script_sections = {"pre_install": "%pre", "post_install": "%post", "pre_remove": "%preun", "post_remove": "%postun"}
                scripts = "\n".join(f"{script_sections[key]}\n{content}" for key, content in payload.maintainer_scripts.items())
                headers = f"Name: {payload.name}\nVersion: {payload.version}\nRelease: {payload.release}\nSummary: {payload.description.splitlines()[0]}\nLicense: {payload.license or 'Proprietary'}\nBuildArch: {payload.architecture}\n"
                if payload.vendor:
                    headers += f"Vendor: {payload.vendor}\n"
                if payload.homepage:
                    headers += f"URL: {payload.homepage}\n"
                if payload.dependencies:
                    headers += "Requires: " + ", ".join(payload.dependencies) + "\n"
                if payload.conflicts:
                    headers += "Conflicts: " + ", ".join(payload.conflicts) + "\n"
                spec = f"{headers}%description\n{payload.description}\n%prep\n%build\n%install\n{chr(10).join(install_lines)}\n{scripts}\n%files\n{chr(10).join(file_lines)}\n"
                spec_path = top / "SPECS" / f"{payload.name}.spec"
                atomic_write(spec_path, spec.encode())
                result = run_tool(["rpmbuild", "--define", f"_topdir {top}", "-bb", str(spec_path)], timeout=600)
                candidates = list((top / "RPMS").rglob("*.rpm"))
                output = candidates[0] if candidates else workspace / "missing.rpm"
            for item in payload.files:
                raw = base64.b64decode(item.content_base64)
                self.store.execute(
                    "INSERT INTO package_build_files(id,build_id,source_name,target_path,owner,group_name,mode,size_bytes,sha256) VALUES(?,?,?,?,?,?,?,?,?)",
                    (object_id(), build_id, item.source_name, item.target_path, item.owner, item.group, item.mode, len(raw), hashlib.sha256(raw).hexdigest()),
                )
            atomic_write(log_path, f"{result.stdout}\n{result.stderr}".encode())
            if result.returncode or not output.is_file():
                raise RuntimeError("package build failed")
            with output.open("rb") as stream:
                package = self.upload_package(payload.repository_id, output.name, stream, actor)
            self.store.execute("UPDATE package_builds SET status='completed',package_id=?,finished_at=? WHERE id=?", (package["id"], time.time(), build_id))
            self._audit(actor, "package_build", build_id, {"package_id": package["id"]})
        except Exception as error:
            self.store.execute("UPDATE package_builds SET status='failed',error=?,finished_at=? WHERE id=?", (str(error)[:2000], time.time(), build_id))
            raise
        return self.store.one("SELECT * FROM package_builds WHERE id=?", (build_id,)) or {}

    def create_backup(self, payload: BackupInput, actor: str) -> dict[str, Any]:
        if not payload.confirm:
            raise ValueError("backup requires confirmation")
        backup_id = f"os-repositories-{int(time.time())}-{object_id()[:8]}"
        staging = self.root / "temporary" / backup_id
        staging.mkdir(mode=0o700)
        database = staging / "repositories.sqlite3"
        with self.store.connect() as source, closing(sqlite3.connect(database)) as destination_database:
            source.backup(destination_database)
            destination_database.commit()
        private_keys: list[dict[str, str]] = []
        with closing(sqlite3.connect(database)) as backup_database:
            backup_database.row_factory = sqlite3.Row
            for row in backup_database.execute("SELECT id,encrypted_private_key FROM signing_keys WHERE secret_configured=1"):
                private_keys.append({"id": row["id"], "secret": self.cipher.decrypt(row["encrypted_private_key"], associated_data=row["id"])})
            backup_database.execute("UPDATE signing_keys SET encrypted_private_key='',secret_configured=0")
            backup_database.commit()
        encrypted_keys = staging / "private-keys.enc"
        if payload.include_private_keys and private_keys:
            atomic_write(encrypted_keys, encrypt_backup_payload(json.dumps(private_keys).encode("utf-8"), payload.passphrase))
        files = {"repositories.sqlite3": hashlib.sha256(database.read_bytes()).hexdigest()}
        if encrypted_keys.exists():
            files[encrypted_keys.name] = hashlib.sha256(encrypted_keys.read_bytes()).hexdigest()
        manifest = {
            "module": "os-repositories",
            "schema_version": 1,
            "created_at": time.time(),
            "description": payload.description,
            "include_content": payload.include_content,
            "private_keys": encrypted_keys.exists(),
            "files": files,
        }
        atomic_write(staging / "manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode())
        backup_path = self.root / "backups" / f"{backup_id}.tar.gz"
        with tarfile.open(backup_path, "w:gz") as archive:

            def add_file(path: Path, arcname: str) -> None:
                # Constructing TarInfo ourselves avoids platform user/group lookups,
                # keeps archive metadata deterministic, and never follows links.
                data = path.read_bytes()
                info = tarfile.TarInfo(arcname)
                info.size = len(data)
                info.mode = 0o600
                info.mtime = int(path.stat().st_mtime)
                archive.addfile(info, io.BytesIO(data))

            add_file(database, "repositories.sqlite3")
            add_file(staging / "manifest.json", "manifest.json")
            if encrypted_keys.exists():
                add_file(encrypted_keys, encrypted_keys.name)
            if payload.include_content:
                content_root = self.root / "content"
                for path in sorted(content_root.rglob("*")):
                    if path.is_file() and not path.is_symlink():
                        add_file(path, (Path("content") / path.relative_to(content_root)).as_posix())
        shutil.rmtree(staging)
        os.chmod(backup_path, 0o600)
        checksum = hashlib.sha256(backup_path.read_bytes()).hexdigest()
        self._audit(actor, "backup_create", backup_id, {"include_content": payload.include_content})
        return {
            "id": backup_id,
            "filename": backup_path.name,
            "size": backup_path.stat().st_size,
            "checksum": checksum,
            "created_at": backup_path.stat().st_mtime,
            "include_content": payload.include_content,
        }

    def backups(self) -> list[dict[str, Any]]:
        return [
            {
                "id": path.name.removesuffix(".tar.gz"),
                "filename": path.name,
                "size": path.stat().st_size,
                "checksum": hashlib.sha256(path.read_bytes()).hexdigest(),
                "created_at": path.stat().st_mtime,
            }
            for path in sorted((self.root / "backups").glob("os-repositories-*.tar.gz"), reverse=True)
        ]

    def restore_backup(self, backup_id: str, checksum: str, confirmation: str, actor: str, private_keys_passphrase: str = "") -> dict[str, Any]:
        if confirmation != "Repozytoria systemowe":
            raise ValueError("restore requires typing Repozytoria systemowe")
        if not re.fullmatch(r"os-repositories-[A-Za-z0-9_-]+", backup_id):
            raise ValueError("invalid backup identifier")
        path = self.root / "backups" / f"{backup_id}.tar.gz"
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise ValueError("backup checksum mismatch")
        safety = self.create_backup(BackupInput(description="Automatic safety backup", confirm=True), actor)
        temporary = self.root / "temporary" / f"restore-{object_id()}.sqlite3"
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if any(
                member.name.startswith(("/", "\\")) or ".." in Path(member.name).parts or member.issym() or member.islnk() or member.size > 20 * 1024**3
                for member in members
            ):
                raise ValueError("backup contains an unsafe member")
            manifest_file = archive.extractfile("manifest.json")
            if manifest_file is None:
                raise ValueError("backup manifest is missing")
            manifest = json.load(manifest_file)
            if manifest.get("module") != "os-repositories" or manifest.get("schema_version") != 1:
                raise ValueError("backup schema is not supported")
            source = archive.extractfile("repositories.sqlite3")
            if source is None:
                raise ValueError("backup database is missing")
            with temporary.open("wb") as output:
                shutil.copyfileobj(source, output)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != manifest.get("files", {}).get("repositories.sqlite3"):
                raise ValueError("backup database checksum mismatch")
            encrypted_file = archive.extractfile("private-keys.enc") if manifest.get("private_keys") else None
            encrypted_keys = encrypted_file.read() if encrypted_file else b""
            if encrypted_keys and hashlib.sha256(encrypted_keys).hexdigest() != manifest.get("files", {}).get("private-keys.enc"):
                raise ValueError("private-key backup checksum mismatch")
        try:
            with closing(sqlite3.connect(temporary)) as connection:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("backup database failed integrity check")
                if encrypted_keys:
                    restored_keys = json.loads(decrypt_backup_payload(encrypted_keys, private_keys_passphrase))
                    for key in restored_keys:
                        secret = str(key["secret"])
                        envelope = self.cipher.encrypt(secret, associated_data=str(key["id"]))
                        connection.execute("UPDATE signing_keys SET encrypted_private_key=?,secret_configured=1 WHERE id=?", (envelope, key["id"]))
                    connection.commit()
            os.replace(temporary, self.store.path)
            os.chmod(self.store.path, 0o600)
            self.store._initialize()
            self._audit(actor, "backup_restore", backup_id, {"safety_backup": safety["id"]})
            return {"ok": True, "safety_backup": safety["id"]}
        finally:
            temporary.unlink(missing_ok=True)

    def full_remove(self, confirmation: str, force: bool, actor: str) -> dict[str, Any]:
        if confirmation != "Repozytoria systemowe":
            raise ValueError("full removal requires typing Repozytoria systemowe")
        assignments = self.store.one("SELECT COUNT(*) AS count FROM host_assignments") or {"count": 0}
        if assignments["count"] and not force:
            raise ValueError("host assignments must be removed or force must be explicitly confirmed")
        size = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file() and not path.is_symlink())
        self._audit(actor, "full_remove", "os-repositories", {"bytes": size, "forced": force})
        shutil.rmtree(self.root)
        return {"ok": True, "removed_bytes": size}

    def _audit(self, actor: str, action: str, target: str, details: dict[str, Any] | None = None) -> None:
        self.store.audit(actor, action, target, details)
        record_activity(ActivityCategory.module, f"os_repositories_{action}", actor, target=target, details=details or {}, source="os-repositories")


@lru_cache
def service() -> RepositoryService:
    return RepositoryService()
