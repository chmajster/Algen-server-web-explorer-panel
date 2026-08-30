from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any

from ...package_center.executor import redact
from .offline_models import OfflineExportInput, OfflineImportInput
from .offline_service import OfflineRepositoryService, offline_service
from .repository import object_id

OFFLINE_OPERATIONS = {"offline_export", "offline_verify", "offline_import"}


class OfflineRepositoryJobManager:
    """Durable offline operations backed by the existing repository job/log tables."""

    def __init__(self, service: OfflineRepositoryService) -> None:
        self.service = service
        self.store = service.store
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="os-repositories-offline")
        self._lock = threading.RLock()
        self._initialize()
        self.resume_pending()

    def _initialize(self) -> None:
        with self.store.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS offline_job_payloads("
                "job_id TEXT PRIMARY KEY REFERENCES repository_sync_jobs(id) ON DELETE CASCADE,"
                "payload_json TEXT NOT NULL)"
            )

    def resume_pending(self) -> None:
        placeholders = ",".join("?" for _ in OFFLINE_OPERATIONS)
        for job in self.store.all(
            f"SELECT id FROM repository_sync_jobs WHERE status='queued' AND operation IN ({placeholders}) ORDER BY created_at",
            tuple(sorted(OFFLINE_OPERATIONS)),
        ):
            self.pool.submit(self._run, str(job["id"]))

    def _enqueue(self, repository_id: str, operation: str, payload: dict[str, Any], actor: str, retry_of: str | None = None) -> dict[str, Any]:
        if operation not in OFFLINE_OPERATIONS:
            raise ValueError("unsupported offline repository operation")
        if not self.service.base.repository(repository_id):
            raise KeyError("repository not found")
        job_id, now = object_id(), time.time()
        with self.store.connect() as connection:
            connection.execute(
                "INSERT INTO repository_sync_jobs(id,repository_id,operation,status,stage,progress,current_item,downloaded_count,downloaded_bytes,speed_bps,warnings_json,error,retry_of,created_at,created_by) "
                "VALUES(?,?,?,'queued','queued',0,'',0,0,0,'[]','',?,?,?)",
                (job_id, repository_id, operation, retry_of, now, actor),
            )
            connection.execute(
                "INSERT INTO offline_job_payloads(job_id,payload_json) VALUES(?,?)",
                (job_id, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
            )
        self.service.base._audit(actor, "offline_job_queued", job_id, {"repository_id": repository_id, "operation": operation, "retry_of": retry_of})
        self.pool.submit(self._run, job_id)
        return self.job(job_id) or {}

    def enqueue_export(self, payload: OfflineExportInput, actor: str, retry_of: str | None = None) -> dict[str, Any]:
        confirmed = payload.model_copy(update={"confirm": True})
        return self._enqueue(payload.repository_id, "offline_export", {"request": confirmed.model_dump(mode="json")}, actor, retry_of)

    def enqueue_verify(self, staged_id: str, repository_id: str, actor: str, retry_of: str | None = None) -> dict[str, Any]:
        return self._enqueue(repository_id, "offline_verify", {"staged_id": staged_id}, actor, retry_of)

    def enqueue_import(self, staged_id: str, payload: OfflineImportInput, actor: str, retry_of: str | None = None) -> dict[str, Any]:
        confirmed = payload.model_copy(update={"confirm": True})
        return self._enqueue(payload.repository_id, "offline_import", {"staged_id": staged_id, "request": confirmed.model_dump(mode="json")}, actor, retry_of)

    def _payload(self, job_id: str) -> dict[str, Any]:
        item = self.store.one("SELECT payload_json FROM offline_job_payloads WHERE job_id=?", (job_id,))
        if not item:
            raise RuntimeError("offline job payload is missing")
        value = item.get("payload")
        if not isinstance(value, dict):
            raise RuntimeError("offline job payload is invalid")
        return value

    def _log(self, job_id: str, stream: str, line: str) -> None:
        safe = redact(line).replace("\x00", "")[:8192]
        if safe:
            self.store.execute(
                "INSERT INTO repository_sync_logs(job_id,stream,line,created_at) VALUES(?,?,?,?)",
                (job_id, stream, safe, time.time()),
            )

    def _cancel_requested(self, job_id: str) -> bool:
        item = self.store.one("SELECT cancel_requested FROM repository_sync_jobs WHERE id=?", (job_id,))
        return bool(item and item["cancel_requested"])

    def _finish_cancelled(self, job_id: str) -> None:
        self.store.execute(
            "UPDATE repository_sync_jobs SET status='cancelled',stage='cancelled',error='',finished_at=? WHERE id=?",
            (time.time(), job_id),
        )

    def _run(self, job_id: str) -> None:
        job = self.job(job_id)
        if not job or job["status"] != "queued":
            return
        if self._cancel_requested(job_id):
            self._finish_cancelled(job_id)
            return
        self.store.execute(
            "UPDATE repository_sync_jobs SET status='running',stage='preparing',progress=5,started_at=? WHERE id=?",
            (time.time(), job_id),
        )
        try:
            payload = self._payload(job_id)
            operation = str(job["operation"])
            actor = str(job["created_by"])
            if operation == "offline_export":
                self.store.execute("UPDATE repository_sync_jobs SET stage='exporting',progress=15 WHERE id=?", (job_id,))
                export_request = OfflineExportInput.model_validate(payload["request"])
                result = self.service.create_bundle(export_request, actor)
                self.store.execute(
                    "UPDATE repository_sync_jobs SET stage='verifying',progress=90,current_item=?,downloaded_count=?,downloaded_bytes=? WHERE id=?",
                    (str(result.get("id", "")), int(result.get("package_count", 0)), int(result.get("size_bytes", 0)), job_id),
                )
                self._log(job_id, "system", f"Offline bundle ready: {result.get('id', '')}")
            elif operation == "offline_verify":
                self.store.execute("UPDATE repository_sync_jobs SET stage='verifying',progress=20,current_item=? WHERE id=?", (str(payload["staged_id"]), job_id))
                result = self.service.verify_staged(str(payload["staged_id"]))
                if not result["safe_to_import"]:
                    raise RuntimeError("offline bundle verification failed")
                self.store.execute(
                    "UPDATE repository_sync_jobs SET progress=90,downloaded_count=?,current_item=? WHERE id=?",
                    (int(result["packages_total"]), str(payload["staged_id"]), job_id),
                )
                self._log(job_id, "system", "Offline bundle integrity verification completed")
            elif operation == "offline_import":
                self.store.execute("UPDATE repository_sync_jobs SET stage='verifying',progress=15,current_item=? WHERE id=?", (str(payload["staged_id"]), job_id))
                import_request = OfflineImportInput.model_validate(payload["request"])
                result = self.service.import_staged(str(payload["staged_id"]), import_request, actor)
                snapshot = result.get("snapshot") or {}
                self.store.execute(
                    "UPDATE repository_sync_jobs SET stage='importing',progress=90,current_item=?,downloaded_count=? WHERE id=?",
                    (str(snapshot.get("id", "")), int(snapshot.get("package_count", 0)), job_id),
                )
                self._log(job_id, "system", f"Offline bundle imported into snapshot {snapshot.get('id', '')}")
            else:
                raise RuntimeError("unsupported offline repository operation")

            self.store.execute(
                "UPDATE repository_sync_jobs SET status='completed',stage='completed',progress=100,finished_at=? WHERE id=?",
                (time.time(), job_id),
            )
            self.service.base._audit(actor, "offline_job_completed", job_id, {"operation": operation})
        except (KeyError, ValueError, RuntimeError, OSError) as error:
            message = redact(str(error))[:2000]
            self._log(job_id, "stderr", message)
            self.store.execute(
                "UPDATE repository_sync_jobs SET status='failed',stage='failed',error=?,finished_at=? WHERE id=?",
                (message, time.time(), job_id),
            )
            self.service.base._audit(str(job["created_by"]), "offline_job_failed", job_id, {"operation": job["operation"], "error": message})

    def job(self, job_id: str) -> dict[str, Any] | None:
        placeholders = ",".join("?" for _ in OFFLINE_OPERATIONS)
        item = self.store.one(
            f"SELECT * FROM repository_sync_jobs WHERE id=? AND operation IN ({placeholders})",
            (job_id, *sorted(OFFLINE_OPERATIONS)),
        )
        if item:
            item["logs"] = self.logs(job_id, 200)
        return item

    def jobs(self, page: int = 1, page_size: int = 50, status: str = "") -> dict[str, Any]:
        placeholders = ",".join("?" for _ in OFFLINE_OPERATIONS)
        where = f"operation IN ({placeholders})"
        values: tuple[Any, ...] = tuple(sorted(OFFLINE_OPERATIONS))
        if status:
            where += " AND status=?"
            values = (*values, status)
        return self.store.page("repository_sync_jobs", page=page, page_size=page_size, order="created_at DESC", where=where, values=values)

    def logs(self, job_id: str, limit: int = 500) -> list[dict[str, Any]]:
        return list(reversed(self.store.all("SELECT * FROM repository_sync_logs WHERE job_id=? ORDER BY id DESC LIMIT ?", (job_id, limit))))

    def cancel(self, job_id: str, actor: str) -> dict[str, Any]:
        job = self.job(job_id)
        if not job:
            raise KeyError("offline job not found")
        if job["status"] not in {"queued", "running"}:
            raise ValueError("offline job is already finished")
        self.store.execute("UPDATE repository_sync_jobs SET cancel_requested=1 WHERE id=?", (job_id,))
        if job["status"] == "queued":
            self._finish_cancelled(job_id)
        self.service.base._audit(actor, "offline_job_cancel_requested", job_id, {"operation": job["operation"]})
        return self.job(job_id) or {}

    def retry(self, job_id: str, actor: str) -> dict[str, Any]:
        job = self.job(job_id)
        if not job:
            raise KeyError("offline job not found")
        if job["status"] not in {"failed", "cancelled"}:
            raise ValueError("only failed or cancelled offline jobs can be retried")
        payload = self._payload(job_id)
        operation = str(job["operation"])
        if operation == "offline_export":
            return self.enqueue_export(OfflineExportInput.model_validate(payload["request"]), actor, retry_of=job_id)
        if operation == "offline_verify":
            return self.enqueue_verify(str(payload["staged_id"]), str(job["repository_id"]), actor, retry_of=job_id)
        if operation == "offline_import":
            return self.enqueue_import(str(payload["staged_id"]), OfflineImportInput.model_validate(payload["request"]), actor, retry_of=job_id)
        raise ValueError("unsupported offline repository operation")


@lru_cache
def offline_job_manager() -> OfflineRepositoryJobManager:
    return OfflineRepositoryJobManager(offline_service())
