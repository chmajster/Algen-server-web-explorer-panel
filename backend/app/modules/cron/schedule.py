from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


MONTH_NAMES = {name.lower(): index for index, name in enumerate(calendar.month_abbr) if name}
WEEKDAY_NAMES = {name.lower(): index for index, name in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}
ALIASES = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}


class CronSyntaxError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CronField:
    values: frozenset[int]
    wildcard: bool


@dataclass(frozen=True, slots=True)
class CronExpression:
    source: str
    minute: CronField | None
    hour: CronField | None
    day_of_month: CronField | None
    month: CronField | None
    day_of_week: CronField | None
    reboot: bool = False

    @classmethod
    def parse(cls, expression: str) -> "CronExpression":
        normalized = " ".join(expression.strip().lower().split())
        if normalized == "@reboot":
            return cls(normalized, None, None, None, None, None, True)
        normalized = ALIASES.get(normalized, normalized)
        fields = normalized.split()
        if len(fields) != 5:
            raise CronSyntaxError("cron expression must contain exactly five fields or @reboot")
        minute = _parse_field(fields[0], 0, 59)
        hour = _parse_field(fields[1], 0, 23)
        day = _parse_field(fields[2], 1, 31)
        month = _parse_field(fields[3], 1, 12, MONTH_NAMES)
        weekday = _parse_field(fields[4], 0, 7, WEEKDAY_NAMES, normalize_weekday=True)
        return cls(" ".join(fields), minute, hour, day, month, weekday)

    def matches(self, value: datetime) -> bool:
        if self.reboot:
            return False
        assert self.minute and self.hour and self.day_of_month and self.month and self.day_of_week
        cron_weekday = (value.weekday() + 1) % 7
        basic = value.minute in self.minute.values and value.hour in self.hour.values and value.month in self.month.values
        day_match = value.day in self.day_of_month.values
        weekday_match = cron_weekday in self.day_of_week.values
        if not self.day_of_month.wildcard and not self.day_of_week.wildcard:
            return basic and (day_match or weekday_match)
        return basic and day_match and weekday_match


def _number(value: str, names: dict[str, int] | None, minimum: int, maximum: int) -> int:
    if names and value in names:
        result = names[value]
    elif re.fullmatch(r"\d{1,2}", value):
        result = int(value)
    else:
        raise CronSyntaxError(f"invalid cron field value: {value}")
    if result < minimum or result > maximum:
        raise CronSyntaxError(f"cron field value {result} is outside {minimum}-{maximum}")
    return result


def _parse_field(value: str, minimum: int, maximum: int, names: dict[str, int] | None = None, *, normalize_weekday: bool = False) -> CronField:
    if not value or any(character.isspace() for character in value):
        raise CronSyntaxError("cron fields cannot be empty")
    values: set[int] = set()
    wildcard = value == "*" or value.startswith("*/")
    for part in value.split(","):
        if not part:
            raise CronSyntaxError("cron lists cannot contain empty values")
        base, separator, step_text = part.partition("/")
        step = 1
        if separator:
            if not re.fullmatch(r"\d+", step_text):
                raise CronSyntaxError("cron step must be a positive integer")
            step = int(step_text)
            if step < 1 or step > maximum - minimum + 1:
                raise CronSyntaxError("cron step is outside the field range")
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            left, right = base.split("-", 1)
            start, end = _number(left, names, minimum, maximum), _number(right, names, minimum, maximum)
            if start > end:
                raise CronSyntaxError("cron ranges must be ascending")
        else:
            if separator:
                raise CronSyntaxError("a cron step requires * or an explicit range")
            start = end = _number(base, names, minimum, maximum)
        values.update(range(start, end + 1, step))
    if normalize_weekday and 7 in values:
        values.remove(7)
        values.add(0)
    if not values:
        raise CronSyntaxError("cron field does not select any values")
    return CronField(frozenset(values), wildcard)


def server_timezone() -> tzinfo:
    for path in (Path("/etc/timezone"),):
        try:
            name = path.read_text(encoding="utf-8", errors="replace").strip()
            if name:
                return ZoneInfo(name)
        except (OSError, ZoneInfoNotFoundError):
            pass
    try:
        target = Path("/etc/localtime").resolve(strict=True)
        marker = "/zoneinfo/"
        if marker in str(target):
            return ZoneInfo(str(target).split(marker, 1)[1])
    except (OSError, ZoneInfoNotFoundError):
        pass
    return datetime.now().astimezone().tzinfo or UTC


def next_occurrence(expression: str, *, after: datetime | None = None, years: int = 5) -> datetime | None:
    parsed = CronExpression.parse(expression)
    if parsed.reboot:
        return None
    timezone = (after.tzinfo if after and after.tzinfo else None) or server_timezone()
    threshold = (after or datetime.now(timezone)).astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
    first_day = threshold.astimezone(timezone).date()
    assert parsed.minute and parsed.hour
    for offset in range(366 * max(1, years) + 1):
        day = first_day + timedelta(days=offset)
        candidates: list[datetime] = []
        for hour in sorted(parsed.hour.values):
            for minute in sorted(parsed.minute.values):
                for fold in (0, 1):
                    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone, fold=fold)
                    instant = local.astimezone(UTC)
                    normalized = instant.astimezone(timezone)
                    if (normalized.date(), normalized.hour, normalized.minute) != (day, hour, minute):
                        continue
                    if instant >= threshold and parsed.matches(normalized):
                        candidates.append(normalized)
        if candidates:
            return min(candidates, key=lambda item: item.astimezone(UTC))
    return None


def explain_schedule(expression: str) -> str:
    normalized = " ".join(expression.strip().lower().split())
    descriptions = {
        "* * * * *": "Runs every minute.",
        "*/5 * * * *": "Runs every 5 minutes.",
        "*/10 * * * *": "Runs every 10 minutes.",
        "*/15 * * * *": "Runs every 15 minutes.",
        "*/30 * * * *": "Runs every 30 minutes.",
        "0 * * * *": "Runs every hour.",
        "0 0 * * *": "Runs every day at 00:00.",
        "0 0 * * 0": "Runs every Sunday at 00:00.",
        "0 0 1 * *": "Runs on the first day of every month at 00:00.",
        "@reboot": "Runs when the cron daemon starts after a system boot.",
    }
    if normalized in descriptions:
        return descriptions[normalized]
    parsed = CronExpression.parse(normalized)
    if parsed.reboot:
        return descriptions["@reboot"]
    return f"Runs according to the server cron schedule: {parsed.source}."
