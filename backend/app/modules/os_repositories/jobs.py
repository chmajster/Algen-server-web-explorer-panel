from __future__ import annotations

import contextlib
import json
import shutil
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any

from ...package_center.executor import redact
from .auth_proxy import authenticated_mirror_proxy
from .repository import object_id
from .security import SAFE_ENV, atomic_write
from .service import RepositoryService, service


class RepositoryJobManager:
    def __init__(self, repository_service: RepositoryService) -> None:
        self.service = repository_service
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="os-repositories")
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self.resume_pending()

    def _air_gapped_mode(self) -> bool:
        try:
            setting = self.service.store.one("SELECT air_gapped_mode FROM offline_settings WHERE id=1")
        except sqlite3.OperationalError:
            return False
        return bool(setting and setting["air_gapped_mode"])

    def resume_pending(self) -> None:
        for job in self.service.store.all("SELECT * FROM repository_sync_jobs WHERE status='queued' AND operation='sync' ORDER BY created_at"):
            self.pool.submit(self._run, str(job["id"]))

    def enqueue_sync(self, repository_id: str, actor: str, retry_of: str | None = None) -> dict[str, Any]:
        if self._air_gapped_mode():
            raise ValueError("repository synchronization is disabled in Air-Gapped Mode")
        repository = self.service.repository(repository_id)
        if not repository:
            raise KeyError("repository not found")
        active = self.service.store.one("SELECT id FROM repository_sync_jobs WHERE repository_id=? AND status IN ('queued','running')", (repository_id,))
        if active:
            raise ValueError("repository operation is already active")
        job_id, now = object_id(), time.time()
        self.service.store.execute(
            "INSERT INTO repository_sync_jobs(id,repository_id,operation,status,stage,progress,current_item,downloaded_count,downloaded_bytes,speed_bps,warnings_json,error,retry_of,created_at,created_by) VALUES(?,?,'sync','queued','queued',0,'',0,0,0,'[]','',?,?,?)",
            (job_id, repository_id, retry_of, now, actor),
        )
        self.service._audit(actor, "sync_queue", job_id, {"repository_id": repository_id, "retry_of": retry_of})
        self.pool.submit(self._run, job_id)
        return self.job(job_id) or {}

    def _log(self, job_id: str, stream: str, line: str) -> None:
        safe = redact(line).replace("\x00", "")[:8192]
        if safe:
            self.service.store.execute("INSERT INTO repository_sync_logs(job_id,stream,line,created_at) VALUES(?,?,?,?)", (job_id, stream, safe, time.time()))

    def _commands(self, repository: dict[str, Any], work: Path, source_url: str | None = None) -> list[list[str]]:
        if repository["kind"] == "local":
            return []
        if repository["format"] == "apt":
            executable = shutil.which("aptly")
            if not executable:
                raise RuntimeError("aptly is unavailable")
            mirror = f"webnas-{repository['id']}"
            config = self.service.root / "config" / f"aptly-{repository['id']}.conf"
            atomic_write(
                config, json.dumps({"rootDir": str(self.service.root / "mirrors" / "aptly" / repository["id"]), "downloadConcurrency": 4}).encode("utf-8")
            )
            base = [executable, f"-config={config}"]
            shown = subprocess.run([*base, "mirror", "show", mirror], capture_output=True, text=True, timeout=30, check=False, shell=False, env=SAFE_ENV)
            commands: list[list[str]] = []
            authenticated = bool(repository.get("auth_secret_configured"))
            if authenticated and not shown.returncode:
                commands.append([*base, "mirror", "drop", "-force", mirror])
            if shown.returncode or authenticated:
                commands.append(
                    [
                        *base,
                        "mirror",
                        "create",
                        f"-architectures={','.join(repository['architectures'])}",
                        mirror,
                        source_url or repository["source_url"],
                        repository["distribution_version"],
                        "main",
                    ]
                )
            commands.append([*base, "mirror", "update", mirror])
            return commands
        executable = shutil.which("dnf") or shutil.which("reposync")
        if not executable:
            raise RuntimeError("dnf/reposync is unavailable")
        if Path(executable).name == "dnf":
            return [
                [
                    executable,
                    "reposync",
                    "--delete",
                    "--download-metadata",
                    "--repoid",
                    "webnas-source",
                    "--repofrompath",
                    f"webnas-source,{source_url or repository['source_url']}",
                    "--download-path",
                    str(work),
                ]
            ]
        raise RuntimeError("standalone reposync cannot safely receive an arbitrary repository URL; install dnf-plugins-core")

    def _ingest_downloads(self, job_id: str, repository: dict[str, Any], work: Path, actor: str) -> tuple[int, int]:
        roots = [work]
        suffix = ".deb" if repository["format"] == "apt" else ".rpm"
        if repository["format"] == "apt":
            roots = [self.service.root / "mirrors" / "aptly" / repository["id"] / "pool"]
        files = sorted(path for root in roots if root.exists() for path in root.rglob(f"*{suffix}") if path.is_file() and not path.is_symlink())
        count = size = 0
        for index, path in enumerate(files, start=1):
            if self.cancel_requested(job_id):
                raise InterruptedError("synchronization cancelled")
            with path.open("rb") as stream:
                package = self.service.upload_package(repository["id"], path.name, stream, actor)
            count += 1
            size += int(package["size_bytes"])
            progress = 65 + int(index / max(1, len(files)) * 15)
            self.service.store.execute(
                "UPDATE repository_sync_jobs SET stage='indexing',progress=?,current_item=?,downloaded_count=?,downloaded_bytes=? WHERE id=?",
                (progress, path.name[:512], count, size, job_id),
            )
        return count, size

    def _run(self, job_id: str) -> None:
        job = self.job(job_id)
        if not job or job["status"] != "queued":
            return
        repository = self.service.repository(str(job["repository_id"]))
        if not repository:
            return
        if self._air_gapped_mode():
            message = "repository synchronization is disabled in Air-Gapped Mode"
            self._log(job_id, "system", message)
            self.service.store.execute(
                "UPDATE repository_sync_jobs SET status='failed',stage='failed',error=?,finished_at=? WHERE id=?",
                (message, time.time(), job_id),
            )
            self.service._audit(str(job["created_by"]), "sync_blocked_air_gapped", job_id, {"repository_id": repository["id"]})
            return
        now = time.time()
        self.service.store.execute("UPDATE repository_sync_jobs SET status='running',stage='preparing',progress=5,started_at=? WHERE id=?", (now, job_id))
        work = self.service.root / "temporary" / f"sync-{job_id}"
        work.mkdir(parents=True, exist_ok=True)
        try:
            if repository["source_url"]:
                from .security import validate_mirror_url

                addresses = validate_mirror_url(
                    repository["source_url"], allow_private_network=repository["allow_private_network"], allow_private_http=repository["allow_private_http"]
                )
                self._log(job_id, "system", f"Source DNS validated: {', '.join(addresses)}")
            authorization = self.service.mirror_authorization(str(repository["id"]))
            proxy_context = (
                authenticated_mirror_proxy(
                    repository["source_url"],
                    authorization,
                    allow_private_network=repository["allow_private_network"],
                    allow_private_http=repository["allow_private_http"],
                )
                if authorization
                else contextlib.nullcontext(repository.get("source_url"))
            )
            with proxy_context as sync_source:
                commands = self._commands(repository, work, sync_source)
                if commands:
                    self.service.store.execute("UPDATE repository_sync_jobs SET stage='downloading',progress=15 WHERE id=?", (job_id,))
                    for command in commands:
                        process = subprocess.Popen(command, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False, env=SAFE_ENV)
                        with self._lock:
                            self._processes[job_id] = process
                        try:
                            stdout, stderr = process.communicate(timeout=7200)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.communicate()
                            raise RuntimeError("repository synchronization exceeded the two-hour timeout")
                        for line in stdout.splitlines()[-2000:]:
                            self._log(job_id, "stdout", line)
                        for line in stderr.splitlines()[-2000:]:
                            self._log(job_id, "stderr", line)
                        if self.cancel_requested(job_id):
                            raise InterruptedError("synchronization cancelled")
                        if process.returncode:
                            raise RuntimeError(f"repository tool exited with code {process.returncode}")
                    count, downloaded = self._ingest_downloads(job_id, repository, work, str(job["created_by"]))
                    self._log(job_id, "system", f"Indexed {count} packages ({downloaded} bytes)")
            self.service.store.execute("UPDATE repository_sync_jobs SET stage='validating',progress=80 WHERE id=?", (job_id,))
            self._log(job_id, "system", "Synchronization completed; the last published snapshot remains unchanged")
            finished = time.time()
            self.service.store.execute(
                "UPDATE repository_sync_jobs SET status='completed',stage='completed',progress=100,finished_at=? WHERE id=?", (finished, job_id)
            )
            self.service.store.execute(
                "UPDATE repositories SET last_sync_at=?,last_sync_status='completed',updated_at=?,updated_by=? WHERE id=?",
                (finished, finished, job["created_by"], repository["id"]),
            )
            self.service._audit(str(job["created_by"]), "sync_complete", job_id, {"repository_id": repository["id"]})
        except InterruptedError as error:
            self._log(job_id, "system", str(error))
            self.service.store.execute(
                "UPDATE repository_sync_jobs SET status='cancelled',stage='cancelled',error='',finished_at=? WHERE id=?", (time.time(), job_id)
            )
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
            message = redact(str(error))[:2000]
            self._log(job_id, "stderr", message)
            self.service.store.execute(
                "UPDATE repository_sync_jobs SET status='failed',stage='failed',error=?,finished_at=? WHERE id=?", (message, time.time(), job_id)
            )
            self.service.store.execute("UPDATE repositories SET last_sync_at=?,last_sync_status='failed' WHERE id=?", (time.time(), repository["id"]))
        finally:
            with self._lock:
                self._processes.pop(job_id, None)
            shutil.rmtree(work, ignore_errors=True)

    def cancel_requested(self, job_id: str) -> bool:
        item = self.service.store.one("SELECT cancel_requested FROM repository_sync_jobs WHERE id=? AND operation='sync'", (job_id,))
        return bool(item and item["cancel_requested"])

    def cancel(self, job_id: str, actor: str) -> dict[str, Any]:
        job = self.job(job_id)
        if not job:
            raise KeyError("job not found")
        if job["status"] not in {"queued", "running"}:
            raise ValueError("job is already finished")
        self.service.store.execute("UPDATE repository_sync_jobs SET cancel_requested=1 WHERE id=?", (job_id,))
        with self._lock:
            process = self._processes.get(job_id)
            if process and process.poll() is None:
                process.terminate()
        if job["status"] == "queued":
            self.service.store.execute("UPDATE repository_sync_jobs SET status='cancelled',stage='cancelled',finished_at=? WHERE id=?", (time.time(), job_id))
        self.service._audit(actor, "job_cancel", job_id)
        return self.job(job_id) or {}

    def retry(self, job_id: str, actor: str) -> dict[str, Any]:
        job = self.job(job_id)
        if not job:
            raise KeyError("job not found")
        if job["status"] not in {"failed", "cancelled"}:
            raise ValueError("only failed or cancelled jobs can be retried")
        return self.enqueue_sync(str(job["repository_id"]), actor, retry_of=job_id)

    def job(self, job_id: str) -> dict[str, Any] | None:
        item = self.service.store.one("SELECT * FROM repository_sync_jobs WHERE id=? AND operation='sync'", (job_id,))
        if item:
            item["logs"] = self.logs(job_id, 200)
        return item

    def jobs(self, page: int = 1, page_size: int = 50, status: str = "") -> dict[str, Any]:
        where = "operation='sync'"
        values: tuple[Any, ...] = ()
        if status:
            where += " AND status=?"
            values = (status,)
        return self.service.store.page(
            "repository_sync_jobs",
            page=page,
            page_size=page_size,
            order="created_at DESC",
            where=where,
            values=values,
        )

    def logs(self, job_id: str, limit: int = 500) -> list[dict[str, Any]]:
        return list(reversed(self.service.store.all("SELECT * FROM repository_sync_logs WHERE job_id=? ORDER BY id DESC LIMIT ?", (job_id, limit))))


@lru_cache
def manager() -> RepositoryJobManager:
    return RepositoryJobManager(service())
