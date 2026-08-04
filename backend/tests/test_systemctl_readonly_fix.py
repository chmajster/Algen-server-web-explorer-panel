from __future__ import annotations

from app.package_center import executor


def test_systemctl_disable_read_only_does_not_abort_uninstall(monkeypatch):
    calls: list[list[str]] = []
    logs: list[tuple[str, str]] = []

    def fake_run(args: list[str], timeout: int, log) -> None:
        calls.append(args)
        raise executor.CommandExecutionError(
            "systemctl",
            1,
            (
                "Synchronizing state of smbd.service with SysV service script.\n"
                "update-rc.d: error: Read-only file system"
            ),
        )

    monkeypatch.setattr(executor, "_run", fake_run)

    executor._run_systemctl_command(
        ["systemctl", "disable", "smbd"],
        120,
        lambda stream, line: logs.append((stream, line)),
    )

    assert calls == [["systemctl", "disable", "smbd"]]
    assert any(
        stream == "warning"
        and "package removal will continue" in line
        and "smbd" in line
        for stream, line in logs
    )
