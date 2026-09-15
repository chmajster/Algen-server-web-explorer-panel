from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.cron import schedule


@pytest.mark.parametrize("name", ["/UTC", "../UTC", "Europe//Warsaw", "Unknown/Zone", ""])
def test_invalid_timezone_file_falls_back_to_localtime(monkeypatch, name):
    monkeypatch.setattr(schedule, "Path", lambda _path: SimpleNamespace(
        read_text=lambda **_kwargs: name,
        resolve=lambda **_kwargs: Path("/usr/share/zoneinfo/Europe/Warsaw"),
    ))
    assert schedule.server_timezone().key == "Europe/Warsaw"


def test_invalid_localtime_zone_falls_back_to_system_offset(monkeypatch):
    monkeypatch.setattr(schedule, "Path", lambda _path: SimpleNamespace(
        read_text=lambda **_kwargs: "../UTC",
        resolve=lambda **_kwargs: Path("/usr/share/zoneinfo/../UTC"),
    ))
    assert schedule.server_timezone().utcoffset(None) is not None
