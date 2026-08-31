from __future__ import annotations

from typing import Protocol

import pytest

from app.modules.ansible_controller import scheduler as ansible_scheduler
from app.modules.os_repositories import scheduler as repositories_scheduler
from app.modules.proxmox_manager import scheduler as proxmox_scheduler


class SchedulerModule(Protocol):
    def start_scheduler(self) -> None: ...

    def stop_scheduler(self) -> None: ...

    def scheduler_status(self) -> dict[str, str]: ...


@pytest.mark.parametrize(
    "scheduler",
    [ansible_scheduler, repositories_scheduler, proxmox_scheduler],
    ids=["ansible-controller", "os-repositories", "proxmox-manager"],
)
def test_module_scheduler_start_stop_is_idempotent(monkeypatch: pytest.MonkeyPatch, scheduler: SchedulerModule) -> None:
    monkeypatch.setattr(scheduler, "scheduler_tick", lambda *args, **kwargs: 0)

    scheduler.stop_scheduler()
    scheduler.start_scheduler()
    scheduler.start_scheduler()

    assert scheduler.scheduler_status()["health_state"] == "healthy"

    scheduler.stop_scheduler()
    scheduler.stop_scheduler()

    assert scheduler.scheduler_status()["health_state"] == "degraded"
