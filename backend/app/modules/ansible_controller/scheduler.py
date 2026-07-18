from __future__ import annotations

import calendar
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...audit import logger
from ...package_center.jobs import manager
from ...package_center.models import PackageAction
from ...package_center.service import repository as package_repository
from ..router import _provider_plan
from .playbooks import analyze_playbook
from .repository import repository


_lock = threading.RLock()
_started = False


def next_run(kind: str, expression: str, timezone: str, after: float | None = None) -> float | None:
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("unknown schedule timezone") from error
    current = datetime.fromtimestamp(after or time.time(), zone)
    if kind == "once":
        try:
            value = datetime.fromisoformat(expression)
        except ValueError as error:
            raise ValueError("invalid one-time schedule") from error
        if value.tzinfo is None:
            value = value.replace(tzinfo=zone)
        return value.timestamp() if value.timestamp() > current.timestamp() else None
    if kind == "hourly":
        return (current.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).timestamp()
    if kind == "daily":
        return (current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()
    if kind == "weekly":
        return (current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=7 - current.weekday())).timestamp()
    if kind == "monthly":
        year, month = current.year + (1 if current.month == 12 else 0), 1 if current.month == 12 else current.month + 1
        day = min(current.day, calendar.monthrange(year, month)[1])
        return current.replace(year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0).timestamp()
    if kind == "cron":
        fields = expression.split()
        if len(fields) != 5:
            raise ValueError("cron requires five fields")
        minute, hour, day, month, weekday = fields
        candidate = current.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(366 * 24 * 60):
            if _matches(minute, candidate.minute, 0, 59) and _matches(hour, candidate.hour, 0, 23) and _matches(day, candidate.day, 1, 31) and _matches(month, candidate.month, 1, 12) and _matches(weekday, (candidate.weekday() + 1) % 7, 0, 7):
                return candidate.timestamp()
            candidate += timedelta(minutes=1)
        raise ValueError("cron has no occurrence in the next year")
    raise ValueError("unsupported schedule kind")


def _matches(field: str, value: int, minimum: int, maximum: int) -> bool:
    if field == "*":
        return True
    for part in field.split(","):
        if part.startswith("*/"):
            step = int(part[2:])
            if step > 0 and value % step == 0:
                return True
        elif "-" in part:
            start, end = (int(item) for item in part.split("-", 1))
            if minimum <= start <= value <= end <= maximum:
                return True
        elif part.isdigit() and int(part) == value:
            return True
    return False


def scheduler_tick(now: float | None = None) -> int:
    current = now or time.time()
    store = repository()
    due = [item for item in store.schedules() if item.get("active") and item.get("next_run_at") is not None and float(item["next_run_at"]) <= current]
    launched = 0
    for schedule in due:
        template = store._get("job_templates", str(schedule["template_id"]))
        execution_id: str | None = None
        try:
            upcoming = next_run(str(schedule["kind"]), str(schedule["expression"]), str(schedule["timezone"]), current)
            with store._lock, store.connect() as connection:
                connection.execute("UPDATE schedules SET last_run_at=?,next_run_at=?,active=?,updated_at=?,updated_by='scheduler' WHERE id=?", (current, upcoming, int(upcoming is not None), current, schedule["id"]))
            if not template or not template.get("active"):
                store.audit("scheduler", "schedule", schedule["id"], "skip", {"reason": "template unavailable"}, result="failure")
                continue
            host_ids = list(template.get("host_ids") or [])
            group_ids = set(template.get("group_ids") or [])
            for group in store.list_groups():
                if group["id"] in group_ids:
                    host_ids.extend(group.get("host_ids") or [])
            playbook = store._get("playbooks", str(template["playbook_id"]))
            analysis = analyze_playbook(str((playbook or {}).get("content") or ""))
            if not host_ids or not analysis["ok"]:
                store.audit("scheduler", "schedule", schedule["id"], "skip", {"reason": "no targets or blocked playbook"}, result="failure")
                continue
            execution = store.create_execution(template["id"], "scheduler", list(dict.fromkeys(host_ids)), analysis["warnings"])
            execution_id = str(execution["id"])
            plan = _provider_plan("ansible-controller", PackageAction.manage, {"operation": "launch", "execution_id": execution["id"]})
            package_job = manager(package_repository()).enqueue(plan, "scheduler")
            store.set_execution_job(execution["id"], package_job["id"])
            launched += 1
        except Exception as error:  # noqa: BLE001
            logger.exception("ansible_schedule_failed schedule=%s", schedule["id"])
            if execution_id:
                store.update_execution(execution_id, "scheduler", status="failed", stage="queue_failed", finished_at=current)
            if schedule.get("missed_policy") == "run_once":
                with store._lock, store.connect() as connection:
                    connection.execute(
                        "UPDATE schedules SET next_run_at=?,active=1,updated_at=?,updated_by='scheduler' WHERE id=?",
                        (current + 30, current, schedule["id"]),
                    )
            store.audit("scheduler", "schedule", schedule["id"], "launch", {"error": str(error)[:500]}, result="failure")
    return launched


def _loop() -> None:
    while True:
        try:
            scheduler_tick()
        except Exception:  # noqa: BLE001
            logger.exception("ansible_scheduler_tick_failed")
        time.sleep(30)


def start_scheduler() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
        threading.Thread(target=_loop, daemon=True, name="ansible-controller-scheduler").start()
