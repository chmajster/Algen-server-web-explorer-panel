from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

import pytest

from app.jobs.models import JobStatus
from app.jobs.repository import JobRepository
from app.jobs.service import JobService, sanitize


class InlineRunner:
    def submit(self, job_id, target):
        future = Future()
        try:
            target()
        except BaseException as error:
            future.set_exception(error)
        else:
            future.set_result(None)
        return future


def test_job_persistence_and_state_transitions(tmp_path):
    path = tmp_path / "jobs.sqlite3"
    repository = JobRepository(path)
    job = repository.create(job_type="demo", module="tests", created_by="alice")
    assert job.status == JobStatus.queued
    running = repository.mark_running(job.id)
    assert running and running.status == JobStatus.running
    complete = repository.mark_success(job.id, result={"ok": True})
    assert complete and complete.status == JobStatus.success and complete.progress == 100
    reopened = JobRepository(path).get(job.id)
    assert reopened and reopened.status == JobStatus.success and reopened.result == {"ok": True}


def test_running_job_is_failed_during_recovery(tmp_path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    job = repository.create(job_type="demo", module="tests", created_by="alice")
    repository.mark_running(job.id)
    assert JobRepository(repository.path).recover_interrupted() == 1
    recovered = repository.get(job.id)
    assert recovered and recovered.status == JobStatus.failed
    assert "restarted" in recovered.error.lower()


def test_queued_job_is_failed_during_recovery_instead_of_staying_stuck(tmp_path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    job = repository.create(job_type="demo", module="tests", created_by="alice", retryable=True)

    assert JobRepository(repository.path).recover_interrupted() == 1

    recovered = repository.get(job.id)
    assert recovered and recovered.status == JobStatus.failed
    assert recovered.retryable is True
    assert "before queued operation started" in recovered.error.lower()
    assert recovered.message == "Interrupted before execution"


def test_job_service_executes_handler_and_sanitizes_payload(tmp_path):
    service = JobService(JobRepository(tmp_path / "jobs.sqlite3"), runner=InlineRunner())
    service.register_handler("demo", lambda context, metadata: {"token": "abc", "value": metadata["value"]}, retryable=True)
    job = service.submit(job_type="demo", module="tests", created_by="alice", metadata={"password": "secret", "value": 7})
    assert job.status == JobStatus.success
    assert job.metadata["password"] == "[REDACTED]"
    assert job.result["token"] == "[REDACTED]"
    assert job.result["value"] == 7


def test_retry_creates_new_job_and_keeps_failed_history(tmp_path):
    service = JobService(JobRepository(tmp_path / "jobs.sqlite3"), runner=InlineRunner())
    service.register_handler("retry-safe", lambda context, metadata: {"ok": True}, retryable=True)
    original = service.create_job(job_type="retry-safe", module="tests", created_by="alice", retryable=True)
    service.repository.mark_running(original.id)
    service.repository.mark_failed(original.id, "boom")
    retried = service.retry(original.id, "alice")
    assert retried.id != original.id
    assert retried.parent_job_id == original.id
    assert retried.retry_count == 1
    assert retried.status == JobStatus.success
    assert service.get(original.id).status == JobStatus.failed


def test_retry_is_rejected_when_handler_is_not_retry_safe(tmp_path):
    service = JobService(JobRepository(tmp_path / "jobs.sqlite3"), runner=InlineRunner())
    original = service.create_job(job_type="unsafe", module="tests", created_by="alice")
    service.repository.mark_running(original.id)
    service.repository.mark_failed(original.id, "boom")
    with pytest.raises(ValueError):
        service.retry(original.id, "alice")


def test_cancel_request_is_persistent(tmp_path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    queued = repository.create(job_type="demo", module="tests", created_by="alice", cancellable=True)
    cancelled = repository.request_cancel(queued.id)
    assert cancelled and cancelled.status == JobStatus.cancelled
    running = repository.create(job_type="demo", module="tests", created_by="alice", cancellable=True)
    repository.mark_running(running.id)
    requested = repository.request_cancel(running.id)
    assert requested and requested.status == JobStatus.cancel_requested and requested.cancel_requested


def test_progress_pagination_filters_and_concurrent_updates(tmp_path):
    repository = JobRepository(tmp_path / "jobs.sqlite3")
    service = JobService(repository, runner=InlineRunner())
    jobs = [service.create_job(job_type="demo", module="alpha" if index < 3 else "beta", created_by="alice") for index in range(6)]
    repository.mark_running(jobs[0].id)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda value: service.update_progress(jobs[0].id, value, f"step {value}"), range(10, 91, 10)))
    updated = repository.get(jobs[0].id)
    assert updated and updated.progress is not None and 10 <= updated.progress <= 90
    page = repository.list(module="alpha", limit=2, offset=1)
    assert page.total == 3 and len(page.items) == 2 and page.offset == 1


def test_sanitizer_redacts_nested_credentials_and_authorization():
    result = sanitize({"metadata": {"credential_id": "cred-1", "password": "bad"}, "message": "Authorization: Bearer abc.def"})
    assert result["metadata"]["credential_id"] == "cred-1"
    assert result["metadata"]["password"] == "[REDACTED]"
    assert "abc.def" not in result["message"]
