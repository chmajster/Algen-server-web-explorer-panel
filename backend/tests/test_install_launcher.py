from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
LAUNCHER = REPOSITORY / "install" / "install.sh"


def _bash() -> str:
    if os.name == "nt":
        pytest.skip("installer behavior requires a native Linux Bash environment")
    executable = shutil.which("bash")
    if not executable:
        pytest.skip("bash is unavailable")
    return executable


def test_launcher_has_valid_bash_syntax():
    result = subprocess.run(
        [_bash(), "-n", str(LAUNCHER)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_launcher_maps_double_dash_y_to_existing_yes_option(tmp_path: Path):
    launcher = tmp_path / "install.sh"
    standard_installer = tmp_path / "install-standard.sh"
    shutil.copy2(LAUNCHER, launcher)
    standard_installer.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [_bash(), str(launcher), "--y"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["--yes"]


def test_launcher_help_documents_double_dash_y_alias():
    result = subprocess.run(
        [_bash(), str(LAUNCHER), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "-y, --y, --yes" in result.stdout
