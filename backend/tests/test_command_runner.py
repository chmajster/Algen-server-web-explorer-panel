from __future__ import annotations

import sys

import pytest

from app.command_runner import CommandTimeoutError, ReadOnlyCommandRunner, _redacted_argv


def test_read_only_command_runner_returns_bounded_output() -> None:
    runner = ReadOnlyCommandRunner(output_limit=32)

    result = runner.run(
        [sys.executable, "-c", "print('x' * 200)"],
        actor="test-suite",
        timeout=5,
    )

    assert result.ok is True
    assert result.returncode == 0
    assert result.truncated is True
    assert len(result.stdout) <= 32
    assert "output truncated" in result.stdout
    assert result.stderr == ""


def test_read_only_command_runner_times_out_and_terminates_process() -> None:
    runner = ReadOnlyCommandRunner()

    with pytest.raises(CommandTimeoutError):
        runner.run(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            actor="test-suite",
            timeout=0.01,
        )


def test_command_runner_redacts_explicit_and_named_secrets() -> None:
    assert _redacted_argv(
        ["tool", "--token", "secret-value", "--password=other-secret", "visible"],
        frozenset(),
    ) == ("tool", "--token", "***", "--password=***", "visible")

    assert _redacted_argv(["tool", "visible", "secret-value"], frozenset({2})) == (
        "tool",
        "visible",
        "***",
    )


def test_command_runner_uses_controlled_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANG", "pl_PL.UTF-8")
    runner = ReadOnlyCommandRunner()

    result = runner.run(
        [sys.executable, "-c", "import os; print(os.environ['LANG']); print(os.environ['LC_ALL'])"],
        actor="test-suite",
    )

    assert result.stdout.splitlines() == ["C.UTF-8", "C.UTF-8"]
