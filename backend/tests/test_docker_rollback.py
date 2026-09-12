from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.docker import rollback as docker_rollback


def write_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: object) -> Path:
    state = tmp_path / "engine-rollback.json"
    state.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(docker_rollback, "ROLLBACK_STATE", state)
    return state


def test_rollback_rejects_malformed_and_wrong_shaped_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    state = tmp_path / "engine-rollback.json"
    monkeypatch.setattr(docker_rollback, "ROLLBACK_STATE", state)
    state.write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="rollback state is invalid"):
        docker_rollback.load_state()
    state.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="rollback state is invalid"):
        docker_rollback.load_state()


@pytest.mark.parametrize(
    "previous",
    ["docker-ce=27", ["--assume-yes"], ["docker-ce=27", 7], ["docker-ce=27\ncontainerd.io=1"]],
)
def test_rollback_rejects_unsafe_package_lists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, previous: object):
    write_state(monkeypatch, tmp_path, {"manager": "apt-get", "previous": previous, "conflicts": []})
    with pytest.raises(RuntimeError, match="rollback state is invalid"):
        docker_rollback.load_state()


def test_apt_rollback_removes_attempted_packages_then_restores_previous_and_conflicts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    state = write_state(
        monkeypatch,
        tmp_path,
        {"manager": "apt-get", "previous": ["docker-ce=5:27.5.1-1~ubuntu.24.04~noble"], "conflicts": ["docker.io"]},
    )
    commands: list[tuple[list[str], bool]] = []

    def fake_run(args: list[str], *, required: bool = True) -> bool:
        commands.append((args, required))
        return True

    monkeypatch.setattr(docker_rollback, "run", fake_run)
    docker_rollback.rollback()

    assert commands[0][0] == ["apt-get", "update"]
    assert commands[1][0][:3] == ["apt-get", "remove", "-y"]
    assert set(commands[1][0][3:]) == set(docker_rollback.DOCKER_PACKAGES)
    assert commands[2][0][-1] == "docker-ce=5:27.5.1-1~ubuntu.24.04~noble"
    assert commands[3][0][-1] == "docker.io"
    assert not state.exists()


def test_rpm_rollback_removes_attempted_packages_before_restore(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    write_state(
        monkeypatch,
        tmp_path,
        {"manager": "dnf", "previous": ["docker-ce-27.5.1-1.el9.x86_64"], "conflicts": ["podman-docker"]},
    )
    commands: list[list[str]] = []

    def fake_run(args: list[str], *, required: bool = True) -> bool:
        commands.append(args)
        return True

    monkeypatch.setattr(docker_rollback, "run", fake_run)
    docker_rollback.rollback()

    assert commands[0][:3] == ["dnf", "remove", "-y"]
    assert commands[1] == ["dnf", "install", "-y", "docker-ce-27.5.1-1.el9.x86_64"]
    assert commands[2] == ["dnf", "install", "-y", "podman-docker"]


def test_failed_required_restore_keeps_rollback_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    state = write_state(monkeypatch, tmp_path, {"manager": "apt-get", "previous": ["docker-ce=27"], "conflicts": []})

    def fake_run(args: list[str], *, required: bool = True) -> bool:
        if args[:2] == ["apt-get", "install"]:
            raise RuntimeError("restore failed")
        return True

    monkeypatch.setattr(docker_rollback, "run", fake_run)
    with pytest.raises(RuntimeError, match="restore failed"):
        docker_rollback.rollback()
    assert state.exists()
