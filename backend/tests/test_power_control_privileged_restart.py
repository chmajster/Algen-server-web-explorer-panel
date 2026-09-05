from __future__ import annotations

import subprocess

import app.power_control as power_control


class ImmediateTimer:
    created: list["ImmediateTimer"] = []

    def __init__(self, interval: float, function, args=(), kwargs=None):
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = False
        self.started = False
        self.__class__.created.append(self)

    def start(self) -> None:
        self.started = True
        self.function(*self.args, **self.kwargs)


def test_application_restart_uses_privileged_broker_in_standard_install(monkeypatch) -> None:
    ImmediateTimer.created.clear()
    calls: list[tuple[list[str], int | float, str]] = []

    monkeypatch.setattr(power_control, "broker_required", lambda: True)
    monkeypatch.setattr(power_control.threading, "Timer", ImmediateTimer)
    monkeypatch.setattr(
        power_control.shutil,
        "which",
        lambda _name: (_ for _ in ()).throw(AssertionError("unprivileged systemd-run must not be used")),
    )

    def fake_broker_command(args, *, timeout, actor):
        calls.append((list(args), timeout, actor))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(power_control, "broker_command", fake_broker_command)

    result = power_control._schedule_systemctl(
        "application-restart",
        "restart",
        "webnas-backend-blue.service",
    )

    assert result == {
        "ok": True,
        "scheduled": True,
        "mode": "privileged-broker-delay",
        "unit": "",
    }
    assert len(ImmediateTimer.created) == 1
    assert ImmediateTimer.created[0].interval == 2.0
    assert ImmediateTimer.created[0].daemon is True
    assert ImmediateTimer.created[0].started is True
    assert calls == [
        (
            ["systemctl", "restart", "webnas-backend-blue.service"],
            120,
            "power-control-application-restart",
        )
    ]


def test_host_restart_uses_privileged_power_operation(monkeypatch) -> None:
    ImmediateTimer.created.clear()
    calls: list[list[str]] = []

    monkeypatch.setattr(power_control, "broker_required", lambda: True)
    monkeypatch.setattr(power_control.threading, "Timer", ImmediateTimer)

    def fake_broker_command(args, *, timeout, actor):
        assert timeout == 120
        assert actor == "power-control-host-restart"
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(power_control, "broker_command", fake_broker_command)

    result = power_control._schedule_systemctl("host-restart", "reboot")

    assert result["mode"] == "privileged-broker-delay"
    assert calls == [["systemctl", "reboot"]]
