from __future__ import annotations

import importlib.util
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "webnas_release_runtime_test",
    REPOSITORY / "scripts" / "webnas_release.py",
)
assert SPEC and SPEC.loader
release_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_module)


def test_release_helper_reexecs_with_candidate_virtualenv(monkeypatch, tmp_path: Path) -> None:
    release = tmp_path / "release"
    candidate_python = release / "backend" / ".venv" / "bin" / "python"
    candidate_python.parent.mkdir(parents=True)
    candidate_python.write_text("#!/bin/sh\n", encoding="utf-8")
    candidate_python.chmod(0o755)

    monkeypatch.setattr(
        release_module.sys,
        "argv",
        [
            str(REPOSITORY / "scripts" / "webnas_release.py"),
            "--root",
            str(tmp_path / "webnas"),
            "--release",
            str(release),
            "--config",
            str(tmp_path / "config.yaml"),
            "--public-port",
            "5000",
        ],
    )
    monkeypatch.setattr(release_module.sys, "executable", "/usr/bin/python3.14")
    executed: dict[str, object] = {}

    def fake_execv(executable: str, argv: list[str]) -> None:
        executed["executable"] = executable
        executed["argv"] = argv

    monkeypatch.setattr(release_module.os, "execv", fake_execv)

    release_module.ensure_candidate_runtime()

    assert executed["executable"] == str(candidate_python)
    argv = executed["argv"]
    assert isinstance(argv, list)
    assert argv[0] == str(candidate_python)
    assert "--release" in argv
    assert str(release) in argv


def test_release_helper_does_not_reexec_when_candidate_runtime_is_active(monkeypatch, tmp_path: Path) -> None:
    release = tmp_path / "release"
    candidate_python = release / "backend" / ".venv" / "bin" / "python"
    candidate_python.parent.mkdir(parents=True)
    candidate_python.write_text("#!/bin/sh\n", encoding="utf-8")
    candidate_python.chmod(0o755)

    monkeypatch.setattr(
        release_module.sys,
        "argv",
        ["webnas_release.py", "--release", str(release)],
    )
    monkeypatch.setattr(release_module.sys, "executable", str(candidate_python))

    def unexpected_execv(*_args: object) -> None:
        raise AssertionError("candidate runtime must not re-exec itself")

    monkeypatch.setattr(release_module.os, "execv", unexpected_execv)

    release_module.ensure_candidate_runtime()
