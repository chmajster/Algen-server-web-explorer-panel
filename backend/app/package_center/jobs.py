from __future__ import annotations

import secrets
import threading
import time

from ..activity import ActivityCategory, ActivityStatus, record_activity
from ..audit import logger
from .detached_updates import detached_update_session
from .executor import execute
from .manifests import load_manifest
from .models import PackageAction, PackageJobStatus, PackagePlan, api_error
from .repository import PackageRepository


class PackageJobManager:
    def __init__(self, repository: PackageRepository) -> None:
        self.repository = repository
        self._lock = threading.RLock()
        for job in repository.active_jobs():
            if job["status"] == PackageJobStatus.running.value and detached_update_session(job.get("plan", {})):
                threading.Thread(target=self._run, args=(job["id"],), daemon=True, name=f"package-resume-{job['id'][:8]}").start()
        self._schedule()

    def enqueue(self, plan: PackagePlan, actor: str, *, retry_of: str | None = None) -> dict:
        if self.repository.active_jobs(plan.module_id):
            api_error(409, "JOB_ALREADY_RUNNING", "An operation for this module is already queued or running")
        job = self.repository.create_job(plan, actor, previous_version=plan.previous_version, retry_of=retry_of)
        logger.info("package_action actor=%s module=%s action=%s job=%s result=queued", actor, plan.module_id, plan.action.value, job["id"])
        record_activity(
            ActivityCategory.module,
            str(plan.payload.get("operation") or plan.action.value),
            actor,
            target=plan.module_id,
            status=ActivityStatus.queued,
            details={"job_id": job["id"], "package_action": plan.action.value},
            source="modules",
        )
        self._schedule()
        return self.repository.get_job(job["id"]) or job

    def _schedule(self) -> None:
        with self._lock:
            running = [job for job in self.repository.active_jobs() if job["status"] == PackageJobStatus.running.value]
            if running:
                return
            queued = [job for job in self.repository.active_jobs() if job["status"] == PackageJobStatus.queued.value]
            if not queued:
                return
            job = queued[0]
            self.repository.update_job(job["id"], status=PackageJobStatus.running.value, started_at=time.time(), current_step="Starting")
            threading.Thread(target=self._run, args=(job["id"],), daemon=True, name=f"package-{job['id'][:8]}").start()

    def _run(self, job_id: str) -> None:
        job = self.repository.get_job(job_id)
        if not job:
            return
        plan = PackagePlan.model_validate(job["plan"])
        manifest = load_manifest(plan.module_id)

        def log(stream: str, line: str) -> None:
            self.repository.append_log(job_id, line, stream)

        def progress(percent: int, step: str) -> None:
            self.repository.update_job(job_id, progress=max(0, min(100, percent)), current_step=step)

        def cancelled() -> bool:
            current = self.repository.get_job(job_id)
            return bool(current and current["cancellation_requested"])

        try:
            if plan.action in {PackageAction.install, PackageAction.reinstall, PackageAction.update, PackageAction.uninstall}:
                result: dict = {}
                if plan.create_backup:
                    from ..modules.providers import get_provider

                    backup = get_provider(plan.module_id, job["created_by"]).create_backup(job["created_by"], f"Automatic backup before {plan.action.value}", True)
                    result["backup"] = backup
                execute(plan, manifest, log, progress, cancelled)
                if plan.action == PackageAction.uninstall:
                    if plan.module_id == "ansible-controller" and plan.remove_data:
                        result.update({"managed_config_removed": True, "remote_accounts_removed": False})
                    else:
                        from ..modules.providers import get_provider

                        result.update(get_provider(plan.module_id, job["created_by"]).cleanup_after_uninstall(job["created_by"], bool(plan.payload.get("remove_config"))))
            else:
                from ..modules.providers import get_provider

                result = get_provider(plan.module_id, job["created_by"]).execute_operation(plan.action, plan.payload, job["created_by"], log, progress, cancelled)
            if cancelled():
                raise InterruptedError("Package operation cancelled")
            if plan.action.value in {"install", "reinstall", "update"}:
                self.repository.mark_installed(plan.module_id, manifest.version, job["created_by"], manifest.requires_reboot)
            elif plan.action.value == "uninstall":
                self.repository.mark_uninstalled(plan.module_id)
            self.repository.update_job(job_id, status=PackageJobStatus.completed.value, progress=100, current_step="Completed", finished_at=time.time(), exit_code=0, warnings=plan.warnings, result=result)
            logger.info("package_action actor=%s module=%s action=%s job=%s result=completed", job["created_by"], plan.module_id, plan.action.value, job_id)
            record_activity(
                ActivityCategory.module,
                str(plan.payload.get("operation") or plan.action.value),
                job["created_by"],
                target=plan.module_id,
                details={"job_id": job_id, "package_action": plan.action.value},
                source="modules",
            )
        except InterruptedError as error:
            self.repository.append_log(job_id, str(error), "stderr")
            self.repository.update_job(job_id, status=PackageJobStatus.cancelled.value, current_step="Cancelled", finished_at=time.time(), error=str(error))
            logger.info("package_action actor=%s module=%s action=%s job=%s result=cancelled", job["created_by"], plan.module_id, plan.action.value, job_id)
            record_activity(
                ActivityCategory.module,
                str(plan.payload.get("operation") or plan.action.value),
                job["created_by"],
                target=plan.module_id,
                status=ActivityStatus.cancelled,
                summary=str(error),
                details={"job_id": job_id, "package_action": plan.action.value},
                source="modules",
            )
        except Exception as error:  # noqa: BLE001
            message = str(error) or "Package operation failed"
            self.repository.append_log(job_id, message, "stderr")
            self.repository.update_job(job_id, status=PackageJobStatus.failed.value, current_step="Failed", finished_at=time.time(), exit_code=1, error=message)
            logger.error("package_action actor=%s module=%s action=%s job=%s result=failed error=%s", job["created_by"], plan.module_id, plan.action.value, job_id, message)
            record_activity(
                ActivityCategory.module,
                str(plan.payload.get("operation") or plan.action.value),
                job["created_by"],
                target=plan.module_id,
                status=ActivityStatus.failure,
                summary=message,
                details={"job_id": job_id, "package_action": plan.action.value},
                source="modules",
            )
        finally:
            finished = self.repository.get_job(job_id)
            if finished:
                self.repository.finish_history(finished)
            self._schedule()

    def cancel(self, job_id: str) -> dict:
        job = self.repository.get_job(job_id)
        if not job:
            api_error(404, "JOB_NOT_FOUND", "Package job not found")
        if job["status"] == PackageJobStatus.queued.value:
            self.repository.update_job(job_id, cancellation_requested=True, status=PackageJobStatus.cancelled.value, current_step="Cancelled", finished_at=time.time(), error="Cancelled before execution")
            cancelled = self.repository.get_job(job_id) or job
            self.repository.finish_history(cancelled)
            self._schedule()
            return cancelled
        if job["status"] != PackageJobStatus.running.value:
            api_error(409, "JOB_NOT_CANCELLABLE", "Only queued or running jobs can be cancelled")
        if detached_update_session(job.get("plan", {})):
            api_error(409, "JOB_NOT_CANCELLABLE", "A detached system update cannot be cancelled safely while the package manager is running")
        self.repository.update_job(job_id, cancellation_requested=True, current_step="Cancellation requested; waiting for a safe step")
        return self.repository.get_job(job_id) or job

    def retry(self, job_id: str, actor: str) -> dict:
        job = self.repository.get_job(job_id)
        if not job:
            api_error(404, "JOB_NOT_FOUND", "Package job not found")
        if job["status"] not in {PackageJobStatus.failed.value, PackageJobStatus.cancelled.value}:
            api_error(409, "JOB_NOT_RETRYABLE", "Only failed or cancelled jobs can be retried")
        retry_plan = PackagePlan.model_validate(job["plan"])
        if detached_update_session(job.get("plan", {})):
            retry_plan.payload["screen_session"] = secrets.token_hex(12)
        return self.enqueue(retry_plan, actor, retry_of=job_id)


_manager: PackageJobManager | None = None
_manager_repo: PackageRepository | None = None
_manager_lock = threading.Lock()


def manager(repository: PackageRepository) -> PackageJobManager:
    global _manager, _manager_repo
    with _manager_lock:
        if _manager is None or _manager_repo is not repository:
            _manager = PackageJobManager(repository)
            _manager_repo = repository
        return _manager
