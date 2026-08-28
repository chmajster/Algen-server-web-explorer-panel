from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.system


def test_trusted_runner_exposes_real_linux_system_interfaces() -> None:
    """Exercise only read-only host capabilities required by trusted adapters."""

    assert os.name == "posix"
    assert Path("/proc/self/status").is_file()
    systemctl = shutil.which("systemctl")
    assert systemctl is not None
    result = subprocess.run(
        [systemctl, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "systemd" in result.stdout.lower()


def test_pam_stack_is_present_without_authenticating_a_real_user() -> None:
    """Validate PAM integration prerequisites without touching credentials."""

    pam_directory = Path("/etc/pam.d")
    assert pam_directory.is_dir()
    assert any(path.is_file() for path in pam_directory.iterdir())
